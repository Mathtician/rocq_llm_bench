"""A run configuration = (harness, model, prompt, harness-specific knobs, subagent)."""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import ROOT


@dataclass(frozen=True)
class Config:
    name: str
    harness: str  # claude | codex | pi | agy | cursor
    model: str
    # The config the main agent can hand lemmas to (`python3 lemma.py prove`, run by rlb as a
    # separate sandboxed attempt), or None: main agent only. Declared in every config file as
    # `subagent = "none"` or a config path; a subagent config's own subagent must be "none".
    # Harness-native subagents are off everywhere except agy, which cannot disable them (see
    # harness/agy.py): they are a property of the harness, not of the config.
    subagent: Config | None
    prompt: str = "prompts/default.md"  # relative to the project root
    timeout_s: int = 900
    env: dict[str, str] = field(default_factory=dict)  # extra env for the harness process
    args: dict = field(default_factory=dict)  # harness-specific; see harness/<name>.py
    api_hosts: list[str] | None = None  # TLS server names counted as inference; default per harness
    path: str = ""  # where this config was loaded from (provenance)

    def prompt_text(self) -> str:
        return (ROOT / self.prompt).read_text()

    def to_dict(self) -> dict:
        return asdict(self)


# A config must keep meaning the same model: aliases like "opus" silently moved from
# Opus 5 to Opus 5.5 between sweeps. Full ids carry a version number.
CLAUDE_PINNED_RE = re.compile(r"claude-[a-z]+-\d[\w.-]*")


def load_config(path: Path) -> Config:
    d = tomllib.loads(path.read_text())
    known = {"name", "harness", "model", "subagent", "prompt", "timeout_s", "env", "args", "api_hosts"}
    unknown = set(d) - known
    if unknown:
        raise SystemExit(f"{path}: unknown keys {sorted(unknown)}; harness-specific knobs go under [args]")
    if d.get("harness") == "claude" and not CLAUDE_PINNED_RE.fullmatch(d.get("model", "")):
        raise SystemExit(f"{path}: model {d.get('model')!r} is a moving alias; pin a full model id "
                         "(e.g. claude-opus-5-5) so the config keeps meaning the same model")
    if "subagent" not in d:
        raise SystemExit(f'{path}: declare subagent = "none" (main agent only) or the path of the subagents\' config')
    if d["subagent"] == "none":
        d["subagent"] = None
    else:
        sub = load_config(ROOT / d["subagent"])
        if sub.subagent is not None:
            raise SystemExit(f"{path}: subagent config {d['subagent']} must itself have subagent = \"none\" (depth 1)")
        d["subagent"] = sub
    return Config(path=str(path), **d)


def config_from_record(config: dict) -> Config:
    """A Config from a stored record (attempt.json, run.json). Records written before `subagent`
    existed carry `subagent_model` (native subagents; see native_subagents_allowed) or nothing."""
    d = {k: v for k, v in config.items() if k != "subagent_model"}
    sub = d.get("subagent")
    d["subagent"] = config_from_record(sub) if sub else None
    return Config(**d)


def native_subagents_allowed(config: dict) -> bool:
    """Whether a stored config's harness-native subagents were allowed. Always for agy (they
    cannot be disabled); for the native-subagent probe of 2026-09-23 (ledger #48), which recorded
    `subagent_model`; never otherwise."""
    return config["harness"] == "agy" or bool(config.get("subagent_model"))
