From Stdlib Require Import Reals Lra Lia.
Open Scope R_scope.

(* sum_{k=1}^{n} 1/(k(k+1)) *)

Fixpoint tsum (n : nat) : R :=
  match n with
  | O => 0
  | S k => tsum k + 1 / (INR (S k) * INR (S (S k)))
  end.

Theorem telescoping (n : nat) : tsum n = INR n / INR (S n).
Proof.
Admitted.
