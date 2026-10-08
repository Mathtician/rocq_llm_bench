From Stdlib Require Import List.
Import ListNotations.

Definition medial {A : Type} (op : A -> A -> A) : Prop :=
  forall x y z w, op (op x y) (op z w) = op (op x z) (op y w).

(* A concrete three-element carrier, using an existing Stdlib type. *)
Definition element := option bool.
Definition index (x : element) : nat :=
  match x with None => 0 | Some false => 1 | Some true => 2 end.
Definition table_op (table : list element) (x y : element) : element :=
  nth (3 * index x + index y) table None.

Theorem medial_countermodel_01 : exists table : list element,
  length table = 9 /\ medial (table_op table) /\
  exists a b c d : element,
  let op := table_op table in
  (op (op (op (op a a) (op b a)) (op (op d a) (op c a))) (op (op (op b d) (op d d)) (op (op b b) (op c c)))) <>
  (op (op (op (op a d) (op d b)) (op (op b d) (op c c))) (op (op (op a a) (op a d)) (op (op b a) (op b c)))).
Proof.
Admitted.
