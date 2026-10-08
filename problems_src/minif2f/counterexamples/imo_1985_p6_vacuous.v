From Stdlib Require Import Reals Lra.
Open Scope R_scope.
Lemma hyps_inconsistent : forall (f : nat -> R -> R),
  (forall x : R, f 1%nat x = x) ->
  (forall (x : R) (n : nat), f (S n) x = f n x * (f n x + /INR n)) -> False.
Proof.
  intros f H1 H2.
  set (c := / INR 0).
  set (x := - (c*c)/4 - 1).
  pose proof (H2 x 0%nat) as E. rewrite H1 in E. fold c in E.
  set (t := f 0%nat x) in *.
  assert (0 <= (t + c/2)^2) by apply pow2_ge_0.
  unfold x in E. nra.
Qed.
