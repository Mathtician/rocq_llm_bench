from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Protocol

from ..config import Config

Line = tuple[float, str]  # (arrival epoch seconds, stdout line)


@dataclass
class Invocation:
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)  # added to the harness process's environment


@dataclass
class HarnessStats:
    """What the harness itself tells us about a run. Everything optional: a
    harness that reports nothing still gets timed from the outside."""
    inference_s: float | None = None  # harness-reported time spent waiting on the model
    tool_intervals: list[tuple[float, float]] | None = None  # epoch intervals of tool executions
    turns: int | None = None
    usage: dict | None = None
    cost_usd: float | None = None
    final_message: str | None = None
    error: str | None = None
    exit_reason: str | None = None
    provider_errors: list[str] = field(default_factory=list)  # inference refusals seen in the event stream (see is_provider_error)
    violations: list[str] = field(default_factory=list)  # rule breaches the harness can see (e.g. web tools): the attempt is invalid and NOT redone


# What makes an inference failure the provider's rather than the model's: quota,
# rate limits, billing, outages. A 400 (e.g. context overflow) is the agent's.
PROVIDER_ERROR_RE = re.compile(
    r"\b(429|402|403|412|5\d\d)\b|rate.?limit|usage limit|session limit|quota|suspended|billing|insufficient"
    r"|overloaded|capacity|payment|eligibility check failed|no such host|connection (refused|reset)|ECONNRE"
    r"|ActionRequiredError|plans? can only use",
    re.I,
)


def is_provider_error(text: str | None) -> bool:
    return bool(text) and PROVIDER_ERROR_RE.search(text) is not None


class Harness(Protocol):
    name: str
    state_paths: tuple[str, ...]  # HOME-relative paths the CLI needs read-write (auth, sessions); all else is hidden
    aux_hosts: tuple[str, ...]  # non-inference hosts the CLI must reach (auth, account checks); allowed, not timed
    passthrough_hosts: tuple[str, ...]  # allowed hosts whose TLS the proxy must not intercept (timed from the pcap instead)

    def api_hosts(self, cfg: Config) -> tuple[str, ...]:
        """TLS server names whose request/response intervals count as model
        inference (exact match). Overridable per config via `api_hosts`."""
        ...

    # Harness-native subagents are disabled (subagents are rlb's: `python3 lemma.py prove`), except
    # where the CLI cannot disable them (agy): then this is the paragraph that tells the model.
    native_subagents_prompt: str | None

    def unauthorized_agent_call(self, native_allowed: bool, attempt_dir: Path) -> str | None:
        """Evidence (from the attempt's stdout.txt or api.jsonl) of a native agent call that should
        have been impossible; the harness failed to block it, a sandbox failure. None if none."""
        ...

    def invocation(self, cfg: Config, workdir: Path, prompt: str) -> Invocation: ...

    def stats(self, lines: list[Line]) -> HarnessStats: ...

    def provider_error(self, ev: dict) -> str | None:
        """The refusal text if this event is the provider refusing an inference
        call (quota, rate limit, billing, outage); None otherwise. Used both by
        stats() and live, to stop waiting on a stalled agent."""
        ...


def grep_stdout(pattern: re.Pattern, attempt_dir: Path) -> str | None:
    out = attempt_dir / "stdout.txt"
    if not out.exists():
        return None
    for line in out.read_text(errors="replace").splitlines():
        m = pattern.search(line)
        if m:
            return m.group(0)[:80]
    return None


def json_lines(lines: list[Line]) -> Iterator[tuple[float, dict]]:
    for t, l in lines:
        l = l.strip()
        if not l.startswith("{"):
            continue
        try:
            yield t, json.loads(l)
        except json.JSONDecodeError:
            continue


def pair_intervals(starts: dict[str, float], ends: dict[str, float]) -> list[tuple[float, float]]:
    return [(starts[k], ends[k]) for k in starts if k in ends]
