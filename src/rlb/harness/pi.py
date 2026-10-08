"""pi coding agent (`pi -p --mode json`): a customizable harness for models on
fast providers (Groq, Cerebras, Fireworks, ...). Keys come from the provider's
env var (GROQ_API_KEY, CEREBRAS_API_KEY, FIREWORKS_API_KEY, ...).

pi reports per-message usage and (for some providers) cost. Inference is
timed by the network capture; the provider's API host comes from
PROVIDER_HOSTS (set `api_hosts` in the config for a provider not listed).

[args] keys: provider, thinking (off|minimal|low|medium|high|xhigh|max),
tools (comma list), system_prompt, append_system_prompt, extra (raw CLI args).
"""
from __future__ import annotations

from pathlib import Path

from ..config import Config
from .base import HarnessStats, Invocation, Line, is_provider_error, json_lines, pair_intervals


PROVIDER_HOSTS = {
    "groq": ["api.groq.com"],
    "cerebras": ["api.cerebras.ai"],
    "fireworks": ["api.fireworks.ai"],
    "moonshotai": ["api.moonshot.ai"],
    "openai": ["api.openai.com"],
    "anthropic": ["api.anthropic.com"],
    "google": ["generativelanguage.googleapis.com"],
    "openrouter": ["openrouter.ai"],
    "sambanova": ["api.sambanova.ai"],
    "together": ["api.together.xyz"],
    "deepinfra": ["api.deepinfra.com"],
    "baseten": ["inference.baseten.co"],
}


class PiHarness:
    name = "pi"
    state_paths = (".pi",)
    aux_hosts = ()
    passthrough_hosts: tuple[str, ...] = ()
    native_subagents_prompt = None

    def unauthorized_agent_call(self, native_allowed: bool, attempt_dir: Path) -> str | None:
        return None  # no subagent tool

    def api_hosts(self, cfg: Config) -> tuple[str, ...]:
        if cfg.api_hosts:
            return tuple(cfg.api_hosts)
        provider = cfg.args.get("provider") or cfg.model.split("/")[0]
        if provider not in PROVIDER_HOSTS:
            raise SystemExit(f"{cfg.name}: no known API host for pi provider {provider!r}; set api_hosts in the config")
        return tuple(PROVIDER_HOSTS[provider])

    def invocation(self, cfg: Config, workdir: Path, prompt: str) -> Invocation:
        a = cfg.args
        argv = [
            "pi", "-p", "--mode", "json", "--no-session", "--no-context-files",
            "--no-extensions", "--no-skills", "--no-prompt-templates",
            "--model", cfg.model,
            "--tools", a.get("tools", "read,bash,edit,write,grep,find,ls"),
        ]
        if a.get("provider"):
            argv += ["--provider", a["provider"]]
        if a.get("thinking"):
            argv += ["--thinking", a["thinking"]]
        if a.get("system_prompt"):
            argv += ["--system-prompt", a["system_prompt"]]
        if a.get("append_system_prompt"):
            argv += ["--append-system-prompt", a["append_system_prompt"]]
        argv += list(a.get("extra", []))
        argv.append(prompt)
        return Invocation(argv)

    def provider_error(self, ev: dict) -> str | None:
        # An inference call that ended in error: message_end with stopReason "error" and the
        # provider's message (e.g. `429 "Rate limit exceeded"`, `412 {... suspended ...}`).
        if ev.get("type") == "message_end":
            msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
            if msg.get("role") == "assistant" and msg.get("stopReason") == "error":
                txt = str(msg.get("errorMessage") or "")
                return txt if is_provider_error(txt) else None
        return None

    def stats(self, lines: list[Line]) -> HarnessStats:
        st = HarnessStats()
        starts: dict[str, float] = {}
        ends: dict[str, float] = {}
        turns = 0
        usage: dict[str, float] = {}
        cost = 0.0
        have_cost = False
        for t, ev in json_lines(lines):
            typ = ev.get("type", "")
            pe = self.provider_error(ev)
            if pe:
                st.provider_errors.append(pe)
            if typ == "tool_execution_start":
                starts[ev.get("toolCallId", str(t))] = t
            elif typ == "tool_execution_end":
                ends[ev.get("toolCallId", "")] = t
            elif typ == "turn_end":
                turns += 1
            elif typ == "message_end":
                msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
                if msg.get("role") != "assistant":
                    continue
                u = msg.get("usage") or {}
                for k, v in u.items():
                    if isinstance(v, (int, float)):
                        usage[k] = usage.get(k, 0) + v
                c = u.get("cost") or {}
                if isinstance(c, dict) and "total" in c:
                    cost += c["total"]
                    have_cost = True
                texts = [b.get("text", "") for b in msg.get("content", []) if b.get("type") == "text"]
                if texts:
                    st.final_message = "\n".join(texts)
                if msg.get("stopReason") == "error":
                    st.error = str(msg.get("errorMessage"))[:500]
                st.exit_reason = msg.get("stopReason")
        st.tool_intervals = pair_intervals(starts, ends)
        st.turns = turns or None
        st.usage = usage or None
        st.cost_usd = cost if have_cost else None
        return st
