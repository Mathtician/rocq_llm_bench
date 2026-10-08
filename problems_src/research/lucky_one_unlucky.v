From Stdlib Require Import Arith Bool List Sorting.Permutation.
Import ListNotations.

(* Spots are 1..n. A car preferring p takes the first unoccupied spot s with
   p <= s, or leaves if there is none. Entry i of the result is the spot of
   the (i+1)-th car, or None if it left. All cars need not park. *)
Definition next_spot (n : nat) (occupied : list nat) (p : nat) : option nat :=
  find (fun s => (p <=? s) && negb (existsb (Nat.eqb s) occupied)) (seq 1 n).

Fixpoint park (n : nat) (occupied : list nat) (prefs : list nat) : list (option nat) :=
  match prefs with
  | [] => []
  | p :: rest =>
      match next_spot n occupied p with
      | Some s => Some s :: park n (s :: occupied) rest
      | None => None :: park n occupied rest
      end
  end.

(* A car is lucky when it parks in its preferred spot. A car that leaves is
   not lucky. *)
Definition lucky_count (n : nat) (prefs : list nat) : nat :=
  length (filter (fun '(p, spot) =>
                    match spot with Some s => Nat.eqb s p | None => false end)
                 (combine prefs (park n [] prefs))).

(* Exactly n-1 lucky cars, written lucky + 1 = n: for n = 0 no list
   qualifies (truncated n-1 would wrongly admit the empty list). *)
Definition one_unlucky (n : nat) (prefs : list nat) : Prop :=
  length prefs = n /\ Forall (fun p => 1 <= p <= n) prefs /\
  lucky_count n prefs + 1 = n.

Definition has_cardinality {A : Type} (P : A -> Prop) (k : nat) : Prop :=
  exists xs : list A, NoDup xs /\ (forall x, In x xs <-> P x) /\ length xs = k.

(* Quicksort with the first entry as pivot. The pivot is compared once with
   each other entry; entries <= pivot go left and larger ones go right, both
   in their original order. The fuel (the list length) bounds the recursion. *)
Fixpoint qs_comparisons_fuel (fuel : nat) (xs : list nat) : nat :=
  match fuel, xs with
  | S fuel', pivot :: rest =>
      length rest
      + qs_comparisons_fuel fuel' (filter (fun x => x <=? pivot) rest)
      + qs_comparisons_fuel fuel' (filter (fun x => pivot <? x) rest)
  | _, _ => 0
  end.
Definition quicksort_comparisons (xs : list nat) : nat :=
  qs_comparisons_fuel (length xs) xs.

(* t is the total number of comparisons over all n! orderings of 1..n,
   summed along a duplicate-free list of exactly those orderings. *)
Definition quicksort_total (n t : nat) : Prop :=
  exists orders : list (list nat),
    NoDup orders /\ (forall w, In w orders <-> Permutation (seq 1 n) w) /\
    list_sum (map quicksort_comparisons orders) = t.

Theorem lucky_one_unlucky : forall n : nat,
  exists t : nat, quicksort_total n t /\ has_cardinality (one_unlucky n) t.
Proof.
Admitted.
