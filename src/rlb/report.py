"""Aggregate attempt.json records into tables."""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

TIERS = ("easy", "medium", "hard", "vhard", "custom", "putnam", "imo", "aime")


def _tier_key(t: str):
    return (TIERS.index(t), "") if t in TIERS else (len(TIERS), t)


from .runner import load_attempts  # noqa: E402  (attempts are reinterpreted on load; see runner.reinterpret)


def _med(xs) -> float | None:
    return statistics.median(xs) if xs else None


def _fmt(x: float | None, unit: str = "", digits: int = 0) -> str:
    return "-" if x is None else f"{x:.{digits}f}{unit}"


def tokens(usage: dict | None) -> tuple[int, int]:
    """(input incl. cache, output) across the three harnesses' usage schemas."""
    u = usage or {}
    tin = (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)  # claude
           + u.get("input", 0) + u.get("cacheRead", 0) + u.get("cacheWrite", 0))  # pi
    tout = u.get("output_tokens", 0) + u.get("output", 0)
    return int(tin), int(tout)


def summarize(attempts: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for a in attempts:
        groups[(a["config"]["name"], a["tier"])].append(a)
        groups[(a["config"]["name"], "all")].append(a)
    rows = []
    for (cfg, tier), xs in sorted(groups.items(), key=lambda kv: (kv[0][0], (len(TIERS) + 1, "") if kv[0][1] == "all" else _tier_key(kv[0][1]))):
        errs = [a for a in xs if a.get("invalid")]
        xs = [a for a in xs if not a.get("invalid")]
        solved = [a for a in xs if a["solved"]]
        if not xs:
            rows.append({"config": cfg, "tier": tier, "n": 0, "solved": 0, "rate": None, "timed_out": 0, "invalid": len(errs),
                         "med_wall_s": None, "med_wall_solved_s": None, "med_prover_s": None, "med_inference_s": None, "med_tools_s": None,
                         "med_prover_calls": None, "prover_frac": None, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0})
            continue
        # Proxy usage (uniform across providers) when every attempt has it; else the harness's own.
        if all(a.get("net", {}).get("source") == "proxy" and a["net"].get("tokens_in") for a in xs):
            tok_in = sum(a["net"]["tokens_in"] + a["net"].get("tokens_cached", 0) for a in xs)
            tok_out = sum(a["net"]["tokens_out"] for a in xs)
        else:
            tok_in = sum(tokens(a["harness"]["usage"])[0] for a in xs)
            tok_out = sum(tokens(a["harness"]["usage"])[1] for a in xs)
        rows.append({
            "config": cfg, "tier": tier, "n": len(xs), "solved": len(solved),
            "rate": len(solved) / len(xs), "timed_out": sum(a["timed_out"] for a in xs), "invalid": len(errs),
            "med_wall_s": _med([a["wall_s"] for a in xs]),
            "med_wall_solved_s": _med([a["wall_s"] for a in solved]),
            "med_prover_s": _med([a["prover"]["busy_s"] for a in xs]),
            "med_inference_s": _med([a["inference_s"] for a in xs]),
            "med_tools_s": _med([a["tools_busy_s"] for a in xs if a["tools_busy_s"] is not None]),
            "med_prover_calls": _med([a["prover"]["calls"] for a in xs]),
            "prover_frac": (sum(a["prover"]["busy_s"] for a in xs) / sum(a["wall_s"] for a in xs)) if xs else None,
            "tokens_in": tok_in, "tokens_out": tok_out,
            "cost_usd": sum(a["harness"]["cost_usd"] or 0 for a in xs),
        })
    return rows


def format_summary(rows: list[dict]) -> str:
    hdr = ["config", "tier", "solved", "timeouts", "med wall", "med wall(solved)", "med prover", "med infer", "med tools", "prover%", "med calls", "tok in/out", "cost$"]
    lines = ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
    for r in rows:
        lines.append("| " + " | ".join([
            r["config"], r["tier"], f"{r['solved']}/{r['n']}", str(r["timed_out"]),
            _fmt(r["med_wall_s"], "s"), _fmt(r["med_wall_solved_s"], "s"), _fmt(r["med_prover_s"], "s", 1),
            _fmt(r["med_inference_s"], "s"), _fmt(r["med_tools_s"], "s"), _fmt(None if r["prover_frac"] is None else 100 * r["prover_frac"], "%"), _fmt(r["med_prover_calls"]),
            f"{r['tokens_in'] / 1000:.0f}k/{r['tokens_out'] / 1000:.0f}k", f"{r['cost_usd']:.2f}",
        ]) + " |")
    return "\n".join(lines)


def mixed_distributions(attempts: list[dict]) -> list[str]:
    """(config, problem) cells whose valid samples carry different inputs
    hashes: they were not drawn from one distribution (prompt, config, tool
    version or timeout changed between invocations)."""
    seen: dict[tuple[str, str], set] = defaultdict(set)
    for a in attempts:
        if a.get("invalid") or not a.get("inputs_hash"):
            continue
        seen[(a["config"]["name"], a["problem"])].add(a["inputs_hash"])
    return [f"{c}/{p}: {len(h)} distributions" for (c, p), h in sorted(seen.items()) if len(h) > 1]


def format_matrix(attempts: list[dict]) -> str:
    """Problems x configs: wall time of the (first) attempt, marked by outcome."""
    cfgs = sorted({a["config"]["name"] for a in attempts})
    probs = sorted({(a["tier"], a["problem"]) for a in attempts}, key=lambda tp: (_tier_key(tp[0]), tp[1]))
    cell: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for a in attempts:
        cell[(a["problem"], a["config"]["name"])].append(a)
    lines = ["| problem | " + " | ".join(cfgs) + " |", "|---|" + "---|" * len(cfgs)]
    for tier, p in probs:
        row = [f"{tier[0]}:{p.removeprefix('lean_workbook_')}"]
        for c in cfgs:
            xs = cell.get((p, c))
            if not xs:
                row.append("")
                continue
            marks = "".join(("!" if a.get("invalid") else "✓" if a["solved"] else "✗") for a in xs)
            row.append(f"{marks} {_med([a['wall_s'] for a in xs]):.0f}s")
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)
