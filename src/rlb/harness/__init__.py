from .agy import AgyHarness
from .base import Harness, HarnessStats, Invocation, Line
from .claude import ClaudeHarness
from .codex import CodexHarness
from .cursor import CursorHarness
from .pi import PiHarness

HARNESSES: dict[str, Harness] = {h.name: h for h in (ClaudeHarness(), CodexHarness(), PiHarness(), AgyHarness(), CursorHarness())}

__all__ = ["HARNESSES", "Harness", "HarnessStats", "Invocation", "Line"]
