"""Run one (config, problem) attempt: launch the harness in a fresh workdir
with timing shims on PATH, inside the sandbox (sandbox.py: own network
namespace with packet capture and an egress allowlist of the API hosts; a
mount namespace hiding everything but the workdir, toolchain and the CLI's
own state), wait (with timeout), verify the result, record.

Time accounting (all epoch seconds):
  wall_s          harness process lifetime
  prover.busy_s   union of intervals in which some Rocq binary was running
  prover.sum_s    sum of Rocq binary durations (> busy when calls overlap)
  inference_s     union of the request/response intervals of TLS calls to the
                  harness's API hosts, from the packet capture (see net.py).
                  Independent of anything the harness reports; the harness's
                  own number, if any, is kept in harness.inference_s.
  tools_busy_s    union of tool-execution intervals from the harness's event
                  stream (None if the harness reports none)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import string
import subprocess
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import lemma_tool
from .config import Config, native_subagents_allowed
from .harness import HARNESSES, HarnessStats, Line
from .harness.base import is_provider_error
from .net import ApiCall, NetStats, parse_pcap
from .problem import Problem
from .sandbox import SandboxSpec, sandbox_argv
from .rocq import Toolchain, VerifyResult, verify
from .shim import ProverCall, make_shim_dir, parse_trace, shim_env, union_seconds

# Env vars that make nested CLIs think they run inside another agent session.
_STRIP_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


@dataclass
class ProverStats:
    calls: int = 0
    failed_calls: int = 0
    busy_s: float = 0.0
    sum_s: float = 0.0
    by_bin: dict[str, dict] = field(default_factory=dict)

    @staticmethod
    def from_calls(calls: list[ProverCall]) -> ProverStats:
        st = ProverStats(calls=len(calls), failed_calls=sum(c.rc != 0 for c in calls))
        st.busy_s = union_seconds([(c.start, c.end) for c in calls])
        st.sum_s = sum(c.seconds for c in calls)
        for c in calls:
            b = st.by_bin.setdefault(c.bin, {"calls": 0, "sum_s": 0.0})
            b["calls"] += 1
            b["sum_s"] += c.seconds
        return st


@dataclass
class Attempt:
    run_id: str
    config: dict
    problem: str
    tier: str
    domain: str
    rep: int
    started_at: float
    wall_s: float
    timed_out: bool
    exit_code: int | None
    prover: ProverStats
    harness: HarnessStats
    net: NetStats
    api_calls: list[ApiCall]  # every TLS request/response seen, API hosts or not
    tools_busy_s: float | None
    inference_s: float  # == net.api_busy_s
    verify: VerifyResult
    solved: bool
    provider_error: str | None = None  # the provider refused (quota, rate limit, billing): not a proving outcome; `run` redoes it
    suspended_s: float = 0.0  # seconds the machine was suspended during the attempt (clocks ran, nothing did): invalid if > 0
    invocation: str | None = None  # "<commit>-<start time>" of the `rlb run` that produced this attempt (one ledger entry)
    inputs_hash: str | None = None  # hash of everything reproducible that shaped this sample: same hash, same distribution
    graded: str = "main"  # the agent's file, or "assembled (L1, ...)": it with subagents' lemma proofs spliced in
    subattempts: list = field(default_factory=list)  # delegated lemmas: one summary each; records under sub/<id>/
    schema: str = "rlb.attempt/2"  # bump when a field's meaning changes; never reuse a name

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SubRun:
    """Where and how a subagent's attempt on a delegated lemma runs (built by delegate.Broker)."""
    attempt_dir: Path  # inside the delegating attempt's record: <attempt>/sub/<request id>/
    workdir: Path
    stop: threading.Event  # set when the delegating agent cancels, or finishes
    prompt_suffix: str  # the delegation note and the hint
    allowed_assumptions: tuple[str, ...]  # lemmas admitted above the delegated one


def render_prompt(cfg: Config, problem: Problem) -> str:
    text = string.Template(cfg.prompt_text()).substitute(file=problem.file_name, theorem=problem.name)
    native = HARNESSES[cfg.harness].native_subagents_prompt
    if native:  # agy: cannot be disabled, so the model is told
        text = text.rstrip("\n") + "\n\n" + native + "\n"
    if cfg.subagent is not None:
        text = text.rstrip("\n") + "\n\n" + LEMMA_PROMPT.substitute(
            file=problem.file_name, timeout=f"{cfg.subagent.timeout_s // 60} minutes") + "\n"
    return text


LEMMA_PROMPT = string.Template("""\
You can hand lemmas to subagents: other agents, each working alone in its own sandbox on one \
lemma, without access to your files or this conversation. State the lemma in $file before its first \
use, as `Lemma L : ... .` followed by `Proof.` and `Admitted.`, then run \
`python3 lemma.py prove L --hint "..."` (the hint is optional and reaches the subagent verbatim; \
it sees your file up to L). The command runs as long as the subagent does, at most $timeout, and \
prints `L: proved` (exit 0) or why not together with the subagent's closing message (exit 1); \
killing the command stops the subagent. To keep working meanwhile, run it in the background like \
any other long command, e.g. `python3 lemma.py prove L > L.out 2>&1 &`, and read L.out later. \
You never need to read or copy a subagent's proof: in the graded file each proved lemma's proof \
replaces its `Admitted`, for as long as your file states the lemma exactly as delegated. \
`python3 lemma.py assemble` builds that file and tells you whether it compiles.""")



STALL_AFTER_PROVIDER_ERROR_S = 120  # a refused agent that produces nothing for this long is not coming back


def _launch(argv: list[str], cwd: Path, env: dict, stdout_path: Path, stderr_path: Path, timeout: float,
            is_provider_error=lambda line: False, stop: threading.Event | None = None):
    """Run argv, streaming stdout lines with arrival times. Kills the whole
    process group on timeout, or once a provider refusal has been seen and
    stdout has been silent for STALL_AFTER_PROVIDER_ERROR_S (pi, for one,
    waits out the whole timeout after a 429)."""
    lines: list[Line] = []
    state = {"last": time.time(), "refused": False}
    susp0 = time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()
    times_path = stdout_path.with_suffix(".times")  # one arrival epoch per stdout line
    with open(stdout_path, "w") as out, open(times_path, "w") as times, open(stderr_path, "w") as err:
        p = subprocess.Popen(
            argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err,
            text=True, start_new_session=True,
        )
        t_start = time.time()

        def reader():
            assert p.stdout is not None
            for line in p.stdout:
                t = time.time()
                lines.append((t, line.rstrip("\n")))
                out.write(line)
                out.flush()
                times.write(f"{t:.3f}\n")
                state["last"] = t
                if not state["refused"] and is_provider_error(line):
                    state["refused"] = True

        th = threading.Thread(target=reader, daemon=True)
        th.start()
        timed_out = False
        deadline = t_start + timeout
        while True:
            try:
                p.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                now = time.time()
                stalled = state["refused"] and now - state["last"] > STALL_AFTER_PROVIDER_ERROR_S
                stopped = stop is not None and stop.is_set()
                if now < deadline and not stalled and not stopped:
                    continue
                timed_out = not stalled and not stopped
                err.write(f"[rlb] {'timeout' if timed_out else 'stopped by the delegating agent' if stopped else 'stalled after provider refusal'} at {now - t_start:.0f}s: SIGTERM to the process group\n")
                err.flush()
                os.killpg(p.pid, signal.SIGTERM)
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    err.write(f"[rlb] still alive after 10s: SIGKILL\n")
                    err.flush()
                    os.killpg(p.pid, signal.SIGKILL)
                    p.wait()
                err.write(f"[rlb] exited rc={p.returncode} at {time.time() - t_start:.0f}s\n")
                err.flush()
                break
        t_end = time.time()
        th.join(timeout=5)
    suspended = (time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()) - susp0
    return lines, p.returncode, timed_out, t_start, t_end, suspended


def inputs_hash(cfg: Config, problem: Problem, prompt: str, tools: dict, timeout_s: int) -> str:
    """The reproducible inputs of an attempt: config, rendered prompt, task
    file, harness argv shape, tool versions, timeout. Two attempts with the
    same hash are samples from the same distribution; what differs between
    them is inference nondeterminism and provider behaviour."""
    import hashlib
    harness = HARNESSES[cfg.harness]
    inv = harness.invocation(cfg, Path("/WORKDIR"), prompt)  # path-independent
    argv = [*inv.argv, *(f"{k}={v}" for k, v in sorted(inv.env.items()))]
    payload = json.dumps({
        "config": {k: v for k, v in cfg.to_dict().items() if k != "path"},
        "prompt": prompt, "task": problem.task_source(), "argv": argv,
        "api_hosts": list(harness.api_hosts(cfg)) + list(harness.aux_hosts), "tools": tools, "timeout_s": timeout_s,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def run_attempt(
    cfg: Config, problem: Problem, tc: Toolchain, run_dir: Path, work_root: Path, run_id: str,
    rep: int = 0, force: bool = False, log=print, invocation: str | None = None, tools: dict | None = None,
    sub: SubRun | None = None,
) -> Attempt:
    """One sandboxed attempt. `sub`: this is a subagent's attempt on a delegated lemma (see
    delegate.py): it lives inside the delegating attempt's record and is never skipped or redone."""
    harness = HARNESSES[cfg.harness]
    api_hosts = harness.api_hosts(cfg)
    for tool, pkg in (("pasta", "passt"), ("bwrap", "bubblewrap"), ("nft", "nftables"), ("mitmdump", "mitmproxy")):
        if shutil.which(tool) is None:
            raise SystemExit(f"`{tool}` not on PATH (nixpkgs `{pkg}`; the flake's dev shell has it)")
    attempt_dir = sub.attempt_dir if sub else run_dir / cfg.name / problem.name / f"r{rep}"
    record = attempt_dir / "attempt.json"
    if record.exists() and force and not sub:
        # results/ is append-only: a tracked record is never rewritten, --force only redoes uncommitted ones.
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(record)], capture_output=True, cwd=ROOT).returncode == 0
        if tracked:
            raise SystemExit(f"{record} is committed; --force cannot overwrite it (run a new rep with --repeat or a new --run-id)")
    if record.exists() and not force and not sub:
        # One valid sample per (config, problem). Invalid attempts (provider refusal,
        # suspend, rule violation: the sandbox now prevents the last) stay on disk
        # (results/ is append-only) and are redone as the next free rep; reports
        # exclude them. A valid sample at any rep means nothing to do.
        reps = []
        while (run_dir / cfg.name / problem.name / f"r{len(reps)}" / "attempt.json").exists():
            d = run_dir / cfg.name / problem.name / f"r{len(reps)}"
            reps.append(reinterpret(json.loads((d / "attempt.json").read_text()), d))
        valid = [(i, a) for i, a in enumerate(reps) if a["invalid"] is None]
        if valid:
            log(f"[{cfg.name}] {problem.name} r{valid[0][0]}: already done, skipping")
            return _load_attempt(run_dir / cfg.name / problem.name / f"r{valid[0][0]}" / "attempt.json")
        rep = len(reps)
        log(f"[{cfg.name}] {problem.name}: r{rep} redoes an invalid attempt ({reps[-1]['invalid'][:60]})")
        attempt_dir = run_dir / cfg.name / problem.name / f"r{rep}"
        record = attempt_dir / "attempt.json"
    if attempt_dir.exists():
        shutil.rmtree(attempt_dir)
    attempt_dir.mkdir(parents=True)

    # The agent works outside the repo so that Claude Code / Codex / pi do not
    # discover this machine's CLAUDE.md / AGENTS.md walking up from cwd.
    workdir = sub.workdir if sub else work_root / run_id / cfg.name / problem.name / f"r{rep}"
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    (workdir / problem.file_name).write_text(problem.task_source())
    if cfg.subagent is not None:
        (workdir / "lemma.py").write_text(
            Path(lemma_tool.__file__).read_text().replace('"__MAIN_FILE__"', repr(problem.file_name)))

    shim_dir = make_shim_dir(run_dir / "shim", tc.bin_dir)
    # Inside the workdir: sandboxed harnesses (Codex) cannot write elsewhere.
    trace = workdir / ".rlb" / "trace.tsv"
    trace.parent.mkdir()
    base_env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
    base_env.update(cfg.env)
    env = shim_env(shim_dir, tc.bin_dir, trace, base_env)

    prompt = render_prompt(cfg, problem) + (sub.prompt_suffix if sub else "")
    (attempt_dir / "prompt.md").write_text(prompt)
    inv = harness.invocation(cfg, workdir, prompt)
    env.update(inv.env)
    (attempt_dir / "argv.json").write_text(json.dumps(inv.argv, indent=1))
    pcap = attempt_dir / "net.pcap"
    home = Path.home()
    ca_dir = work_root / run_id / "ca"  # created by cli.cmd_run (ensure_ca) before attempts start; key stays out of results/
    if not (ca_dir / "mitmproxy-ca-cert.pem").exists():
        raise SystemExit(f"{ca_dir}: proxy CA missing (ensure_ca must run before attempts)")
    api_log = attempt_dir / "api.jsonl"
    spec = SandboxSpec(
        argv=inv.argv, workdir=str(workdir), allowed_hosts=[*api_hosts, *harness.aux_hosts],
        ro_paths=[str(tc.bin_dir.parent), str(shim_dir)],
        rw_paths=[str(home / p) for p in harness.state_paths if (home / p).exists()],
        uid=os.getuid(), gid=os.getgid(), home=str(home), pcap=str(pcap), ca_dir=str(ca_dir), api_log=str(api_log),
        passthrough_hosts=list(harness.passthrough_hosts),
    )
    spec_path = attempt_dir / "sandbox.json"
    SandboxSpec.write(spec, spec_path)

    log(f"[{cfg.name}] {problem.name} r{rep}: running (timeout {cfg.timeout_s}s)")
    def refused(line: str) -> bool:
        line = line.strip()
        if not line.startswith("{"):
            return False
        try:
            return harness.provider_error(json.loads(line)) is not None
        except json.JSONDecodeError:
            return False

    broker = None
    if cfg.subagent is not None:
        from .delegate import Broker
        broker = Broker(cfg, problem, workdir, attempt_dir, tc, run_dir, work_root, run_id, rep,
                        deadline=time.time() + cfg.timeout_s, log=log, invocation=invocation, tools=tools)
        broker.start()
    try:
        lines, code, timed_out, t_start, t_end, suspended = _launch(
            sandbox_argv(spec_path, pcap), workdir, env, attempt_dir / "stdout.txt", attempt_dir / "stderr.txt", cfg.timeout_s,
            is_provider_error=refused, stop=sub.stop if sub else None,
        )
    finally:
        subattempts = broker.stop() if broker else []  # the main agent is done: cancel what still runs
    wall = t_end - t_start
    pcap_calls = parse_pcap(pcap)
    (attempt_dir / "net.json").write_text(json.dumps([asdict(c) for c in pcap_calls], indent=1))
    proxy_calls, proxy_violations, tokens, blocked = parse_api_log(api_log)
    # The proxy sees requests in the clear: exact boundaries and usage. The capture is the cross-check.
    # Hosts passed through the proxy un-inspected are only visible in the capture.
    passthrough = [c for c in pcap_calls if c.host in harness.passthrough_hosts]
    api_calls = (proxy_calls + passthrough) if proxy_calls else pcap_calls
    net = NetStats.from_calls(api_calls, api_hosts)
    net.source = ("proxy+pcap" if passthrough else "proxy") if proxy_calls else "pcap"
    net.pcap_busy_s = NetStats.from_calls(pcap_calls, api_hosts).api_busy_s
    net.tokens_in, net.tokens_out, net.tokens_cached = tokens
    net.blocked = blocked

    if trace.exists():
        shutil.move(trace, attempt_dir / "trace.tsv")
    for leftover in trace.parent.iterdir() if trace.parent.exists() else []:
        if leftover.name != "delegate":  # delegation requests/results stay with the attempt's record
            shutil.rmtree(leftover) if leftover.is_dir() else leftover.unlink()
    if trace.parent.exists() and not any(trace.parent.iterdir()):
        trace.parent.rmdir()
    prover = ProverStats.from_calls(parse_trace(attempt_dir / "trace.tsv"))
    hs = harness.stats(lines)
    if not hs.provider_errors and (hs.error or "").startswith("no result event"):
        # a refusal before the first turn reaches stderr only (Cursor's ActionRequiredError, CLI startup failures)
        err_text = (attempt_dir / "stderr.txt").read_text(errors="replace").strip()[-600:]
        if is_provider_error(err_text):
            hs.provider_errors.append(err_text.splitlines()[-1][:300])
    hs.violations = [*proxy_violations, *hs.violations]
    tools_busy = union_seconds(hs.tool_intervals) if hs.tool_intervals is not None else None
    inference = net.api_busy_s

    sol = workdir / problem.file_name
    text = sol.read_text() if sol.exists() else None
    graded = "main"
    if text is not None and cfg.subagent is not None:
        # the same assembly the agent's `python3 lemma.py assemble` performs (identity without lemmas)
        assembled, inlined = lemma_tool.assemble(workdir, text)
        if inlined:
            text, graded = assembled, f"assembled ({', '.join(inlined)})"
            (attempt_dir / "graded.v").write_text(text)
    vr = verify(problem, text, tc, attempt_dir / "verify", sub.allowed_assumptions if sub else ())
    provider_error = detect_provider_error(hs, vr.ok)

    shutil.copytree(workdir, attempt_dir / "workdir", symlinks=True)
    shutil.rmtree(workdir)

    att = Attempt(
        run_id=run_id, config=cfg.to_dict(), problem=problem.name, tier=problem.tier, domain=problem.domain,
        rep=rep, started_at=t_start, wall_s=wall, timed_out=timed_out, exit_code=code,
        prover=prover, harness=hs, net=net, api_calls=api_calls, tools_busy_s=tools_busy, inference_s=inference,
        verify=vr, solved=vr.ok, provider_error=provider_error, suspended_s=round(suspended, 1), invocation=invocation,
        inputs_hash=inputs_hash(cfg, problem, prompt, tools or {}, cfg.timeout_s), graded=graded,
        subattempts=subattempts,
    )
    record.write_text(json.dumps(att.to_dict(), indent=1, allow_nan=False))
    log(
        f"[{cfg.name}] {problem.name} r{rep}: "
        + ("PROVIDER-ERROR " + provider_error[:80] if provider_error else f"VIOLATION {hs.violations[0][:70]}" if hs.violations
           else f"SUSPENDED {suspended:.0f}s" if suspended > SUSPEND_TOLERANCE_S
           else ('SOLVED' if att.solved else 'FAILED(' + vr.status + ')'))
        + f"{' TIMEOUT' if timed_out else ''} wall={wall:.0f}s prover={prover.busy_s:.1f}s/{prover.calls} calls "
        f"inference={inference:.0f}s/{net.api_calls} calls"
        + (f" (harness says {hs.inference_s:.0f}s)" if hs.inference_s is not None else "")
    )
    return att


SUSPEND_TOLERANCE_S = 5.0

# Reference material no attempt may touch: this repo's flake snapshots in the Nix store
# (which contain every problem's .ref.v) and reference files by name. Harness-independent:
# matched against the raw event stream, so any tool call or output mentioning them counts.
REFERENCE_ACCESS_RE = re.compile(r"/nix/store/[a-z0-9]{32}-source/(problems|results|prompts|vendor)/|\.ref\.v\b")


def reference_access(attempt_dir: Path) -> str | None:
    out_path = attempt_dir / "stdout.txt"
    if not out_path.exists():
        return None
    for line in out_path.read_text(errors="replace").splitlines():
        m = REFERENCE_ACCESS_RE.search(line)
        if m:
            i = max(0, m.start() - 80)
            return "reference material reached: " + line[i:m.end() + 60].replace("\\n", " ")
    return None


def unauthorized_subagent(att: dict, attempt_dir: Path) -> str | None:
    """An agent call the attempt's config does not allow (any subagent under "none"; tools that
    reach agents beyond the declared subagents in every config): the harness failed to block it,
    which is a sandbox failure (like a dead network), not a choice the model was offered."""
    evidence = HARNESSES[att["config"]["harness"]].unauthorized_agent_call(native_subagents_allowed(att["config"]), attempt_dir)
    return f"sandbox failure: unauthorized subagent call ({evidence})" if evidence else None


def sub_invalid(att: dict, attempt_dir: Path) -> str | None:
    """A composite attempt is a sample only if every subagent attempt in it is: a provider refusal
    or sandbox failure inside one is an abnormal failure of the whole."""
    for s in att.get("subattempts") or []:
        d = attempt_dir / "sub" / s["id"]
        if (d / "attempt.json").exists():
            sa = reinterpret(json.loads((d / "attempt.json").read_text()), d)
            if sa["invalid"]:
                return f"subagent attempt {s['id']} invalid: {sa['invalid'][:120]}"
    return None


def invalid_reason(att: dict) -> str | None:
    """Why this attempt is not a sample of the (config, problem) distribution:
    the provider refused, the machine suspended while it ran, or the agent
    broke a rule (web tools). None if valid."""
    if att.get("provider_error"):
        return att["provider_error"]
    if att.get("sandbox_failure"):
        return att["sandbox_failure"]
    v = (att.get("harness") or {}).get("violations") or []
    if v:
        return f"rule violation: {v[0]} (+{len(v) - 1} more)" if len(v) > 1 else f"rule violation: {v[0]}"
    if (att.get("suspended_s") or 0) > SUSPEND_TOLERANCE_S:
        return f"machine suspended {att['suspended_s']:.0f}s during the attempt"
    net = att.get("net") or {}
    if not att["solved"] and not net.get("calls") and not net.get("api_calls"):
        # Every real attempt makes at least one inference call; none means the sandbox's
        # network never worked (seen: pasta pre-binding the proxy port, Codex retrying for an hour).
        return "no API call left the sandbox (network/proxy failure)"
    return None


def reinterpret(att: dict, attempt_dir: Path) -> dict:
    """Apply today's provider-error rule to a stored attempt. Records are
    never rewritten (results/ is append-only); the transcript is re-read so
    old records get the same classification as new ones."""
    if "provider_errors" not in att["harness"] or "violations" not in att["harness"]:
        times_path, out_path = attempt_dir / "stdout.times", attempt_dir / "stdout.txt"
        if times_path.exists() and out_path.exists():
            times = [float(x) for x in times_path.read_text().split()]
            lines = list(zip(times, out_path.read_text(errors="replace").splitlines()))
            st = HARNESSES[att["config"]["harness"]].stats(lines)
            att["harness"]["provider_errors"] = st.provider_errors
            att["harness"]["violations"] = st.violations
        else:
            att["harness"].setdefault("provider_errors", [])
            att["harness"].setdefault("violations", [])
    if att.get("net", {}).get("source") == "proxy" and "tokens_in" not in att["net"]:
        _, _, (att["net"]["tokens_in"], att["net"]["tokens_out"], att["net"]["tokens_cached"]), att["net"]["blocked"] = parse_api_log(attempt_dir / "api.jsonl")
    ref = reference_access(attempt_dir)
    if ref and ref not in (att["harness"].get("violations") or []):
        att["harness"]["violations"] = [ref, *(att["harness"].get("violations") or [])]
    att["sandbox_failure"] = unauthorized_subagent(att, attempt_dir) or sub_invalid(att, attempt_dir)
    att["provider_error"] = detect_provider_error(HarnessStats(**att["harness"]), att["solved"])
    att["invalid"] = invalid_reason(att)
    return att


def load_attempts(dirs: list[Path]) -> list[dict]:
    """Every attempt.json under the given result dirs, reinterpreted."""
    out = []
    for d in dirs:
        for f in sorted(Path(d).glob("*/*/r*/attempt.json")):  # not sub/<id>/attempt.json: part of their parent
            out.append(reinterpret(json.loads(f.read_text()), f.parent))
    return out


def parse_api_log(path: Path) -> tuple[list[ApiCall], list[str], tuple[int, int, int], list[str]]:
    """The proxy's records -> ApiCalls (exact), violations, (in, out, cached)
    tokens, and blocked requests (endpoints off the allowlist: recorded, not
    a violation, since nothing came back)."""
    from .proxy_policy import normalize_usage
    calls: list[ApiCall] = []
    violations: list[str] = []
    blocked: list[str] = []
    tin = tout = tcached = 0
    if not path.exists():
        return calls, violations, (0, 0, 0), blocked
    for line in path.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("event") == "blocked":
            blocked.append(f"{r.get('method', '')} {r['host']}{r.get('path', '')}")
        if r.get("violation"):
            violations.append(r["violation"])
        if r.get("event") == "call" and r.get("t_sent"):
            calls.append(ApiCall(host=r["host"], port=0, start=r["t_sent"], first=r.get("t_first"),
                                 end=r.get("t_last") or r["t_sent"], req_bytes=r.get("req_bytes", 0),
                                 resp_bytes=r.get("resp_bytes", 0)))
            i, o, c = normalize_usage(r.get("usage"))
            tin, tout, tcached = tin + i, tout + o, tcached + c
    return sorted(calls, key=lambda c: c.start), violations, (tin, tout, tcached), blocked


def detect_provider_error(hs: HarnessStats, solved: bool) -> str | None:
    """An unsolved trial during which the provider refused an inference call
    is invalid: the failure cannot be attributed to the model. A solved one
    stands (the agent got through anyway; the refusal only cost time)."""
    if solved or not hs.provider_errors:
        return None
    return hs.provider_errors[0].strip()[:300]


def _load_attempt(record: Path) -> Attempt:
    d = json.loads(record.read_text())
    d["prover"] = ProverStats(**d["prover"])
    d["harness"] = HarnessStats(**d["harness"])
    d["net"] = NetStats(**d["net"])
    d["api_calls"] = [ApiCall(**c) for c in d["api_calls"]]
    d["verify"] = VerifyResult(**d["verify"])
    return Attempt(**d)
