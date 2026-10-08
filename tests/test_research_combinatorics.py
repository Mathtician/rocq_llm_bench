"""Semantics of the five combinatorics research statements.

For each statement: the admitted statement passes the verifier; Rocq examples
pin its conventions; the formula side matches brute-force values; an independent
Python enumeration checks the paper's claim; and, for small sizes, the exact
statement instance is proven in Rocq by exhibiting the counted list.
"""
import itertools
import math
import re
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from rlb.external import _load, split_v
from rlb.problem import PREAMBLE_HAZARD_RE, Problem
from rlb.research import SOURCE
from rlb.rocq import Toolchain, coqc, verify

TC = Toolchain.discover()
NAMES = ["lucky_one_unlucky", "parking_exced_des", "cyclic_4321_213_fib",
         "cyclic_rot1432_4321", "vpf_nonincreasing"]


@pytest.mark.parametrize("name", NAMES)
def test_statement_passes_verifier(name):
    path = SOURCE / f"{name}.v"
    stem, imports, preamble, statement = split_v(path.read_text())
    assert stem == path.stem and not PREAMBLE_HAZARD_RE.search(preamble)
    p = Problem(stem, "research", "combinatorics", imports, preamble, statement, None, None)
    with TemporaryDirectory() as t:
        vr = verify(p, p.task_source(), TC, Path(t) / "check")
    assert vr.status == "axioms" and [n for n, _ in vr.assumptions] == [f"Solution.{name}"], \
        (vr.status, vr.message)


def statement_as_definition(p: Problem) -> str:
    """`Theorem X : forall B, BODY.` becomes `Definition X_at B : Prop := BODY.`,
    so instances below are proven about the literal statement text."""
    m = re.fullmatch(r"Theorem (\w+) : forall (.*?),(.*)\.", p.statement, re.S)
    assert m, p.statement
    binders = m.group(2).strip()
    if not binders.startswith("("):
        binders = f"({binders})"
    return f"Definition {m.group(1)}_at {binders} : Prop :={m.group(3)}."


# Finite-enumeration helpers shared by the Rocq examples. `card_by_filter`
# turns a boolean characterization of a predicate plus a complete, duplicate-free
# universe into an exact `has_cardinality` witness.
COMMON = r"""
From Stdlib Require Import Lia Bool Arith List Sorting.Permutation Sorting.Sorted.
Import ListNotations.
Fixpoint all_lists (k len : nat) : list (list nat) :=
  match len with
  | 0 => [[]]
  | S l => flat_map (fun x => map (cons x) (all_lists k l)) (seq 1 k)
  end.

Lemma all_lists_complete : forall k w, Forall (fun x => 1 <= x <= k) w ->
  In w (all_lists k (length w)).
Proof.
  intros k w H. induction H; simpl; [auto|].
  apply in_flat_map. exists x. split; [apply in_seq; lia | apply in_map; assumption].
Qed.
Lemma in_all_lists : forall n w, length w = n -> Forall (fun x => 1 <= x <= n) w ->
  In w (all_lists n n).
Proof. intros n w <- H. apply all_lists_complete, H. Qed.

Fixpoint nodupb {A : Type} (eqb : A -> A -> bool) (l : list A) : bool :=
  match l with
  | [] => true
  | x :: r => negb (existsb (eqb x) r) && nodupb eqb r
  end.
Lemma nodupb_spec {A : Type} (eqb : A -> A -> bool)
  (Heq : forall x y, eqb x y = true <-> x = y) :
  forall l, NoDup l <-> nodupb eqb l = true.
Proof.
  induction l as [|x r IH]; simpl; [split; auto using NoDup_nil|].
  rewrite andb_true_iff, negb_true_iff, <- IH, NoDup_cons_iff.
  split; intros [H1 H2]; split; auto.
  - apply not_true_is_false. intros H. apply existsb_exists in H as [y [Hy Hxy]].
    apply Heq in Hxy. subst. auto.
  - intros Hin. assert (existsb (eqb x) r = true) as E
      by (apply existsb_exists; exists x; split; [auto | apply Heq; reflexivity]).
    congruence.
Qed.
Definition nat_nodup_spec := nodupb_spec Nat.eqb Nat.eqb_eq.

Lemma NoDup_map_cons : forall (x : nat) (L : list (list nat)),
  NoDup L -> NoDup (map (cons x) L).
Proof.
  intros x L H. induction H as [|y L Hy HL IH]; simpl; constructor; auto.
  rewrite in_map_iff. intros [z [Hz Hin]]. injection Hz as ->. contradiction.
Qed.
Lemma all_lists_NoDup : forall k len, NoDup (all_lists k len).
Proof.
  intros k len. induction len as [|len IH]; simpl; [repeat constructor; simpl; tauto|].
  generalize (seq_NoDup k 1). generalize (seq 1 k). intros l Hl.
  induction Hl as [|x l Hx Hl IHl]; simpl; [constructor|].
  apply NoDup_app; [apply NoDup_map_cons, IH | exact IHl |].
  intros a Ha Hb. apply in_map_iff in Ha as [u [<- _]].
  apply in_flat_map in Hb as [y [Hy Hb]]. apply in_map_iff in Hb as [v [Hv _]].
  injection Hv as -> _. contradiction.
Qed.

Definition range_b (n : nat) (w : list nat) : bool :=
  forallb (fun x => (1 <=? x) && (x <=? n)) w.
Lemma range_spec : forall n w, Forall (fun x => 1 <= x <= n) w <-> range_b n w = true.
Proof.
  intros n w. unfold range_b. rewrite Forall_forall, forallb_forall.
  split; intros H x Hx; specialize (H x Hx);
    [apply andb_true_iff; rewrite !Nat.leb_le | apply andb_true_iff in H; rewrite !Nat.leb_le in H];
    lia.
Qed.

Definition permb (n : nat) (w : list nat) : bool :=
  (length w =? n) && nodupb Nat.eqb w && range_b n w.
Lemma perm_facts : forall n w, Permutation (seq 1 n) w ->
  length w = n /\ Forall (fun x => 1 <= x <= n) w.
Proof.
  intros n w H. split; [rewrite <- (Permutation_length H), length_seq; reflexivity|].
  apply Forall_forall. intros x Hx.
  apply (Permutation_in _ (Permutation_sym H)), in_seq in Hx. lia.
Qed.
Lemma permb_spec : forall n w, Permutation (seq 1 n) w <-> permb n w = true.
Proof.
  intros n w. unfold permb. rewrite !andb_true_iff, Nat.eqb_eq, <- nat_nodup_spec, <- range_spec.
  split.
  - intros H. destruct (perm_facts n w H). repeat split; auto.
    exact (Permutation_NoDup H (seq_NoDup _ _)).
  - intros [[Hl Hnd] Hr]. rewrite Forall_forall in Hr.
    assert (incl w (seq 1 n)) as Hi by (intros x Hx; apply in_seq; specialize (Hr x Hx); lia).
    apply NoDup_Permutation; [apply seq_NoDup | exact Hnd|]. intros x. split; [|apply Hi].
    apply (NoDup_length_incl Hnd); [rewrite length_seq; lia | exact Hi].
Qed.

Lemma card_by_filter (P : list nat -> Prop) (p : list nat -> bool) (U : list (list nat)) :
  NoDup U -> (forall w, P w -> In w U) -> (forall w, P w <-> p w = true) ->
  has_cardinality P (length (filter p U)).
Proof.
  intros HU Hc Hp. exists (filter p U). split; [|split; [|reflexivity]].
  - apply NoDup_filter, HU.
  - intros w. rewrite filter_In, <- Hp. split; [tauto | intros H; split; auto].
Qed.

(* Permutations of 1..n are exactly the entries of this list, without repetition. *)
Lemma perm_enum : forall n,
  NoDup (filter (permb n) (all_lists n n)) /\
  (forall w, In w (filter (permb n) (all_lists n n)) <-> Permutation (seq 1 n) w).
Proof.
  intros n. split.
  - apply NoDup_filter, all_lists_NoDup.
  - intros w. rewrite filter_In, <- permb_spec. split; [tauto|].
    intros H. split; [|exact H]. destruct (perm_facts n w H). apply in_all_lists; auto.
Qed.
Lemma perm_in_all : forall n w, Permutation (seq 1 n) w -> In w (all_lists n n).
Proof. intros n w H. destruct (perm_facts n w H). apply in_all_lists; auto. Qed.
"""

EXAMPLES = {}

EXAMPLES["lucky_one_unlucky"] = r"""
(* Figure 2 of the paper: (3,1,1,2) has two lucky cars; (2,1,4,4) has three,
   and its fourth car leaves. *)
Example figure_2 : lucky_count 4 [3;1;1;2] = 2 /\ lucky_count 4 [2;1;4;4] = 3 /\
  park 4 [] [2;1;4;4] = [Some 2; Some 1; Some 4; None].
Proof. vm_compute. repeat split. Qed.
Example distinct_preferences_all_lucky : lucky_count 3 [2;3;1] = 3.
Proof. reflexivity. Qed.
(* n = 0: the empty list has 0 lucky cars, but 0 + 1 <> 0. *)
Example empty_not_counted : ~ one_unlucky 0 [].
Proof. intros [_ [_ H]]. discriminate. Qed.
Example one_car_never_unlucky : ~ one_unlucky 1 [1].
Proof. intros [_ [_ H]]. discriminate. Qed.
(* Not a parking function, still counted: the second car leaves unlucky. *)
Example leaving_car_counts : one_unlucky 2 [2;2].
Proof. split; [reflexivity|]. split; [apply range_spec; reflexivity | reflexivity]. Qed.
(* Preferences outside 1..n are excluded even when the lucky count fits. *)
Example range_enforced : lucky_count 2 [1;3] = 1 /\ ~ one_unlucky 2 [1;3].
Proof. split; [reflexivity|]. intros [_ [H _]]. apply range_spec in H. discriminate. Qed.
Example quicksort_small : quicksort_comparisons [] = 0 /\
  quicksort_comparisons [1;2;3] = 3 /\ quicksort_comparisons [2;1;3] = 2 /\
  quicksort_comparisons [3;1;4;2] = 4.
Proof. vm_compute. repeat split. Qed.
(* The formula side: total comparisons over all orderings, n = 0..5. *)
Example quicksort_totals :
  map (fun n => list_sum (map quicksort_comparisons (filter (permb n) (all_lists n n))))
      (seq 0 6) = [0;0;2;16;116;888].
Proof. vm_compute. reflexivity. Qed.

Definition one_unlucky_b (n : nat) (w : list nat) : bool :=
  (length w =? n) && range_b n w && (lucky_count n w + 1 =? n).
Lemma one_unlucky_spec : forall n w, one_unlucky n w <-> one_unlucky_b n w = true.
Proof.
  intros n w. unfold one_unlucky, one_unlucky_b.
  rewrite !andb_true_iff, !Nat.eqb_eq, <- range_spec. tauto.
Qed.
Lemma lucky_instance : forall n,
  length (filter (one_unlucky_b n) (all_lists n n)) =
    list_sum (map quicksort_comparisons (filter (permb n) (all_lists n n))) ->
  lucky_one_unlucky_at n.
Proof.
  intros n Hc. unfold lucky_one_unlucky_at.
  exists (list_sum (map quicksort_comparisons (filter (permb n) (all_lists n n)))). split.
  - exists (filter (permb n) (all_lists n n)). destruct (perm_enum n). auto.
  - rewrite <- Hc. apply card_by_filter; [apply all_lists_NoDup | | apply one_unlucky_spec].
    intros w [Hl [Hr _]]. apply in_all_lists; auto.
Qed.
(* The exact theorem statement for n = 0..5. *)
Example lucky_small : lucky_one_unlucky_at 0 /\ lucky_one_unlucky_at 1 /\
  lucky_one_unlucky_at 2 /\ lucky_one_unlucky_at 3 /\ lucky_one_unlucky_at 4 /\
  lucky_one_unlucky_at 5.
Proof. repeat split; apply lucky_instance; vm_compute; reflexivity. Qed.
"""

EXAMPLES["parking_exced_des"] = r"""
Example contents : parking_content 3 [1;1;3] /\ ~ parking_content 3 [1;2;1] /\
  ~ parking_content 2 [1;3].
Proof.
  split; [|split].
  - split; [reflexivity|]. split; [repeat constructor|].
    intros [|[|[|i]]] H; simpl; lia.
  - intros [_ [H _]]. inversion H as [|? ? H1 H2]; subst.
    inversion H1 as [|? ? H3 H4]; subst. inversion H4; subst. lia.
  - intros [_ [_ H]]. specialize (H 1 ltac:(lia)). simpl in H. lia.
Qed.
(* pi_i = b_(w(i)): w(1) = 3 gives pi_1 = b_3 = 2. *)
Example content_word_orientation : content_word [1;1;2] [3;1;2] = [2;1;1].
Proof. reflexivity. Qed.
(* Strict, one-based excedances. *)
Example exced_convention : exced [1;2;3] = 0 /\ exced [2;1;1] = 1 /\ exced [2;3;3] = 2.
Proof. vm_compute. repeat split. Qed.
Example des_convention : des [] = 0 /\ des [1] = 0 /\ des [2;4;1;3] = 1 /\ des [3;1;4;2] = 2.
Proof. vm_compute. repeat split. Qed.
(* sigma(i) is the spot of car i: for (3,1,1) it is 312, not its inverse 231. *)
Example outcome_orientation : park 3 [] [3;1;1] = map Some [3;1;2] /\
  park 3 [] [1;1;1] = map Some [1;2;3] /\ park 4 [] [2;4;1;3] = map Some [2;4;1;3].
Proof. vm_compute. repeat split. Qed.

Fixpoint all_some (l : list (option nat)) : option (list nat) :=
  match l with
  | [] => Some []
  | Some x :: r => option_map (cons x) (all_some r)
  | None :: _ => None
  end.
Lemma all_some_spec : forall l s, all_some l = Some s <-> l = map Some s.
Proof.
  induction l as [|[x|] r IH]; intros s; simpl.
  - split; [intros H; injection H as <-; reflexivity | destruct s; simpl; congruence].
  - destruct (all_some r) as [t|] eqn:E; simpl.
    + split; [intros H; injection H as <-; simpl; f_equal; apply IH; reflexivity|].
      destruct s as [|y s]; simpl; [congruence|]. intros H; injection H as -> H.
      apply IH in H. congruence.
    + split; [congruence|]. destruct s as [|y s]; simpl; [congruence|].
      intros H; injection H as -> H. apply IH in H. congruence.
  - split; [congruence|]. destruct s; simpl; congruence.
Qed.

Definition exc_b (n : nat) (b : list nat) (k : nat) (w : list nat) : bool :=
  permb n w && (exced (content_word b w) =? k).
Definition des_b (n : nat) (b : list nat) (k : nat) (w : list nat) : bool :=
  permb n w && match all_some (park n [] (content_word b w)) with
               | Some s => des s =? k
               | None => false
               end.
Lemma des_b_spec : forall n b k w,
  (Permutation (seq 1 n) w /\ exists sigma, park n [] (content_word b w) = map Some sigma /\
     des sigma = k) <-> des_b n b k w = true.
Proof.
  intros n b k w. unfold des_b. rewrite andb_true_iff, <- permb_spec.
  destruct (all_some (park n [] (content_word b w))) as [s|] eqn:E.
  - rewrite Nat.eqb_eq. split; intros [H1 H2]; split; auto.
    + destruct H2 as [sigma [H3 H4]]. apply all_some_spec in H3. congruence.
    + exists s. split; auto. apply all_some_spec, E.
  - split; intros [H1 H2]; [|discriminate].
    destruct H2 as [sigma [H3 _]]. apply all_some_spec in H3. congruence.
Qed.
Lemma pexd_from_counts : forall n b k,
  length (filter (exc_b n b k) (all_lists n n)) =
    length (filter (des_b n b k) (all_lists n n)) ->
  parking_exced_des_at n b k.
Proof.
  intros n b k Heq _. exists (length (filter (exc_b n b k) (all_lists n n))). split.
  - apply card_by_filter; [apply all_lists_NoDup | intros w [H _]; apply perm_in_all, H |].
    intros w. unfold exc_b. rewrite andb_true_iff, <- permb_spec, Nat.eqb_eq. tauto.
  - rewrite Heq. apply card_by_filter; [apply all_lists_NoDup | intros w [H _]; apply perm_in_all, H |].
    apply des_b_spec.
Qed.
(* The exact theorem statement for n = 4, every content b and every k. Only
   the bounds 1 <= b_j <= j are used, so the 24 bounded words are checked. *)
Example pexd_4 : forall b k, parking_exced_des_at 4 b k.
Proof.
  intros b k Hb. pose proof Hb as [Hl [_ Hbd]].
  destruct b as [|x [|y [|z [|u [|? ?]]]]]; try discriminate.
  pose proof (Hbd 0 ltac:(lia)); pose proof (Hbd 1 ltac:(lia));
    pose proof (Hbd 2 ltac:(lia)); pose proof (Hbd 3 ltac:(lia)); simpl in *.
  assert (x = 1) as -> by lia.
  assert (y = 1 \/ y = 2) as [-> | ->] by lia;
  assert (z = 1 \/ z = 2 \/ z = 3) as [-> | [-> | ->]] by lia;
  assert (u = 1 \/ u = 2 \/ u = 3 \/ u = 4) as [-> | [-> | [-> | ->]]] by lia;
  (revert Hb; apply pexd_from_counts;
   destruct k as [|[|[|[|[|k]]]]]; vm_compute; reflexivity).
Qed.

(* The inverse orientation (cars listed by spot) breaks the identity at n = 4. *)
Fixpoint index_of (x : nat) (l : list nat) : nat :=
  match l with [] => 0 | y :: r => if x =? y then 1 else S (index_of x r) end.
Definition inverse_perm (s : list nat) : list nat :=
  map (fun spot => index_of spot s) (seq 1 (length s)).
Definition des_inv_b (n : nat) (b : list nat) (k : nat) (w : list nat) : bool :=
  permb n w && match all_some (park n [] (content_word b w)) with
               | Some s => des (inverse_perm s) =? k
               | None => false
               end.
Example wrong_orientation_differs :
  inverse_perm [3;1;2] = [2;3;1] /\
  length (filter (exc_b 4 [1;1;3;3] 2) (all_lists 4 4)) = 4 /\
  length (filter (des_b 4 [1;1;3;3] 2) (all_lists 4 4)) = 4 /\
  length (filter (des_inv_b 4 [1;1;3;3] 2) (all_lists 4 4)) = 0.
Proof. vm_compute. repeat split. Qed.
"""

EXAMPLES["cyclic_4321_213_fib"] = r"""
(* c_(i+1) = pi(c_i): pi = 231 is the cycle (1,2,3), and 312 is (1,3,2). *)
Example cycle_form_convention : cycle_form [2;3;1] = [1;2;3] /\
  cycle_form [3;1;2] = [1;3;2] /\ cycle_form [3;4;2;1] = [1;3;2;4] /\
  cycle_form [4;3;1;2] = [1;4;2;3].
Proof. vm_compute. repeat split. Qed.
Example cyclic_yes : cyclic_perm 4 [3;4;2;1].
Proof. split; [apply permb_spec | apply nat_nodup_spec]; reflexivity. Qed.
Example cyclic_no : ~ cyclic_perm 4 [2;1;4;3] /\ ~ cyclic_perm 3 [1;3;2].
Proof.
  split; intros [_ H]; apply nat_nodup_spec in H; vm_compute in H; discriminate.
Qed.
(* Occurrences need not be consecutive; equal lengths are required. *)
Example containment : avoids [2;1;3] [1;3;2;4] = false /\
  avoids [2;1;3] [3;9;1;7;4] = false /\ avoids [2;1;3] [1;4;2;3] = true /\
  avoids [4;3;2;1] [3;4;2;1] = true /\ avoids [4;3;2;1] [5;3;4;2;1] = false /\
  avoids [2;1;3] [] = true /\ avoids [1;2] [5] = true /\ avoids [1] [5] = false.
Proof. vm_compute. repeat split. Qed.
(* The cycle convention matters for individual permutations: pi = 3421 has
   cycle form 1324, which contains 213; the reversed form 1423 (the standard
   form of pi^-1) avoids it. Brute force shows the counts agree anyway. *)
Example convention_matters_pointwise :
  avoids [2;1;3] (cycle_form [3;4;2;1]) = false /\
  avoids [2;1;3] (cycle_form [4;3;1;2]) = true.
Proof. vm_compute. repeat split. Qed.
Example fib_values : map (fun n => fib (2 * n + 1)) (seq 0 8) = [1;2;5;13;34;89;233;610].
Proof. vm_compute. reflexivity. Qed.

Definition pan_b (n : nat) (w : list nat) : bool :=
  permb (n + 2) w && nodupb Nat.eqb (cycle_form w) &&
  avoids [4;3;2;1] w && avoids [2;1;3] (cycle_form w).
Lemma pan_instance : forall n,
  length (filter (pan_b n) (all_lists (n + 2) (n + 2))) = fib (2 * n + 1) ->
  cyclic_4321_213_fib_at n.
Proof.
  intros n Hc. unfold cyclic_4321_213_fib_at. rewrite <- Hc.
  apply card_by_filter; [apply all_lists_NoDup | intros w [[H _] _]; apply perm_in_all, H |].
  intros w. unfold pan_b, cyclic_perm.
  rewrite !andb_true_iff, <- permb_spec, <- nat_nodup_spec. tauto.
Qed.
(* The exact theorem statement for sizes 2..5. *)
Example pan_small : cyclic_4321_213_fib_at 0 /\ cyclic_4321_213_fib_at 1 /\
  cyclic_4321_213_fib_at 2 /\ cyclic_4321_213_fib_at 3.
Proof. repeat split; apply pan_instance; vm_compute; reflexivity. Qed.
"""

EXAMPLES["cyclic_rot1432_4321"] = r"""
Example rotations : rotate 0 [1;2;3] = [1;2;3] /\ rotate 1 [1;2;3;4] = [2;3;4;1] /\
  rotate 3 [1;2;3;4] = [4;1;2;3].
Proof. vm_compute. repeat split. Qed.
Example cycle_form_convention : cycle_form [2;3;1] = [1;2;3] /\ cycle_form [3;1;2] = [1;3;2].
Proof. vm_compute. repeat split. Qed.
(* pi = 35214 avoids 4321 and its standard cycle form 13254 avoids 1432, but
   the rotation 25413 contains 1432 (as 2543), so pi is excluded. *)
Example rotation_matters : cyclic_perm 5 [3;5;2;1;4] /\
  avoids [4;3;2;1] [3;5;2;1;4] = true /\
  cycle_form [3;5;2;1;4] = [1;3;2;5;4] /\
  avoids [1;4;3;2] (rotate 0 (cycle_form [3;5;2;1;4])) = true /\
  rotate 2 (cycle_form [3;5;2;1;4]) = [2;5;4;1;3] /\
  avoids [1;4;3;2] (rotate 2 (cycle_form [3;5;2;1;4])) = false.
Proof.
  split; [split; [apply permb_spec | apply nat_nodup_spec]; reflexivity|].
  vm_compute. repeat split.
Qed.
Example formula_values : map (fun n => 2 ^ (n + 2) - (3 * n + 4) / 2) (seq 0 7) =
  [2;5;11;26;56;119;245].
Proof. vm_compute. reflexivity. Qed.

Definition zz_b (n : nat) (w : list nat) : bool :=
  permb (n + 3) w && nodupb Nat.eqb (cycle_form w) && avoids [4;3;2;1] w &&
  forallb (fun i => avoids [1;4;3;2] (rotate i (cycle_form w))) (seq 0 (n + 3)).
Lemma zz_instance : forall n,
  length (filter (zz_b n) (all_lists (n + 3) (n + 3))) + (3 * n + 4) / 2 = 2 ^ (n + 2) ->
  cyclic_rot1432_4321_at n.
Proof.
  intros n Hc. unfold cyclic_rot1432_4321_at.
  exists (length (filter (zz_b n) (all_lists (n + 3) (n + 3)))). split; [|exact Hc].
  apply card_by_filter; [apply all_lists_NoDup | intros w [[H _] _]; apply perm_in_all, H |].
  intros w. unfold zz_b, cyclic_perm.
  rewrite !andb_true_iff, <- permb_spec, <- nat_nodup_spec, forallb_forall.
  assert ((forall i, i < n + 3 -> avoids [1;4;3;2] (rotate i (cycle_form w)) = true) <->
          (forall i, In i (seq 0 (n + 3)) -> avoids [1;4;3;2] (rotate i (cycle_form w)) = true))
    as E by (split; intros H i Hi; apply H; [apply in_seq in Hi | apply in_seq]; lia).
  rewrite E. tauto.
Qed.
(* The exact theorem statement for sizes 3..5. *)
Example zz_small : cyclic_rot1432_4321_at 0 /\ cyclic_rot1432_4321_at 1 /\
  cyclic_rot1432_4321_at 2.
Proof. repeat split; apply zz_instance; vm_compute; reflexivity. Qed.
"""

EXAMPLES["vpf_nonincreasing"] = r"""
(* Occupied p: back to p-1 first, then forward to p+1, and no further. *)
Example tie_breaking : vacillating_spot 3 [2] 2 = Some 1 /\
  vacillating_spot 3 [1;2] 2 = Some 3 /\ vacillating_spot 3 [1] 1 = Some 2 /\
  vacillating_spot 3 [3;2] 3 = None /\ vacillating_spot 4 [3;2;4] 3 = None.
Proof. vm_compute. repeat split. Qed.
(* Examples from the proof of Theorem 3.6. *)
Example paper_examples : all_park 3 [] [3;1;1] = true /\ all_park 4 [] [4;2;2;1] = false.
Proof. vm_compute. repeat split. Qed.
Example orientation : Sorted ge [3;3;1] /\ ~ Sorted ge [1;2].
Proof.
  split; [repeat constructor|].
  intros H. inversion H as [|? ? _ H1]; subst. inversion H1; subst. unfold ge in *. lia.
Qed.
Example empty_counted : nonincreasing_vpf 0 [].
Proof. repeat split; constructor. Qed.
Example count_values : map vpf_count (seq 0 10) = [1;1;3;6;13;29;64;141;311;686].
Proof. vm_compute. reflexivity. Qed.

Fixpoint noninc_b (l : list nat) : bool :=
  match l with
  | x :: ((y :: _) as r) => (y <=? x) && noninc_b r
  | _ => true
  end.
Lemma noninc_spec : forall l, Sorted ge l <-> noninc_b l = true.
Proof.
  induction l as [|x [|y r] IH]; simpl; [split; auto | split; auto; repeat constructor|].
  rewrite andb_true_iff, Nat.leb_le, <- IH. split.
  - intros H. inversion H as [|? ? H1 H2]; subst. inversion H2; subst. unfold ge in *. auto.
  - intros [H1 H2]. constructor; [exact H2 | constructor; unfold ge; lia].
Qed.
Definition vpf_b (n : nat) (w : list nat) : bool :=
  (length w =? n) && range_b n w && noninc_b w && all_park n [] w.
(* The paper's list of the six members for n = 3, in the same order. *)
Example paper_list_3 : filter (vpf_b 3) (all_lists 3 3) =
  [[2;2;2];[3;1;1];[3;2;1];[3;2;2];[3;3;1];[3;3;2]].
Proof. vm_compute. reflexivity. Qed.
Lemma vpf_instance : forall n,
  length (filter (vpf_b n) (all_lists n n)) = vpf_count n -> vpf_nonincreasing_at n.
Proof.
  intros n Hc. unfold vpf_nonincreasing_at. rewrite <- Hc.
  apply card_by_filter; [apply all_lists_NoDup | intros w [Hl [Hr _]]; apply in_all_lists; auto |].
  intros w. unfold nonincreasing_vpf, vpf_b.
  rewrite !andb_true_iff, Nat.eqb_eq, <- range_spec, <- noninc_spec. tauto.
Qed.
(* The exact theorem statement for n = 0..5. *)
Example vpf_small : vpf_nonincreasing_at 0 /\ vpf_nonincreasing_at 1 /\
  vpf_nonincreasing_at 2 /\ vpf_nonincreasing_at 3 /\ vpf_nonincreasing_at 4 /\
  vpf_nonincreasing_at 5.
Proof. repeat split; apply vpf_instance; vm_compute; reflexivity. Qed.
"""


@pytest.mark.parametrize("name", NAMES)
def test_rocq_examples_and_small_instances(name, tmp_path):
    p = _load(SOURCE / f"{name}.v", "research", "combinatorics")
    text = "\n\n".join([p.header(), statement_as_definition(p), COMMON, EXAMPLES[name]])
    (tmp_path / "Examples.v").write_text(text)
    result = coqc(TC, tmp_path, "Examples.v")
    assert result.ok, result.stderr


# Independent Python enumerations of the papers' claims. They share no code
# with the Rocq definitions and follow the papers' wording directly.

def park_forward(prefs, n):
    """Spot of each car (None if it leaves) under the classical rule."""
    occupied, spots = set(), []
    for p in prefs:
        s = next((s for s in range(p, n + 1) if s not in occupied), None)
        spots.append(s)
        if s is not None:
            occupied.add(s)
    return spots


def test_lucky_cars_python():
    def quicksort(xs):
        if not xs:
            return 0
        pivot, rest = xs[0], xs[1:]
        return (len(rest) + quicksort([x for x in rest if x <= pivot])
                + quicksort([x for x in rest if x > pivot]))

    def recurrence(n):  # A(m+1) = (m+2) A(m) + 2 m m!
        a = 0
        for m in range(n):
            a = (m + 2) * a + 2 * m * math.factorial(m)
        return a

    from fractions import Fraction
    for n in range(8):
        total = sum(quicksort(list(w)) for w in itertools.permutations(range(1, n + 1)))
        harmonic = sum(Fraction(1, i) for i in range(1, n + 1))
        assert total == recurrence(n) == math.factorial(n) * (2 * (n + 1) * harmonic - 4 * n)
        if n <= 6:
            lucky = sum(1 for a in itertools.product(range(1, n + 1), repeat=n)
                        if sum(s == p for p, s in zip(a, park_forward(a, n))) == n - 1)
            assert lucky == total, n
    assert [recurrence(n) for n in range(8)] == [0, 0, 2, 16, 116, 888, 7416, 67968]


def test_parking_exced_des_python():
    def contents(n, prefix=()):
        if len(prefix) == n:
            yield prefix
            return
        for v in range(prefix[-1] if prefix else 1, len(prefix) + 2):
            yield from contents(n, prefix + (v,))

    def des(s):
        return sum(s[i] > s[i + 1] for i in range(len(s) - 1))

    def inverse(s):
        inv = [0] * len(s)
        for car, spot in enumerate(s, 1):
            inv[spot - 1] = car
        return inv

    inverse_fails = set()
    for n in range(1, 6):
        for b in contents(n):
            exced, descents, inverse_descents = ([0] * (n + 1) for _ in range(3))
            for w in itertools.permutations(range(1, n + 1)):
                pi = [b[j - 1] for j in w]
                sigma = park_forward(pi, n)
                assert None not in sigma
                exced[sum(pi[i - 1] > i for i in range(1, n + 1))] += 1
                descents[des(sigma)] += 1
                inverse_descents[des(inverse(sigma))] += 1
            assert exced == descents, (b, exced, descents)
            if exced != inverse_descents:
                inverse_fails.add(n)
    # The wrong orientation oc(pi)^-1 holds through n = 3 and fails from n = 4.
    assert inverse_fails == {4, 5}


def contains_pattern(pattern, xs):
    k = len(pattern)
    return any(all((xs[i[s]] < xs[i[t]]) == (pattern[s] < pattern[t])
                   for s in range(k) for t in range(s + 1, k))
               for i in itertools.combinations(range(len(xs)), k))


def cyclic_permutations(n):
    """(one-line, standard cycle form) with pi(c_i) = c_(i+1)."""
    for rest in itertools.permutations(range(2, n + 1)):
        c = (1,) + rest
        w = [0] * n
        for i in range(n):
            w[c[i] - 1] = c[(i + 1) % n]
        yield tuple(w), c


def test_cyclic_patterns_python():
    fib = [0, 1]
    while len(fib) < 20:
        fib.append(fib[-1] + fib[-2])
    for n in range(1, 9):
        pan = pan_inverse_convention = rot = 0
        for w, c in cyclic_permutations(n):
            if contains_pattern((4, 3, 2, 1), w):
                continue
            pan += not contains_pattern((2, 1, 3), c)
            # Inverse convention (c_(i+1) = pi^-1(c_i)) reverses c_2 ... c_n.
            pan_inverse_convention += not contains_pattern((2, 1, 3), (1,) + c[:0:-1])
            rot += all(not contains_pattern((1, 4, 3, 2), c[i:] + c[:i]) for i in range(n))
        formula = 2 ** (n - 1) - (3 * n - 5) // 2
        if n >= 2:
            assert pan == fib[2 * n - 3], n
        # The inverse convention gives the same counts (a_n(4321;312) in the paper).
        assert pan_inverse_convention == pan
        # Zhang-Zhao's formula holds from n = 3 but not for n = 1, 2.
        assert (rot == formula) == (n >= 3), (n, rot, formula)


def test_vacillating_python():
    def all_park(prefs, n):
        occupied = set()
        for p in prefs:
            s = next((s for s in (p, p - 1, p + 1) if 1 <= s <= n and s not in occupied), None)
            if s is None:
                return False
            occupied.add(s)
        return True

    v = [sum(all_park(a, n) for a in itertools.combinations_with_replacement(range(n, 0, -1), n))
         for n in range(11)]
    assert v == [1, 1, 3, 6, 13, 29, 64, 141, 311, 686, 1513]
    assert all(v[n] == 2 * v[n - 1] + v[n - 3] for n in range(4, 11))
    assert v[3] != 2 * v[2] + v[0]  # so the recurrence needs four initial values
