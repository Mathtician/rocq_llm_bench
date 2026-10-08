(** Putnam 2025 B1 (axiom-free formulation).
    If every point in the plane is colored red or green, and for every
    three noncollinear same-color points the circumcenter also has that
    color, then all points are the same color.

    This version replaces the Parameter/Axiom circumcenter with a

concrete Cramer's-rule construction. *)

From Stdlib Require Import Reals.
Open Scope R_scope.

Definition point := (R * R)%type.

Definition noncollinear (A B C : point) : Prop :=
  (fst B - fst A) * (snd C - snd A) - (snd B - snd A) * (fst C - fst A) <> 0.

Definition dist_sq (P Q : point) : R :=
  (fst P - fst Q)² + (snd P - snd Q)².

Definition is_circumcenter (A B C O : point) : Prop :=
  dist_sq O A = dist_sq O B /\ dist_sq O B = dist_sq O C.

Definition circumcenter (A B C : point) : point :=
  let ax := fst A in let ay := snd A in
  let bx := fst B in let by_ := snd B in
  let cx := fst C in let cy := snd C in
  let d := (bx - ax) * (cy - ay) - (by_ - ay) * (cx - ax) in
  let ux := bx*bx + by_*by_ - ax*ax - ay*ay in
  let vx := cx*cx + cy*cy - ax*ax - ay*ay in
  ( ((cy - ay) * ux - (by_ - ay) * vx) / (2 * d),
    ((bx - ax) * vx - (cx - ax) * ux) / (2 * d) ).

Theorem putnam_2025_b1 :
  forall (color : point -> bool),
    (forall A B C : point,
       noncollinear A B C ->
       color A = color B ->
       color A = color C ->
       color A = color (circumcenter A B C)) ->
    exists c0 : bool, forall P : point, color P = c0.
Proof.
Admitted.
