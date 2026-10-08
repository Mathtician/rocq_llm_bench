# Third-party material

This repository's own code and text are not yet licensed (see README, Status).
The files below are derived from third-party works and remain under those
works' licenses, copies of which are in [`third_party/`](third_party/).

## miniF2F-rocq (MIT)

- Source: <https://github.com/LLM4Rocq/miniF2F-rocq>, commit `d9480b5e4711a4a8e8334dad3ef2e72c2ec0efdd`
- Copyright (c) 2025 LLM4Rocq. License: MIT, [`third_party/miniF2F-rocq.LICENSE`](third_party/miniF2F-rocq.LICENSE)
- Derived files: `problems/imo/*.v`, `problems/aime/*.v`, the `imo` and `aime`
  entries of `problems/manifest.json`, and the statements restated in
  `problems_src/minif2f/counterexamples/*.v`.
- Changes: each upstream file is split into imports, preamble and theorem
  statement and reassembled with the proof replaced by `Proof. Admitted.`
  (`src/rlb/external.py`); statements are otherwise unchanged.

## Putnam2025-Rocq (Apache-2.0)

- Source: <https://github.com/LLM4Rocq/Putnam2025-Rocq>, commit `9e221268d01232e18b6c11822ea2b26463ae6ddd`
- Copyright 2026 Inria. License: Apache License 2.0, [`third_party/Putnam2025-Rocq.LICENSE`](third_party/Putnam2025-Rocq.LICENSE)
- Derived files: `problems/putnam/*.v` and the `putnam` entries of `problems/manifest.json`.
- Changes: as for miniF2F-rocq above (statement kept, proof replaced by
  `Proof. Admitted.`). Upstream's reference solutions are not included.

## rocq-workbook (no license: not redistributed)

<https://github.com/LLM4Rocq/rocq-workbook> carries no license, so none of its
content is included here. The easy, medium, hard and vhard tiers are built
locally from a clone in `vendor/rocq-workbook/` by `rlb select` and
`rlb tier vhard` (`src/rlb/dataset.py`).
