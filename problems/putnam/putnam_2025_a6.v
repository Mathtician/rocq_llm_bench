(** Putnam 2025 Problem A6

    Let b_0 = 0 and b_{n+1} = 2*b_n^2 + b_n + 1.
    For each k >= 1, show that b_{2^{k+1}} - 2*b_{2^k}
    is divisible by 2^{2k+2} but not by 2^{2k+3}.

*)

From Stdlib Require Import ZArith.

Open Scope Z_scope.

(** The recurrence b_{n+1} = 2*b_n^2 + b_n + 1 with b_0 = 0. *)
Fixpoint b (n : nat) : Z :=
  match n with
  | O => 0
  | S n' => 2 * (b n') ^ 2 + b n' + 1
  end.

Theorem putnam_2025_a6 :
  forall k : nat, (k >= 1)%nat ->
    (* 2^{2k+2} divides b_{2^{k+1}} - 2 * b_{2^k} *)
    (2 ^ (Z.of_nat (2 * k + 2)) | b (2 ^ (k + 1))%nat - 2 * b (2 ^ k)%nat) /\
    (* but 2^{2k+3} does not *)
    ~ (2 ^ (Z.of_nat (2 * k + 3)) | b (2 ^ (k + 1))%nat - 2 * b (2 ^ k)%nat).
Proof.
Admitted.
