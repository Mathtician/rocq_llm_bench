(** Putnam 2025 B6.
    Find the largest real constant r such that there exists g : N -> N
    with g(n+1) - g(n) >= g(g(n))^r for all n >= 1.
    Answer: r = 1/4.

    We state this as: 1/4 is the supremum of the set of r for which

such a g exists. *)

From Stdlib Require Import Reals Rpower.
Open Scope R_scope.

(** The set of valid exponents. *)
Definition valid_exponent (r : R) : Prop :=
  exists g : nat -> nat,
    (forall n, (n > 0)%nat -> (g n > 0)%nat) /\
    (forall n, (n >= 1)%nat ->
       INR (g (S n)) - INR (g n) >= Rpower (INR (g (g n))) r).

Theorem putnam_2025_b6 :
  valid_exponent (1/4) /\
  forall r, valid_exponent r -> r <= 1/4.
Proof.
Admitted.
