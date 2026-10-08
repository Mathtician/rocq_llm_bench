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

Definition has_cardinality {A : Type} (P : A -> Prop) (k : nat) : Prop :=
  exists xs : list A, NoDup xs /\ (forall x, In x xs <-> P x) /\ length xs = k.

(* fib 0 = 0 and fib 1 = 1. *)
Fixpoint fib (n : nat) : nat :=
  match n with
  | 0 => 0
  | S m => match m with 0 => 1 | S p => fib m + fib p end
  end.

(* Size n+2 >= 2; the paper's F_(2(n+2)-3) is fib (2n+1). *)
Theorem cyclic_4321_213_fib : forall n : nat,
  has_cardinality (fun w => cyclic_perm (n + 2) w /\
                            avoids [4; 3; 2; 1] w = true /\
                            avoids [2; 1; 3] (cycle_form w) = true)
                  (fib (2 * n + 1)).
Proof.
Admitted.
