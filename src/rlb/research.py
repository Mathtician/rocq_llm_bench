"""Curated research statements, with optional independently checked references."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from . import ROOT
from .dataset import Selected, write_tier
from .external import split_v
from .problem import PREAMBLE_HAZARD_RE, Problem
from .rocq import Toolchain, verify

SOURCE = ROOT / "problems_src" / "research"


def import_research(tc: Toolchain, out_dir: Path, log=print, src_dir: Path = SOURCE) -> list[Selected]:
    """Check every input before replacing the tier. Admitted inputs are statements,
    never evidence that a problem is solvable. References must pass the verifier.
    """
    metadata = json.loads((src_dir / "metadata.json").read_text())
    selected = []
    files = sorted(p for p in src_dir.glob("*.v") if not p.name.endswith(".ref.v"))
    if {p.stem for p in files} != set(metadata["problems"]):
        raise ValueError("research source files and metadata do not match")
    with TemporaryDirectory(prefix="rlb-research-") as tmp:
        for path in files:
            name, imports, preamble, statement = split_v(path.read_text())
            if name != path.stem or PREAMBLE_HAZARD_RE.search(preamble):
                raise ValueError(f"{path}: invalid name or unsupported preamble")
            info = metadata["problems"][name]
            ref = path.with_suffix(".ref.v")
            p = Problem(name, "research", info["domain"], imports, preamble, statement,
                        None, ref.read_text() if ref.exists() else None)
            vr = verify(p, p.task_source(), tc, Path(tmp) / "check")
            if vr.status != "axioms" or [n for n, _ in vr.assumptions] != [f"Solution.{name}"]:
                raise ValueError(f"{path}: statement check failed: {vr.status}\n{vr.message}")
            if p.has_ref():
                vr = verify(p, p.ref_source(), tc, Path(tmp) / "check")
                if not vr.ok:
                    raise ValueError(f"{ref}: reference check failed: {vr.status}\n{vr.message}")
            selected.append(Selected(p, len(p.ref_source().splitlines()) if p.has_ref() else 0, vr.check_s))
            log(f"  accept {name}: {'reference verified' if p.has_ref() else 'statement checked; no reference'}")
    write_tier(out_dir, "research", selected, metadata)
    return selected
