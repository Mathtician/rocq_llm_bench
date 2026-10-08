"""mitmproxy addon: the sandbox's view into the harness's API traffic.

Runs inside the network namespace (sandbox.py starts `mitmdump -s` on it).
The harness is pointed at it with HTTPS_PROXY and trusts its CA through the
usual environment variables. Two jobs:

1. Policy (proxy_policy.py, an allowlist): only listed endpoints per host
   pass (403 otherwise, logged as `blocked`); in inference requests only
   client-side tool declarations survive (function/custom tools with a
   schema; Gemini functionDeclarations), so server-side tools (web search,
   URL context, code execution, MCP connectors, ...) are removed whatever
   they are called, including inside Codex's WebSocket frames; a response
   that shows a server-side tool having run anyway is a violation.

2. Timing and usage. For every request to an inference host: time sent,
   time of the response headers, first body byte, last byte, sizes, and the
   usage block the provider reports (Anthropic message_delta / final message,
   OpenAI response.completed, Gemini usageMetadata, OpenAI-compatible chat
   completions). Written as JSON lines to $RLB_PROXY_LOG. Bodies are never
   stored (they hold the whole conversation).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from mitmproxy import http

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the repo's src/, for rlb.proxy_policy
from rlb.proxy_policy import RESPONSE_TOOL_USE_RE, allowed, model_from_text, sanitize_request, usage_from_text  # noqa: E402

LOG_PATH = os.environ.get("RLB_PROXY_LOG", "api.jsonl")


def _log(rec: dict) -> None:
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")


class RlbProxy:
    def request(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        path = flow.request.path.split("?")[0]
        if not allowed(host, path):
            _log({"t": time.time(), "event": "blocked", "host": host, "path": path[:120], "method": flow.request.method})
            flow.response = http.Response.make(403, b'{"error":"blocked by the benchmark sandbox: endpoint not on its allowlist"}',
                                               {"content-type": "application/json"})
            return
        flow.metadata["t_sent"] = time.time()
        flow.metadata["req_bytes"] = len(flow.request.raw_content or b"")
        if flow.request.headers.get("content-type", "").startswith("application/json"):
            try:
                body = json.loads(flow.request.get_text(strict=False) or "")
            except (json.JSONDecodeError, ValueError):
                return
            if isinstance(body, dict):
                body, removed = sanitize_request(host, path, body)
                if removed:
                    flow.request.set_text(json.dumps(body))
                    flow.metadata["stripped"] = removed
                    _log({"t": time.time(), "event": "stripped", "host": host, "path": flow.request.path.split("?")[0], "tools": removed})

    def responseheaders(self, flow: http.HTTPFlow) -> None:
        flow.metadata["t_headers"] = time.time()
        # Stream the body through untouched so the client sees real streaming; observe chunks for timing.
        chunks: list[bytes] = []

        def observe(data: bytes) -> bytes:
            now = time.time()
            flow.metadata.setdefault("t_first", now)
            flow.metadata["t_last"] = now
            flow.metadata["resp_bytes"] = flow.metadata.get("resp_bytes", 0) + len(data)
            if flow.metadata["resp_bytes"] < 4_000_000:
                chunks.append(data)
            return data

        flow.metadata["chunks"] = chunks
        flow.response.stream = observe

    def response(self, flow: http.HTTPFlow) -> None:
        md = flow.metadata
        if "t_sent" not in md:
            return  # blocked before it was sent
        raw = b"".join(md.get("chunks") or [])
        ce = flow.response.headers.get("content-encoding", "")
        decode_error = None
        if ce and ce != "identity":
            try:
                if ce in ("gzip", "deflate"):
                    import zlib
                    raw = zlib.decompressobj(47).decompress(raw)
                elif ce == "br":
                    import brotli
                    raw = brotli.decompress(raw)
                elif ce == "zstd":
                    import zstandard
                    raw = zstandard.ZstdDecompressor().decompressobj().decompress(raw)
            except Exception as e:  # noqa: BLE001 - keep the record even if decoding fails
                decode_error = f"{type(e).__name__}: {e}"[:120]
        text = raw.decode("utf-8", "replace")
        rec = {
            "t": md.get("t_sent"), "event": "call", "host": flow.request.pretty_host,
            "path": flow.request.path.split("?")[0][:80], "status": flow.response.status_code,
            "t_sent": md.get("t_sent"), "t_headers": md.get("t_headers"), "t_first": md.get("t_first"),
            "t_last": md.get("t_last") or md.get("t_headers"),
            "req_bytes": md.get("req_bytes", 0), "resp_bytes": md.get("resp_bytes", 0),
            "usage": usage_from_text(text), "model": model_from_text(text), "stripped": md.get("stripped"),
            "ce": ce or None, "ct": flow.response.headers.get("content-type", "")[:40], "decoded": len(text),
            "decode_error": decode_error,
        }
        m = RESPONSE_TOOL_USE_RE.search(text)
        if m:
            rec["violation"] = f"server-side tool used ({m.group(0)[:40]}) in response from {flow.request.pretty_host}"
        _log(rec)

    # Codex: one WebSocket per session; each response.create is a call, each response.completed its end.
    def websocket_message(self, flow: http.HTTPFlow) -> None:
        msg = flow.websocket.messages[-1]
        now = time.time()
        host = flow.request.pretty_host
        if os.environ.get("RLB_PROXY_DEBUG"):
            _log({"t": now, "event": "ws", "host": host, "dir": ">" if msg.from_client else "<", "head": msg.content[:80].decode("utf-8", "replace")})
        if msg.from_client:
            if b'"response.create"' in msg.content[:200]:
                try:
                    body = json.loads(msg.content)
                    body, removed = sanitize_request(host, "/backend-api/codex/responses", body)
                    if removed:
                        msg.content = json.dumps(body, separators=(",", ":")).encode()
                        _log({"t": now, "event": "stripped", "host": host, "path": "ws:responses", "tools": removed})
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
                flow.metadata["ws_call"] = {"t_sent": now, "req_bytes": len(msg.content), "t_first": None, "resp_bytes": 0}
            return
        call = flow.metadata.get("ws_call")
        if call is None:
            return
        call["t_first"] = call["t_first"] or now
        call["resp_bytes"] += len(msg.content)
        head = msg.content[:120]
        if b'"web_search_call"' in msg.content or b'"web_search"' in head and b'"type":"response.output_item' in head:
            _log({"t": now, "event": "violation", "host": host,
                  "violation": "server-side tool used (web_search_call) in Codex response"})
        if b'"response.completed"' in head or b'"response.failed"' in head or b'"response.incomplete"' in head:
            _log({"t": call["t_sent"], "event": "call", "host": host, "path": "ws:responses", "status": 200,
                  "t_sent": call["t_sent"], "t_headers": call["t_first"], "t_first": call["t_first"], "t_last": now,
                  "req_bytes": call["req_bytes"], "resp_bytes": call["resp_bytes"],
                  "usage": usage_from_text(msg.content.decode("utf-8", "replace")),
                  "model": model_from_text(msg.content.decode("utf-8", "replace")), "stripped": None})
            flow.metadata["ws_call"] = None


addons = [RlbProxy()]
