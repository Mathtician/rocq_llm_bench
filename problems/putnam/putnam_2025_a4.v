(** Putnam 2025 Problem A4

    Find the minimal value of k such that there exist k-by-k real
    matrices A_1, ..., A_2025 with A_i * A_j = A_j * A_i iff
    |i - j| ∈ {0, 1, 2024}.

Answer: k = 3. *)

From Stdlib Require Import Reals ZArith.
Open Scope R_scope.

(** Matrix represented as a function nat -> nat -> R.
    Matrix multiplication for k×k matrices. *)
Definition mat_mul (k : nat) (A B : nat -> nat -> R) : nat -> nat -> R :=
  fun i j =>
    let fix sum_aux (n : nat) : R :=
      match n with
      | O => A i O * B O j
      | S n' => sum_aux n' + A i n * B n j
      end
    in match k with
       | O => 0
       | S k' => sum_aux k'
       end.

(** Two k×k matrices are equal (as functions on {0,..,k-1}). *)
Definition mat_eq (k : nat) (A B : nat -> nat -> R) : Prop :=
  forall i j, (i < k)%nat -> (j < k)%nat -> A i j = B i j.

(** The commutativity condition:
    A_i * A_j = A_j * A_i  iff  |i - j| ∈ {0, 1, 2024}.

    We index A from 0 to 2024 (i.e., Fin 2025 as naturals). *)
Definition commute_cond (k : nat) (A : nat -> nat -> nat -> R) : Prop :=
  forall i j : nat,
    (i < 2025)%nat -> (j < 2025)%nat ->
    (mat_eq k (mat_mul k (A i) (A j)) (mat_mul k (A j) (A i))
     <->
     (i = j \/ (Z.abs (Z.of_nat i - Z.of_nat j) = 1)%Z
            \/ (Z.abs (Z.of_nat i - Z.of_nat j) = 2024)%Z)).

(** The set of valid k: positive k for which the family exists. *)
Definition valid_k (k : nat) : Prop :=
  (k > 0)%nat /\ exists A : nat -> nat -> nat -> R, commute_cond k A.

(** Statement: 3 is the least element of valid_k. *)

Theorem putnam_2025_a4 :
  valid_k 3 /\ (forall k, valid_k k -> (3 <= k)%nat).
Proof.
Admitted.
