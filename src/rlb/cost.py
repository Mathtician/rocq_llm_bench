"""API-equivalent cost of an attempt, in USD: the common unit for composites of different models.

One price source for every harness: prices.toml (list prices, each with its source).
  computed   per-call usage from the proxy log (api.jsonl) x prices.toml, keyed by the model that
             served the call (logged by the proxy since 2026-09-23; before that, the config's model,
             which misprices Claude Code's small background calls to other models by cents); long-
             context tiers and DeepSeek's off-peak rate per call. For Cursor, whose model traffic
             bypasses the proxy, the usage in its final result event (absent after a mid-run
             reconnect: then no cost).
  harness    the same prices applied to the harness's own usage totals, when the proxy log is
             missing (runs before 2026-09-05) or incomplete (it missed some calls' usage: its output
             total falls short of the harness's; seen on DeepSeek); totals cannot tell long-context
             or off-peak calls apart, so those are priced at the base rate.
  reported   the harness's own figure (Claude Code's total_cost_usd, pi's registry cost): only when
             nothing can be computed, and as a cross-check of the table.
A composite's cost is its own plus its subagent attempts' (records under sub/<id>/).
"""
from __future__ import annotations

import json
import tomllib
from functools import cache
from pathlib import Path

from . import ROOT

PRICES = ROOT / "prices.toml"
# Records made before configs pinned model ids name aliases; resolved from the ids the API
# reported in those runs' stream-json (commit e630876).
ALIASES = {"opus": "claude-opus-5", "sonnet": "claude-sonnet-5", "haiku": "claude-haiku-4-5-20251001"}


@cache
def prices() -> dict[str, dict]:
    return tomllib.loads(PRICES.read_text())["models"]


def price_of(model: str, config_model: str | None = None) -> dict | None:
    """Prices for a model id. A served id that is the config's id without its provider prefix
    (Cerebras reports gpt-oss-120b for cerebras/gpt-oss-120b) is the same model; any other unknown
    id has no price: it is added to prices.toml, never guessed."""
    key = ALIASES.get(model, model)
    if key not in prices() and config_model and config_model.endswith("/" + model):
        key = config_model
    p = prices().get(key)
    return None if p is None or p.get("unpriced") else p


def deepseek_offpeak(t: float) -> bool:
    """DeepSeek's peak hours: 01:00-04:00 and 06:00-10:00 UTC, Monday-Friday (Chinese public
    holidays, also off-peak, are not modelled: such a call is priced at the peak rate)."""
    import datetime as dt
    u = dt.datetime.fromtimestamp(t, dt.timezone.utc)
    return u.weekday() >= 5 or not (1 <= u.hour < 4 or 6 <= u.hour < 10)


def call_cost(usage: dict, p: dict, t: float | None = None) -> float:
    """USD for one call's flattened usage dict (as the proxy logs it) at prices p (USD per M),
    sent at epoch t (for time-of-day rates)."""
    def g(k):
        return int(usage.get(k) or 0)
    anthropic = "cache_read_input_tokens" in usage or "cache_creation_input_tokens" in usage
    gemini = "promptTokenCount" in usage
    prompt = (g("input_tokens") + g("cache_read_input_tokens") + g("cache_creation_input_tokens") if anthropic
              else g("promptTokenCount") if gemini else g("input_tokens") or g("prompt_tokens"))
    variant = ("long_" if prompt > p.get("long_context_threshold_tokens", float("inf"))
               else "offpeak_" if "offpeak_input" in p and t is not None and deepseek_offpeak(t) else "")

    def rate(k, fallback=None):
        return p.get(variant + k, p.get(k, fallback))
    inp, out_rate = rate("input"), rate("output")
    cached_rate = rate("cached_input", inp)
    if anthropic:
        # input_tokens excludes both cache reads and cache writes
        w1h = g("cache_creation.ephemeral_1h_input_tokens")
        w5m = g("cache_creation_input_tokens") - w1h
        return (g("input_tokens") * inp + g("cache_read_input_tokens") * cached_rate
                + w5m * rate("cache_write_5m", inp) + w1h * rate("cache_write_1h", inp)
                + g("output_tokens") * out_rate) / 1e6
    if gemini:
        # the prompt count includes cached content; thoughts are billed as output
        cached = g("cachedContentTokenCount")
        return ((prompt - cached) * inp + cached * cached_rate
                + (g("candidatesTokenCount") + g("thoughtsTokenCount")) * out_rate) / 1e6
    # OpenAI Responses and OpenAI-compatible chat: input includes its cached and cache-write parts;
    # output includes reasoning
    cached = g("input_tokens_details.cached_tokens") or g("prompt_tokens_details.cached_tokens") or g("prompt_cache_hit_tokens")
    written = g("input_tokens_details.cache_write_tokens")
    out = g("output_tokens") or g("completion_tokens")
    return ((prompt - cached - written) * inp + cached * cached_rate + written * rate("cache_write", inp)
            + out * out_rate) / 1e6


def computed_cost(att: dict, attempt_dir: Path) -> tuple[float | None, str]:
    cfg = att["config"]
    if cfg["harness"] == "cursor":
        u = (att.get("harness") or {}).get("usage") or {}
        out = attempt_dir / "stdout.txt"
        if not u or (out.exists() and '"type":"retry"' in out.read_text(errors="replace")):
            return None, "cursor usage missing or partial (reconnect)"
        p = price_of(cfg["model"])
        if p is None:
            return None, f"no price for {cfg['model']}"
        return call_cost({"prompt_tokens": u.get("inputTokens", 0) + u.get("cacheReadTokens", 0),
                          "prompt_cache_hit_tokens": u.get("cacheReadTokens", 0),
                          "completion_tokens": u.get("outputTokens", 0)}, p), "computed"
    api = attempt_dir / "api.jsonl"
    if not api.exists():
        return None, "no proxy log"
    total, calls = 0.0, 0
    for line in api.read_text().splitlines():
        r = json.loads(line)
        if r.get("event") != "call" or not r.get("usage"):
            continue
        model = r.get("model") or cfg["model"]  # the served model, logged since 2026-09-23
        p = price_of(model, cfg["model"])
        if p is None:
            return None, f"no price for {model}"
        total += call_cost(r["usage"], p, r.get("t_sent"))
        calls += 1
    if calls == 0:  # nothing to price is not the same as free
        return None, "no usage in the proxy log"
    return total, "computed"


def harness_usage(att: dict) -> dict | None:
    """The harness's usage totals in the shape of one provider call (call_cost's input). Each
    harness's fields were checked against the proxy's per-call sums (2026-09-23)."""
    u = (att.get("harness") or {}).get("usage") or {}
    h = att["config"]["harness"]
    if h == "codex" and "input_tokens" in u:  # input includes cached and written; output includes reasoning
        return {"input_tokens": u["input_tokens"], "input_tokens_details.cached_tokens": u.get("cached_input_tokens", 0),
                "input_tokens_details.cache_write_tokens": u.get("cache_write_input_tokens", 0),
                "output_tokens": u.get("output_tokens", 0)}
    if h == "agy" and "input_tokens" in u:  # cache reads are apart from input; output includes thinking
        return {"promptTokenCount": u["input_tokens"] + u.get("cache_read_tokens", 0),
                "cachedContentTokenCount": u.get("cache_read_tokens", 0), "candidatesTokenCount": u.get("output_tokens", 0)}
    if h == "pi" and "input" in u:  # cacheRead apart from input; output includes reasoning
        return {"prompt_tokens": u["input"] + u.get("cacheRead", 0), "prompt_tokens_details.cached_tokens": u.get("cacheRead", 0),
                "completion_tokens": u.get("output", 0)}
    return None  # claude: its reported cost covers it (per-model usage, its own list prices)


def attempt_cost(att: dict, attempt_dir: Path) -> tuple[float | None, str]:
    """(USD, source) for one attempt, without its subagents."""
    computed, why = computed_cost(att, attempt_dir)
    hu = harness_usage(att)
    if computed is not None:
        proxy_out = (att.get("net") or {}).get("tokens_out") or 0
        harness_out = int((hu or {}).get("output_tokens") or (hu or {}).get("completion_tokens") or (hu or {}).get("candidatesTokenCount") or 0)
        if not harness_out or proxy_out >= 0.98 * harness_out:
            return computed, "computed"
        why = f"proxy log incomplete ({proxy_out} of {harness_out} output tokens)"
    p = price_of(att["config"]["model"])
    if hu is not None and p is not None:
        return call_cost(hu, p), "harness"
    reported = (att.get("harness") or {}).get("cost_usd")
    return (float(reported), "reported") if reported else (None, why)


def composite_cost(att: dict, attempt_dir: Path) -> float | None:
    """An attempt's cost plus its subagent attempts'; None if any part has no cost."""
    parts = [attempt_cost(att, attempt_dir)[0]]
    for s in att.get("subattempts") or []:
        d = attempt_dir / "sub" / s["id"]
        if (d / "attempt.json").exists():
            parts.append(attempt_cost(json.loads((d / "attempt.json").read_text()), d)[0])
    return None if any(c is None for c in parts) else sum(parts)


def lower_bound_cost(att: dict, attempt_dir: Path) -> float | None:
    """A cost the attempt certainly reached, for attempts whose full cost is unknown. Enough for an
    unsolved attempt, which the fits treat as censored (cost >= this) anyway; never for a solved one.
      claude  the usage at the start of each API message in its stream (input and cache counts are
              complete there, output is not), at the model that served it
      cursor  the usage its final event reports, which after a reconnect covers only the resumed part"""
    cfg = att["config"]
    if cfg["harness"] == "cursor":
        u = (att.get("harness") or {}).get("usage") or {}
        p = price_of(cfg["model"])
        if not u or p is None:
            return None
        return call_cost({"prompt_tokens": u.get("inputTokens", 0) + u.get("cacheReadTokens", 0),
                          "prompt_cache_hit_tokens": u.get("cacheReadTokens", 0),
                          "completion_tokens": u.get("outputTokens", 0)}, p)
    if cfg["harness"] == "claude":
        out = attempt_dir / "stdout.txt"
        if not out.exists():
            return None
        per_msg: dict[str, tuple[str, dict]] = {}
        for line in out.read_text(errors="replace").splitlines():
            if '"type":"assistant"' not in line:
                continue
            try:
                m = json.loads(line)["message"]
            except (json.JSONDecodeError, KeyError):
                continue
            u = m.get("usage") or {}
            flat = {k: v for k, v in u.items() if isinstance(v, int)}
            flat.update({f"cache_creation.{k}": v for k, v in (u.get("cache_creation") or {}).items() if isinstance(v, int)})
            prev = per_msg.get(m.get("id"), (None, {}))[1]
            per_msg[m.get("id")] = (m.get("model") or cfg["model"], {k: max(v, prev.get(k, 0)) for k, v in flat.items()})
        total = 0.0
        for model, u in per_msg.values():
            p = price_of(model, cfg["model"])
            if p is None:
                return None
            total += call_cost(u, p)
        return total or None
    return None
