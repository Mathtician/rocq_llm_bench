From Stdlib Require Import Arith List Sorting.Sorted.
Import ListNotations.

(* Spots are 1..n; spot 0 and spot n+1 do not exist. *)

Definition spot_free (n : nat) (occupied : list nat) (s : nat) : bool :=
  (1 <=? s) && (s <=? n) && negb (existsb (Nat.eqb s) occupied).

(* A car preferring p tries p, then p-1, then p+1, and takes the first of
   these that exists and is free. For p = 1, p-1 is 0, which is not a spot. *)
Definition vacillating_spot (n : nat) (occupied : list nat) (p : nat) : option nat :=
  find (spot_free n occupied) [p; p - 1; p + 1].

Fixpoint all_park (n : nat) (occupied : list nat) (prefs : list nat) : bool :=
  match prefs with
  | [] => true
  | p :: rest =>
      match vacillating_spot n occupied p with
      | Some s => all_park n (s :: occupied) rest
      | None => false
      end
  end.

(* Non-increasing: a_1 >= a_2 >= ... >= a_n. *)
Definition nonincreasing_vpf (n : nat) (prefs : list nat) : Prop :=
  length prefs = n /\ Forall (fun p => 1 <= p <= n) prefs /\
  Sorted ge prefs /\ all_park n [] prefs = true.

Definition has_cardinality {A : Type} (P : A -> Prop) (k : nat) : Prop :=
  exists xs : list A, NoDup xs /\ (forall x, In x xs <-> P x) /\ length xs = k.

(* The paper's recurrence v(n) = 2 v(n-1) + v(n-3) with v(1), v(2), v(3) =
   1, 3, 6. Length 0 has one (empty) list; the recurrence starts at n = 4.
   In the last branch n = p+1 and p = q+2, with q >= 1. *)
Fixpoint vpf_count (n : nat) : nat :=
  match n with
  | 0 => 1
  | 1 => 1
  | 2 => 3
  | 3 => 6
  | S ((S (S ((S _) as q))) as p) => 2 * vpf_count p + vpf_count q
  end.

Theorem vpf_nonincreasing : forall n : nat,
  has_cardinality (nonincreasing_vpf n) (vpf_count n).
Proof.
Admitted.
