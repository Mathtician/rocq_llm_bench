From Stdlib Require Import ZArith Znumtheory Lia.
Open Scope Z_scope.

(* Z-valued factorial *)

Fixpoint zfact (n : nat) : Z :=
  match n with
  | O => 1
  | S k => Z.of_nat (S k) * zfact k
  end.

(* There are infinitely many primes: above any n there is a prime. *)

Theorem infinitude_primes (n : Z) : exists p, prime p /\ n < p.
Proof.
Admitted.
