From Stdlib Require Import Arith List.
Import ListNotations.

(* Decimal digits are most significant first. *)
Fixpoint decimal_value (ds : list nat) : nat :=
  match ds with
  | [] => 0
  | d :: rest => d * 10 ^ length rest + decimal_value rest
  end.

(* ds is the decimal expansion of n: nonempty, no leading zero. So 1 <= n. *)
Definition decimal_expansion (n : nat) (ds : list nat) : Prop :=
  Forall (fun d => d < 10) ds /\
  (match ds with [] => False | d :: _ => d <> 0 end) /\
  decimal_value ds = n.

(* m is obtained by inserting one digit x at one of the length+1 gaps of ds,
   and the result has no leading zero. The predicate is on values m, so equal
   values from different insertions are one element of the set S(n). *)
Definition inserted (ds : list nat) (m : nat) : Prop :=
  exists i x : nat, i <= length ds /\ x < 10 /\
    let es := firstn i ds ++ x :: skipn i ds in
    (match es with [] => False | e :: _ => e <> 0 end) /\
    decimal_value es = m.

Definition has_cardinality {A : Type} (P : A -> Prop) (k : nat) : Prop :=
  exists xs : list A, NoDup xs /\ (forall x, In x xs <-> P x) /\ length xs = k.

(* The one-based position of 10n in the increasing enumeration of S(n) is the
   number of elements of S(n) that are at most 10n, given 10n is in S(n). *)
Theorem digit_insert_rank : forall (n : nat) (ds : list nat),
  decimal_expansion n ds ->
  inserted ds (10 * n) /\
  has_cardinality (fun m => inserted ds m /\ m <= 10 * n) (list_sum ds).
Proof.
Admitted.
