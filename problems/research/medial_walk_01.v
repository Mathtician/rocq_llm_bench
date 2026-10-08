From Stdlib Require Import List.
Import ListNotations.

Definition medial {A : Type} (op : A -> A -> A) : Prop :=
  forall x y z w, op (op x y) (op z w) = op (op x z) (op y w).

Theorem medial_walk_01 : forall (A : Type) (op : A -> A -> A),
  medial op -> forall a b c d : A,
  (op (op (op (op a a) (op b a)) (op (op d a) (op c a))) (op (op (op b d) (op d d)) (op (op b b) (op c c)))) =
  (op (op (op (op a b) (op d b)) (op (op b d) (op c c))) (op (op (op a a) (op a d)) (op (op d a) (op b c)))).
Proof.
Admitted.
