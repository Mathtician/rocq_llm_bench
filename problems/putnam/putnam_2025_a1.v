(** Putnam 2025 Problem A1

    Let m₀ and n₀ be distinct positive integers. For every positive
    integer k, define mₖ and nₖ to be the relatively prime positive
    integers such that mₖ/nₖ = (2·m_{k-1}+1)/(2·n_{k-1}+1).
    Prove that 2·mₖ+1 and 2·nₖ+1 are relatively prime for all but
    finitely many k.

*)

From Stdlib Require Import ZArith QArith Arith PeanoNat.

Open Scope Z_scope.

(** The recurrence: given (m,n), form the rational (2m+1)/(2n+1)
    in lowest terms.  The numerator and denominator of Qred give
    the coprime pair (m', n'). *)

Definition step (m n : Z) : Q :=
  Qred (Qmake (2 * m + 1) (Z.to_pos (2 * n + 1))).

Theorem putnam_2025_a1 :
  forall (m n : nat -> Z),
    (* m 0 and n 0 are distinct positive integers *)
    (0 < m 0%nat)%Z ->
    (0 < n 0%nat)%Z ->
    m 0%nat <> n 0%nat ->
    (* Recurrence: (m(k+1), n(k+1)) is the reduced form of
       (2*m(k)+1) / (2*n(k)+1) *)
    (forall k, 0 < 2 * n k + 1) ->
    (forall k, Qnum (step (m k) (n k)) = m (S k)) ->
    (forall k, Z.pos (Qden (step (m k) (n k))) = n (S k)) ->
    (* Conclusion: there exists N such that for all k >= N,
       gcd(2*m(k)+1, 2*n(k)+1) = 1 *)
    exists N : nat, forall k, (k >= N)%nat ->
      Z.gcd (2 * m k + 1) (2 * n k + 1) = 1.
Proof.
Admitted.
