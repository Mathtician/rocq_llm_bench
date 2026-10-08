"""Run a sweep through the ledger and keep resuming it until every (config, problem) has a
valid sample or the attempts stop failing for provider reasons.

Each pass is one `rlb log run ... -- uv run rlb run ...` (its own ledger entry and commits).
After a pass, the run's attempts are reinterpreted with the runner's own rules: a problem whose
latest attempt is invalid (provider refusal such as a usage limit, a machine suspend, a dead
sandbox network) is redone by the next pass, which the runner does on its own since it skips
only problems with a valid sample. A valid failure (timeout, wrong proof) is a real sample and
is not retried.

Between passes the script waits for the provider: if the refusal text names a reset time
("resets at 3pm", "try again at 14:30", "Resets in 2h26m") it sleeps until then plus a margin,
otherwise a default interval. Run it from the dev shell so the sandbox tools are on PATH:

    nix develop ./nix -c uv run python scripts/sweep_retry.py --run-id fable-low-sweep-1 \
        -c configs/claude-fable-low.toml --tier easy --tier custom --tier hard --tier vhard --tier putnam \
        --note "Fable 5.1 low effort on every tier"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rlb.runner import load_attempts  # noqa: E402

QUOTA_RE = re.compile(r"\b429\b|usage limit|session limit|quota|rate.?limit|overloaded|capacity", re.I)


def reset_delay_s(text: str, now: dt.datetime) -> float | None:
    """Seconds until the reset named in a refusal message, or None if it names none."""
    m = re.search(r"resets? in\s*(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?", text, re.I)
    if m and any(m.groups()):
        h, mi, s = (int(g or 0) for g in m.groups())
        return h * 3600 + mi * 60 + s
    # "resets 12am (America/Chicago)", "resets at 3pm", "try again at 14:30"
    m = re.search(r"(?:resets?|try again|available)\s+(?:at\s+|after\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s*\(([A-Za-z_]+/[A-Za-z_]+)\))?", text, re.I)
    if m:
        hour, minute, ampm, tzname = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower(), m.group(4)
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        if tzname:
            try:
                from zoneinfo import ZoneInfo
                now = now.astimezone(ZoneInfo(tzname)) if now.tzinfo else now.replace(tzinfo=dt.datetime.now().astimezone().tzinfo).astimezone(ZoneInfo(tzname))
            except Exception:  # noqa: BLE001 - unknown zone: fall back to local time
                pass
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += dt.timedelta(days=1)
        return (target - now).total_seconds()
    return None


def tier_problems(tiers: list[str]) -> set[str]:
    """Every problem the run should cover (problems/manifest.json), so that problems the runner
    never reached (a crash mid-pass, e.g. a full disk) count as pending too."""
    manifest = json.loads((ROOT / "problems" / "manifest.json").read_text())
    return {p["name"] for p in manifest["problems"] if p["tier"] in tiers}


def pending(run_dir: Path, config: str, expected: set[str]) -> tuple[list[str], list[str]]:
    """Problems without a valid sample, split into (provider-refused, other-invalid-or-unattempted)."""
    latest: dict[str, dict] = {}
    for a in load_attempts([run_dir]):
        if a["config"]["name"] != config:
            continue
        if a["problem"] not in latest or a["rep"] > latest[a["problem"]]["rep"]:
            latest[a["problem"]] = a
    has_valid = {a["problem"] for a in load_attempts([run_dir]) if a["config"]["name"] == config and a["invalid"] is None}
    refused, other = [], []
    for q in sorted(expected | set(latest)):
        if q in has_valid:
            continue
        a = latest.get(q)
        (refused if a and QUOTA_RE.search(a["invalid"] or "") else other).append(q)
    return refused, other


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("-c", "--config", required=True)
    ap.add_argument("--tier", action="append", required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--max-passes", type=int, default=12)
    ap.add_argument("--default-wait-min", type=float, default=30)
    ap.add_argument("--margin-min", type=float, default=3)
    a = ap.parse_args()
    cfg_name = Path(a.config).stem
    run_dir = ROOT / "results" / a.run_id
    tiers = [x for t in a.tier for x in ("--tier", t)]
    expected = tier_problems(a.tier)

    for n in range(1, a.max_passes + 1):
        note = a.note + (f" (pass {n}: resume after provider refusals)" if n > 1 else "")
        cmd = ["uv", "run", "rlb", "log", "run", "--note", note, "--",
               "uv", "run", "rlb", "run", *tiers, "--jobs", str(a.jobs), "--run-id", a.run_id, "-c", a.config]
        print(f"[sweep_retry] pass {n}: {' '.join(cmd)}", flush=True)
        rc = subprocess.run(cmd, cwd=ROOT).returncode
        if rc != 0:
            print(f"[sweep_retry] rlb exited {rc}; the pass is incomplete, checking what is pending", flush=True)
        refused, other = pending(run_dir, cfg_name, expected)
        if not refused and not other:
            print("[sweep_retry] every problem has a valid sample; done", flush=True)
            return
        print(f"[sweep_retry] pending after pass {n}: {len(refused)} provider-refused, {len(other)} other invalid", flush=True)
        # find the most informative refusal text for a reset time
        texts = [x["invalid"] for x in load_attempts([run_dir]) if x["config"]["name"] == cfg_name and x["invalid"]]
        now = dt.datetime.now()
        delays = [d for d in (reset_delay_s(t, now) for t in texts) if d is not None]
        wait = (max(delays) + a.margin_min * 60) if delays else a.default_wait_min * 60
        if not refused:  # only suspend/network invalids: retry soon, nothing to wait for on the provider side
            wait = min(wait, 120)
        until = (now + dt.timedelta(seconds=wait)).strftime("%H:%M:%S")
        print(f"[sweep_retry] waiting {wait / 60:.0f} min (until {until}); refusal text: {texts[-1][:120] if texts else '-'}", flush=True)
        time.sleep(wait)
    print("[sweep_retry] max passes reached", flush=True)
    sys.exit(2)


if __name__ == "__main__":
    main()
