"""Claude Code (`claude -p --output-format stream-json`). Uses the Max
subscription login.

The final `result` event reports `duration_api_ms` (the CLI's own count of
model time; kept for comparison with the network capture), turns, usage and
cost. Tool-execution intervals are reconstructed from `tool_use` blocks and
their `tool_result`s.

[args] keys: effort, max_turns, allowed_tools, disallowed_tools,
setting_sources (default "local"), strict_mcp (default true; add MCP servers via
extra = ["--mcp-config", ...]), append_system_prompt, extra (raw CLI args).
"""
from __future__ import annotations

import re
from pathlib import Path

from ..config import Config
from .base import HarnessStats, Invocation, Line, grep_stdout, is_provider_error, json_lines, pair_intervals


# Tools that start or reach other agents, all blocked: Agent (old name Task) and Workflow start
# subagents, RemoteTrigger cloud sessions outside the sandbox, SendMessage/ListAgents reach other
# sessions on the machine. Subagents are rlb's (lemma.py), not Claude Code's.
AGENT_TOOLS = ("Agent", "Task", "Workflow", "RemoteTrigger", "SendMessage", "ListAgents")


class ClaudeHarness:
    name = "claude"
    state_paths = (".claude", ".claude.json")
    aux_hosts = ("platform.claude.com", "console.anthropic.com")  # OAuth token refresh (expected, not yet observed)
    passthrough_hosts: tuple[str, ...] = ()

    native_subagents_prompt = None

    def unauthorized_agent_call(self, native_allowed: bool, attempt_dir: Path) -> str | None:
        # the 2026-09-23 native probe (ledger #48) opened Agent only; the rest stayed blocked
        tools = AGENT_TOOLS[2:] if native_allowed else AGENT_TOOLS
        return grep_stdout(re.compile(r'"type":"tool_use","id":"[^"]*","name":"(%s)"' % "|".join(tools)), attempt_dir)

    def api_hosts(self, cfg: Config) -> tuple[str, ...]:
        return tuple(cfg.api_hosts or ["api.anthropic.com"])

    def invocation(self, cfg: Config, workdir: Path, prompt: str) -> Invocation:
        a = cfg.args
        # Prompt right after -p: --allowedTools/--disallowedTools are variadic
        # and would otherwise swallow a trailing prompt.
        argv = [
            "claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--no-session-persistence",
            "--model", cfg.model,
            "--allowedTools", a.get("allowed_tools", "Bash,Read,Edit,Write,Glob,Grep"),
            "--disallowedTools", ",".join([a.get("disallowed_tools", "WebSearch,WebFetch"), *AGENT_TOOLS]),
            "--max-turns", str(a.get("max_turns", 80)),
            # No user-level plugins/hooks/MCP servers unless a config asks for them:
            # `local` loads only settings from the (empty) workdir.
            "--setting-sources", a.get("setting_sources", "local"),
        ]
        if a.get("strict_mcp", True):
            argv.append("--strict-mcp-config")
        if a.get("effort"):
            argv += ["--effort", a["effort"]]
        if a.get("append_system_prompt"):
            argv += ["--append-system-prompt", a["append_system_prompt"]]
        argv += list(a.get("extra", []))
        return Invocation(argv)

    def provider_error(self, ev: dict) -> str | None:
        # A refused API call surfaces as an assistant text block with the refusal, and at the
        # end as a `result` with is_error / api_error_status. Both are matched against the pattern.
        if ev.get("type") == "result" and (ev.get("is_error") or ev.get("api_error_status")):
            txt = f"{ev.get('api_error_status') or ''} {ev.get('result') or ''}".strip()
            return txt if is_provider_error(txt) else None
        if ev.get("type") == "assistant":
            msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
            for b in msg.get("content") or []:
                if b.get("type") == "text" and is_provider_error(b.get("text")) and len(b.get("text", "")) < 400:
                    return b["text"]
        return None

    def stats(self, lines: list[Line]) -> HarnessStats:
        st = HarnessStats()
        starts: dict[str, float] = {}
        ends: dict[str, float] = {}
        usage: dict[str, int] = {}
        turns = 0
        result = None
        for t, ev in json_lines(lines):
            typ = ev.get("type")
            pe = self.provider_error(ev)
            if pe:
                st.provider_errors.append(pe)
            msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}  # some events carry a string message
            content = msg.get("content") if isinstance(msg.get("content"), list) else []
            if typ == "assistant":
                turns += 1
                for k, v in (msg.get("usage") or {}).items():
                    if isinstance(v, int):
                        usage[k] = usage.get(k, 0) + v
                for b in content:
                    if b.get("type") == "tool_use":
                        starts[b["id"]] = t
                    elif b.get("type") == "text" and b.get("text"):
                        st.final_message = b["text"]
            elif typ == "user":
                for b in content:
                    if b.get("type") == "tool_result":
                        ends[b.get("tool_use_id", "")] = t
            elif typ == "result":
                result = ev
        st.tool_intervals = pair_intervals(starts, ends)
        st.turns = turns or None
        st.usage = usage or None
        if result is None:
            st.error = "no result event (killed?)"
            return st
        st.inference_s = result["duration_api_ms"] / 1000 if "duration_api_ms" in result else None
        st.turns = result.get("num_turns", st.turns)
        st.usage = result.get("usage", st.usage)
        st.cost_usd = result.get("total_cost_usd")
        st.final_message = result.get("result", st.final_message)
        st.exit_reason = result.get("subtype")
        if result.get("is_error"):
            st.error = f"{result.get('subtype')}: {str(result.get('result'))[:500]}"
        return st
