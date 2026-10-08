#!/usr/bin/env python3
"""Reproduce the pilot medial-magma tasks and their kernel-checkable references.

These are generated identities, not claims of new mathematics or calibrated
hardness. A random walk supplies a proof; a leaf swap supplies a nearby negative
control checked in a three-element affine magma. No external solver is needed.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def show(t):
    return t if isinstance(t, str) else f"(op {show(t[0])} {show(t[1])})"


def paths(t, p=()):
    if isinstance(t, tuple):
        yield p
        yield from paths(t[0], p + (0,))
        yield from paths(t[1], p + (1,))


def at(t, p):
    for i in p:
        t = t[i]
    return t


def put(t, p, u):
    if not p:
        return u
    parts = list(t)
    parts[p[0]] = put(parts[p[0]], p[1:], u)
    return tuple(parts)


def evaluate(t, values):
    if isinstance(t, str):
        return values[t]
    return (2 * evaluate(t[0], values) + evaluate(t[1], values)) % 3


HEADER = """From Stdlib Require Import List.
Import ListNotations.

Definition medial {A : Type} (op : A -> A -> A) : Prop :=
  forall x y z w, op (op x y) (op z w) = op (op x z) (op y w).
"""
FINITE = """
(* A concrete three-element carrier, using an existing Stdlib type. *)
Definition element := option bool.
Definition index (x : element) : nat :=
  match x with None => 0 | Some false => 1 | Some true => 2 end.
Definition table_op (table : list element) (x y : element) : element :=
  nth (3 * index x + index y) table None.
"""


def generate(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    metadata = {}
    for family, seed in enumerate((20260909, 20260910), 1):
        rng = random.Random(seed)

        def tree(depth):
            return rng.choice("abcd") if depth == 0 else (tree(depth - 1), tree(depth - 1))

        start = tree(4)
        current = start
        seen = {current}
        steps = []
        for _ in range(32):
            choices = []
            for p in paths(current):
                sub = at(current, p)
                if all(isinstance(s, tuple) for s in sub):
                    (a, b), (c, d) = sub
                    nxt = put(current, p, ((a, c), (b, d)))
                    if nxt not in seen:
                        choices.append((p, a, b, c, d, nxt))
            if not choices:
                raise RuntimeError("walk exhausted; choose another seed")
            p, a, b, c, d, nxt = rng.choice(choices)
            ctx = show(put(current, p, "hole"))
            steps.append(f"  etransitivity; [exact (f_equal (fun hole : A => {ctx}) "
                         f"(Hmed {show(a)} {show(b)} {show(c)} {show(d)})) |].")
            current = nxt
            seen.add(current)
        name = f"medial_walk_{family:02d}"
        stmt = (f"\nTheorem {name} : forall (A : Type) (op : A -> A -> A),\n"
                f"  medial op -> forall a b c d : A,\n  {show(start)} =\n  {show(current)}.\n")
        (out / f"{name}.v").write_text(HEADER + stmt + "Proof.\nAdmitted.\n")
        proof = "Proof.\n  intros A op Hmed a b c d.\n" + "\n".join(steps) + "\n  reflexivity.\nQed.\n"
        (out / f"{name}.ref.v").write_text(HEADER + stmt + proof)
        metadata[name] = {"domain": "equational_theories", "family": f"medial_{family}",
                          "seed": seed, "walk_steps": len(steps), "reference": "generated, kernel checked on import",
                          "status": "known_true", "difficulty": "uncalibrated"}

        # Swap two distinct leaves, preserving the variable multiset. Keep only
        # a mutation that the specified affine magma actually separates.
        leaves = [p + (i,) for p in paths(current) for i in (0, 1)
                  if isinstance(at(current, p + (i,)), str)]
        values = dict(zip("abcd", (0, 1, 2, 0)))
        candidates = []
        for i, p in enumerate(leaves):
            for q in leaves[i + 1:]:
                mutant = put(put(current, p, at(current, q)), q, at(current, p))
                if evaluate(start, values) != evaluate(mutant, values):
                    candidates.append((p, q, mutant))
        if not candidates:
            raise RuntimeError("no separating mutation")
        p, q, mutant = rng.choice(candidates)
        name = f"medial_countermodel_{family:02d}"
        stmt = (f"\nTheorem {name} : exists table : list element,\n"
                "  length table = 9 /\\ medial (table_op table) /\\\n"
                "  exists a b c d : element,\n"
                f"  let op := table_op table in\n  {show(start)} <>\n  {show(mutant)}.\n")
        code = ("None", "Some false", "Some true")
        table = "; ".join(code[(2*x+y) % 3] for x in range(3) for y in range(3))
        proof = (f"Proof.\n  exists [{table}].\n  split; [reflexivity |].\n  split.\n"
                 "  - intros [[]|] [[]|] [[]|] [[]|]; reflexivity.\n"
                 "  - exists None, (Some false), (Some true), None.\n    discriminate.\nQed.\n")
        (out / f"{name}.v").write_text(HEADER + FINITE + stmt + "Proof.\nAdmitted.\n")
        (out / f"{name}.ref.v").write_text(HEADER + FINITE + stmt + proof)
        metadata[name] = {"domain": "equational_theories", "family": f"medial_{family}",
                          "seed": seed, "swapped_leaf_paths": [p, q],
                          "reference": "three-element countermodel, kernel checked on import",
                          "status": "known_counterexample", "difficulty": "calibration control"}
    (out / "equations.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("problems_src/research"))
    generate(parser.parse_args().out)
