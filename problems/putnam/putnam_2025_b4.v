(** Putnam 2025 Problem B4

    For n ≥ 2, let A be an n×n matrix of nonnegative integers with:
    (a) a_{i,j} = 0 when i + j ≤ n,
    (b) a_{i+1,j} ∈ {a_{i,j}, a_{i,j} + 1},
    (c) a_{i,j+1} ∈ {a_{i,j}, a_{i,j} + 1}.
    Let S = sum of all entries, N = number of nonzero entries.

Prove 3 * S ≤ (n + 2) * N. *)

From Stdlib Require Import Arith Lia.

(** Matrix conditions. Indices are 1-based: i, j ∈ {1, ..., n}. *)

Definition cond_zero (n : nat) (A : nat -> nat -> nat) : Prop :=
  forall i j, (1 <= i <= n)%nat -> (1 <= j <= n)%nat ->
    (i + j <= n)%nat -> A i j = 0.

Definition cond_row_step (n : nat) (A : nat -> nat -> nat) : Prop :=
  forall i j, (1 <= i)%nat -> (i < n)%nat -> (1 <= j <= n)%nat ->
    (A (S i) j = A i j \/ A (S i) j = A i j + 1).

Definition cond_col_step (n : nat) (A : nat -> nat -> nat) : Prop :=
  forall i j, (1 <= i <= n)%nat -> (1 <= j)%nat -> (j < n)%nat ->
    (A i (S j) = A i j \/ A i (S j) = A i j + 1).

Definition matrix_cond (n : nat) (A : nat -> nat -> nat) : Prop :=
  cond_zero n A /\ cond_row_step n A /\ cond_col_step n A.

(** Sum of all entries. *)
Fixpoint sum_row (A : nat -> nat -> nat) (i : nat) (j : nat) : nat :=
  match j with
  | O => 0
  | S j' => sum_row A i j' + A i (S j')
  end.

Fixpoint total_sum (A : nat -> nat -> nat) (i n : nat) : nat :=
  match i with
  | O => 0
  | S i' => total_sum A i' n + sum_row A (S i') n
  end.

Definition S_total (n : nat) (A : nat -> nat -> nat) : nat :=
  total_sum A n n.

(** Count of nonzero entries. *)
Fixpoint count_nonzero_row (A : nat -> nat -> nat) (i : nat) (j : nat) : nat :=
  match j with
  | O => 0
  | S j' => count_nonzero_row A i j' +
             (if Nat.eqb (A i (S j')) 0 then 0 else 1)
  end.

Fixpoint count_nonzero (A : nat -> nat -> nat) (i n : nat) : nat :=
  match i with
  | O => 0
  | S i' => count_nonzero A i' n + count_nonzero_row A (S i') n
  end.

Definition N_nonzero (n : nat) (A : nat -> nat -> nat) : nat :=
  count_nonzero A n n.

(** Statement: 3 * S ≤ (n + 2) * N. *)

Theorem putnam_2025_b4 :
  forall (n : nat) (A : nat -> nat -> nat),
    (2 <= n)%nat ->
    matrix_cond n A ->
    3 * S_total n A <= (n + 2) * N_nonzero n A.
Proof.
Admitted.
