From Stdlib Require Import Arith Bool List Sorting.Permutation.
Import ListNotations.

(* One-line notation: entry i-1 of w is pi(i), for i in 1..n. *)

Definition apply_perm (w : list nat) (i : nat) : nat := nth (i - 1) w 0.

Fixpoint orbit (w : list nat) (steps start : nat) : list nat :=
  match steps with
  | 0 => []
  | S s => start :: orbit w s (apply_perm w start)
  end.

(* Standard cycle form (1, pi(1), pi^2(1), ..., pi^(n-1)(1)), so each entry
   is sent by pi to the next one. *)
Definition cycle_form (w : list nat) : list nat := orbit w (length w) 1.

(* pi is one n-cycle exactly when its standard cycle form has n distinct entries. *)
Definition cyclic_perm (n : nat) (w : list nat) : Prop :=
  Permutation (seq 1 n) w /\ NoDup (cycle_form w).

Fixpoint subsequences (xs : list nat) : list (list nat) :=
  match xs with
  | [] => [[]]
  | x :: rest => let s := subsequences rest in map (cons x) s ++ s
  end.

(* u and v have the same length and every earlier/later pair of positions
   compares the same way in both. *)
Fixpoint same_order (u v : list nat) : bool :=
  match u, v with
  | [], [] => true
  | x :: u', y :: v' =>
      forallb (fun '(x', y') => Bool.eqb (x <? x') (y <? y') && Bool.eqb (x' <? x) (y' <? y))
              (combine u' v')
      && same_order u' v'
  | _, _ => false
  end.

(* xs contains the pattern iff some subsequence of xs is order-isomorphic to it. *)
Definition avoids (pattern xs : list nat) : bool :=
  negb (existsb (same_order pattern) (subsequences xs)).
(* Rotation i of c_1 ... c_n is c_(i+1) ... c_n c_1 ... c_i. *)
Definition rotate (i : nat) (c : list nat) : list nat := skipn i c ++ firstn i c.

Definition has_cardinality {A : Type} (P : A -> Prop) (k : nat) : Prop :=
  exists xs : list A, NoDup xs /\ (forall x, In x xs <-> P x) /\ length xs = k.

(* Size N = n+3 >= 3. The paper's count 2^(N-1) - floor((3N-5)/2) is m with
   m + floor((3n+4)/2) = 2^(n+2), stated without subtraction. *)

Theorem cyclic_rot1432_4321 : forall n : nat,
  exists m : nat,
    has_cardinality (fun w => cyclic_perm (n + 3) w /\
                              avoids [4; 3; 2; 1] w = true /\
                              (forall i : nat, i < n + 3 ->
                                 avoids [1; 4; 3; 2] (rotate i (cycle_form w)) = true))
                    m /\
    m + (3 * n + 4) / 2 = 2 ^ (n + 2).
Proof.
Admitted.
