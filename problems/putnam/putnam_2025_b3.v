(** Putnam 2025 B3.
    If S is a nonempty set of positive integers such that for every n in S,
    every positive divisor of 2025^n - 15^n is also in S,

then S contains all positive integers. *)

From Stdlib Require Import Arith PeanoNat.

Theorem putnam_2025_b3 :
  forall (S : nat -> Prop),
    (exists n, n > 0 /\ S n) ->
    (forall n, S n -> n > 0) ->
    (forall n, S n ->
       forall d, d > 0 -> Nat.divide d (2025^n - 15^n) -> S d) ->
    forall n, n > 0 -> S n.
Proof.
Admitted.
