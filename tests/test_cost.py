"""API-equivalent cost: per-call usage shapes x prices; reported cost preferred; composites add up."""
import json

import pytest

from rlb import cost
from rlb.proxy_policy import model_from_text

P = {"input": 2.0, "cached_input": 0.2, "cache_write_5m": 2.5, "cache_write_1h": 4.0, "output": 10.0}


def test_anthropic_usage_prices_cache_reads_and_both_write_kinds():
    u = {"input_tokens": 1_000, "cache_read_input_tokens": 10_000, "cache_creation_input_tokens": 3_000,
         "cache_creation.ephemeral_1h_input_tokens": 2_000, "output_tokens": 500}
    assert cost.call_cost(u, P) == pytest.approx((1_000 * 2 + 10_000 * 0.2 + 1_000 * 2.5 + 2_000 * 4 + 500 * 10) / 1e6)


def test_openai_input_includes_its_cached_part():
    u = {"input_tokens": 10_000, "input_tokens_details.cached_tokens": 8_000, "output_tokens": 300,
         "output_tokens_details.reasoning_tokens": 200}
    assert cost.call_cost(u, P) == pytest.approx((2_000 * 2 + 8_000 * 0.2 + 300 * 10) / 1e6)


def test_openai_compatible_and_deepseek_cache_hits():
    u = {"prompt_tokens": 5_000, "prompt_cache_hit_tokens": 4_000, "prompt_cache_miss_tokens": 1_000, "completion_tokens": 100}
    assert cost.call_cost(u, P) == pytest.approx((1_000 * 2 + 4_000 * 0.2 + 100 * 10) / 1e6)


def test_gemini_thoughts_are_output():
    u = {"promptTokenCount": 3_000, "cachedContentTokenCount": 1_000, "candidatesTokenCount": 50, "thoughtsTokenCount": 450}
    assert cost.call_cost(u, P) == pytest.approx((2_000 * 2 + 1_000 * 0.2 + 500 * 10) / 1e6)


def test_served_model_from_responses():
    assert model_from_text('event: message_start\ndata: {"type":"message_start","message":{"model":"claude-opus-5-5"}}') == "claude-opus-5-5"
    assert model_from_text('{"usageMetadata":{},"modelVersion":"gemini-3.8-flash"}') == "gemini-3.8-flash"


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setattr(cost, "prices", lambda: {"m": P, "free": {"unpriced": True}})


def write_attempt(d, att, calls):
    d.mkdir(parents=True, exist_ok=True)
    (d / "attempt.json").write_text(json.dumps(att))
    (d / "api.jsonl").write_text("".join(json.dumps(c) + "\n" for c in calls))


def call(usage, model=None):
    return {"event": "call", "usage": usage, **({"model": model} if model else {})}


def test_attempt_and_composite_cost(tmp_path, table):
    u = {"prompt_tokens": 1_000_000, "completion_tokens": 0}
    main = {"config": {"harness": "codex", "model": "m"}, "harness": {"cost_usd": None},
            "subattempts": [{"id": "L-1"}]}
    write_attempt(tmp_path, main, [call(u), {"event": "blocked", "usage": u}])
    write_attempt(tmp_path / "sub" / "L-1", {"config": {"harness": "claude", "model": "x"}, "harness": {"cost_usd": 0.5}}, [])
    assert cost.attempt_cost(main, tmp_path) == (2.0, "computed")
    assert cost.composite_cost(main, tmp_path) == pytest.approx(2.5)  # the sub's reported cost is used


def test_unpriced_served_model_is_no_cost_not_a_guess(tmp_path, table):
    att = {"config": {"harness": "codex", "model": "m"}, "harness": {}}
    write_attempt(tmp_path, att, [call({"prompt_tokens": 10}, model="m-2026-09-01")])
    assert cost.attempt_cost(att, tmp_path) == (None, "no price for m-2026-09-01")


def test_long_context_tier_and_offpeak():
    p = {"input": 1.0, "output": 1.0, "long_context_threshold_tokens": 100, "long_input": 2.0, "long_output": 3.0}
    assert cost.call_cost({"prompt_tokens": 100, "completion_tokens": 10}, p) == pytest.approx(110 / 1e6)
    assert cost.call_cost({"prompt_tokens": 101, "completion_tokens": 10}, p) == pytest.approx((202 + 30) / 1e6)
    ds = {"input": 0.3, "output": 1.2, "offpeak_input": 0.15, "offpeak_output": 0.6}
    wed_0800, wed_1200 = 1790121600 + 8 * 3600, 1790121600 + 12 * 3600  # 1790121600 = Wed 2026-09-23 00:00 UTC
    u = {"prompt_tokens": 1_000_000, "completion_tokens": 0}
    assert cost.call_cost(u, ds, wed_0800) == pytest.approx(0.3) and cost.call_cost(u, ds, wed_1200) == pytest.approx(0.15)


def test_openai_cache_writes_and_prefixless_served_ids(monkeypatch):
    p = {"input": 2.0, "cached_input": 0.2, "cache_write": 2.5, "output": 10.0}
    u = {"input_tokens": 10_000, "input_tokens_details.cached_tokens": 6_000, "input_tokens_details.cache_write_tokens": 3_000}
    assert cost.call_cost(u, p) == pytest.approx((1_000 * 2 + 6_000 * 0.2 + 3_000 * 2.5) / 1e6)
    monkeypatch.setattr(cost, "prices", lambda: {"cerebras/gpt-oss-120b": p})
    assert cost.price_of("gpt-oss-120b", "cerebras/gpt-oss-120b") is p
    assert cost.price_of("gpt-oss-120b", "groq/openai/gpt-oss-120b") is None


def test_claude_lower_bound_takes_each_message_once_at_its_largest(tmp_path, monkeypatch):
    monkeypatch.setattr(cost, "prices", lambda: {"m": P})
    def ev(mid, out):
        return json.dumps({"type": "assistant", "message": {"id": mid, "model": "m", "usage": {
            "input_tokens": 1_000, "cache_read_input_tokens": 0, "output_tokens": out}}}, separators=(",", ":"))
    (tmp_path / "stdout.txt").write_text("\n".join([ev("a", 1), ev("a", 50), ev("b", 10)]) + "\n")
    att = {"config": {"harness": "claude", "model": "m"}, "harness": {}}
    assert cost.lower_bound_cost(att, tmp_path) == pytest.approx((2_000 * 2 + 60 * 10) / 1e6)
