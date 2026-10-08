From Stdlib Require Import Arith Lia.

(* Pigeonhole: n+1 pigeons (indices 0..n) in n holes (values 0..n-1). *)

Theorem pigeonhole (n : nat) (f : nat -> nat) (hf : forall i, i <= n -> f i < n) :
  exists i j, i < j /\ j <= n /\ f i = f j.
Proof.
Admitted.
