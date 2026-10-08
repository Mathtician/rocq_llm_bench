"""Subagent policy: every config declares its subagent config; native subagents are blocked (agy
excepted, and declared); a native call that gets through is a sandbox failure."""
import json
from pathlib import Path

import pytest

from rlb.config import Config, config_from_record, load_config, native_subagents_allowed
from rlb.harness import HARNESSES
from rlb.problem import Problem
from rlb.runner import render_prompt, unauthorized_subagent

ROOT = Path(__file__).resolve().parents[1]
PI = Config(name="p", harness="pi", model="m", subagent=None)


def write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body)
    return p


def test_policy_must_be_declared(tmp_path):
    with pytest.raises(SystemExit, match="declare subagent"):
        load_config(write(tmp_path, "c.toml", 'name="c"\nharness="pi"\nmodel="m"\n'))
    assert load_config(write(tmp_path, "c.toml", 'name="c"\nharness="pi"\nmodel="m"\nsubagent="none"\n')).subagent is None


def test_subagent_config_is_loaded_and_has_depth_one(tmp_path):
    sub = write(tmp_path, "sub.toml", 'name="s"\nharness="codex"\nmodel="gpt-6-astra"\nsubagent="none"\n')
    main = load_config(write(tmp_path, "m.toml", f'name="m"\nharness="pi"\nmodel="x"\nsubagent="{sub}"\n'))
    assert main.subagent.name == "s" and main.to_dict()["subagent"]["harness"] == "codex"
    nested = write(tmp_path, "n.toml", f'name="n"\nharness="pi"\nmodel="x"\nsubagent="{tmp_path / "m.toml"}"\n')
    with pytest.raises(SystemExit, match="depth 1"):
        load_config(nested)


def test_every_shipped_config_declares_a_policy():
    composites = {"claude-opus55-medium-subagents": "claude-opus55-medium",
                  "codex-astra-low-subagents": "codex-astra-low"}
    for f in [*ROOT.glob("configs/*.toml"), *ROOT.glob("configs/retired/*.toml")]:
        cfg = load_config(f)
        assert (cfg.subagent.name if cfg.subagent else None) == composites.get(cfg.name), f


def test_native_subagents_are_blocked():
    claude = Config(name="c", harness="claude", model="claude-opus-5-5", subagent=None, args={"disallowed_tools": "WebSearch"})
    argv = HARNESSES["claude"].invocation(claude, Path("/W"), "p").argv
    assert {"Agent", "Task", "Workflow", "RemoteTrigger"} <= set(argv[argv.index("--disallowedTools") + 1].split(","))
    codex = Config(name="c", harness="codex", model="gpt-6-astra", subagent=PI)
    assert "features.multi_agent=false" in HARNESSES["codex"].invocation(codex, Path("/W"), "p").argv


def test_prompts_declare_what_exists():
    p = Problem("t", "easy", "d", "", "", "Theorem t : True.", None)
    assert "manage_subagents" in render_prompt(Config(name="a", harness="agy", model="g", subagent=None), p)
    assert "subagent" not in render_prompt(PI, p).lower()
    composite = render_prompt(Config(name="c", harness="pi", model="m", subagent=PI), p)
    assert "python3 lemma.py prove L" in composite and "15 minutes" in composite


def test_records_before_the_field():
    assert native_subagents_allowed({"harness": "agy", "model": "g"})
    assert not native_subagents_allowed({"harness": "claude", "model": "claude-opus-5"})
    assert native_subagents_allowed({"harness": "claude", "model": "x", "subagent_model": "x"})  # ledger #48 probe
    assert config_from_record({"name": "c", "harness": "claude", "model": "x", "subagent_model": "x"}).subagent is None


def tool_use(name):
    return json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "toolu_1", "name": name, "input": {}}]}}, separators=(",", ":")) + "\n"


def test_native_call_that_gets_through_is_a_sandbox_failure(tmp_path):
    (tmp_path / "stdout.txt").write_text(tool_use("Agent"))
    att = {"config": {"harness": "claude", "model": "claude-opus-5-5", "subagent": None}}
    assert unauthorized_subagent(att, tmp_path).startswith("sandbox failure: unauthorized subagent call")
    probe = {"config": {"harness": "claude", "model": "claude-opus-5-5", "subagent_model": "claude-opus-5-5"}}
    assert unauthorized_subagent(probe, tmp_path) is None  # the native probe allowed Agent...
    (tmp_path / "stdout.txt").write_text(tool_use("Workflow"))
    assert unauthorized_subagent(probe, tmp_path) is not None  # ...and nothing else
    (tmp_path / "stdout.txt").write_text(tool_use("Bash"))
    assert unauthorized_subagent(att, tmp_path) is None


def test_codex_subagent_shows_only_as_a_second_model_session(tmp_path):
    ws = '{"event":"call","host":"chatgpt.com","path":"/backend-api/codex/responses","status":101}\n'
    (tmp_path / "api.jsonl").write_text(ws)
    att = {"config": {"harness": "codex", "model": "gpt-6-astra", "subagent": None}}
    assert unauthorized_subagent(att, tmp_path) is None
    (tmp_path / "api.jsonl").write_text(ws * 2)
    assert "2 model sessions" in unauthorized_subagent(att, tmp_path)
