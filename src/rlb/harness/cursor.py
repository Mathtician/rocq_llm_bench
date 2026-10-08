"""Cursor CLI (`cursor-agent -p --output-format stream-json`). Uses the Cursor login.

Event stream (observed 2026-09-07, cursor-agent 2026.08/09): `system/init` (model name),
`user`, `thinking/delta|completed`, `assistant` (one per model call, text blocks),
`tool_call/started|completed` keyed by `call_id` with the tool kind as the single key of
`tool_call` (`shellToolCall`, `readToolCall`, `editToolCall`, `globToolCall`, ...),
`retry/starting` on transport failures, and a final `result` with `duration_api_ms`,
`is_error`, `result` (concatenated assistant text) and `usage`
{inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens}.

Network: control calls to api2.cursor.sh (models, account, traces); the agent loop itself is a
bidirectional stream to agentn.global.api5.cursor.sh which does not survive TLS interception,
so that host is passed through the proxy un-inspected (`passthrough_hosts`) and timed from the
packet capture. Consequence: tool declarations on that stream cannot be stripped; any
web/search/fetch tool call the model makes is recorded as a rule violation instead.

Usage caveat: after a `retry`/`connection reconnecting` event the final usage covers only the
resumed segment (undercount); scripts/fit_tokens.py drops such attempts from the token fit.

Refusals (plan/quota) arrive on stderr as `ActionRequiredError: ...` with no `result` event;
the runner's stderr fallback classifies those (see runner.detect_provider_error).

[args] keys: extra (raw CLI args).
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from ..config import Config
from .base import HarnessStats, Invocation, Line, grep_stdout, is_provider_error, json_lines, pair_intervals

# Tool kinds that reach outside the sandbox: recorded as violations (they are executed by Cursor's
# servers or fetch the web; the sandbox cannot see or block them).
WEB_TOOL_KINDS = ("webSearch", "webFetch", "fetch", "browser", "mcp")


class CursorHarness:
    name = "cursor"
    # the CLI binary lives under ~/.local/share/cursor-agent (a version dir + launcher symlink in
    # ~/.local/bin); auth and settings in ~/.cursor and ~/.config/cursor
    state_paths = (".cursor", ".config/cursor", ".local/share/cursor-agent")
    aux_hosts = ("api2.cursor.sh",)
    passthrough_hosts = ("agentn.global.api5.cursor.sh",)  # TLS not intercepted; allowlisted and timed from pcap
    native_subagents_prompt = None

    def unauthorized_agent_call(self, native_allowed: bool, attempt_dir: Path) -> str | None:
        # The CLI has no switch for its Task/subagent tools (none called in any run so far); audit instead.
        return None if native_allowed else grep_stdout(re.compile(r'"(taskToolCall|subagentToolCall)"'), attempt_dir)

    def api_hosts(self, cfg: Config) -> tuple[str, ...]:
        return tuple(cfg.api_hosts or ["agentn.global.api5.cursor.sh"])

    def invocation(self, cfg: Config, workdir: Path, prompt: str) -> Invocation:
        a = cfg.args
        launcher = shutil.which("cursor-agent")
        if launcher is None:
            raise SystemExit("cursor-agent not on PATH")
        argv = [
            # the real launcher, not the ~/.local/bin symlink: it locates its bundled node and index.js
            # next to itself, and only the versions dir under ~/.local/share is visible inside the sandbox
            os.path.realpath(launcher), "-p", "--output-format", "stream-json",
            "--force",  # run every command without asking (ours is the sandbox)
            "--trust", "--sandbox", "disabled",  # its own sandbox breaks inside ours, as Codex's does
            "--workspace", str(workdir),
            "--model", cfg.model,
        ]
        argv += list(a.get("extra", []))
        argv.append(prompt)
        return Invocation(argv)

    def provider_error(self, ev: dict) -> str | None:
        if ev.get("type") == "result" and ev.get("is_error"):
            txt = str(ev.get("result") or ev.get("error") or "")
            return txt if is_provider_error(txt) else None
        if ev.get("type") == "error":
            txt = str(ev.get("message") or ev.get("error") or "")
            return txt if is_provider_error(txt) else None
        return None

    def stats(self, lines: list[Line]) -> HarnessStats:
        st = HarnessStats()
        starts: dict[str, float] = {}
        ends: dict[str, float] = {}
        calls: set[str] = set()  # model_call_id: one per inference call
        result = None
        for t, ev in json_lines(lines):
            typ, sub = ev.get("type"), ev.get("subtype")
            pe = self.provider_error(ev)
            if pe:
                st.provider_errors.append(pe)
            if ev.get("model_call_id"):
                calls.add(ev["model_call_id"])
            if typ == "assistant":
                for b in (ev.get("message") or {}).get("content") or []:
                    if b.get("type") == "text" and b.get("text"):
                        st.final_message = b["text"]
            elif typ == "tool_call":
                cid = ev.get("call_id", "")
                kinds = [k for k in (ev.get("tool_call") or {}) if k.endswith("ToolCall")]
                if sub == "started":
                    starts[cid] = t
                    for k in kinds:
                        if k.startswith(WEB_TOOL_KINDS):
                            args = (ev["tool_call"].get(k) or {}).get("args") or {}
                            st.violations.append(f"web tool {k}: {str(args)[:120]}")
                elif sub == "completed":
                    ends[cid] = t
            elif typ == "result":
                result = ev
        st.tool_intervals = pair_intervals(starts, ends)
        st.turns = len(calls) or None
        if result is None:
            st.error = "no result event (killed, or refused before the first turn: see stderr)"
            return st
        st.inference_s = result["duration_api_ms"] / 1000 if "duration_api_ms" in result else None
        st.usage = result.get("usage")
        st.final_message = result.get("result", st.final_message)
        st.exit_reason = result.get("subtype")
        if result.get("is_error"):
            st.error = f"{result.get('subtype')}: {str(result.get('result'))[:500]}"
        return st
