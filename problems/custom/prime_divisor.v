From Stdlib Require Import ZArith Znumtheory Lia.
Open Scope Z_scope.

(* Every integer >= 2 has a prime divisor. *)

Theorem prime_divisor (n : Z) (hn : 2 <= n) : exists p, prime p /\ (p | n).
Proof.
Admitted.
