Prove the theorem in `$file` (Rocq 9.1.1 with only its standard library, imported as `From Stdlib Require ...`).

The file ends with `Proof.` / `Admitted.` after `Theorem $theorem`. Replace that with a complete proof ending in `Qed.`.

Rules, enforced mechanically by the grader:
- Keep the definitions and the statement of `$theorem` exactly as given. You may add Stdlib imports and helper lemmas before the `Theorem` line.
- No `Axiom`, `Parameter`, `Hypothesis`, `Variable`, `admit` or `Admitted`. Only Stdlib axioms are accepted (`Print Assumptions $theorem` may list Stdlib/Corelib constants only).
- Only `$file` is graded; it is recompiled on its own with `coqc -q $file`. Do not create or depend on other files.
- Check your work with `coqc -q $file`. Exit status 0 with `Qed.` means you are done; warnings are fine.

This is Rocq, not Lean: there is no `nlinarith`, `linarith`, `omega`, `norm_num`, `positivity`, `field_simp`, `simp` or `sorry`, and tactics take no `[...]` hint list. The arithmetic closers are `lia`, `nia`, `lra`, `nra` and `psatz`, plus `ring` and `field` (`simpl` exists; `simp` does not); if the file does not import them, add `From Stdlib Require Import Lia Lra Psatz.` Rocq 9 names its library `Stdlib` (`From Stdlib Require Import ...`); `Field` is `Stdlib.setoid_ring.Field`, and there is no `Stdlib.micromega.Field` or `.Nra`. Use `Search` to find lemma names rather than guessing.

Work only in this directory, from the Rocq standard library and your own reasoning: do not search the web, fetch URLs, or look up solutions by any means; an attempt that does is discarded. Stop as soon as the file compiles; no summary is needed.
