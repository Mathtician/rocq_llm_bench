"""Integration tests for the verifier (need a Rocq toolchain)."""
import pytest

from rlb.problem import Problem
from rlb.rocq import Toolchain, verify

TC = Toolchain.discover(None)

BINDERS = Problem(
    name="t_bind", tier="easy", domain="algebra",
    imports="From Stdlib Require Import Reals Psatz.\nOpen Scope R_scope.", preamble="",
    statement="Theorem t_bind (x y : R) (h : x <= y) : x + 1 <= y + 1.",
    ref_proof="Proof. lra. Qed.",
)
FORALL = Problem(
    name="t_all", tier="easy", domain="algebra",
    imports="From Stdlib Require Import Reals Psatz.\nOpen Scope R_scope.", preamble="",
    statement="Theorem t_all : forall x y : R, x <= y -> x + 1 <= y + 1.",
    ref_proof="Proof. intros; lra. Qed.",
)
PREAMBLE = Problem(
    name="t_pre", tier="easy", domain="algebra",
    imports="From Stdlib Require Import Arith Lia.\nOpen Scope nat_scope.",
    preamble="Definition twice (n : nat) := 2 * n.\nFixpoint tri (n : nat) := match n with 0 => 0 | S k => n + tri k end.",
    statement="Theorem t_pre (n : nat) : twice (tri n) = n * (n + 1).",
    ref_proof="Proof. unfold twice. induction n; simpl; lia. Qed.",
)


@pytest.fixture
def scratch(tmp_path):
    return tmp_path / "v"


@pytest.mark.parametrize("p", [BINDERS, FORALL, PREAMBLE], ids=lambda p: p.name)
def test_reference_passes(p, scratch):
    assert verify(p, p.ref_source(), TC, scratch).status == "ok"


def test_binder_form_change_is_fine(scratch):
    # Same type, different surface syntax.
    src = BINDERS.header() + "\nTheorem t_bind : forall x y : R, x <= y -> x + 1 <= y + 1.\nProof. intros; lra. Qed.\n"
    assert verify(BINDERS, src, TC, scratch).status == "ok"


def test_helper_lemma_allowed(scratch):
    src = BINDERS.header() + "\nLemma h1 : forall a : R, a + 0 = a. Proof. intro; ring. Qed.\n" + BINDERS.statement + "\nProof. lra. Qed.\n"
    assert verify(BINDERS, src, TC, scratch).status == "ok"


def test_admitted_rejected(scratch):
    assert verify(BINDERS, BINDERS.task_source(), TC, scratch).status == "axioms"


def test_axiom_rejected(scratch):
    src = BINDERS.header() + "\nAxiom cheat : forall P : Prop, P.\n" + BINDERS.statement + "\nProof. apply cheat. Qed.\n"
    r = verify(BINDERS, src, TC, scratch)
    assert r.status == "axioms" and any(f == "Solution.cheat" for _, f in r.assumptions)


def test_stdlib_axiom_allowed(scratch):
    src = (BINDERS.header() + "\nFrom Stdlib Require Import FunctionalExtensionality.\n" + BINDERS.statement
           + "\nProof. assert (H : (fun z : R => z) = (fun z => z + 0)) by (apply functional_extensionality; intro; ring). lra. Qed.\n")
    r = verify(BINDERS, src, TC, scratch)
    assert r.status == "ok" and r.assumptions and all(f.startswith("Stdlib.") for _, f in r.assumptions)


def test_notation_hijack_rejected(scratch):
    src = (BINDERS.header()
           + '\nNotation "a + b" := (Rminus a b) (at level 50, left associativity) : R_scope.\n'
           + BINDERS.statement + "\nProof. lra. Qed.\n")
    assert verify(BINDERS, src, TC, scratch).status == "statement_mismatch"


def test_weakened_statement_rejected(scratch):
    src = BINDERS.header() + "\nTheorem t_bind (x y : R) (h : x <= y) (h2 : x = y) : x + 1 <= y + 1.\nProof. lra. Qed.\n"
    assert verify(BINDERS, src, TC, scratch).status == "statement_mismatch"


def test_missing_theorem_rejected(scratch):
    src = BINDERS.header() + "\nTheorem other : True. Proof. exact I. Qed.\n"
    assert verify(BINDERS, src, TC, scratch).status == "statement_mismatch"


def test_compile_error(scratch):
    assert verify(BINDERS, BINDERS.header() + "\n" + BINDERS.statement + "\nProof. lia. Qed.\n", TC, scratch).status == "compile_error"


def test_missing_file(scratch):
    assert verify(BINDERS, None, TC, scratch).status == "missing"


IMPLICIT = Problem(
    name="t_impl", tier="easy", domain="logic_other",
    imports="From Stdlib Require Import Ensembles.", preamble="",
    statement="Theorem t_impl {U : Type} (A B : Ensemble U) : Included U (Intersection U A B) A.",
    ref_proof="Proof. intros x H. destruct H. assumption. Qed.",
)


def test_implicit_binder_reference_passes(scratch):
    assert verify(IMPLICIT, IMPLICIT.ref_source(), TC, scratch).status == "ok"
