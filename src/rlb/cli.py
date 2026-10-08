from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
import time
from pathlib import Path

from . import ROOT
from .config import load_config
from .dataset import load_manifest, select
from .problem import Problem
from .report import mixed_distributions, format_matrix, format_summary, load_attempts, summarize
from .rocq import Toolchain, verify
from .runner import run_attempt

DEFAULT_PROBLEMS = ROOT / "problems"
DEFAULT_RESULTS = ROOT / "results"
DEFAULT_WORK_ROOT = Path("/tmp/rlb-work")


def cmd_select(a):
    tc = Toolchain.discover(a.rocq_bin)
    print(f"toolchain: {tc.version()} ({tc.bin_dir})")
    m = select(a.per_tier, a.seed, tc, a.out)
    print(f"selected {len(m['problems'])} problems -> {a.out / 'manifest.json'}; rejected {len(m['rejected'])}")


def cmd_tier(a):
    """Build one of the extra tiers into problems/ (replacing that tier only)."""
    from .dataset import select_workbook_tier
    from .external import import_minif2f, import_putnam
    tc = Toolchain.discover(a.rocq_bin)
    print(f"toolchain: {tc.version()} ({tc.bin_dir})")
    if a.name == "vhard":
        chosen = select_workbook_tier("vhard", a.min_ref_lines, a.n, a.seed, tc, a.out)
    elif a.name == "putnam":
        chosen = import_putnam(tc, a.out)
    elif a.name in ("imo", "aime"):
        chosen = import_minif2f(a.name, a.name, tc, a.out)
    elif a.name == "custom":
        from .external import CUSTOM, import_dir
        chosen = import_dir("custom", CUSTOM, tc, a.out)
    elif a.name == "research":
        from .research import import_research
        chosen = import_research(tc, a.out)
    else:
        raise SystemExit(a.name)
    print(f"tier {a.name}: {len(chosen)} problems -> {a.out / a.name}")


def _problems(a) -> list[Problem]:
    entries = load_manifest(a.problems)
    ps = [Problem.from_dict(e) for e in entries]
    if a.tier:
        ps = [p for p in ps if p.tier in a.tier]
    if a.only:
        ps = [p for p in ps if p.name in a.only or p.name.removeprefix("lean_workbook_") in a.only]
    if a.limit:
        ps = ps[: a.limit]
    if not ps:
        raise SystemExit("no problems match")
    return ps


def cmd_selftest(a):
    from tempfile import TemporaryDirectory
    tc = Toolchain.discover(a.rocq_bin)
    bad = 0
    checked = skipped = 0
    with TemporaryDirectory(prefix="rlb-selftest-") as tmp:
        for p in _problems(a):
            if not p.has_ref():
                print(f"{p.tier:6} {p.name}: skipped (no reference proof)")
                skipped += 1
                continue
            vr = verify(p, p.ref_source(), tc, Path(tmp) / "check")
            print(f"{p.tier:6} {p.name}: {vr.status} ({vr.check_s:.1f}s)")
            checked += 1
            bad += not vr.ok
    print(f"references: {checked} checked, {bad} failed; {skipped} problems without references skipped")
    sys.exit(1 if bad else 0)


def cmd_verify(a):
    tc = Toolchain.discover(a.rocq_bin)
    p = next(p for p in (Problem.from_dict(e) for e in load_manifest(a.problems)) if p.name == a.problem)
    vr = verify(p, Path(a.file).read_text(), tc, a.problems / ".scratch")
    print(json.dumps(vr.to_dict(), indent=1))
    sys.exit(0 if vr.ok else 1)


def _head() -> str:
    import subprocess
    p = subprocess.run(["git", "rev-parse", "--short=8", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return p.stdout.strip() or "nogit"


def cmd_run(a):
    tc = Toolchain.discover(a.rocq_bin)
    cfgs = [load_config(Path(c)) for c in a.config]
    ps = _problems(a)
    run_id = a.run_id or time.strftime("%Y%m%d-%H%M%S")
    run_dir = a.results / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    # results/ is append-only and a run id may be resumed by several invocations (even concurrent
    # ones): each invocation's files are named by its commit and start time, never overwritten.
    invocation = f"{_head()}-{time.strftime('%Y%m%d-%H%M%S')}"
    from .ledger import tool_versions
    tools = tool_versions()
    (run_dir / f"run.{invocation}.json").write_text(json.dumps({
        "run_id": run_id, "invocation": invocation, "rocq": tc.version(), "rocq_bin": str(tc.bin_dir),
        "configs": [c.to_dict() for c in cfgs], "problems": [p.name for p in ps], "repeat": a.repeat, "jobs": a.jobs,
        "timeout_override": a.timeout,
    }, indent=1))
    print(f"run {run_id}: {len(cfgs)} config(s) x {len(ps)} problem(s) x {a.repeat} rep(s); toolchain {tc.version()}")

    # Timeout precedence: --timeout, else the tier's timeout_s (manifest "tiers"), else the config's.
    tier_timeouts = {t: m.get("timeout_s") for t, m in json.loads((a.problems / "manifest.json").read_text()).get("tiers", {}).items()}
    from .sandbox import ensure_ca
    ensure_ca(a.work_root / run_id / "ca")  # once, before attempts run concurrently
    # Problem-major order: with --jobs N, concurrent attempts belong to different configs (and so,
    # usually, different providers), instead of N attempts hammering one provider's quota.
    jobs = []
    for p in ps:
        for rep in range(a.repeat):
            for cfg in cfgs:
                timeout = a.timeout or tier_timeouts.get(p.tier) or cfg.timeout_s
                c = cfg if timeout == cfg.timeout_s else type(cfg)(**{**cfg.to_dict(), "timeout_s": timeout})
                jobs.append((c, p, rep))

    def one(job):
        cfg, p, rep = job
        try:
            return run_attempt(cfg, p, tc, run_dir, a.work_root, run_id, rep, a.force, invocation=invocation, tools=tools)
        except Exception as e:  # keep the run going; the attempt is simply missing
            print(f"[{cfg.name}] {p.name} r{rep}: ERROR {type(e).__name__}: {e}", file=sys.stderr)
            return None

    if a.jobs == 1:
        results = [one(j) for j in jobs]
    else:
        with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
            results = list(ex.map(one, jobs))
    done = [r for r in results if r is not None]
    rows = summarize([r.to_dict() for r in done])
    summary = {"schema": "rlb.summary/1", "run_id": run_id, "attempts": len(done), "planned": len(jobs), "rows": rows,
               "artifacts": [str(run_dir.relative_to(ROOT)) if run_dir.is_relative_to(ROOT) else str(run_dir)]}
    _emit_output(summary, run_dir / f"summary.{invocation}.json")
    print(f"\n{len(done)}/{len(jobs)} attempts recorded in {run_dir}\n")
    print(format_summary(rows))


def _emit_output(data: dict, also: Path | None = None):
    """Structured output for the ledger (`rlb log run` sets RLB_LOG_OUTPUT)."""
    text = json.dumps(data, indent=1, allow_nan=False)
    if also is not None:
        also.write_text(text)
    if os.environ.get("RLB_LOG_OUTPUT"):
        Path(os.environ["RLB_LOG_OUTPUT"]).write_text(text)


def cmd_report(a):
    atts = load_attempts([Path(d) for d in a.run_dir])
    if not atts:
        raise SystemExit("no attempt.json found")
    rows = summarize(atts)
    _emit_output({"schema": "rlb.summary/1", "attempts": len(atts), "rows": rows,
                  "artifacts": [str(Path(d).resolve().relative_to(ROOT)) for d in a.run_dir if Path(d).resolve().is_relative_to(ROOT)]})
    if a.json:
        print(json.dumps(rows, indent=1))
        return
    print(format_summary(rows))
    print()
    print(format_matrix(atts))
    mixed = mixed_distributions(atts)
    if mixed:
        print("\nWARNING cells mixing samples from different input distributions: " + "; ".join(mixed))


def cmd_timeline(a):
    """Print the harness event stream of one attempt with time offsets, plus
    the prover calls, so one can see where wall time went."""
    from .shim import parse_trace
    from .harness.base import json_lines
    d = Path(a.attempt_dir)
    att = json.loads((d / "attempt.json").read_text())
    t0 = att["started_at"]
    times = [float(x) for x in (d / "stdout.times").read_text().split()]
    lines = list(zip(times, (d / "stdout.txt").read_text().splitlines()))
    rows = []
    for t, ev in json_lines(lines):
        typ = ev.get("type", "?")
        sub = ev.get("subtype") or (ev.get("item") or {}).get("type") or ev.get("toolName") or ""
        detail = ""
        msg = ev.get("message") or {}
        for b in (msg.get("content") if isinstance(msg.get("content"), list) else []):
            if b.get("type") == "tool_use":
                detail = f"tool_use {b.get('name')} {json.dumps(b.get('input'))[:80]}"
            elif b.get("type") == "tool_result":
                detail = "tool_result"
            elif b.get("type") == "text":
                detail = "text " + b.get("text", "")[:60].replace("\n", " ")
        if typ in ("item.started", "item.completed"):
            detail = str((ev.get("item") or {}).get("command", ""))[:80]
        rows.append((t - t0, f"{typ} {sub} {detail}".strip()))
    for c in parse_trace(d / "trace.tsv"):
        rows.append((c.start - t0, f"PROVER {c.bin} {c.seconds:.2f}s rc={c.rc} {' '.join(c.argv)[:60]}"))
    for c in att["api_calls"]:
        ttfb = f"ttfb={c['first'] - c['start']:.2f}s " if c["first"] is not None else ""
        rows.append((c["start"] - t0, f"NET {c['host']} {c['end'] - c['start']:.2f}s {ttfb}req={c['req_bytes']}B resp={c['resp_bytes']}B"))
    for off, text in sorted(rows):
        print(f"{off:8.2f}  {text}")
    hs = att["harness"]
    print(f"{att['wall_s']:8.2f}  END wall (inference {att['inference_s']:.1f}s over {att['net']['api_calls']} API calls"
          + (f", harness says {hs['inference_s']:.1f}s" if hs.get("inference_s") is not None else "")
          + f"; prover busy {att['prover']['busy_s']:.1f}s)")


def cmd_gantt(a):
    """Render one HTML page with a segmented timeline bar per attempt."""
    from .gantt import load_rows, render_html
    rows = load_rows([Path(d) for d in a.run_dir], invocation=a.invocation)
    out = Path(a.output)
    out.write_text(render_html(rows, a.title or ", ".join(Path(d).name for d in a.run_dir)))
    print(f"{out}: {len(rows)} attempts")


def cmd_log_run(a):
    from .ledger import dumps, read_entries, run_logged, summary_line
    cmd = a.command[1:] if a.command[:1] == ["--"] else a.command  # REMAINDER keeps the "--"
    if not cmd:
        raise SystemExit("usage: rlb log run [--note ...] -- command...")
    e = run_logged(cmd, a.note)
    print("\nlogged: " + summary_line(len(read_entries()) - 1, dumps(e)))
    sys.exit(e["exit_code"])


def cmd_log_verify(a):
    from .ledger import read_entries, verify_lines, verify_staged
    try:
        msg = verify_staged() if a.staged else f"log/entries.jsonl: {verify_lines(read_entries())} entries ok"
    except ValueError as ex:
        raise SystemExit(f"log: {ex}")
    print(msg)


def cmd_log_show(a):
    from .ledger import read_entries, summary_line
    lines = read_entries()
    start = max(0, len(lines) - a.n) if a.n else 0
    for i in range(start, len(lines)):
        print(summary_line(i, lines[i]))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rlb", description="Rocq LLM bench meta-harness")
    ap.add_argument("--rocq-bin", help="dir containing coqc (default: $RLB_ROCQ_BIN, ./_opam/bin, PATH)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("select", help="pick problems from rocq-workbook and verify their reference proofs")
    s.add_argument("--per-tier", type=int, default=10)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--out", type=Path, default=DEFAULT_PROBLEMS)
    s.set_defaults(fn=cmd_select)

    def problem_args(p):
        p.add_argument("--problems", type=Path, default=DEFAULT_PROBLEMS)
        p.add_argument("--tier", action="append", help="easy | medium | hard | vhard | putnam | imo | aime | custom | research (repeatable)")
        p.add_argument("--only", nargs="+", help="problem names (lean_workbook_ prefix optional)")
        p.add_argument("--limit", type=int, help="take only the first N matching problems")

    s = sub.add_parser("selftest", help="verify every reference solution with the current toolchain")
    problem_args(s)
    s.set_defaults(fn=cmd_selftest)

    s = sub.add_parser("verify", help="verify a solution file for one problem")
    s.add_argument("problem")
    s.add_argument("file")
    s.add_argument("--problems", type=Path, default=DEFAULT_PROBLEMS)
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("tier", help="build an extra tier: vhard (workbook, long refs), putnam, imo, aime, custom, research (problems_src/)")
    s.add_argument("name", choices=["vhard", "putnam", "imo", "aime", "custom", "research"])
    s.add_argument("--n", type=int, default=10, help="vhard: problems to select")
    s.add_argument("--min-ref-lines", type=int, default=30, help="vhard: reference proof length threshold")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--out", type=Path, default=ROOT / "problems")
    s.add_argument("--rocq-bin", type=Path)
    s.set_defaults(fn=cmd_tier)

    s = sub.add_parser("run", help="run configs against problems")
    s.add_argument("--config", "-c", action="append", required=True, help="config .toml (repeatable)")
    problem_args(s)
    s.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    s.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT, help="agent workdirs (outside the repo)")
    s.add_argument("--run-id")
    s.add_argument("--repeat", type=int, default=1)
    s.add_argument("--jobs", type=int, default=1, help=">1 distorts prover timing; use for cheap smoke tests")
    s.add_argument("--timeout", type=int, help="override the timeout (else the tier's timeout_s from the manifest, else the config's)")
    s.add_argument("--force", action="store_true", help="redo attempts that already have an attempt.json")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("report", help="summarize one or more run directories")
    s.add_argument("run_dir", nargs="+")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("log", help="append-only ledger of commands and their outputs (see log/)")
    ls = s.add_subparsers(dest="logcmd", required=True)
    l = ls.add_parser("run", help="run a command and append an entry: commit, tools, argv, output")
    l.add_argument("--note")
    l.add_argument("command", nargs=argparse.REMAINDER)
    l.set_defaults(fn=cmd_log_run)
    l = ls.add_parser("verify", help="check entries parse; --staged also checks the append-only invariants")
    l.add_argument("--staged", action="store_true")
    l.set_defaults(fn=cmd_log_verify)
    l = ls.add_parser("show", help="one line per entry")
    l.add_argument("-n", type=int, default=0, help="last N entries")
    l.set_defaults(fn=cmd_log_show)

    s = sub.add_parser("gantt", help="HTML timeline: one segmented bar per attempt (prover / model / tool / other)")
    s.add_argument("run_dir", nargs="+")
    s.add_argument("-o", "--output", required=True, help="output .html")
    s.add_argument("--title")
    s.add_argument("--invocation", help="only attempts produced by this invocation (<commit>-<time>, see run.<invocation>.json)")
    s.set_defaults(fn=cmd_gantt)

    s = sub.add_parser("timeline", help="show one attempt's event stream with time offsets")
    s.add_argument("attempt_dir")
    s.set_defaults(fn=cmd_timeline)

    a = ap.parse_args(argv)
    a.fn(a)
