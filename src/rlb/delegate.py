"""Runs subagents for a main agent: the host side of `python3 lemma.py prove L`.

While a main attempt runs, a Broker polls its workdir for request files (.rlb/delegate/<id>/
request.json, written by lemma.py). Each request becomes an ordinary sandboxed attempt of the main
config's subagent config, on a Problem built from the request: the main file up to L is the header,
L (as a Theorem) the statement. The benchmark's verifier grades it, with the lemmas admitted above L
as allowed assumptions (they are the main agent's to prove). The broker then writes result.json
(what lemma.py prints) and, if L is proved, lemmas/L.v and lemmas/L.json (what assemble splices).

The subagent's record lives inside the main attempt's: <attempt>/sub/<id>/. It times out at its
own config's timeout or when the main attempt ends, whichever is first; a `cancel` file (lemma.py
killed) or the main agent finishing stops it.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import replace
from pathlib import Path

from . import lemma_tool
from .config import Config
from .problem import PREAMBLE_HAZARD_RE, Problem
from .rocq import Toolchain

POLL_S = 1.0
MIN_SUB_S = 60  # a subagent needs at least this long to be worth starting
MESSAGE_CHARS = 2000  # of the subagent's closing message passed back

_HEADER_LINE_RE = re.compile(r"^\s*(From\s|Require\s|Import\s|Export\s|Open\s+Scope|Set\s|Unset\s|Local\s+Open)")
_ADMITTED_NAME_RE = re.compile(rf"^[ \t]*{lemma_tool._KIND}\s+([A-Za-z_][A-Za-z0-9_']*)", re.M)


def lemma_problem(parent: Problem, req: dict) -> tuple[Problem, tuple[str, ...]]:
    """The delegated lemma as a Problem, and the names admitted above it. Raises ValueError if the
    main file above L uses a construct the verifier cannot re-check."""
    prefix, name = req["prefix"], req["name"]
    lines = prefix.splitlines()
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith("(*") or _HEADER_LINE_RE.match(lines[i])):
        i += 1
    imports, preamble = "\n".join(lines[:i]).strip(), "\n".join(lines[i:]).strip()
    if PREAMBLE_HAZARD_RE.search(preamble):
        raise ValueError(f"the file above {name} uses {PREAMBLE_HAZARD_RE.search(preamble).group(0)}, "
                         "which a delegated lemma cannot build on")
    statement = "Theorem " + req["statement_key"]
    admitted = tuple(n for n in _ADMITTED_NAME_RE.findall(preamble)
                     if (b := lemma_tool.find_block(preamble, n)) is not None and b.ending == "Admitted")
    return Problem(name, parent.tier, parent.domain, imports, preamble, statement, None), admitted


def proof_part(problem: Problem, solution: str) -> str | None:
    """The subagent's text after the task's header (helper lemmas, then L with its proof), or None
    if it changed anything above its statement (then it cannot be spliced into the main file)."""
    head = problem.header() + "\n\n"
    if not solution.startswith(head):
        return None
    tail = solution[len(head):]
    b = lemma_tool.find_block(tail, problem.name)
    return tail[:b.end] + "\n" if b is not None else None


class Broker:
    def __init__(self, cfg: Config, problem: Problem, workdir: Path, attempt_dir: Path, tc: Toolchain,
                 run_dir: Path, work_root: Path, run_id: str, rep: int, deadline: float, log=print,
                 invocation: str | None = None, tools: dict | None = None):
        assert cfg.subagent is not None
        self.cfg, self.problem, self.workdir, self.attempt_dir = cfg, problem, workdir, attempt_dir
        self.tc, self.run_dir, self.work_root, self.run_id, self.rep = tc, run_dir, work_root, run_id, rep
        self.deadline, self.log, self.invocation, self.tools = deadline, log, invocation, tools
        self.done = threading.Event()  # the main agent has finished
        self.threads: list[threading.Thread] = []
        self.summaries: list[dict] = []
        self.lock = threading.Lock()
        self.poller = threading.Thread(target=self._poll, daemon=True)

    def start(self) -> None:
        self.poller.start()

    def stop(self) -> list[dict]:
        """Cancel whatever still runs and wait for it; the summaries of every delegation."""
        self.done.set()
        self.poller.join()
        for t in self.threads:
            t.join()
        return sorted(self.summaries, key=lambda s: s["id"])

    def _poll(self) -> None:
        seen: set[str] = set()
        root = self.workdir / lemma_tool.DELEGATE_DIR
        while not self.done.is_set():
            for req in sorted(root.glob("*/request.json")) if root.is_dir() else []:
                if req.parent.name not in seen:
                    seen.add(req.parent.name)
                    t = threading.Thread(target=self._serve, args=(req.parent,), daemon=True)
                    self.threads.append(t)
                    t.start()
            self.done.wait(POLL_S)

    def _serve(self, req_dir: Path) -> None:
        req = json.loads((req_dir / "request.json").read_text())
        summary = {"id": req_dir.name, "lemma": req["name"], "status": "failed", "reason": "", "wall_s": 0.0}
        try:
            result = self._run(req_dir, req, summary)
        except Exception as e:  # noqa: BLE001 - a broken delegation must still answer lemma.py
            result = {"status": "failed", "reason": f"delegation error: {type(e).__name__}: {e}", "message": ""}
        summary.update(status=result["status"], reason=result["reason"])
        (req_dir / "result.json.tmp").write_text(json.dumps(result))
        (req_dir / "result.json.tmp").rename(req_dir / "result.json")
        with self.lock:
            self.summaries.append(summary)

    def _run(self, req_dir: Path, req: dict, summary: dict) -> dict:
        from .runner import SubRun, run_attempt
        try:
            problem, admitted = lemma_problem(self.problem, req)
        except ValueError as e:
            return {"status": "failed", "reason": str(e), "message": ""}
        left = self.deadline - time.time()
        if left < MIN_SUB_S:
            return {"status": "failed", "reason": f"only {left:.0f}s of your time left", "message": ""}
        sub_cfg = self.cfg.subagent
        if sub_cfg.timeout_s > left:
            sub_cfg = replace(sub_cfg, timeout_s=int(left))
        stop = threading.Event()
        watcher = threading.Thread(target=self._watch, args=(req_dir, stop), daemon=True)
        watcher.start()
        hint = req.get("hint") or ""
        run = SubRun(
            attempt_dir=self.attempt_dir / "sub" / req_dir.name,
            workdir=self.workdir.parent / f"{self.workdir.name}-sub" / req_dir.name,
            stop=stop,
            prompt_suffix=(
                "\nThis lemma was handed to you by another agent working on a larger proof. If you cannot "
                "prove it, for instance because it is false as stated, say why in your final message: that "
                "message is passed back to that agent."
                + (f"\n\nThe other agent's hint:\n<hint>\n{hint}\n</hint>\n" if hint else "\n")),
            allowed_assumptions=admitted,
        )
        att = run_attempt(sub_cfg, problem, self.tc, self.run_dir, self.work_root, self.run_id, self.rep,
                          log=self.log, invocation=self.invocation, tools=self.tools, sub=run)
        stopped_early = stop.is_set()
        stop.set()
        summary["wall_s"] = round(att.wall_s, 1)
        message = (att.harness.final_message or "")[-MESSAGE_CHARS:]
        if att.provider_error:
            return {"status": "failed", "reason": "the subagent's provider refused (this attempt will be redone)", "message": ""}
        if not att.solved:
            why = ("timed out" if att.timed_out else "stopped (cancelled, or your attempt ended)" if stopped_early
                   else att.verify.status.replace("_", " "))
            return {"status": "failed", "reason": why, "message": message}
        solution = (run.attempt_dir / "workdir" / problem.file_name).read_text()
        part = proof_part(problem, solution)
        if part is None:
            return {"status": "failed", "reason": "proved, but the subagent changed its file above the lemma, so "
                    "the proof cannot be spliced into yours", "message": message}
        lemmas = self.workdir / lemma_tool.LEMMA_DIR
        lemmas.mkdir(exist_ok=True)
        (lemmas / f"{problem.name}.v").write_text(part)
        (lemmas / f"{problem.name}.json").write_text(json.dumps({"statement": req["statement_key"], "request": req_dir.name}))
        return {"status": "proved", "reason": "", "message": message}

    def _watch(self, req_dir: Path, stop: threading.Event) -> None:
        """Stop the subagent when lemma.py is killed (cancel file) or the main agent finishes."""
        while not stop.is_set():
            if self.done.is_set() or (req_dir / "cancel").exists():
                stop.set()
                return
            time.sleep(POLL_S)
