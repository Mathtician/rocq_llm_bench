"""Google Antigravity CLI (`agy -p --output-format stream-json`). Uses the
Google AI Pro login (OAuth token under ~/.gemini/antigravity-cli).

Model ids carry the effort level (`agy models`: gemini-3.8-flash-high, ...).
Inference goes to daily-cloudcode-pa.googleapis.com; the same host also
serves a ~2 s "checkpoint" call at the start of each run and a burst of small
config fetches, which the capture cannot tell apart from model calls. Expect
the network figure to run 1-3 s above the sum of `agent_response` steps.

Print mode denies every non-read tool unless permissions are bypassed;
neither a workspace-local settings file nor `--mode` changes that. So the
harness passes --dangerously-skip-permissions, the headless equivalent of
Claude's --allowedTools. The agent works in a throwaway directory.

Event stream: `step_update` events with step_type user_input | checkpoint |
agent_response (usage) | tool (state ACTIVE -> DONE/ERROR, duration_seconds),
then one `result` (status, response, error, duration_seconds, usage).

[args] keys: print_timeout (default: the config's timeout_s), extra (raw CLI args).
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import Config
from .base import HarnessStats, Invocation, Line, is_provider_error, json_lines, pair_intervals


# Tools that reach the internet through Google's servers: invisible to the sandbox's
# network allowlist. Using any of them breaks the "no looking things up" rule.
WEB_TOOLS = ("search_web", "read_url_content", "open_browser_url", "browser_subagent", "read_browser_page",
             "execute_browser_javascript", "click_browser_pixel", "browser_click_element", "browser_input")


class AgyHarness:
    name = "agy"
    state_paths = (".gemini",)
    # Startup "eligibility check": userinfo, then the account's profile picture (both observed;
    # the run aborts without them). oauth2: token refresh (expected).
    aux_hosts = ("www.googleapis.com", "lh3.googleusercontent.com", "oauth2.googleapis.com")
    passthrough_hosts: tuple[str, ...] = ()
    # manage_subagents survives every setting tried (disabledTools, --mode); its agents run the
    # main model. So they are always on, and the model is told.
    native_subagents_prompt = ("You may delegate work to subagents with the manage_subagents tool. They run the "
                               "same model as you and share this workspace. Whether and how to use them is up to you.")

    def unauthorized_agent_call(self, native_allowed: bool, attempt_dir: Path) -> str | None:
        return None  # native subagents cannot be disabled, so they are always allowed

    def api_hosts(self, cfg: Config) -> tuple[str, ...]:
        return tuple(cfg.api_hosts or ["daily-cloudcode-pa.googleapis.com"])

    def invocation(self, cfg: Config, workdir: Path, prompt: str) -> Invocation:
        a = cfg.args
        argv = [
            "agy", "-p", prompt, "--output-format", "stream-json",
            "--model", cfg.model,
            "--print-timeout", f"{a.get('print_timeout', cfg.timeout_s)}s",  # default is 5m, silently short
            "--disable-slash-commands",
            "--dangerously-skip-permissions",
            # Without this, run_command executes in ~/.gemini/antigravity-cli/scratch, not the
            # workspace; the agent then cannot find its file and goes looking across the filesystem.
            "--add-dir", str(workdir),
        ]
        argv += list(a.get("extra", []))
        return Invocation(argv)

    def provider_error(self, ev: dict) -> str | None:
        # The CLI's final status is ERROR even on success (see module doc), so only the
        # pattern decides; the startup eligibility check counts (it blocks all inference).
        if ev.get("event") == "result":
            txt = str((ev.get("result") or {}).get("error") or "")
            return txt if is_provider_error(txt) else None
        return None

    def stats(self, lines: list[Line]) -> HarnessStats:
        st = HarnessStats()
        starts: dict[str, float] = {}
        ends: dict[str, float] = {}
        usage: dict[str, int] = {}
        turns = 0
        model_s = 0.0
        result = None
        for t, ev in json_lines(lines):
            pe = self.provider_error(ev)
            if pe:
                st.provider_errors.append(pe)
            if ev.get("event") == "step_update":
                su = ev["step_update"]
                key = str(su.get("step_index"))
                typ, state = su.get("step_type"), su.get("state")
                if typ == "tool":
                    if state == "ACTIVE" and su.get("tool_name") in WEB_TOOLS:
                        st.violations.append(f"web tool {su['tool_name']}: {json.dumps(su.get('tool_info', {}).get('parameters', {}))[:120]}")
                    if state == "ACTIVE":
                        starts[key] = t
                    elif state in ("DONE", "ERROR"):
                        ends[key] = t
                elif typ == "agent_response" and state == "DONE":
                    turns += 1
                    model_s += su.get("duration_seconds") or 0.0
                    for k, v in (su.get("usage") or {}).items():
                        if isinstance(v, int):
                            usage[k] = usage.get(k, 0) + v
            elif ev.get("event") == "result":
                result = ev["result"]
        st.tool_intervals = pair_intervals(starts, ends)
        st.turns = turns or None
        st.usage = usage or None
        st.inference_s = model_s if turns else None  # the CLI's own per-response timer, for comparison
        if result is None:
            st.error = "no result event (killed?)"
            return st
        st.usage = result.get("usage", st.usage)
        st.final_message = result.get("response") or st.final_message
        st.exit_reason = result.get("status")
        if result.get("status") != "SUCCESS":
            st.error = f"{result.get('status')}: {str(result.get('error'))[:500]}"
        return st
