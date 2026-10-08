From Stdlib Require Import Reals Lra ZArith Lia.
Open Scope R_scope.

(* The square root of 2 is irrational. *)

Theorem sqrt2_irrational (p q : Z) (hq : (0 < q)%Z) : IZR p / IZR q <> sqrt 2.
Proof.
Admitted.
