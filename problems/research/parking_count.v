From Stdlib Require Import Arith List Sorting.Permutation Sorting.Sorted.
Import ListNotations.

(* Positive preferences, and an explicitly sorted permutation. The index i
   is zero-based, so its upper bound is a + b*i. No counting recurrence is

built into the definition. *)
Definition parking_function (a b n : nat) (xs : list nat) : Prop :=
  length xs = n /\ Forall (fun x => 1 <= x) xs /\
  exists ys : list nat, Permutation xs ys /\ StronglySorted le ys /\
    (forall i : nat, i < n -> nth i ys 0 <= a + b * i).

Definition has_cardinality {A : Type} (P : A -> Prop) (k : nat) : Prop :=
  exists xs : list A, NoDup xs /\ (forall x, In x xs <-> P x) /\ length xs = k.

(* Length zero has one empty preference list, including when a=0. *)
Definition parking_formula (a b n : nat) : nat :=
  match n with
  | 0 => 1
  | S m => a * (a + b * S m) ^ m
  end.

Theorem parking_count : forall a b n : nat,
  has_cardinality (parking_function a b n) (parking_formula a b n).
Proof.
Admitted.
