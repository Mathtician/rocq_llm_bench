"""The proxy's request policy (an allowlist), on request shapes captured from the real CLIs."""
from rlb.proxy_policy import allowed, sanitize_request, usage_from_text, normalize_usage


def test_endpoint_allowlist():
    assert allowed("api.deepseek.com", "/chat/completions")
    assert not allowed("api.deepseek.com", "/search")
    assert allowed("api.anthropic.com", "/v1/messages")
    assert allowed("chatgpt.com", "/backend-api/codex/responses")
    assert not allowed("chatgpt.com", "/backend-api/codex/alpha/search")  # Codex's web search
    assert not allowed("daily-cloudcode-pa.googleapis.com", "/v1internal:fetchFromTrawlerCache")  # Gemini's URL fetch cache
    assert not allowed("api.anthropic.com", "/v1/mcp_servers")
    assert not allowed("example.com", "/")


def test_anthropic_only_client_tools_survive():
    body = {"tools": [{"name": "Bash", "input_schema": {}}, {"type": "web_search_20250305", "name": "web_search"},
                      {"type": "custom", "name": "Edit", "input_schema": {}}, {"type": "some_future_tool_2027", "name": "x"}],
            "mcp_servers": [{"url": "https://mcp.example"}]}
    out, removed = sanitize_request("api.anthropic.com", "/v1/messages", body)
    assert [t["name"] for t in out["tools"]] == ["Bash", "Edit"]
    assert removed == ["web_search_20250305", "some_future_tool_2027", "mcp_servers"]
    assert "mcp_servers" not in out


def test_gemini_only_function_declarations_survive():
    body = {"request": {"tools": [{"functionDeclarations": [{"name": "run_command"}]}, {"googleSearch": {}},
                                  {"urlContext": {}, "functionDeclarations": [{"name": "x"}]}, {"newServerThing": {}}]}}
    out, removed = sanitize_request("daily-cloudcode-pa.googleapis.com", "/v1internal:streamGenerateContent", body)
    assert out["request"]["tools"] == [{"functionDeclarations": [{"name": "run_command"}]}, {"functionDeclarations": [{"name": "x"}]}]
    assert removed == ["googleSearch", "urlContext", "newServerThing"]


def test_codex_frame_tool_groups_and_top_level():
    body = {"type": "response.create", "tools": [{"type": "web_search"}, {"type": "function", "name": "f"}],
            "input": [{"type": "additional_tools", "tools": [
                {"type": "namespace", "name": "functions", "tools": [{"type": "custom", "name": "exec"}, {"type": "web_search"}]},
                {"type": "file_search"}]}]}
    out, removed = sanitize_request("chatgpt.com", "/backend-api/codex/responses", body)
    assert out["tools"] == [{"type": "function", "name": "f"}]
    assert [t["name"] for t in out["input"][0]["tools"][0]["tools"]] == ["exec"]
    assert len(out["input"][0]["tools"]) == 1
    assert sorted(removed) == ["file_search", "web_search", "web_search"]


def test_chat_completions_function_tools_kept_and_non_inference_untouched():
    body = {"tools": [{"type": "function", "function": {"name": "bash"}}, {"type": "retrieval"}]}
    out, removed = sanitize_request("api.fireworks.ai", "/inference/v1/chat/completions", body)
    assert [t["type"] for t in out["tools"]] == ["function"] and removed == ["retrieval"]
    settings = {"tools": [{"type": "web_search"}]}
    assert sanitize_request("api.anthropic.com", "/api/oauth/account/settings", dict(settings)) == (settings, [])


def test_usage_parsing_and_normalization():
    sse = 'data: {"type":"message_start","message":{"usage":{"input_tokens":12,"cache_read_input_tokens":3000,"cache_creation":{"ephemeral_5m_input_tokens":7}}}}\n' \
          'data: {"type":"message_delta","usage":{"output_tokens":45}}\n'
    u = usage_from_text(sse)
    assert u["input_tokens"] == 12 and u["output_tokens"] == 45 and u["cache_creation.ephemeral_5m_input_tokens"] == 7
    assert normalize_usage(u) == (12, 45, 3000)
    assert normalize_usage({"prompt_tokens": 50, "completion_tokens": 7, "prompt_tokens_details.cached_tokens": 40}) == (50, 7, 40)
    assert normalize_usage({"promptTokenCount": 100, "candidatesTokenCount": 9, "thoughtsTokenCount": 30, "cachedContentTokenCount": 80}) == (100, 39, 80)
    assert usage_from_text("no usage here") is None
