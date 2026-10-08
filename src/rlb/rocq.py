"""Rocq toolchain discovery and solution verification.

Verification re-proves the ORIGINAL statement in a fresh file that `Require`s
(but does not `Import`) the agent's file, so the agent's notations, hints and
scopes cannot change what the statement means:

    <original imports + preamble>
    Require Solution.
    Theorem <name> : <original statement>.
    Proof. <revert all hypotheses> exact @Solution.<name>. Qed.

(`@` so that implicit binders such as `{U : Type}` are not instantiated with evars.)
    Print Assumptions <name>.

Then every printed assumption is `Locate`d and must live under Stdlib/Corelib.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import ROOT
from .problem import Problem

ALLOWED_AXIOM_PREFIXES = ("Stdlib.", "Corelib.")
COQC_TIMEOUT_S = 300

# `Theorem name (binders) : goal` auto-introduces the binders at `Proof.`; put
# them back so the goal is the full statement again. `revert` fails on a
# hypothesis others depend on, and `match goal` then tries the next one.
REVERT_ALL = "repeat match goal with H : _ |- _ => revert H end."


@dataclass(frozen=True)
class Toolchain:
    bin_dir: Path

    @property
    def coqc(self) -> Path:
        return self.bin_dir / "coqc"

    def version(self) -> str:
        out = subprocess.run([str(self.coqc), "--version"], capture_output=True, text=True)
        return out.stdout.strip().splitlines()[0] if out.stdout else out.stderr.strip()

    @staticmethod
    def discover(explicit: str | None = None) -> Toolchain:
        cands = [explicit, os.environ.get("RLB_ROCQ_BIN"), ROOT / "_opam" / "bin"]
        for c in cands:
            if c and (Path(c) / "coqc").exists():
                return Toolchain(Path(c).resolve())
        w = shutil.which("coqc")
        if w:
            return Toolchain(Path(w).resolve().parent)
        raise SystemExit("no Rocq toolchain: pass --rocq-bin, set RLB_ROCQ_BIN, or run scripts/setup-rocq.sh")


@dataclass
class CoqcRun:
    ok: bool
    seconds: float
    stdout: str
    stderr: str
    timed_out: bool = False


def coqc(tc: Toolchain, cwd: Path, file: str, timeout: float = COQC_TIMEOUT_S) -> CoqcRun:
    t0 = time.monotonic()
    try:
        p = subprocess.run(
            [str(tc.coqc), "-q", file], cwd=cwd, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "RLB_TRACE": ""},  # never let verification hit a timing shim
        )
    except subprocess.TimeoutExpired as e:
        return CoqcRun(False, time.monotonic() - t0, e.stdout or "", e.stderr or "", timed_out=True)
    return CoqcRun(p.returncode == 0, time.monotonic() - t0, p.stdout, p.stderr)


@dataclass
class VerifyResult:
    status: str  # ok | missing | compile_error | statement_mismatch | axioms | locate_error | timeout
    message: str = ""
    assumptions: list[tuple[str, str]] = field(default_factory=list)  # (printed name, full path)
    check_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict:
        return asdict(self)


_AXIOM_LINE_RE = re.compile(r"^(\S+) :(?:\s|$)")
_LOCATE_RE = re.compile(r"^Constant (\S+)")


_BYPASSED_CHECK_RE = re.compile(r"^(\S+) is assumed to be (guarded|positive|universe.?consistent|.*)\.?$")


class BypassedCheck(Exception):
    """`Print Assumptions` reports a definition that bypassed a kernel check
    (`Unset Guard Checking`, `#[bypass_check(...)]`): the solution is unsound
    by construction and is rejected outright."""


def parse_assumptions(stdout: str) -> list[str] | None:
    """Names printed by `Print Assumptions`; [] if closed; None if unparseable.
    Raises BypassedCheck for a disabled guard/positivity/universe check."""
    lines = stdout.splitlines()
    if any(l.startswith("Closed under the global context") for l in lines):
        return []
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith("Axioms:"))
    except StopIteration:
        return None
    names = []
    for l in lines[start + 1:]:
        if not l or l[0].isspace():
            continue  # continuation of a multi-line type
        b = _BYPASSED_CHECK_RE.match(l)
        if b:
            raise BypassedCheck(l.strip())
        m = _AXIOM_LINE_RE.match(l)
        if m is None:
            return None
        names.append(m.group(1))
    return names


def verify(problem: Problem, solution_src: str | None, tc: Toolchain, scratch: Path,
           allowed_assumptions: tuple[str, ...] = ()) -> VerifyResult:
    """Verify `solution_src` (the agent's whole file) against `problem` in `scratch`.
    `allowed_assumptions`: names in the problem's header that the proof may use although they are
    admitted there (a delegated lemma may rely on lemmas the delegating agent has not proved yet)."""
    t0 = time.monotonic()
    if solution_src is None:
        return VerifyResult("missing", "no solution file")
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True)
    (scratch / "Solution.v").write_text(solution_src)

    def done(status: str, msg: str = "", assumptions=()) -> VerifyResult:
        return VerifyResult(status, msg, list(assumptions), time.monotonic() - t0)

    r = coqc(tc, scratch, "Solution.v")
    if r.timed_out:
        return done("timeout", "coqc Solution.v timed out")
    if not r.ok:
        return done("compile_error", r.stderr[-4000:])

    name = problem.name
    (scratch / "Verify.v").write_text(
        f"{problem.header()}\n\nRequire Solution.\n\n{problem.statement.rstrip()}\n"
        f"Proof. {REVERT_ALL} exact @Solution.{name}. Qed.\nPrint Assumptions {name}.\n"
    )
    r = coqc(tc, scratch, "Verify.v")
    if r.timed_out:
        return done("timeout", "coqc Verify.v timed out")
    if not r.ok:
        return done("statement_mismatch", r.stderr[-4000:])
    try:
        names = parse_assumptions(r.stdout)
    except BypassedCheck as e:
        return done("axioms", f"kernel check bypassed: {e}")
    if names is None:
        return done("locate_error", "could not parse Print Assumptions output:\n" + r.stdout[-2000:])
    if not names:
        return done("ok")

    (scratch / "Axioms.v").write_text(
        f"{problem.header()}\n\nRequire Solution.\n\n" + "".join(f"Locate Term {n}.\n" for n in names)
    )
    r = coqc(tc, scratch, "Axioms.v")
    if not r.ok:
        return done("locate_error", r.stderr[-4000:])
    full = [m.group(1) for l in r.stdout.splitlines() if (m := _LOCATE_RE.match(l))]
    if len(full) != len(names):
        return done("locate_error", f"expected {len(names)} Locate results, got {len(full)}:\n{r.stdout[-2000:]}")
    pairs = list(zip(names, full))
    bad = [f for _, f in pairs if not f.startswith(ALLOWED_AXIOM_PREFIXES)
           and f not in {f"Solution.{a}" for a in allowed_assumptions}]
    if bad:
        return done("axioms", "non-stdlib assumptions: " + ", ".join(bad), pairs)
    return done("ok", "", pairs)
