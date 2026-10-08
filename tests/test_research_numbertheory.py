"""Statement checks for the number-theory research tasks.

Each problem gets (1) the verifier check of the admitted statement, (2) Rocq
examples on the actual definitions, pinning conventions and pitfalls, plus
vm_compute comparisons of the computable side and, where cheap, a proof of a
tiny instance, and (3) an independent Python enumeration of the paper claim.
Finite checks are sanity checks, not proofs of the general statements.
"""
import itertools
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from rlb.external import _load, split_v
from rlb.problem import PREAMBLE_HAZARD_RE, Problem
from rlb.research import SOURCE
from rlb.rocq import Toolchain, coqc, verify

TC = Toolchain.discover()
NAMES = ["fib_signed_zero_trib", "quaternary_shift", "digit_insert_rank",
         "hofstadter3_death", "comma_danger_count"]


@pytest.mark.parametrize("name", NAMES)
def test_statement_passes_verifier_as_admitted(name):
    path = SOURCE / f"{name}.v"
    stem, imports, preamble, statement = split_v(path.read_text())
    assert stem == path.stem and not PREAMBLE_HAZARD_RE.search(preamble)
    p = Problem(stem, "research", "number_theory", imports, preamble, statement, None, None)
    with TemporaryDirectory() as t:
        vr = verify(p, p.task_source(), TC, Path(t) / "check")
    assert vr.status == "axioms", (vr.status, vr.message)
    assert [n for n, _ in vr.assumptions] == [f"Solution.{stem}"], vr.assumptions


# Shared Ltac for the Rocq examples below.
TACTICS = r'''
From Stdlib Require Import Bool Lia.
Ltac nodup_lits :=
  repeat (apply NoDup_cons; [simpl; intuition discriminate|]); apply NoDup_nil.
Ltac in_lits := simpl; repeat (first [left; reflexivity | right]).
Ltac forall_lia := repeat (apply Forall_cons; [lia|]); apply Forall_nil.
'''

FIB = r'''
Example fib_initial : map fib (seq 0 9) = [0;1;1;2;3;5;8;13;21]%Z.
Proof. reflexivity. Qed.
Example trib_initial : map trib (seq 0 14) =
  [1;1;3;5;9;17;31;57;105;193;355;653;1201;2209].
Proof. reflexivity. Qed.
(* F_1 and F_2 are distinct positions of equal weight; last digit is F_1. *)
Example positions_1_2 : fib_value [1;0]%Z = 1%Z /\ fib_value [0;1]%Z = 1%Z /\
  fib_value [1;0;0;0]%Z = 3%Z.
Proof. repeat split. Qed.
Example paper_length_3 : signed_zero_rep 3 [1;-1;-1]%Z /\
  signed_zero_rep 3 [-1;1;1]%Z.
Proof. repeat split; repeat constructor; discriminate. Qed.
Example leading_zero_allowed : signed_zero_rep 3 [0;1;-1]%Z.
Proof. repeat split; repeat constructor; discriminate. Qed.
Example length_is_fixed : ~ signed_zero_rep 3 [1;-1]%Z.
Proof. intros [H _]; discriminate. Qed.
Example digit_bound : fib_value [2;-2]%Z = 0%Z /\ ~ signed_zero_rep 2 [2;-2]%Z.
Proof. split; [reflexivity|]. intros [_ [H _]]. inversion H; lia. Qed.
Example empty_list : signed_zero_rep 0 [].
Proof. repeat split; constructor. Qed.

(* Test-only enumeration of all fixed-length digit lists. *)
Fixpoint all_digit_lists (k : nat) : list (list Z) :=
  match k with
  | 0 => [[]]
  | S k' => flat_map (fun ds => [(-1)%Z :: ds; 0%Z :: ds; 1%Z :: ds])
                     (all_digit_lists k')
  end.
Example enumerated_counts :
  map (fun k => length (filter (fun ds => Z.eqb (fib_value ds) 0)
                               (all_digit_lists k))) (seq 0 11)
  = map trib (seq 0 11).
Proof. vm_compute. reflexivity. Qed.

Ltac digit_cases :=
  repeat match goal with
  | H : Forall _ (_ :: _) |- _ => apply Forall_cons_iff in H; destruct H
  | H : (-1 <= ?a <= 1)%Z |- _ =>
      assert (a = -1 \/ a = 0 \/ a = 1)%Z by lia; clear H
  | H : _ \/ _ |- _ => destruct H; subst
  end.
Ltac card_proof :=
  split; [nodup_lits|]; split; [|reflexivity]; intros ds; split;
  [ intros H; simpl in H; repeat destruct H as [H|H]; subst; try contradiction;
    (split; [reflexivity|split; [forall_lia|reflexivity]])
  | intros [Hl [Hd Hv]];
    repeat (destruct ds as [|?d ds]; simpl in Hl; try discriminate);
    digit_cases; vm_compute in Hv; try discriminate; in_lits ].

(* The statement itself, fully proved at k = 2 and k = 3. *)
Example card_2 : has_cardinality (signed_zero_rep 2) (trib 2).
Proof. exists [[0;0];[1;-1];[-1;1]]%Z. card_proof. Qed.
Example card_3 : has_cardinality (signed_zero_rep 3) (trib 3).
Proof. exists [[0;0;0];[0;1;-1];[0;-1;1];[1;-1;-1];[-1;1;1]]%Z. card_proof. Qed.
'''


def rocq_examples(name, examples, tmp_path):
    p = _load(SOURCE / f"{name}.v", "research", "test")
    (tmp_path / "Examples.v").write_text(p.header() + "\n" + TACTICS + "\n" + examples)
    result = coqc(TC, tmp_path, "Examples.v")
    assert result.ok, result.stderr


def test_fib_rocq_examples(tmp_path):
    rocq_examples("fib_signed_zero_trib", FIB, tmp_path)


def test_fib_small_counts_independently():
    # Independent enumeration with F_1 = F_2 = 1 as distinct positions, and
    # the paper's initial values B(0;1..3) = 1, 3, 5 plus the empty list.
    fib = [0, 1]
    while len(fib) < 16:
        fib.append(fib[-1] + fib[-2])
    counts = [sum(sum(a * fib[k - i] for i, a in enumerate(ds)) == 0
                  for ds in itertools.product((-1, 0, 1), repeat=k)) for k in range(12)]
    assert counts[:4] == [1, 1, 3, 5]
    for k in range(3, 11):
        assert counts[k + 1] == counts[k] + counts[k - 1] + counts[k - 2]
    # Theorem 1.1's printed values.
    assert counts[1:12] == [1, 3, 5, 9, 17, 31, 57, 105, 193, 355, 653]


def quaternary_counts(digits, max_len):
    """Values of all digit strings with no leading zero, up to max_len digits;
    the empty string represents 0."""
    counts = {0: 1}
    for size in range(1, max_len + 1):
        for ds in itertools.product(digits, repeat=size):
            if ds[0] != 0:
                v = 0
                for d in ds:
                    v = 4 * v + d
                counts[v] = counts.get(v, 0) + 1
    return counts


def ones(j):
    return (4**j - 1) // 3


def test_quaternary_shift_small_cases_independently():
    # Strings of length L have value >= 4^(L-1) (hyper) or
    # |value| >= (4^(L-1)+2)/3 (balanced), so these lengths give exact
    # f4(m) for m < 4^6 and b4(n) for |n| <= 5461.
    f4 = quaternary_counts(range(5), 6)
    b4 = quaternary_counts(range(-2, 3), 8)
    assert f4[67] == 3 and b4[25] == 3          # the paper's examples
    for j in range(1, 6):
        lo, hi, t = -ones(j), ones(j + 1), 2 * ones(j)
        assert t + hi + 1 < 4**6 and max(-lo, hi) + 1 <= 5461
        assert all(f4.get(t + n, 0) == b4[n] for n in range(lo, hi + 1)), j
        # Sharpness (not part of the Rocq statement): fails just outside.
        assert f4.get(t + lo - 1, 0) != b4[lo - 1]
        assert f4.get(t + hi + 1, 0) != b4[hi + 1]
    # j = 0 also holds on [0, 1]; the statement follows the paper's j >= 1.
    assert f4[0] == b4[0] == 1 and f4[1] == b4[1] == 1


QUATERNARY = r'''
Example repdigits : repdigit 1 0 = 0%Z /\ repdigit 1 1 = 1%Z /\
  repdigit 1 2 = 5%Z /\ repdigit 1 3 = 21%Z /\ repdigit 2 1 = 2%Z /\
  repdigit 2 3 = 42%Z.
Proof. repeat split. Qed.

Ltac rep_ok := split; [forall_lia|split; [simpl; first [exact I | discriminate]
                                          | reflexivity]].
(* The paper's examples f4(67) = 3 and b4(25) = 3. *)
Example hyper_67 : hyperquaternary 67 [1;0;0;3]%Z /\ hyperquaternary 67 [4;0;3]%Z /\
  hyperquaternary 67 [3;4;3]%Z.
Proof. repeat (split; [rep_ok|]); rep_ok. Qed.
Example balanced_25 : balanced_quaternary 25 [1;2;1]%Z /\
  balanced_quaternary 25 [2;-2;1]%Z /\ balanced_quaternary 25 [1;-2;-2;1]%Z.
Proof. repeat (split; [rep_ok|]); rep_ok. Qed.
Example empty_is_zero : hyperquaternary 0 [] /\ balanced_quaternary 0 [].
Proof. split; rep_ok. Qed.
Example no_leading_zero : ~ hyperquaternary 3 [0;3]%Z /\ ~ balanced_quaternary 0 [0]%Z.
Proof. split; intros [_ [H _]]; apply H; reflexivity. Qed.
Ltac bad_digit := intros [H _];
  repeat (apply Forall_cons_iff in H; destruct H as [? H]); lia.
Example digit_ranges : ~ hyperquaternary 5 [5]%Z /\ ~ hyperquaternary 3 [1;-1]%Z /\
  ~ balanced_quaternary 3 [3]%Z /\ balanced_quaternary 3 [1;-1]%Z.
Proof. repeat split; try bad_digit; try forall_lia; discriminate. Qed.

(* Test-only truncated enumeration: all digit strings of length <= L. *)
Fixpoint strings (digits : list Z) (len : nat) : list (list Z) :=
  match len with
  | 0 => [[]]
  | S l => flat_map (fun ds => map (fun d => d :: ds) digits) (strings digits l)
  end.
Definition count_reps (digits : list Z) (L : nat) (v : Z) : nat :=
  length (filter (fun ds => (match ds with [] => true | d :: _ => negb (Z.eqb d 0) end)
                            && Z.eqb (quaternary_value ds) v)
                 (flat_map (strings digits) (seq 0 (S L)))).
Definition zrange (lo : Z) (len : nat) : list Z :=
  map (fun i => lo + Z.of_nat i)%Z (seq 0 len).
(* j = 3: n in [-21, 85]; five digits suffice for both families here. *)
Example j3_matches_python :
  map (count_reps [-2;-1;0;1;2]%Z 5) (zrange (-21)%Z 107) = PYTHON_B4 /\
  map (fun n => count_reps [0;1;2;3;4]%Z 5 (repdigit 2 3 + n)) (zrange (-21)%Z 107)
    = PYTHON_B4.
Proof. split; vm_compute; reflexivity. Qed.

(* Length bounds, then the statement proved at j = 1 for n = -1 and n = 2. *)
Lemma pow4_nonneg (k : nat) : (1 <= 4 ^ Z.of_nat k)%Z.
Proof. assert (0 < 4 ^ Z.of_nat k)%Z by (apply Z.pow_pos_nonneg; lia). lia. Qed.
Lemma pow4_succ (k : nat) : (4 ^ Z.of_nat (S k) = 4 * 4 ^ Z.of_nat k)%Z.
Proof. rewrite Nat2Z.inj_succ, Z.pow_succ_r by lia. reflexivity. Qed.
Lemma hq_nonneg ds : Forall (fun d => 0 <= d <= 4)%Z ds -> (0 <= quaternary_value ds)%Z.
Proof.
  induction 1 as [|d ds Hd _ IH]; simpl; [lia|].
  pose proof (pow4_nonneg (length ds)). nia.
Qed.
Lemma hq_lead m d ds : hyperquaternary m (d :: ds) -> (4 ^ Z.of_nat (length ds) <= m)%Z.
Proof.
  intros [H [Hz Hv]]. apply Forall_cons_iff in H as [Hd H]. apply hq_nonneg in H.
  simpl in Hv. pose proof (pow4_nonneg (length ds)). nia.
Qed.
Lemma bq_bound ds : Forall (fun d => -2 <= d <= 2)%Z ds ->
  (-2 * (4 ^ Z.of_nat (length ds) - 1) <= 3 * quaternary_value ds
     <= 2 * (4 ^ Z.of_nat (length ds) - 1))%Z.
Proof.
  induction 1 as [|d ds Hd _ IH]; [simpl; lia|].
  change (quaternary_value (d :: ds))
    with (d * 4 ^ Z.of_nat (length ds) + quaternary_value ds)%Z.
  change (length (d :: ds)) with (S (length ds)).
  rewrite pow4_succ. pose proof (pow4_nonneg (length ds)). nia.
Qed.
Lemma bq_lead n d ds : balanced_quaternary n (d :: ds) ->
  (4 ^ Z.of_nat (length ds) + 2 <= 3 * Z.abs n)%Z.
Proof.
  intros [H [Hz Hv]]. apply Forall_cons_iff in H as [Hd H]. apply bq_bound in H.
  simpl in Hv. pose proof (pow4_nonneg (length ds)).
  assert (1 <= d \/ d <= -1)%Z as [|] by lia; nia.
Qed.

Ltac zcases :=
  repeat match goal with
  | H : Forall _ (_ :: _) |- _ => apply Forall_cons_iff in H; destruct H
  | H : (0 <= ?a <= 4)%Z |- _ =>
      assert (a = 0 \/ a = 1 \/ a = 2 \/ a = 3 \/ a = 4)%Z by lia; clear H
  | H : (-2 <= ?a <= 2)%Z |- _ =>
      assert (a = -2 \/ a = -1 \/ a = 0 \/ a = 1 \/ a = 2)%Z by lia; clear H
  | H : _ \/ _ |- _ => destruct H; subst
  end.
Ltac quaternary_card lead :=
  split; [nodup_lits|]; split; [|reflexivity]; intros ds; split;
  [ intros H; simpl in H; repeat destruct H as [H|H]; subst; try contradiction; rep_ok
  | intros H; destruct ds as [|d [|e [|f ds]]];
    [ destruct H as [_ [_ Hv]]; vm_compute in Hv; discriminate
    | destruct H as [Hf [Hz Hv]]; zcases; vm_compute in Hv; try discriminate; in_lits
    | destruct H as [Hf [Hz Hv]]; zcases; try (exfalso; apply Hz; reflexivity);
      vm_compute in Hv; try discriminate; in_lits
    | apply lead in H; simpl length in H; rewrite !pow4_succ in H;
      pose proof (pow4_nonneg (length ds));
      try (unfold repdigit in H; simpl repeat in H; simpl quaternary_value in H);
      lia ] ].

Example j1_n_minus_1 :
  has_cardinality (hyperquaternary (repdigit 2 1 + -1)) 1 /\
  has_cardinality (balanced_quaternary (-1)) 1.
Proof.
  split; [exists [[1]]%Z; quaternary_card hq_lead
         |exists [[-1]]%Z; quaternary_card bq_lead].
Qed.
Example j1_n_2 :
  has_cardinality (hyperquaternary (repdigit 2 1 + 2)) 2 /\
  has_cardinality (balanced_quaternary 2) 2.
Proof.
  split; [exists [[4];[1;0]]%Z; quaternary_card hq_lead
         |exists [[2];[1;-2]]%Z; quaternary_card bq_lead].
Qed.
'''


def test_quaternary_rocq_examples(tmp_path):
    b4 = quaternary_counts(range(-2, 3), 5)
    expected = "[" + ";".join(str(b4[n]) for n in range(-21, 86)) + "]"
    rocq_examples("quaternary_shift", QUATERNARY.replace("PYTHON_B4", expected), tmp_path)


def insertion_set(n):
    s = str(n)
    return {int(t) for i in range(len(s) + 1) for x in "0123456789"
            for t in [s[:i] + x + s[i:]] if t[0] != "0"}


def test_digit_insert_rank_independently():
    assert sorted(insertion_set(8)) == [18, 28, 38, 48, 58, 68, 78, 80, 81, 82, 83,
                                        84, 85, 86, 87, 88, 89, 98]  # paper's S(8)
    for n in range(1, 20000):
        s = sorted(insertion_set(n))
        assert s.index(10 * n) + 1 == sum(map(int, str(n))), n
    # Counting (position, digit) pairs instead of values would be wrong: for
    # n = 10 the value 100 arises twice, so the pair count exceeds a(10) = 1.
    pairs = sum(1 for i in range(3) for x in "0123456789"
                if (t := "10"[:i] + x + "10"[i:])[0] != "0" and int(t) <= 100)
    assert pairs == 2 and sum(m <= 100 for m in insertion_set(10)) == 1


DIGIT_INSERT = r'''
Example value_123 : decimal_value [1;2;3] = 123.
Proof. reflexivity. Qed.
Example expansion_8 : decimal_expansion 8 [8].
Proof. repeat split; [forall_lia|discriminate]. Qed.
Example expansion_no_leading_zero : ~ decimal_expansion 8 [0;8].
Proof. intros [_ [H _]]; apply H; reflexivity. Qed.
Example expansion_nonempty : ~ decimal_expansion 0 [].
Proof. intros [_ [H _]]; exact H. Qed.

Ltac ins i x := exists i, x; split; [simpl; lia|]; split; [lia|];
  simpl; split; [discriminate|reflexivity].
Example inserted_examples : inserted [8] 18 /\ inserted [8] 80 /\ inserted [8] 98
  /\ inserted [1;0] 100 /\ inserted [1;0] 190.
Proof. repeat split; [ins 0 1|ins 1 0|ins 0 9|ins 1 0|ins 1 9]. Qed.
(* 100 arises from two different insertions into 10; it is one value. *)
Example two_insertions_one_value : inserted [1;0] 100.
Proof. ins 2 0. Qed.

Ltac split_nat x := destruct x as [|x]; [|first [lia | split_nat x]].
Ltac insertion_cases :=
  let i := fresh "i" in let x := fresh "x" in
  intros [i [x [Hi [Hx H]]]]; simpl length in Hi; split_nat i; split_nat x;
  simpl in H; destruct H as [Hlead Hval]; try (exfalso; apply Hlead; reflexivity);
  subst.
(* Inserting 0 in front of 8 gives 08, which has a leading zero. *)
Example leading_zero_insertion : ~ inserted [8] 8.
Proof. insertion_cases; discriminate. Qed.

(* Test-only enumeration of S(n) and of the rank. *)
Definition insertion_values (ds : list nat) : list nat :=
  flat_map (fun i => flat_map (fun x =>
      match firstn i ds ++ x :: skipn i ds with
      | [] => []
      | e :: es => if e =? 0 then [] else [decimal_value (e :: es)]
      end) (seq 0 10)) (seq 0 (S (length ds))).
Definition rank (ds : list nat) : nat :=
  length (nodup Nat.eq_dec
    (filter (fun m => m <=? 10 * decimal_value ds) (insertion_values ds))).
Fixpoint digits_rev (fuel n : nat) : list nat :=
  match fuel with
  | 0 => []
  | S f => if n =? 0 then [] else n mod 10 :: digits_rev f (n / 10)
  end.
Definition digits (n : nat) : list nat := rev (digits_rev n n).
Example paper_S8 : length (nodup Nat.eq_dec (insertion_values [8])) = 18 /\
  forallb (fun m => existsb (Nat.eqb m) (insertion_values [8]))
    [18;28;38;48;58;68;78;80;81;82;83;84;85;86;87;88;89;98] = true.
Proof. vm_compute. split; reflexivity. Qed.
Example ranks : forallb (fun n => let ds := digits n in
    (decimal_value ds =? n) && (rank ds =? list_sum ds)) (seq 1 120) = true.
Proof. vm_compute. reflexivity. Qed.

(* The statement proved at n = 8 and n = 10, including uniqueness of ds. *)
Lemma pow10_pos k : 1 <= 10 ^ k.
Proof. pose proof (Nat.pow_nonzero 10 k ltac:(lia)). lia. Qed.
Ltac expansion_cases :=
  let ds := fresh "ds" in
  intros ds [Hf [Hz Hv]];
  destruct ds as [|d [|e [|f ds]]]; try contradiction; simpl in Hz;
  [ apply Forall_cons_iff in Hf as [Hd _]; simpl in Hv
  | apply Forall_cons_iff in Hf as [Hd Hf]; apply Forall_cons_iff in Hf as [He _];
    simpl in Hv
  | exfalso; simpl in Hv; pose proof (pow10_pos (length ds)); nia ].
Ltac ins_search := (exists 0 + exists 1 + exists 2); (exists 0 + exists 1 +
  exists 2 + exists 3 + exists 4 + exists 5 + exists 6 + exists 7 + exists 8 +
  exists 9); split; [simpl; lia|]; split; [lia|]; simpl;
  split; [discriminate|reflexivity].
Ltac insert_card :=
  split; [nodup_lits|]; split; [|reflexivity]; intros m; split;
  [ intros H; simpl in H; repeat destruct H as [H|H]; subst; try contradiction;
    (split; [ins_search|lia])
  | intros [H Hle]; revert H; insertion_cases; try lia; in_lits ].
Example n_8 : forall ds, decimal_expansion 8 ds ->
  inserted ds (10 * 8) /\
  has_cardinality (fun m => inserted ds m /\ m <= 10 * 8) (list_sum ds).
Proof.
  expansion_cases; [|exfalso; lia].
  assert (d = 8) by lia; subst. split; [ins 1 0|].
  exists [18;28;38;48;58;68;78;80]. insert_card.
Qed.
Example n_10 : forall ds, decimal_expansion 10 ds ->
  inserted ds (10 * 10) /\
  has_cardinality (fun m => inserted ds m /\ m <= 10 * 10) (list_sum ds).
Proof.
  expansion_cases; [exfalso; lia|].
  assert (d = 1 /\ e = 0) as [-> ->] by lia. split; [ins 2 0|].
  exists [100]. insert_card.
Qed.
'''


def test_digit_insert_rocq_examples(tmp_path):
    rocq_examples("digit_insert_rank", DIGIT_INSERT, tmp_path)


def hofstadter_length(N):
    """Number of terms of B_N; a term is undefined when an index it needs
    falls outside 1..n-1 (the paper's 'dies')."""
    B = {i: i for i in range(1, N + 1)}
    n = N + 1
    while True:
        idx = [n - B[n - j] for j in (1, 2, 3)]
        if min(idx) < 1 or max(idx) > n - 1:
            return n - 1
        B[n] = sum(B[i] for i in idx)
        n += 1


def paper_hofstadter_terms(N):
    return [6, N+1, N+2, N+3, 9, N+4, N+5, N+6, 12, N+7, N+8, N+9, 15, N+10,
            N+11, 17, N+13, 18, N+13, N+15, N+16, 22, 21, 2*N+11]


def test_hofstadter_independently():
    # The paper's small cases: B3(4), B4(5), B10(1015), ... are last terms.
    assert [hofstadter_length(N) for N in (3, 4, 10, 11, 12, 13)] == \
        [4, 5, 1015, 117, 45, 73]
    assert all(hofstadter_length(N) == N + 24 for N in range(14, 3000))
    for N in range(9, 200):  # the paper says its 24 symbolic terms hold for N >= 9
        B = list(range(1, N + 1))
        for n in range(N + 1, N + 25):
            B.append(sum(B[n - B[n - 1 - j] - 1] for j in (1, 2, 3)))
        assert B[N:] == paper_hofstadter_terms(N), N


HOFSTADTER = r'''
Example init_5 : linear_init 5 = [1;2;3;4;5]%Z.
Proof. reflexivity. Qed.
Example term_range : term [7;8;9]%Z 1 = Some 7%Z /\ term [7;8;9]%Z 3 = Some 9%Z /\
  term [7;8;9]%Z 0 = None /\ term [7;8;9]%Z (-1) = None /\ term [7;8;9]%Z 4 = None.
Proof. repeat split. Qed.
(* n = 4: every index is 4 - B(3) = 3, so B(4) = 3 * B(3). *)
Example recurrence_step : next_term [1;1;1]%Z = Some 3%Z.
Proof. reflexivity. Qed.
(* B(3) = 5 at n = 4 needs B(-1); B(3) = 0 at n = 4 needs B(4) itself. *)
Example nonpositive_index : next_term [1;2;5]%Z = None.
Proof. reflexivity. Qed.
Example current_index : next_term [1;1;0]%Z = None.
Proof. reflexivity. Qed.
Example no_extension : forall l, extend l 0 = Some l.
Proof. reflexivity. Qed.

(* The paper's 24 symbolic terms, at N = 20. *)
Example paper_terms_20 : extend (linear_init 20) 24 =
  Some (linear_init 20 ++ PAPER_TERMS_20).
Proof. vm_compute. reflexivity. Qed.

Definition terms_count (N k : nat) : Prop :=
  (exists terms, extend (linear_init N) k = Some terms) /\
  extend (linear_init N) (S k) = None.
Ltac count_tac := split;
  [ match goal with |- exists t, ?e = Some t =>
      let v := eval vm_compute in e in
      match v with Some ?l => exists l; vm_compute; reflexivity end end
  | vm_compute; reflexivity ].
(* Theorem 1's small cases: 4, 5, 1015, 117, 45 and 73 terms. *)
Example small_N : terms_count 3 1 /\ terms_count 4 1 /\ terms_count 10 1005 /\
  terms_count 11 106 /\ terms_count 12 33 /\ terms_count 13 60.
Proof. repeat (apply conj; [count_tac|]); count_tac. Qed.
(* The statement itself at N = 14, 15 and 50. *)
Example instances : terms_count 14 24 /\ terms_count 15 24 /\ terms_count 50 24.
Proof. repeat (apply conj; [count_tac|]); count_tac. Qed.
'''


def test_hofstadter_rocq_examples(tmp_path):
    terms = "[" + ";".join(map(str, paper_hofstadter_terms(20))) + "]%Z"
    rocq_examples("hofstadter3_death", HOFSTADTER.replace("PAPER_TERMS_20", terms), tmp_path)


def comma_leading(c, b):
    while c >= b:
        c //= b
    return c


def comma_successor(a, b):
    """Definition 1: least y in 1..b-1 that is the leading digit of a+bx+y."""
    for y in range(1, b):
        c = a + b * (a % b) + y
        if comma_leading(c, b) == y:
            return c
    return None


def trapped(b, m):
    """Initial values in [b^m - b^2, b^m) whose sequence terminates below b^m."""
    out = []
    for v in range(max(1, b**m - b * b), b**m):
        a = v
        while a is not None and a < b**m:
            a = comma_successor(a, b)
        if a is None:
            out.append(v)
    return out


def triangular_differences(k):
    tri = lambda n: n * (n + 1) // 2
    return sum(1 for u in range(1, k + 2) for w in range(1, u) if tri(u) - tri(w) == k)


def comma_formula(b):
    return sum(triangular_differences(k) for k in range(1, b + 1)) - 1


def test_comma_independently():
    # Paper examples: base 10 from 1 gives 1, 12, 35, 94, ...; 3, 36 terminates.
    seq = [1]
    for _ in range(9):
        seq.append(comma_successor(seq[-1], 10))
    assert seq == [1, 12, 35, 94, 135, 186, 248, 331, 344, 387]
    assert comma_successor(3, 10) == 36 and comma_successor(36, 10) is None
    # The generating function's first terms: D(2..6) = 0, 1, 2, 4, 5.
    assert [comma_formula(b) for b in range(2, 7)] == [0, 1, 2, 4, 5]
    for b in range(2, 16):
        for m in range(3, 6 if b <= 6 else 4):
            assert len(trapped(b, m)) == comma_formula(b), (b, m)
    # Theorem 2 says m >= 2, but m = 2 fails: in base 3, both 3 = (10)_3 and
    # 4 = (11)_3 are trapped below 9, while the formula gives 1.
    assert trapped(3, 2) == [3, 4] and comma_formula(3) == 1
    assert [b for b in range(3, 9) if len(trapped(b, 2)) != comma_formula(b)] == \
        [3, 4, 6, 7, 8]


COMMA = r'''
Lemma pow_pos' b k : 1 <= b -> 1 <= b ^ k.
Proof. intros. pose proof (Nat.pow_nonzero b k ltac:(lia)). lia. Qed.
Ltac split_nat x := destruct x as [|x]; [|first [lia | split_nat x]].
(* Refute y * b^k <= c < (y+1) * b^k for all k, with b, y and c concrete. *)
(* Arithmetic on concrete candidates without unfolding numerals: expand
   b^(S k) = b * b^k and evaluate closed remainders. *)
Ltac pow_lia := unfold comma_candidate in *;
  rewrite ?Nat.pow_succ_r', ?Nat.pow_0_r in *;
  repeat match goal with
  | |- context [?a mod ?b] =>
      let v := eval vm_compute in (a mod b) in change (a mod b) with v
  | H : context [?a mod ?b] |- _ =>
      let v := eval vm_compute in (a mod b) in change (a mod b) with v in H
  end; lia.
Ltac forall_pow := repeat (apply Forall_cons; [pow_lia|]); apply Forall_nil.
Ltac not_leading :=
  let k := fresh "k" in
  intros [? [k [? ?]]]; destruct k as [|[|[|[|k]]]]; try pow_lia;
  match goal with H : context [?b ^ k] |- _ =>
    pose proof (pow_pos' b k ltac:(lia)) end; pow_lia.

Example leading_positive : leading_digit 10 1 12 /\ leading_digit 10 3 35 /\
  leading_digit 3 1 4 /\ leading_digit 10 1 100.
Proof.
  repeat split; try lia; [exists 1|exists 1|exists 1|exists 2]; pow_lia.
Qed.
Example leading_negative : ~ leading_digit 10 2 12 /\ ~ leading_digit 10 0 5 /\
  ~ leading_digit 10 1 99.
Proof. repeat split; not_leading. Qed.

(* 1 -> 12 -> 35 as in the paper; 12 -> 35 skips y = 1, 2. *)
Example steps : comma_step 10 1 12 /\ comma_step 10 12 35.
Proof.
  split.
  - exists 1. split; [split; [lia|exists 1; pow_lia]|].
    split; [reflexivity|]. intros y' Hy'. split_nat y'. not_leading.
  - exists 3. split; [split; [lia|exists 1; pow_lia]|].
    split; [reflexivity|]. intros y' Hy'. split_nat y'; not_leading.
Qed.
(* The paper: 3, 36 terminates. The successor rule uses the least y only. *)
Ltac landmine_tac :=
  let y := fresh "y" in intros y Hl; pose proof (proj1 Hl) as Hb;
  split_nat y; revert Hl; not_leading.
Example landmine_36 : landmine 10 36.
Proof. landmine_tac. Qed.
Example not_landmine_35 : ~ landmine 10 35.
Proof. intros H. apply (H 9). split; [lia|exists 1; pow_lia]. Qed.

(* Base 3, m = 2: 3 -> 4 and 4 is a landmine, so both 3 and 4 are trapped
   below 9, although the formula gives one. So the paper's m = 2 is false. *)
Example trapped_3_2 : trapped 3 2 3 /\ trapped 3 2 4.
Proof.
  split; (split; [pow_lia|]); (split; [pow_lia|]).
  - exists [4]. split; [|split; [forall_pow|simpl; landmine_tac]].
    split; [|exact I]. exists 1. split; [split; [lia|exists 1; pow_lia]|].
    split; [reflexivity|]. intros y' Hy'. split_nat y'. not_leading.
  - exists []. split; [exact I|split; [forall_pow|simpl; landmine_tac]].
Qed.
Example m_2_fails : ~ exists c : nat, has_cardinality (trapped 3 2) c /\
  c + 1 = list_sum (map triangular_differences (seq 1 3)).
Proof.
  intros [c [[xs [_ [Hin Hlen]] ] Hc]].
  assert (list_sum (map triangular_differences (seq 1 3)) = 2) as E
    by (vm_compute; reflexivity).
  rewrite E in Hc.
  destruct trapped_3_2 as [H3 H4]. apply Hin in H3, H4. clear Hin.
  destruct xs as [|x [|x' xs]]; simpl in Hlen, H3, H4; lia.
Qed.

(* A trapped value for b = m = 3: 22 = (211)_3 is a landmine. *)
Example trapped_3_3 : trapped 3 3 22.
Proof.
  split; [pow_lia|]; split; [pow_lia|].
  exists []. split; [exact I|split; [forall_pow|simpl; landmine_tac]].
Qed.

Example formula_values :
  map triangular_differences (seq 1 16) = PYTHON_R /\
  map (fun b => list_sum (map triangular_differences (seq 1 b))) (seq 2 14)
    = PYTHON_SUMS.
Proof. vm_compute. split; reflexivity. Qed.

(* The statement proved for b = 2 and every m: base 2 has no landmines. *)
Lemma base_2_no_landmine a : ~ landmine 2 a.
Proof.
  intros H. apply (H 1). split; [lia|].
  set (c := comma_candidate 2 a 1).
  assert (0 < c) by (unfold c, comma_candidate; lia).
  exists (Nat.log2 c). pose proof (Nat.log2_spec c H0) as [Hlo Hhi].
  rewrite Nat.pow_succ_r' in Hhi. lia.
Qed.
Example base_2 : forall m : nat, 3 <= m -> exists c : nat,
  has_cardinality (trapped 2 m) c /\
  c + 1 = list_sum (map triangular_differences (seq 1 2)).
Proof.
  intros m _. exists 0. split; [|reflexivity].
  exists []. split; [constructor|split; [|reflexivity]].
  intros v; split; [intros []|].
  intros [_ [_ [rest [_ [_ H]]]]]. exact (base_2_no_landmine _ H).
Qed.

(* The statement proved for b = m = 3: only 22 is trapped in [18, 27).
   Successors are unique, so following the computed successors of each
   other v past 27 shows that no trapping path exists from v. *)
Definition reach_trap (b M v : nat) : Prop :=
  exists rest : list nat,
    comma_path b (v :: rest) /\ Forall (fun a => a < M) (v :: rest) /\
    landmine b (last (v :: rest) v).
Lemma step_unique b a c1 c2 : comma_step b a c1 -> comma_step b a c2 -> c1 = c2.
Proof.
  intros [y1 [L1 [E1 M1]]] [y2 [L2 [E2 M2]]]; subst.
  destruct (Nat.lt_trichotomy y1 y2) as [H|[H|H]].
  - exfalso; exact (M2 y1 H L1).
  - subst; reflexivity.
  - exfalso; exact (M1 y2 H L2).
Qed.
Lemma last_default {A} (l : list A) d1 d2 : l <> [] -> last l d1 = last l d2.
Proof.
  induction l as [|a l IH]; intros H; [contradiction|].
  destruct l as [|a' l]; [reflexivity|]. apply IH. discriminate.
Qed.
Lemma no_trap_step b M v w :
  comma_step b v w -> ~ reach_trap b M w -> ~ reach_trap b M v.
Proof.
  intros Hs Hn [rest [Hp [Hf Hl]]]. destruct rest as [|w' rest].
  - destruct Hs as [y [Ly _]]. exact (Hl y Ly).
  - destruct Hp as [Hs' Hp]. pose proof (step_unique _ _ _ _ Hs Hs'); subst w'.
    apply Hn. exists rest. split; [exact Hp|]. split; [inversion Hf; assumption|].
    change (last (v :: w :: rest) v) with (last (w :: rest) v) in Hl.
    rewrite (last_default (w :: rest) v w) in Hl by discriminate.
    exact Hl.
Qed.
Lemma no_trap_big b M w : M <= w -> ~ reach_trap b M w.
Proof. intros H [rest [_ [Hf _]]]. inversion Hf; lia. Qed.
Lemma trapped_reach v : ~ reach_trap 3 (3 ^ 3) v -> trapped 3 3 v -> False.
Proof. intros H [_ [_ Hr]]. exact (H Hr). Qed.
Ltac step_tac := (exists 1 + exists 2);
  split; [split; [lia|(exists 0 + exists 1 + exists 2 + exists 3); pow_lia]|];
  split; [reflexivity|intros y' Hy'; split_nat y'; not_leading].
Ltac escape :=
  first [apply no_trap_big; pow_lia | eapply no_trap_step; [step_tac|escape]].
Example b3_m3 : exists c : nat, has_cardinality (trapped 3 3) c /\
  c + 1 = list_sum (map triangular_differences (seq 1 3)).
Proof.
  exists 1. split; [|vm_compute; reflexivity].
  exists [22]. split; [nodup_lits|]. split; [|reflexivity].
  intros v; split; [intros [<-|[]]; exact trapped_3_3|].
  intros Ht. assert (18 <= v < 27) by (destruct Ht as [? [? _]]; pow_lia).
  assert (v = 18 \/ v = 19 \/ v = 20 \/ v = 21 \/ v = 22 \/ v = 23 \/ v = 24 \/
          v = 25 \/ v = 26) by lia.
  repeat match goal with H : _ \/ _ |- _ => destruct H end; subst;
    try (left; reflexivity); exfalso; refine (trapped_reach _ _ Ht); escape.
Qed.
'''


def test_comma_rocq_examples(tmp_path):
    r = [triangular_differences(k) for k in range(1, 17)]
    sums = [comma_formula(b) + 1 for b in range(2, 16)]
    text = (COMMA.replace("PYTHON_R", "[" + ";".join(map(str, r)) + "]")
            .replace("PYTHON_SUMS", "[" + ";".join(map(str, sums)) + "]"))
    rocq_examples("comma_danger_count", text, tmp_path)
