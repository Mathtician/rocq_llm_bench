"""Cursor CLI event stream, captured from a real `cursor-agent -p --output-format stream-json` run."""
from pathlib import Path

from rlb.config import Config
from rlb.harness.cursor import CursorHarness

FIX = Path(__file__).with_name("fixtures") / "cursor_events.jsonl"


def test_stats_from_captured_stream():
    lines = [(float(i), l) for i, l in enumerate(FIX.read_text().splitlines())]
    st = CursorHarness().stats(lines)
    assert st.exit_reason == "success" and st.error is None
    assert st.turns == 5  # distinct model_call_id values (inference calls; one made only a tool call, no text)
    assert st.usage == {"inputTokens": 13353, "outputTokens": 911, "cacheReadTokens": 72620, "cacheWriteTokens": 0}
    assert st.inference_s == 28.318
    assert len(st.tool_intervals) == 6 and all(b > a for a, b in st.tool_intervals)
    assert st.violations == [] and st.provider_errors == []
    assert "compiles successfully" in st.final_message


def test_web_tool_is_a_violation_and_refusal_is_provider_error():
    h = CursorHarness()
    lines = [(0.0, '{"type":"tool_call","subtype":"started","call_id":"x","tool_call":{"webSearchToolCall":{"args":{"query":"putnam 2025 b6"}}}}')]
    assert h.stats(lines).violations == ["web tool webSearchToolCall: {'query': 'putnam 2025 b6'}"]
    assert h.provider_error({"type": "result", "is_error": True, "result": "You've hit your usage limit"}) is not None
    assert h.provider_error({"type": "result", "is_error": False, "result": "ok"}) is None


def test_invocation_shape():
    cfg = Config(name="c", harness="cursor", model="composer-2.5", subagent=None)
    argv = CursorHarness().invocation(cfg, Path("/W"), "prove it").argv
    assert argv[0].endswith("/cursor-agent") and argv[1:4] == ["-p", "--output-format", "stream-json"] and argv[-1] == "prove it"
    assert "--force" in argv and argv[argv.index("--model") + 1] == "composer-2.5"
