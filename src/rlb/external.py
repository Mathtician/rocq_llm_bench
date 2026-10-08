"""Problems from other Rocq formalizations, as tiers alongside the workbook.

  putnam   LLM4Rocq/Putnam2025-Rocq: the 2025 Putnam, statements plus
           machine-found reference proofs (300-1500 lines each). Only the
           problems whose statement the verifier can handle (no Inductive /
           Section / Axiom in the preamble) and whose reference verifies with
           our toolchain (Stdlib only): 9 of 12.
  imo, aime  LLM4Rocq/miniF2F-rocq: competition problems, statements only
           upstream (its audit marks 3 statements "wrong", excluded). Those
           whose statement compiles under Rocq 9.1.1 with only Stdlib.
           Reference proofs are verified benchmark solutions copied into
           problems_src/minif2f/ (scripts/harvest-minif2f-refs.py); a problem
           without one is imported unreferenced, a reference that fails to
           verify is an error. problems_src/minif2f/audit.json is our own
           faithfulness audit of every statement against the official
           problem: "wrong" (false) and "trivialized" (vacuous hypotheses)
           are excluded, each backed by a Rocq proof in counterexamples/;
           "weakened" ones stay and are tagged in the tier metadata.

A `.v` file is split into imports (Require/From/Open/Set lines and comments
before the first definition), preamble (definitions up to the theorem), and
the statement (`Theorem <name> ... .` up to `Proof`).
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import replace
from pathlib import Path

from . import ROOT
from .dataset import Selected, write_tier
from .problem import PREAMBLE_HAZARD_RE, Problem
from .rocq import Toolchain, verify

PUTNAM = ROOT / "vendor" / "Putnam2025-Rocq"
MINIF2F = ROOT / "vendor" / "miniF2F-rocq"

_STMT_RE = re.compile(r"^(Theorem\s+([A-Za-z_][A-Za-z0-9_']*)\b.*?\.)\s*\n\s*Proof\b", re.M | re.S)
_HEADER_LINE_RE = re.compile(r"^\s*(From\s|Require\s|Open\s+Scope|Set\s|Import\s|Local\s+Open)")


def split_v(src: str) -> tuple[str, str, str, str]:
    """(name, imports, preamble, statement) of a problem file."""
    m = _STMT_RE.search(src)
    if m is None:
        raise ValueError("no `Theorem <name> ... . Proof` found")
    stmt, name = m.group(1), m.group(2)
    head = src[: m.start()]
    lines = head.splitlines()
    # imports = leading run of header lines / comments / blanks; the rest is preamble
    i = 0
    depth = 0
    while i < len(lines):
        l = lines[i]
        depth += l.count("(*") - l.count("*)")
        if depth > 0 or l.strip().startswith("(*") or not l.strip() or _HEADER_LINE_RE.match(l):
            i += 1
            continue
        break
    imports = "\n".join(lines[:i]).strip()
    preamble = "\n".join(lines[i:]).strip()
    return name, imports, preamble, stmt.strip()


def _load(path: Path, tier: str, domain: str) -> Problem:
    name, imports, preamble, stmt = split_v(path.read_text())
    return Problem(name=name, tier=tier, domain=domain, imports=imports, preamble=preamble, statement=stmt, ref_proof=None)


def import_putnam(tc: Toolchain, out_dir: Path, log=print) -> list[Selected]:
    scratch = out_dir / ".scratch"
    chosen: list[Selected] = []
    for pf in sorted((PUTNAM / "problems").glob("putnam_2025_*.v")):
        p = _load(pf, "putnam", "putnam")
        if PREAMBLE_HAZARD_RE.search(p.preamble):
            log(f"  skip {p.name}: preamble construct the verifier cannot re-check")
            continue
        sol = PUTNAM / "solutions" / f"proof_{p.name.removeprefix('putnam_2025_')}.v"
        p = replace(p, ref_full=sol.read_text())
        vr = verify(p, p.ref_source(), tc, scratch)
        if not vr.ok:
            log(f"  reject {p.name}: {vr.status}: {(vr.message or '').strip().splitlines()[-1][:100] if vr.message else ''}")
            continue
        chosen.append(Selected(p, len(p.ref_full.splitlines()), vr.check_s))
        log(f"  accept {p.name}: ref {chosen[-1].ref_proof_lines} lines, check {vr.check_s:.1f}s")
    shutil.rmtree(scratch, ignore_errors=True)
    write_tier(out_dir, "putnam", chosen, {"source": "vendor/Putnam2025-Rocq", "commit": _head(PUTNAM)})
    return chosen


def import_minif2f(tier: str, prefix: str, tc: Toolchain, out_dir: Path, log=print) -> list[Selected]:
    """Accepted iff the task file (with `Admitted`) passes the verifier up to the expected single
    assumption (the theorem itself) and neither audit rejects it. `audit` is upstream's (edit
    history); `ours` (faithfulness) must cover every problem, so a new one cannot slip in unaudited."""
    audit = json.loads((MINIF2F / "audit.json").read_text())
    ours = json.loads((MINIF2F_REFS / "audit.json").read_text())
    scratch = out_dir / ".scratch"
    chosen: list[Selected] = []
    files = sorted(f for sub in ("test", "valid") for f in (MINIF2F / sub).glob(f"{prefix}_*.v"))
    for pf in files:
        try:
            p = _load(pf, tier, prefix)
        except ValueError as e:
            log(f"  skip {pf.name}: {e}")
            continue
        if (audit.get(p.name) or {}).get("status") == "wrong":
            log(f"  skip {p.name}: audit says wrong")
            continue
        if PREAMBLE_HAZARD_RE.search(p.preamble):
            log(f"  skip {p.name}: preamble hazard")
            continue
        vr = verify(p, p.task_source(), tc, scratch)
        if vr.status != "axioms" or [n for n, _ in vr.assumptions] != [f"Solution.{p.name}"]:
            log(f"  reject {p.name}: {vr.status}")
            continue
        if p.name not in ours:
            raise ValueError(f"{p.name}: statement compiles but is not in {MINIF2F_REFS / 'audit.json'}; audit it first")
        if ours[p.name]["status"] in AUDIT_EXCLUDED:
            log(f"  skip {p.name}: our audit says {ours[p.name]['status']} ({ours[p.name]['counterexample']})")
            continue
        ref = MINIF2F_REFS / f"{p.name}.ref.v"
        if ref.exists():
            p = replace(p, ref_full=ref.read_text())
            vr = verify(p, p.ref_source(), tc, scratch)
            if not vr.ok:
                raise ValueError(f"{ref}: reference check failed: {vr.status}\n{vr.message}")
        chosen.append(Selected(p, len(p.ref_full.splitlines()) if p.has_ref() else 0, vr.check_s))
        log(f"  accept {p.name} (ours: {ours[p.name]['status']}; "
            f"{'reference verified' if p.has_ref() else 'no reference'})")
    shutil.rmtree(scratch, ignore_errors=True)
    write_tier(out_dir, tier, chosen, {"source": "vendor/miniF2F-rocq", "commit": _head(MINIF2F), "prefix": prefix,
                                       "references": "problems_src/minif2f (verified benchmark solutions)",
                                       "audit": {s.problem.name: ours[s.problem.name]["status"] for s in chosen}})
    return chosen


MINIF2F_REFS = ROOT / "problems_src" / "minif2f"
AUDIT_EXCLUDED = ("wrong", "trivialized")
CUSTOM = ROOT / "problems_src" / "custom"


def import_dir(tier: str, src_dir: Path, tc: Toolchain, out_dir: Path, log=print) -> list[Selected]:
    """Hand-written problems: each `.v` is a complete proof; the file itself is
    the reference and the task is the same file with the proof replaced."""
    scratch = out_dir / ".scratch"
    chosen: list[Selected] = []
    for pf in sorted(src_dir.glob("*.v")):
        src = pf.read_text()
        p = replace(_load(pf, tier, tier), ref_full=src)
        if PREAMBLE_HAZARD_RE.search(p.preamble):
            raise SystemExit(f"{pf}: preamble construct the verifier cannot re-check")
        vr = verify(p, p.ref_source(), tc, scratch)
        if not vr.ok:
            raise SystemExit(f"{pf}: reference does not verify: {vr.status}\n{vr.message}")
        proof_lines = len(src[src.index("Proof."):].splitlines()) if "Proof." in src else 0
        chosen.append(Selected(p, proof_lines, vr.check_s))
        log(f"  accept {p.name}: proof {proof_lines} lines, check {vr.check_s:.1f}s")
    shutil.rmtree(scratch, ignore_errors=True)
    write_tier(out_dir, tier, chosen, {"source": str(src_dir.relative_to(ROOT))})
    return chosen


def _head(repo: Path) -> str:
    import subprocess
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
