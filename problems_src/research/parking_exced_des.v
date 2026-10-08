From Stdlib Require Import Arith Bool List Sorting.Permutation Sorting.Sorted.
Import ListNotations.

(* A parking content b_1 <= ... <= b_n with 1 <= b_j <= j. Zero-based entry
   i of the list is b_(i+1). *)
Definition parking_content (n : nat) (b : list nat) : Prop :=
  length b = n /\ Sorted le b /\ (forall i : nat, i < n -> 1 <= nth i b 0 <= S i).

(* w is a permutation of 1..n in one-line notation, and pi_i = b_(w(i)).
   Entries j of w are at least 1, so j - 1 does not truncate. *)
Definition content_word (b w : list nat) : list nat :=
  map (fun j => nth (j - 1) b 0) w.

(* Spots are 1..n. A car preferring p takes the first unoccupied spot s with
   p <= s, or leaves if there is none. Entry i of the result is the spot of
   the (i+1)-th car, or None if it left. *)
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

(* exced(pi) = #{i in 1..n : pi_i > i}: strict and one-based. *)
Fixpoint exced_from (i : nat) (pi : list nat) : nat :=
  match pi with
  | [] => 0
  | x :: rest => (if i <? x then 1 else 0) + exced_from (S i) rest
  end.
Definition exced (pi : list nat) : nat := exced_from 1 pi.

(* des(sigma) = #{i in 1..n-1 : sigma(i) > sigma(i+1)}. *)
Fixpoint des (sigma : list nat) : nat :=
  match sigma with
  | x :: ((y :: _) as rest) => (if y <? x then 1 else 0) + des rest
  | _ => 0
  end.

Definition has_cardinality {A : Type} (P : A -> Prop) (k : nat) : Prop :=
  exists xs : list A, NoDup xs /\ (forall x, In x xs <-> P x) /\ length xs = k.

(* Both sides count permutations w (with multiplicity in pi). The outcome
   sigma = oc(pi) lists, car by car, the spot where each car parks; it is
   not the inverse listing of the car in each spot. *)
Theorem parking_exced_des : forall (n : nat) (b : list nat) (k : nat),
  parking_content n b ->
  exists m : nat,
    has_cardinality (fun w => Permutation (seq 1 n) w /\
                              exced (content_word b w) = k) m /\
    has_cardinality (fun w => Permutation (seq 1 n) w /\
                              exists sigma : list nat,
                                park n [] (content_word b w) = map Some sigma /\
                                des sigma = k) m.
Proof.
Admitted.
