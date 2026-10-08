# Hand-written problems

`custom/*.v`: one theorem per file with a complete `Qed` proof, written for
this benchmark (Rocq 9.1.1, Stdlib only). `rlb tier custom` turns each into a
task (statement with `Admitted`) and a verified reference, exactly as for the
imported tiers. Difficulty is meant to span "one induction" (bernoulli,
telescoping) to "a real argument" (pigeonhole, sqrt2_irrational,
infinitude_primes); none is a single-lemma lookup. **Not included in the public
release** (each file is its own reference proof); the task statements are in
`problems/custom/`.

`research/`: the phase-two pilot, with fixed statements from two papers and
generated equational-theory controls. References are optional and explicitly
tracked. See [research/README.md](research/README.md); build with
`rlb tier research`.
