From Stdlib Require Import Reals Lra.
Open Scope R_scope.

(* Bernoulli's inequality. *)

Theorem bernoulli (x : R) (n : nat) (hx : -1 <= x) : 1 + INR n * x <= (1 + x) ^ n.
Proof.
Admitted.
