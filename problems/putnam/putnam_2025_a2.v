(** Putnam 2025 Problem A2

    Find the largest a and smallest b such that
      a * x * (pi - x) <= sin x <= b * x * (pi - x)
    for all x in [0, pi].

    Answer: a = 1/pi, b = 4/pi^2.

*)

From Stdlib Require Import Reals Lra.

Open Scope R_scope.

Theorem putnam_2025_a2 :
  (* Part 1: a = 1/PI is the greatest lower coefficient *)
  (forall x, 0 <= x <= PI -> (1 / PI) * x * (PI - x) <= sin x) /\
  (forall a, (forall x, 0 <= x <= PI -> a * x * (PI - x) <= sin x) ->
             a <= 1 / PI)
  /\
  (* Part 2: b = 4/PI^2 is the least upper coefficient *)
  (forall x, 0 <= x <= PI -> sin x <= (4 / PI ^ 2) * x * (PI - x)) /\
  (forall b, (forall x, 0 <= x <= PI -> sin x <= b * x * (PI - x)) ->
             4 / PI ^ 2 <= b).
Proof.
Admitted.
