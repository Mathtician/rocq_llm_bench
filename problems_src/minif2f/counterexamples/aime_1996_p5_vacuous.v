From Stdlib Require Import Reals Lra Psatz.
Open Scope R_scope.
Theorem aime_1996_p5_vacuous :
  forall (a b c r s t : R) (f g : R -> R),
  (forall x, f x = x^3 + 3*x^2 + 4*x - 11) ->
  (forall x, g x = x^3 + r*x^2 + s*x + t) ->
  f a = 0 -> f b = 0 -> f c = 0 ->
  g (a + b) = 0 -> g (b + c) = 0 -> g (c + a) = 0 ->
  a <> b -> b <> c -> c <> a -> t = 23.
Proof.
  intros a b c r s t f g Hf Hg Ha Hb _ _ _ _ Hab _ _.
  exfalso. rewrite Hf in Ha, Hb.
  assert (Hq : 0 < a^2 + a*b + b^2 + 3*(a+b) + 4) by (pose proof (pow2_ge_0 (a-b)); pose proof (pow2_ge_0 (a+b+2)); nra).
  assert (E : (a - b) * (a^2 + a*b + b^2 + 3*(a+b) + 4) = 0) by (replace ((a - b) * (a^2 + a*b + b^2 + 3*(a+b) + 4)) with ((a^3 + 3*a^2 + 4*a - 11) - (b^3 + 3*b^2 + 4*b - 11)) by ring; lra).
  apply Rmult_integral in E. destruct E; [apply Hab; lra | lra].
Qed.
