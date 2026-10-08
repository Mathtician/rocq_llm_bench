"""Statement semantics, references, and atomic validation of the research tier."""
import importlib.util
import itertools
import json

import pytest

from rlb import ROOT
from rlb.external import _load
from rlb.research import SOURCE, import_research
from rlb.rocq import Toolchain, coqc

TC = Toolchain.discover()


def test_selftest_skips_missing_references(tmp_path, capsys):
    from rlb.cli import main
    from rlb.problem import Problem
    proved = Problem("proved", "research", "test", "", "", "Theorem proved : True.",
                     "Proof. exact I. Qed.")
    unproved = Problem("unproved", "research", "test", "", "", "Theorem unproved : False.", None)
    (tmp_path / "manifest.json").write_text(json.dumps({
        "problems": [proved.to_dict(), unproved.to_dict()]}))
    with pytest.raises(SystemExit) as result:
        main(["selftest", "--problems", str(tmp_path), "--tier", "research"])
    assert result.value.code == 0
    assert "1 checked, 0 failed; 1 problems without references skipped" in capsys.readouterr().out
    assert not (tmp_path / ".scratch").exists()


def test_research_import_checks_statements_and_references(tmp_path):
    out = tmp_path / "problems"
    out.mkdir()
    old = {"name": "preserve_me", "tier": "custom"}
    (out / "manifest.json").write_text(json.dumps({"problems": [old]}))
    selected = import_research(TC, out, log=lambda _: None)
    assert len(selected) == 17
    assert sum(s.problem.has_ref() for s in selected) == 4
    entries = json.loads((out / "manifest.json").read_text())["problems"]
    assert entries[0] == old
    for s in selected:
        assert (out / "research" / s.problem.file_name).read_text() == s.problem.task_source()
        assert (out / "research" / f"{s.problem.name}.ref.v").exists() == s.problem.has_ref()


def test_bad_reference_does_not_replace_tier(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "metadata.json").write_text(json.dumps({"problems": {"bad": {"domain": "test"}}}))
    text = "From Stdlib Require Import Arith.\nTheorem bad : False.\nProof.\nAdmitted.\n"
    (src / "bad.v").write_text(text)
    (src / "bad.ref.v").write_text(text)
    out = tmp_path / "out"
    out.mkdir()
    manifest = '{"problems": []}'
    (out / "manifest.json").write_text(manifest)
    with pytest.raises(ValueError, match="reference check failed"):
        import_research(TC, out, src_dir=src, log=lambda _: None)
    assert (out / "manifest.json").read_text() == manifest
    assert not (out / "research").exists()


def test_equation_generation_is_reproducible(tmp_path):
    path = ROOT / "scripts" / "generate-research-equations.py"
    spec = importlib.util.spec_from_file_location("equations", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.generate(tmp_path)
    for generated in tmp_path.iterdir():
        assert generated.read_bytes() == (SOURCE / generated.name).read_bytes()
    metadata = json.loads((SOURCE / "metadata.json").read_text())["problems"]
    for name, info in json.loads((tmp_path / "equations.json").read_text()).items():
        assert metadata[name] == info


@pytest.mark.parametrize("name,examples", [
    ("short_bsd_stern", r'''
Example stern_initial : map stern (seq 0 17) =
  [0;1;1;2;1;3;2;3;1;4;3;5;2;5;3;4;1].
Proof. vm_compute. reflexivity. Qed.
Example short_five : short_bsd 5 [1%Z;0%Z;(-1)%Z;(-1)%Z].
Proof. unfold short_bsd; repeat split; try discriminate;
  repeat constructor; discriminate. Qed.
Example not_short : ~ short_bsd 1 [1%Z;(-1)%Z].
Proof. unfold short_bsd; intros [_ [[_ H] _]]; apply H; reflexivity. Qed.
Example empty_is_not_short : ~ short_bsd 0 [].
Proof. intros [_ [H _]]; exact H. Qed.
'''),
    ("short_bsd_hyperbinary", r'''
Example hyperbinary_zero : hyperbinary 0 [].
Proof. repeat split; constructor. Qed.
Example no_leading_zero : ~ hyperbinary 0 [0%Z].
Proof. intros [_ [H _]]; apply H; reflexivity. Qed.
Example hyperbinary_four : hyperbinary 4 [1%Z;2%Z].
Proof. unfold hyperbinary; repeat split; try discriminate;
  repeat constructor; discriminate. Qed.
'''),
    ("parking_count", r'''
From Stdlib Require Import Lia.
Example empty_parking : forall a b, parking_function a b 0 [].
Proof. intros; split; [reflexivity|]; split; [constructor|].
  exists []; repeat split; try constructor.
  intros i H; inversion H. Qed.
Example zero_formula : forall b, parking_formula 0 b 0 = 1 /\
  parking_formula 0 b 1 = 0.
Proof. intros; split; reflexivity. Qed.
Example no_zero_preference : ~ parking_function 1 1 1 [0].
Proof. intros [_ [H _]]; inversion H; subst; inversion H2. Qed.
Example unsorted_parking : parking_function 1 1 2 [2;1].
Proof. split; [reflexivity|]; split.
  - repeat constructor.
  - exists [1;2]. split; [apply perm_swap|]. split.
    + repeat constructor.
    + intros [|[|i]] H; simpl; lia. Qed.
'''),
], ids=["binary", "hyperbinary", "parking"])
def test_rocq_definition_examples(name, examples, tmp_path):
    p = _load(SOURCE / f"{name}.v", "research", "test")
    (tmp_path / "Examples.v").write_text(p.header() + "\n" + examples)
    result = coqc(TC, tmp_path, "Examples.v")
    assert result.ok, result.stderr


def test_small_paper_counts_independently():
    # Independent finite enumeration sanity checks, not proofs of the general
    # statements. Enumerate all digit strings through length 7 (enough for
    # short representations of n <= 32 and hyperbinary representations <= 31).
    short, hyper = [0] * 33, [0] * 32
    hyper[0] = 1
    for size in range(1, 8):
        weights = [2**i for i in reversed(range(size))]
        for digits in itertools.product((-1, 0, 1), repeat=size):
            if digits[0] == 0 or (size > 1 and digits[0] == -digits[1]):
                continue
            n = sum(d*w for d, w in zip(digits, weights))
            if 0 <= n <= 32:
                short[n] += 1
        for digits in itertools.product((0, 1, 2), repeat=size):
            if digits[0] == 0:
                continue
            n = sum(d*w for d, w in zip(digits, weights))
            if n < 32:
                hyper[n] += 1
    stern = [0, 1]
    for n in range(2, 33):
        stern.append(stern[n//2] if n % 2 == 0 else stern[n//2] + stern[n//2+1])
    assert short == stern
    assert short[1:] == hyper
    for a, b, n in itertools.product(range(4), range(3), range(5)):
        count = sum(all(x <= a + b*i for i, x in enumerate(sorted(xs)))
                    for xs in itertools.product(range(1, a + b*max(n-1, 0) + 1), repeat=n))
        assert count == (1 if n == 0 else a * (a+b*n)**(n-1)), (a, b, n)


def test_minif2f_audit_exclusions_are_proved(tmp_path):
    """Each statement our audit excludes has a Rocq proof that it is false or vacuous."""
    from rlb.external import AUDIT_EXCLUDED, MINIF2F_REFS
    audit = json.loads((MINIF2F_REFS / "audit.json").read_text())
    excluded = {n: e for n, e in audit.items() if e["status"] in AUDIT_EXCLUDED}
    assert excluded
    for name, e in excluded.items():
        src = ROOT / e["counterexample"]
        assert name in src.name
        (tmp_path / src.name).write_text(src.read_text())
        result = coqc(TC, tmp_path, src.name)
        assert result.ok, (name, result.stderr)
        assert "Admitted" not in src.read_text() and "admit" not in src.read_text()
