"""Delegation: `lemma.py prove` <-> delegate.Broker <-> a (faked) subagent attempt; `assemble`;
the lemma as a Problem, verified for real."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from rlb import delegate, lemma_tool
from rlb.config import Config
from rlb.problem import Problem
from rlb.rocq import Toolchain, verify

TC = Toolchain.discover()
HEADER = "From Stdlib Require Import Arith Lia.\n\nDefinition double (n : nat) := n + n."
PROBLEM = Problem("main_thm", "research", "test", "From Stdlib Require Import Arith Lia.",
                  "Definition double (n : nat) := n + n.", "Theorem main_thm : forall n, double n = 2 * n.", None)
MAIN = HEADER + """

Lemma plus_S : forall a b, a + S b = S (a + b).
Proof.
Admitted.

Lemma double_S : forall n, double (S n) = S (S (double n)).
Proof.
Admitted.

Theorem main_thm : forall n, double n = 2 * n.
Proof.
  induction n as [|n IH]; [reflexivity|]. rewrite double_S, IH. lia.
Qed.
"""
# a subagent's proof: a helper, then the lemma, using plus_S (admitted above it: the main agent's job)
SUB_PROOF = """Lemma unfold_double : forall n, double n = n + n.
Proof. reflexivity. Qed.

Theorem double_S : forall n, double (S n) = S (S (double n)).
Proof. intros; rewrite !unfold_double; simpl; rewrite plus_S; reflexivity. Qed.
"""
CFG = Config(name="main", harness="pi", model="m", subagent=Config(name="sub", harness="pi", model="m", subagent=None))


@pytest.fixture
def workdir(tmp_path):
    w = tmp_path / "work"
    w.mkdir()
    (w / "main_thm.v").write_text(MAIN)
    (w / "lemma.py").write_text(Path(lemma_tool.__file__).read_text().replace('"__MAIN_FILE__"', repr("main_thm.v")))
    return w


def start_prove(workdir, *args):
    env = {**os.environ, "PATH": f"{TC.bin_dir}:{os.environ['PATH']}"}
    return subprocess.Popen([sys.executable, "lemma.py", "prove", *args], cwd=workdir, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)


def broker(workdir, monkeypatch, fake):
    import rlb.runner
    seen = {}

    def run_attempt(cfg, problem, *a, sub, **k):
        seen.update(cfg=cfg, problem=problem, sub=sub)
        return fake(problem, sub)
    monkeypatch.setattr(rlb.runner, "run_attempt", run_attempt)
    b = delegate.Broker(CFG, PROBLEM, workdir, workdir.parent / "attempt", TC, workdir.parent, workdir.parent,
                        "run", 0, deadline=time.time() + 600)
    b.start()
    return b, seen


def attempt(solved, message="", status="ok", timed_out=False):
    return SimpleNamespace(solved=solved, timed_out=timed_out, provider_error=None, wall_s=1.0,
                           verify=SimpleNamespace(status=status), harness=SimpleNamespace(final_message=message))


def test_prove_then_assemble(workdir, monkeypatch):
    def fake(problem, sub):
        (sub.attempt_dir / "workdir").mkdir(parents=True)
        (sub.attempt_dir / "workdir" / problem.file_name).write_text(problem.header() + "\n\n" + SUB_PROOF)
        return attempt(True, "done")
    b, seen = broker(workdir, monkeypatch, fake)
    p = start_prove(workdir, "double_S", "--hint", "unfold double; plus_S is above")
    out, _ = p.communicate(timeout=30)
    summaries = b.stop()
    assert p.returncode == 0 and out.endswith("double_S: proved\n")
    assert seen["cfg"].name == "sub" and seen["problem"].statement == \
        "Theorem double_S : forall n, double (S n) = S (S (double n))."
    assert "<hint>\nunfold double; plus_S is above\n</hint>" in seen["sub"].prompt_suffix
    assert seen["sub"].allowed_assumptions == ("plus_S",)
    assert [s["status"] for s in summaries] == ["proved"]
    text, inlined = lemma_tool.assemble(workdir, MAIN)
    assert inlined == ["double_S"] and "unfold_double" in text and (workdir / "main_thm.v").read_text() == MAIN
    vr = verify(PROBLEM, text, TC, workdir.parent / "v")  # plus_S is still admitted: an axiom, rejected
    assert vr.status == "axioms" and "plus_S" in vr.message
    proved_plus = text.replace("Lemma plus_S : forall a b, a + S b = S (a + b).\nProof.\nAdmitted.",
                               "Lemma plus_S : forall a b, a + S b = S (a + b).\nProof. intros; lia. Qed.")
    assert verify(PROBLEM, proved_plus, TC, workdir.parent / "v").ok
    # a restated lemma no longer takes the delegated proof
    assert lemma_tool.assemble(workdir, MAIN.replace("S (S (double n))", "2 + double n"))[1] == []


def test_failure_carries_the_subagents_message(workdir, monkeypatch):
    b, _ = broker(workdir, monkeypatch, lambda problem, sub: attempt(False, "false as stated: n = 0", "compile_error"))
    p = start_prove(workdir, "double_S")
    out, _ = p.communicate(timeout=30)
    b.stop()
    assert p.returncode == 1
    assert "double_S: not proved (compile error)" in out and "false as stated: n = 0" in out
    assert not (workdir / "lemmas" / "double_S.json").exists()


def test_killing_prove_stops_the_subagent(workdir, monkeypatch):
    started = threading.Event()

    def fake(problem, sub):
        started.set()
        assert sub.stop.wait(30), "the subagent was never stopped"
        return attempt(False, "", "missing")
    b, _ = broker(workdir, monkeypatch, fake)
    p = start_prove(workdir, "double_S")
    assert started.wait(30)
    p.send_signal(signal.SIGTERM)
    p.wait(timeout=30)
    assert [s["reason"] for s in b.stop()] == ["stopped (cancelled, or your attempt ended)"]


def test_prove_needs_an_admitted_lemma(workdir):
    p = start_prove(workdir, "main_thm")
    assert p.communicate(timeout=30)[0] == "main_thm: already closed with Qed. in main_thm.v\n" and p.returncode == 1


def test_lemma_problem_refuses_unverifiable_preambles():
    req = {"name": "L", "prefix": "From Stdlib Require Import Arith.\n\nSection S.\nVariable x : nat.\n",
           "statement": "Lemma L : x = x.\n", "statement_key": "L : x = x."}
    with pytest.raises(ValueError, match="Section"):
        delegate.lemma_problem(PROBLEM, req)


def test_verifier_allows_only_the_named_admitted_lemmas(tmp_path):
    prefix = MAIN[:MAIN.index("Lemma double_S")]
    req = {"name": "double_S", "prefix": prefix, "statement_key": "double_S : forall n, double (S n) = S (S (double n))."}
    problem, admitted = delegate.lemma_problem(PROBLEM, req)
    solution = problem.header() + "\n\n" + SUB_PROOF
    assert verify(problem, solution, TC, tmp_path / "a", admitted).ok
    assert verify(problem, solution, TC, tmp_path / "b").status == "axioms"
    assert delegate.proof_part(problem, solution) == SUB_PROOF
    assert delegate.proof_part(problem, solution.replace("n + n", "2 * n", 1)) is None
