"""Append-only ledger: "on commit X, running command Y produced output Z".

One JSON object per line in log/entries.jsonl (JSON escapes newlines, so a
record is always exactly one line). Git is the history: every commit's
version of the file extends the previous one, and results/ and log/patches/
only ever gain files. `verify --staged` enforces both at commit time.

`log run` makes the commits itself. Before the command starts, any change to
code or configs (everything outside log/ and results/) is committed, so the
entry's commit is exactly what ran; a run started while an earlier one is
still in flight gets its own commit, and that earlier run's results land
with its own entry later. After the command finishes, the entry and the
run's completed artifacts (attempt dirs with an attempt.json, top-level run
files) are committed together.

Contract for commands: the wrapper sets $RLB_LOG_OUTPUT to a temp path. A
command may write a JSON object there; it becomes `output.data`. If that
object has an `artifacts` list of repo-relative paths, they are recorded.
Everything else (stdout/stderr tails, exit code) is captured regardless, so
any script qualifies.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import ROOT

SCHEMA = "rlb.log/1"
LOG_DIR = ROOT / "log"
ENTRIES = LOG_DIR / "entries.jsonl"
PATCHES = LOG_DIR / "patches"
TAIL_BYTES = 8192
TOOLS = ("claude", "codex", "pi", "uv")
# Output directories, not code: their presence never makes the tree "dirty".
NOT_CODE = ("log", "results")
APPEND_ONLY = ("results/", "log/patches/")


def _git(*args: str, env: dict | None = None, check: bool = True) -> str:
    p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, env=env)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


def clean(s: str | None) -> str | None:
    """argv/notes arrive via surrogateescape; make them valid UTF-8 (bytes as \\xNN)."""
    return None if s is None else s.encode("utf-8", "surrogateescape").decode("utf-8", "backslashreplace")


def dumps(obj) -> str:
    """Strict, single-line JSON (no NaN/Infinity; newlines escaped)."""
    line = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    assert "\n" not in line
    return line


def read_entries(text: str | None = None) -> list[str]:
    if text is None:
        text = ENTRIES.read_text() if ENTRIES.exists() else ""
    return [l for l in text.split("\n") if l]


def worktree_patch() -> bytes | None:
    """Patch from HEAD to the working tree (tracked + untracked, .gitignore
    respected), ignoring NOT_CODE dirs. None if clean."""
    with tempfile.TemporaryDirectory() as td:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(td) / "index")}
        _git("read-tree", "HEAD", env=env)
        _git("add", "-A", "--", ".", *(f":!{d}" for d in NOT_CODE), env=env)
        tree = _git("write-tree", env=env).strip()
        if tree == _git("rev-parse", "HEAD^{tree}").strip():
            return None
        # bytes: a patch may contain non-UTF-8 file content; it is written verbatim
        p = subprocess.run(["git", "diff-tree", "-p", "--binary", "HEAD", tree], cwd=ROOT, capture_output=True, env=env)
        if p.returncode != 0:
            raise RuntimeError(f"git diff-tree: {p.stderr.decode(errors='replace').strip()}")
        return p.stdout


def tool_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for t in TOOLS:
        try:
            p = subprocess.run([t, "--version"], capture_output=True, text=True, timeout=20, errors="backslashreplace")
            out[t] = (p.stdout or p.stderr).strip().splitlines()[0]
        except (FileNotFoundError, subprocess.TimeoutExpired, IndexError):
            out[t] = None
    try:
        from .rocq import Toolchain
        out["rocq"] = Toolchain.discover(None).version()
    except SystemExit:
        out["rocq"] = None
    out["python"] = sys.version.split()[0]
    return out


def _tee(stream, sink, buf: list[str]):
    for line in iter(stream.readline, ""):
        sink.write(line)
        sink.flush()
        buf.append(line)


def commit_code(message: str) -> str | None:
    """Commit every change outside NOT_CODE (tracked and untracked, .gitignore
    respected). Returns the new commit, or None if there was nothing to commit."""
    if worktree_patch() is None:
        return None
    _git("add", "-A", "--", ".", *(f":!{d}" for d in NOT_CODE))
    _git("commit", "-q", "-m", message)
    return _git("rev-parse", "HEAD").strip()


def stage_artifacts(artifacts: list[str]) -> list[str]:
    """Stage a run's completed output: attempt dirs that have an attempt.json
    (an in-flight attempt's files would change later and break append-only),
    plus the run dir's top-level files. Returns what was staged."""
    staged = []
    for a in artifacts:
        d = ROOT / a
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if f.is_file():
                staged.append(str(f.relative_to(ROOT)))
        for rec in d.glob("*/*/r*/attempt.json"):
            staged.append(str(rec.parent.relative_to(ROOT)))
    if staged:
        _git("add", "--", *staged)
    return staged


def run_logged(argv: list[str], note: str | None) -> dict:
    argv_json = [clean(a) for a in argv]
    note = clean(note)
    branch = _git("rev-parse", "--abbrev-ref", "HEAD").strip()
    pre = commit_code(f"pre-run: {note or ' '.join(argv_json)[:72]}")
    if pre:
        print(f"committed working tree as {pre[:8]} before the run", file=sys.stderr)
    commit = _git("rev-parse", "HEAD").strip()
    patch_ref = None

    tools = tool_versions()
    # A suspended machine freezes every attempt while their clocks run (invalidating them, see
    # runner.invalid_reason): hold a sleep/idle inhibitor for the duration of the command.
    inhibit = ["systemd-inhibit", "--what=sleep:idle", "--who=rlb", "--why=benchmark run in progress",
               "--mode=block"] if shutil.which("systemd-inhibit") else []
    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "output.json"
        env = {**os.environ, "RLB_LOG_OUTPUT": str(out_path)}
        start = dt.datetime.now(dt.UTC)
        t0 = time.monotonic()
        # Bytes that are not UTF-8 survive as \xNN escapes rather than crashing the logger.
        p = subprocess.Popen([*inhibit, *argv], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, errors="backslashreplace")
        out_buf: list[str] = []
        err_buf: list[str] = []
        ts = [threading.Thread(target=_tee, args=(p.stdout, sys.stdout, out_buf)),
              threading.Thread(target=_tee, args=(p.stderr, sys.stderr, err_buf))]
        for t in ts:
            t.start()
        code = p.wait()
        for t in ts:
            t.join()
        seconds = time.monotonic() - t0
        end = dt.datetime.now(dt.UTC)
        data = None
        if out_path.exists():
            try:
                data = json.loads(out_path.read_text())
            except (json.JSONDecodeError, OSError) as e:  # e.g. truncated on a full disk: the entry is still worth writing
                data = {"error": f"unreadable $RLB_LOG_OUTPUT: {e}"}

    artifacts = []
    if isinstance(data, dict) and isinstance(data.get("artifacts"), list):
        artifacts = [str(a) for a in data["artifacts"]]

    entry = {
        "schema": SCHEMA,
        "time": {"start": start.isoformat(timespec="seconds"), "end": end.isoformat(timespec="seconds"),
                 "seconds": round(seconds, 3)},
        "host": socket.gethostname(),
        "git": {"commit": commit, "branch": branch, "dirty": False, "patch": patch_ref},
        "tools": tools,
        "argv": argv_json,
        "exit_code": code,
        "output": {"data": data, "stdout_tail": "".join(out_buf)[-TAIL_BYTES:], "stderr_tail": "".join(err_buf)[-TAIL_BYTES:]},
        "artifacts": artifacts,
        "note": note,
    }
    line = dumps(entry)
    LOG_DIR.mkdir(exist_ok=True)
    with open(ENTRIES, "a") as f:
        f.write(line + "\n")
    idx = len(read_entries()) - 1
    _git("add", "--", str(ENTRIES.relative_to(ROOT)))
    staged = stage_artifacts(artifacts)
    try:
        _git("commit", "-q", "-m", f"log #{idx}: {summary_line(idx, line)[:200]}")
        entry["_committed"] = _git("rev-parse", "HEAD").strip()
    except RuntimeError as e:  # the entry is on disk regardless; the hook says what to fix
        print(f"ledger: entry #{idx} written but not committed ({e})", file=sys.stderr)
    return entry


def verify_lines(lines: list[str]) -> int:
    for i, l in enumerate(lines):
        try:
            e = json.loads(l)
        except json.JSONDecodeError as ex:
            raise ValueError(f"entry #{i}: not JSON ({ex})")
        if not isinstance(e, dict) or "schema" not in e:
            raise ValueError(f"entry #{i}: not an object with a 'schema' field")
    return len(lines)


def verify_staged() -> str:
    """Commit-time invariants: entries.jsonl only grows; APPEND_ONLY dirs only
    gain files. Returns a one-line report."""
    p = subprocess.run(["git", "show", "HEAD:log/entries.jsonl"], cwd=ROOT, capture_output=True, text=True)
    old = p.stdout if p.returncode == 0 else ""
    p = subprocess.run(["git", "show", ":log/entries.jsonl"], cwd=ROOT, capture_output=True, text=True)
    new = p.stdout if p.returncode == 0 else ""
    if old and not new.startswith(old):
        raise ValueError("staged log/entries.jsonl does not extend the committed one (edited, truncated or deleted)")
    n = verify_lines(read_entries(new))
    bad = []
    for line in _git("diff", "--cached", "--name-status", "--", *APPEND_ONLY).splitlines():
        status, _, path = line.partition("\t")
        if status[0] != "A":
            bad.append(f"{status} {path}")
    if bad:
        raise ValueError("append-only paths modified or deleted: " + ", ".join(bad[:5]))
    return f"log/entries.jsonl: {n} entries ok; append-only dirs ok"


def summary_line(idx: int, l: str) -> str:
    e = json.loads(l)
    d = e["output"]["data"]
    what = ""
    if isinstance(d, dict):
        rows = d.get("rows")
        if isinstance(rows, list) and rows:
            what = "; ".join(f"{r.get('config')}/{r.get('tier')} {r.get('solved')}/{r.get('n')}"
                             for r in rows if r.get("tier") != "all")[:100]
        elif d:
            what = json.dumps(d)[:100]
    dirty = "+patch" if e["git"]["dirty"] else ""
    return (f"#{idx:<4} {e['time']['start']}  {e['git']['commit'][:8]}{dirty}  exit={e['exit_code']}  "
            f"{' '.join(e['argv'])[:60]}  {what}" + (f"  # {e['note']}" if e.get("note") else ""))
