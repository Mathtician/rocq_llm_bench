From Stdlib Require Import List Znumtheory ZArith Reals Lia Lra.
Open Scope nat_scope.
Lemma imo_1987_p6_false : ~ (forall (n : nat), 2 <= n ->
  (forall k, (2 <= INR k <= sqrt (INR n / 3))%R ->
    prime (Z.of_nat (k ^ 2 + k + n))) ->
  forall k, k <= n - 2 -> prime (Z.of_nat (k ^ 2 + k + n))).
Proof.
  intro H.
  assert (Hp : prime (Z.of_nat (0 ^ 2 + 0 + 4))).
  { apply (H 4); [lia| |lia].
    intros k [Hk1 Hk2].
    exfalso.
    replace (INR 4) with 4%R in Hk2 by (simpl; lra).
    assert (Hq : (0 <= 4/3)%R) by lra.
    pose proof (sqrt_sqrt _ Hq) as Hs.
    pose proof (sqrt_pos (4/3)) as Hs0.
    nra. }
  simpl in Hp.
  apply prime_alt in Hp. destruct Hp as [_ Hp].
  apply (Hp 2%Z); [lia| exists 2%Z; reflexivity].
Qed.
