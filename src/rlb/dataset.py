"""Select a benchmark subset from rocq-workbook and write problems/."""
from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from . import ROOT
from .problem import Problem
from .rocq import Toolchain, verify

TIERS = ("easy", "medium", "hard")
DATASET = ROOT / "vendor" / "rocq-workbook" / "rocq_workbook_10k.jsonl"


def load_records(path: Path = DATASET) -> list[dict]:
    with open(path) as f:
        return [json.loads(l) for l in f]


def candidates(records: list[dict]) -> dict[str, list[Problem]]:
    """Stdlib-only problems with a reference proof, in the shape the verifier
    handles. Requiring a reference proof guarantees the statement is provable
    (the Lean workbook contains false statements) at the cost of a selection
    bias toward problems some prover has already solved."""
    out: dict[str, list[Problem]] = {t: [] for t in TIERS}
    for r in records:
        if r["rocq_library"] != "stdlib" or not r["rocq_proved"]:
            continue
        p = Problem.from_record(r)
        if p is not None and p.tier in out:
            out[p.tier].append(p)
    return out


def round_robin_by_domain(problems: list[Problem], rng: random.Random) -> Iterator[Problem]:
    """Cycle through domains so a 10-problem tier is not 70% inequalities."""
    groups: dict[str, list[Problem]] = defaultdict(list)
    for p in sorted(problems, key=lambda p: p.name):  # deterministic before shuffling
        groups[p.domain].append(p)
    order = sorted(groups)
    rng.shuffle(order)
    for g in groups.values():
        rng.shuffle(g)
    while any(groups.values()):
        for d in order:
            if groups[d]:
                yield groups[d].pop()


@dataclass
class Selected:
    problem: Problem
    ref_proof_lines: int
    ref_check_s: float


def select(per_tier: int, seed: int, tc: Toolchain, out_dir: Path, records: list[dict] | None = None, log=print) -> dict:
    records = records if records is not None else load_records()
    cands = candidates(records)
    rng = random.Random(seed)
    scratch = out_dir / ".scratch"
    chosen: dict[str, list[Selected]] = {}
    rejected: list[tuple[str, str, str]] = []
    for tier in TIERS:
        chosen[tier] = []
        for p in round_robin_by_domain(cands[tier], rng):
            if len(chosen[tier]) >= per_tier:
                break
            vr = verify(p, p.ref_source(), tc, scratch)
            if not vr.ok:
                rejected.append((tier, p.name, f"{vr.status}: {vr.message.strip().splitlines()[-1] if vr.message else ''}"))
                log(f"  reject {p.name} ({tier}): {vr.status}")
                continue
            assert p.ref_proof is not None
            chosen[tier].append(Selected(p, len(p.ref_proof.strip().splitlines()), vr.check_s))
            log(f"  accept {p.name} ({tier}/{p.domain}) ref {chosen[tier][-1].ref_proof_lines} lines, check {vr.check_s:.1f}s")
        if len(chosen[tier]) < per_tier:
            raise SystemExit(f"only {len(chosen[tier])} verified candidates in tier {tier}")

    import shutil
    shutil.rmtree(scratch, ignore_errors=True)
    entries = []
    for tier in TIERS:
        d = out_dir / tier
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        for s in chosen[tier]:
            (d / s.problem.file_name).write_text(s.problem.task_source())
            (d / f"{s.problem.name}.ref.v").write_text(s.problem.ref_source())
            entries.append({
                **s.problem.to_dict(),
                "file": f"{tier}/{s.problem.file_name}",
                "ref_file": f"{tier}/{s.problem.name}.ref.v",
                "ref_proof_lines": s.ref_proof_lines,
                "ref_check_s": s.ref_check_s,
            })
    manifest = {
        "seed": seed, "per_tier": per_tier, "dataset": str(DATASET.relative_to(ROOT)),
        "rocq": tc.version(), "candidates_per_tier": {t: len(cands[t]) for t in TIERS},
        "rejected": rejected, "problems": entries,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def load_manifest(problems_dir: Path) -> list[dict]:
    return json.loads((problems_dir / "manifest.json").read_text())["problems"]


def write_tier(out_dir: Path, tier: str, selected: list[Selected], meta: dict) -> None:
    """Replace one tier's files and manifest entries; other tiers untouched.
    `meta` is recorded under manifest["tiers"][tier] (source, criteria)."""
    import shutil
    mpath = out_dir / "manifest.json"
    manifest = json.loads(mpath.read_text())
    d = out_dir / tier
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    entries = [e for e in manifest["problems"] if e["tier"] != tier]
    for s in selected:
        (d / s.problem.file_name).write_text(s.problem.task_source())
        e = {**s.problem.to_dict(), "file": f"{tier}/{s.problem.file_name}", "ref_check_s": s.ref_check_s}
        if s.problem.has_ref():
            (d / f"{s.problem.name}.ref.v").write_text(s.problem.ref_source())
            e["ref_file"] = f"{tier}/{s.problem.name}.ref.v"
            e["ref_proof_lines"] = s.ref_proof_lines
        entries.append(e)
    manifest["problems"] = entries
    manifest.setdefault("tiers", {})[tier] = meta
    mpath.write_text(json.dumps(manifest, indent=1))


def select_workbook_tier(
    tier: str, min_ref_lines: int, n: int, seed: int, tc: Toolchain, out_dir: Path, log=print,
) -> list[Selected]:
    """A workbook tier by reference-proof length (the dataset's own difficulty
    label does not track what agents find hard). Refs verified as in `select`."""
    from dataclasses import replace
    cands = [replace(p, tier=tier) for ps in candidates(load_records()).values() for p in ps
             if p.ref_proof is not None and len(p.ref_proof.strip().splitlines()) >= min_ref_lines]
    rng = random.Random(seed)
    scratch = out_dir / ".scratch"
    chosen: list[Selected] = []
    for p in round_robin_by_domain(cands, rng):
        if len(chosen) >= n:
            break
        vr = verify(p, p.ref_source(), tc, scratch)
        if not vr.ok:
            log(f"  reject {p.name}: {vr.status}")
            continue
        chosen.append(Selected(p, len(p.ref_proof.strip().splitlines()), vr.check_s))
        log(f"  accept {p.name} ({p.domain}) ref {chosen[-1].ref_proof_lines} lines, check {vr.check_s:.1f}s")
    if len(chosen) < n:
        raise SystemExit(f"only {len(chosen)} verified candidates with ref >= {min_ref_lines} lines")
    import shutil
    shutil.rmtree(scratch, ignore_errors=True)
    write_tier(out_dir, tier, chosen, {"source": str(DATASET.relative_to(ROOT)), "min_ref_lines": min_ref_lines,
                                       "candidates": len(cands), "seed": seed})
    return chosen
