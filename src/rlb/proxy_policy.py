"""Request policy for the sandbox proxy: an allowlist. Pure functions (no
mitmproxy import), unit-tested, imported by proxy.py under mitmproxy's Python.

Three layers, each "only what is listed":

  endpoints   per host, the paths the CLI needs: the inference endpoint and
              the account/telemetry calls observed in real runs. Anything
              else on any host is answered 403 and logged as `blocked`
              (e.g. Codex's search endpoint, Gemini's URL-fetch cache).
  tools       in an inference request, a tool declaration survives only if
              it is a client-side tool the harness executes itself (a
              function/custom tool with a schema). Server-side tools (web
              search, URL context, code execution, MCP connectors, computer
              use, ...) are removed, whatever they are called.
  responses   a response that shows a server-side tool having run anyway is
              a violation (the model got information from outside).

A blocked request delivered nothing, so it is recorded but does not by
itself invalidate the attempt; a violation does.
"""
from __future__ import annotations

import json
import re

# host -> path prefixes allowed. Inference endpoints first; the rest are what the CLIs
# call at startup and for telemetry (observed through the proxy, Sept 2026).
ALLOWED_PATHS: dict[str, tuple[str, ...]] = {
    "api.anthropic.com": (
        "/v1/messages",
        "/api/claude_cli/bootstrap", "/api/oauth/account/settings", "/api/event_logging/", "/api/eval/",
        "/v1/ultrareview/quota", "/api/claude_code_grove", "/api/claude_code_penguin_mode", "/api/hello",
    ),
    "platform.claude.com": ("/v1/oauth/",),
    "console.anthropic.com": ("/v1/oauth/",),
    "chatgpt.com": (
        "/backend-api/codex/responses", "/backend-api/codex/models", "/backend-api/codex/analytics-events/",
        "/backend-api/wham/settings/user",
    ),
    "auth.openai.com": ("/oauth/",),
    "ab.chatgpt.com": ("/otlp/",),
    "api.openai.com": ("/v1/responses", "/v1/chat/completions", "/v1/models"),
    "daily-cloudcode-pa.googleapis.com": (
        "/v1internal:generateContent", "/v1internal:streamGenerateContent",
        "/v1internal:fetchUserInfo", "/v1internal:loadCodeAssist", "/v1internal:listExperiments",
        "/v1internal:setUserSettings", "/v1internal:recordCodeAssistMetrics", "/v1internal:retrieveUserQuotaSummary",
        "/v1internal:fetchAvailableModels", "/v1internal:fetchAdminControls", "/v1internal:writeTrajectoryAcls",
    ),
    "www.googleapis.com": ("/oauth2/",),
    "oauth2.googleapis.com": ("/token",),
    "lh3.googleusercontent.com": ("/a/",),
    "play.googleapis.com": ("/log",),
    "antigravity-unleash.goog": ("/api/client/",),
    # OpenAI-compatible providers (pi)
    "api.deepseek.com": ("/chat/completions",),
    "api.fireworks.ai": ("/inference/v1/chat/completions", "/inference/v1/models", "/v1/models"),
    "api.cerebras.ai": ("/v1/chat/completions", "/v1/models"),
    "api.groq.com": ("/openai/v1/chat/completions", "/openai/v1/models"),
    "inference.baseten.co": ("/v1/chat/completions", "/v1/models"),
    "api.together.xyz": ("/v1/chat/completions", "/v1/models"),
    "api.deepinfra.com": ("/v1/openai/chat/completions", "/v1/openai/models"),
    "api.moonshot.ai": ("/v1/chat/completions", "/v1/models"),
    "generativelanguage.googleapis.com": ("/v1beta/models/",),
    # Cursor CLI: control plane (models, account, plugins, traces); the agent stream host is passed through
    "api2.cursor.sh": ("/aiserver.v1.", "/v1/traces"),
    "agentn.global.api5.cursor.sh": ("/agent.v1.AgentService/",),
}

INFERENCE_PATHS = ("/v1/messages", "/backend-api/codex/responses", "/v1/responses", "/chat/completions",
                   ":generateContent", ":streamGenerateContent", "/v1beta/models/", "/agent.v1.AgentService/Run")

# Tool declaration types the harness executes itself (client-side).
CLIENT_TOOL_TYPES = {"function", "custom", "local_shell"}  # OpenAI-style `type`
ANTHROPIC_CLIENT_TYPES = {"custom", ""}  # Anthropic: client tools have no `type` (or "custom") and an input_schema
GEMINI_CLIENT_KEYS = {"functionDeclarations"}

RESPONSE_TOOL_USE_RE = re.compile(
    r'"type"\s*:\s*"(server_tool_use|web_search_tool_result|web_search_call|web_fetch_call|web_search_result'
    r'|url_context_call|code_interpreter_call|file_search_call|mcp_call|computer_call|image_generation_call)"'
    r'|"groundingMetadata"|"urlContextMetadata"|"searchEntryPoint"|"executableCode"|"codeExecutionResult"'
)


def allowed(host: str, path: str) -> bool:
    return any(path.startswith(p) for p in ALLOWED_PATHS.get(host, ()))


def is_inference(path: str) -> bool:
    return any(k in path for k in INFERENCE_PATHS)


def _sanitize_tool_list(host: str, tools: list) -> tuple[list, list[str]]:
    keep, removed = [], []
    for t in tools:
        if not isinstance(t, dict):
            removed.append(str(t)[:40])
            continue
        if host.endswith("anthropic.com"):
            typ = str(t.get("type") or "")
            ok = (typ in ANTHROPIC_CLIENT_TYPES or typ.startswith("custom")) and "input_schema" in t
            (keep if ok else removed).append(t if ok else (typ or t.get("name") or "?"))
        elif host.endswith("googleapis.com"):
            rest = {k: v for k, v in t.items() if k in GEMINI_CLIENT_KEYS}
            removed += [k for k in t if k not in GEMINI_CLIENT_KEYS]
            if rest:
                keep.append(rest)
        else:  # OpenAI Responses and chat-completions shapes
            typ = str(t.get("type") or "")
            ok = typ in CLIENT_TOOL_TYPES
            (keep if ok else removed).append(t if ok else (typ or "?"))
    return keep, removed


def sanitize_request(host: str, path: str, body: dict) -> tuple[dict, list[str]]:
    """Allowlist the tool declarations of an inference request in place.
    Returns the body and the names/types of what was removed."""
    removed: list[str] = []
    if not is_inference(path):
        return body, removed
    if host.endswith("anthropic.com"):
        if isinstance(body.get("tools"), list):
            body["tools"], r = _sanitize_tool_list(host, body["tools"])
            removed += r
        for key in ("mcp_servers", "container"):  # server-side connectors / hosted environments
            if key in body:
                removed.append(key)
                del body[key]
    elif host.endswith("googleapis.com"):
        req = body.get("request") if isinstance(body.get("request"), dict) else body
        if isinstance(req.get("tools"), list):
            req["tools"], r = _sanitize_tool_list(host, req["tools"])
            removed += r
    else:
        if isinstance(body.get("tools"), list):
            body["tools"], r = _sanitize_tool_list(host, body["tools"])
            removed += r
        # Codex carries its tools inside the input as `additional_tools` groups.
        for item in body.get("input", []) if isinstance(body.get("input"), list) else []:
            if isinstance(item, dict) and item.get("type") == "additional_tools" and isinstance(item.get("tools"), list):
                groups = []
                for g in item["tools"]:
                    if isinstance(g, dict) and isinstance(g.get("tools"), list):
                        g["tools"], r = _sanitize_tool_list(host, g["tools"])
                        removed += r
                        groups.append(g)
                    elif isinstance(g, dict) and str(g.get("type") or "") in CLIENT_TOOL_TYPES:
                        groups.append(g)
                    else:
                        removed.append(str((g or {}).get("type") or (g or {}).get("name") or "?")[:40] if isinstance(g, dict) else "?")
                item["tools"] = groups
    return body, removed


def _flatten_numbers(obj: dict, prefix: str = "") -> dict:
    out: dict = {}
    for k, v in obj.items():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out[prefix + k] = v
        elif isinstance(v, dict):
            out.update(_flatten_numbers(v, prefix + k + "."))
    return out


def usage_from_text(text: str) -> dict | None:
    """Every `"usage": {...}` / `"usageMetadata": {...}` object in a (possibly
    SSE) response body, nested objects flattened with dotted keys, later
    occurrences overriding earlier ones (a stream's final block is complete)."""
    found: dict = {}
    dec = json.JSONDecoder()
    for m in re.finditer(r'"(usage|usageMetadata)"\s*:\s*(?=\{)', text):
        try:
            obj, _ = dec.raw_decode(text, m.end())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            found.update(_flatten_numbers(obj))
    return found or None


# Provider usage fields -> (input, output, cached). Anthropic, OpenAI Responses,
# OpenAI-compatible chat completions (Fireworks, Cerebras, Groq, Baseten), Gemini.
_IN = ("input_tokens", "prompt_tokens", "promptTokenCount")
_OUT = ("output_tokens", "completion_tokens", "candidatesTokenCount")
_CACHED = ("cache_read_input_tokens", "input_tokens_details.cached_tokens", "prompt_tokens_details.cached_tokens",
           "cachedContentTokenCount", "cached_input_tokens")


_MODEL_RE = re.compile(r'"(?:model|modelVersion)"\s*:\s*"([^"]{1,100})"')


def model_from_text(text: str) -> str | None:
    """The model that served a response, as the provider names it (Anthropic message_start and
    OpenAI responses: `model`; Gemini: `modelVersion`); for pricing each call (rlb.cost)."""
    m = _MODEL_RE.search(text)
    return m.group(1) if m else None


def normalize_usage(usage: dict | None) -> tuple[int, int, int]:
    """(input, output, cached) token counts from a flattened usage dict; output
    includes reasoning/thinking tokens where the provider reports them apart
    (Gemini's candidatesTokenCount excludes thoughts; OpenAI's output_tokens
    includes them, and reasoning_output_tokens is a detail, not added twice)."""
    if not usage:
        return 0, 0, 0

    def first(keys):
        for k in keys:
            if k in usage:
                return int(usage[k])
        return 0

    out = first(_OUT)
    if "candidatesTokenCount" in usage:
        out += int(usage.get("thoughtsTokenCount", 0))
    return first(_IN), out, first(_CACHED)
