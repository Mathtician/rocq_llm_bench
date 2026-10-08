"""Copy verified benchmark solutions of imo/aime problems into problems_src/minif2f/ as reference proofs.

miniF2F-rocq ships statements only. A reference here is a solvability witness (as for every other
tier: the grader never reads it), so any valid, solved attempt will do. Existing references are
never replaced, so a reference, once chosen, stays the same file; refs.json records the attempt
each one was copied from. The tier importer (`rlb tier imo|aime`) re-verifies every reference.

    uv run python scripts/harvest-minif2f-refs.py            # report what would be added
    uv run python scripts/harvest-minif2f-refs.py --write
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rlb.external import AUDIT_EXCLUDED, MINIF2F_REFS  # noqa: E402
from rlb.runner import load_attempts  # noqa: E402

TIERS = ("imo", "aime")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    manifest = json.loads((ROOT / "problems" / "manifest.json").read_text())["problems"]
    audit = json.loads((MINIF2F_REFS / "audit.json").read_text())
    wanted = {p["name"] for p in manifest if p["tier"] in TIERS and audit[p["name"]]["status"] not in AUDIT_EXCLUDED}
    prov_path = MINIF2F_REFS / "refs.json"
    prov = json.loads(prov_path.read_text()) if prov_path.exists() else {}
    existing = len(prov)

    runs = sorted(p for p in (ROOT / "results").iterdir() if p.is_dir())
    candidates: dict[str, dict] = {}
    for att in load_attempts(runs):
        q = att["problem"]
        if q not in wanted or q in prov or att["invalid"] is not None or not att["solved"]:
            continue
        key = (att["run_id"], att["config"]["name"], att["rep"])
        if q not in candidates or key < candidates[q]["key"]:
            candidates[q] = {"key": key, "attempt": att}

    for q in sorted(candidates):
        run_id, config, rep = candidates[q]["key"]
        src = ROOT / "results" / run_id / config / q / f"r{rep}" / "workdir" / f"{q}.v"
        assert src.exists(), src
        print(f"{q}: {src.relative_to(ROOT)}")
        if a.write:
            MINIF2F_REFS.mkdir(parents=True, exist_ok=True)
            (MINIF2F_REFS / f"{q}.ref.v").write_text(src.read_text())
            prov[q] = {"run_id": run_id, "config": config, "rep": rep, "file": str(src.relative_to(ROOT))}
    missing = sorted(wanted - set(prov) - set(candidates))
    print(f"{len(candidates)} new, {existing} existing, "
          f"{len(missing)} without a verified solution: {' '.join(missing)}")
    if a.write:
        prov_path.write_text(json.dumps(dict(sorted(prov.items())), indent=1) + "\n")


if __name__ == "__main__":
    main()
