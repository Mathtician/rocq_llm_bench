From Stdlib Require Import List.
Import ListNotations.

Definition medial {A : Type} (op : A -> A -> A) : Prop :=
  forall x y z w, op (op x y) (op z w) = op (op x z) (op y w).

Theorem medial_walk_02 : forall (A : Type) (op : A -> A -> A),
  medial op -> forall a b c d : A,
  (op (op (op (op a c) (op a b)) (op (op c c) (op c a))) (op (op (op a b) (op b b)) (op (op d c) (op a d)))) =
  (op (op (op (op a c) (op a b)) (op (op a b) (op c c))) (op (op (op c b) (op c a)) (op (op d a) (op b d)))).
Proof.
Admitted.
