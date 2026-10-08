"""A benchmark problem: a Rocq file with one `Theorem <name>` left `Admitted`."""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict

# The theorem name must be the record id; `select` enforces this so that the
# verifier can refer to `Solution.<name>` without parsing anything else.
THEOREM_RE = re.compile(r"^Theorem\s+([A-Za-z_][A-Za-z0-9_']*)")

# Preamble constructs that would make `Verify.v`'s copy of the header
# non-convertible with `Solution.v`'s copy (two Inductives are distinct types;
# Parameters are distinct constants). Definitions and Fixpoints are fine: they
# unfold to structurally equal terms.
PREAMBLE_HAZARD_RE = re.compile(
    r"\b(Inductive|Record|Variant|Class|Structure|CoInductive|Parameter|Parameters|"
    r"Axiom|Axioms|Variable|Variables|Hypothesis|Hypotheses|Context|Section|Module)\b"
)

PLACEHOLDER_PROOF = "Proof.\nAdmitted."


@dataclass(frozen=True)
class Problem:
    name: str
    tier: str
    domain: str
    imports: str
    preamble: str
    statement: str
    ref_proof: str | None  # full `Proof. ... Qed.` block, or None
    ref_full: str | None = None  # a complete reference file instead (helper lemmas before the theorem), or None

    @property
    def file_name(self) -> str:
        return f"{self.name}.v"

    def header(self) -> str:
        parts = [self.imports.rstrip()]
        if self.preamble.strip():
            parts.append(self.preamble.rstrip())
        return "\n\n".join(parts)

    def source(self, proof: str) -> str:
        return f"{self.header()}\n\n{self.statement.rstrip()}\n{proof.rstrip()}\n"

    def task_source(self) -> str:
        return self.source(PLACEHOLDER_PROOF)

    def has_ref(self) -> bool:
        return self.ref_full is not None or self.ref_proof is not None

    def ref_source(self) -> str:
        if self.ref_full is not None:
            return self.ref_full
        assert self.ref_proof is not None, f"{self.name} has no reference proof"
        return self.source(self.ref_proof)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> Problem:
        return Problem(**{k: d.get(k) for k in Problem.__dataclass_fields__})

    @staticmethod
    def from_record(r: dict) -> Problem | None:
        """Build from a rocq-workbook JSONL record; None if the record is outside
        the shape this harness handles (see `select`)."""
        stmt = r["rocq_statement"]
        m = THEOREM_RE.match(stmt)
        if m is None or m.group(1) != r["name"]:
            return None
        pre = r.get("rocq_preamble") or ""
        if PREAMBLE_HAZARD_RE.search(pre):
            return None
        proof = r.get("rocq_proof") or ""
        return Problem(
            name=r["name"],
            tier=r["difficulty"],
            domain=r["domain"],
            imports=r["rocq_imports"],
            preamble=pre,
            statement=stmt,
            ref_proof=proof if (r.get("rocq_proved") and proof.strip()) else None,
        )
