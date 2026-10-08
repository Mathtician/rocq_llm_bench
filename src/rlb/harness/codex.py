"""OpenAI Codex CLI (`codex exec --json`). Uses the ChatGPT login.

Codex reports token usage but no model time. Inference goes over a WebSocket
to chatgpt.com (`/backend-api/codex/responses`), which the network capture
times. By default Codex also pages through the whole remote plugin catalog at
startup (~20 MB from the same host, overlapping the first turn); the
`plugins` knob turns that off so it cannot pollute the inference measure.

[args] keys: effort (model_reasoning_effort), sandbox (danger-full-access
default: ours confines it), ignore_user_config (default true), plugins
(default false), web_search (default false), config (list of extra
`-c key=value`), extra (raw CLI args).
"""
from __future__ import annotations

from pathlib import Path

from ..config import Config
from .base import HarnessStats, Invocation, Line, is_provider_error, json_lines, pair_intervals


class CodexHarness:
    name = "codex"
    state_paths = (".codex",)
    aux_hosts = ("auth.openai.com",)  # OAuth token refresh (expected, not yet observed)
    passthrough_hosts: tuple[str, ...] = ()

    native_subagents_prompt = None

    def unauthorized_agent_call(self, native_allowed: bool, attempt_dir: Path) -> str | None:
        # `codex exec --json` does not report spawn_agent (probe, ledger #48): a sub-agent shows up
        # only as another model session, i.e. another WebSocket upgrade of /backend-api/codex/responses
        # in the proxy log. Every main-agent-only attempt so far had exactly one (53 of 53); a
        # reconnect would also count, and costs a redo.
        if native_allowed:
            return None
        api = attempt_dir / "api.jsonl"
        if not api.exists():
            return None
        sessions = sum(1 for l in api.read_text().splitlines()
                       if '"path":"/backend-api/codex/responses"' in l and '"status":101' in l)
        return f"{sessions} model sessions (WebSocket upgrades)" if sessions > 1 else None

    def api_hosts(self, cfg: Config) -> tuple[str, ...]:
        return tuple(cfg.api_hosts or ["chatgpt.com", "api.openai.com"])

    def invocation(self, cfg: Config, workdir: Path, prompt: str) -> Invocation:
        a = cfg.args
        argv = [
            "codex", "exec", "--json", "--ephemeral", "--skip-git-repo-check",
            # Codex's own sandbox (Landlock/seccomp) fails its write probe inside ours (sandbox.py),
            # and ours already confines it; so it runs with its sandbox off.
            "--sandbox", a.get("sandbox", "danger-full-access"),
            "-C", str(workdir), "-m", cfg.model,
            "-c", "shell_environment_policy.inherit=all",
        ]
        if a.get("ignore_user_config", True):
            argv.append("--ignore-user-config")
        if not a.get("plugins", False):
            argv += ["-c", "features.plugins=false", "-c", "features.remote_plugin=false", "-c", "features.apps=false"]
        # OpenAI's web_search tool runs server-side, outside the sandbox's network allowlist;
        # on Putnam, Codex used it to hunt for the published reference solutions. Off by default.
        if not a.get("web_search", False):
            argv += ["-c", 'web_search="disabled"']
        # multi_agent (spawn_agent, send_input, wait_agent, ...) is on by default since ~0.150.
        argv += ["-c", "features.multi_agent=false", "-c", "features.multi_agent_v2=false"]
        if a.get("effort"):
            argv += ["-c", f'model_reasoning_effort="{a["effort"]}"']
        for kv in a.get("config", []):
            argv += ["-c", kv]
        argv += list(a.get("extra", []))
        argv.append(prompt)
        return Invocation(argv)

    def provider_error(self, ev: dict) -> str | None:
        if ev.get("type") in ("error", "turn.failed"):
            err = ev.get("error") if isinstance(ev.get("error"), dict) else {}
            txt = str(err.get("message") or ev.get("message") or "")
            return txt if is_provider_error(txt) else None
        return None

    def stats(self, lines: list[Line]) -> HarnessStats:
        st = HarnessStats()
        starts: dict[str, float] = {}
        ends: dict[str, float] = {}
        turns = 0
        usage: dict[str, int] = {}
        for t, ev in json_lines(lines):
            typ = ev.get("type", "")
            pe = self.provider_error(ev)
            if pe:
                st.provider_errors.append(pe)
            item = ev.get("item") or {}
            if typ == "item.completed" and item.get("type") == "web_search":
                # Server-side web search (OpenAI's tool): invisible to the sandbox, and a rule breach.
                st.violations.append(f"web search: {str(item.get('query') or item.get('action') or '')[:120]}")
            if typ == "item.started" and item.get("type") == "command_execution":
                starts[item.get("id", str(t))] = t
            elif typ == "item.completed":
                if item.get("type") == "command_execution":
                    ends[item.get("id", "")] = t
                elif item.get("type") == "agent_message":
                    st.final_message = item.get("text")
            elif typ == "turn.completed":
                turns += 1
                for k, v in (ev.get("usage") or {}).items():
                    if isinstance(v, int):
                        usage[k] = usage.get(k, 0) + v
            elif typ in ("turn.failed", "error"):
                st.error = str(ev.get("error") or ev.get("message") or ev)[:500]
        st.tool_intervals = pair_intervals(starts, ends)
        st.turns = turns or None
        st.usage = usage or None
        return st
