"""Shared timeline: one horizontal bar per attempt, segmented by what the
attempt was doing at each instant. Self-contained HTML with inline SVG.

Instant classification, highest precedence first:
  prover   some Rocq binary is running (shim trace)
  model    a request to an API host is outstanding; split at the first
           response byte into "waiting" (time to first token) and "streaming"
  tool     the harness reports a tool execution (event stream) that is not
           already prover/model time
  other    everything else: harness bookkeeping, startup, non-API traffic
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path

from .runner import reinterpret
from .shim import parse_trace

# Category order is the legend order and the precedence order.
CATEGORIES = ("prover", "model_wait", "model_stream", "tool", "other")
LABELS = {
    "prover": "Rocq prover",
    "model_wait": "model: waiting for first token",
    "model_stream": "model: streaming response",
    "tool": "other tool execution",
    "other": "harness / startup / other",
}
PRECEDENCE = {"prover": 0, "model_wait": 1, "model_stream": 1, "tool": 2, "other": 3}


@dataclass
class Segment:
    start: float  # seconds from attempt start
    end: float
    cat: str


@dataclass
class Row:
    label: str  # config name
    problem: str
    sub: str  # problem, rep
    solved: bool
    timed_out: bool
    wall: float
    segments: list[Segment]
    totals: dict[str, float]
    api_calls: int
    harness_inference: float | None
    net_other: list[tuple[float, float, str]]  # non-API TLS calls (start, end, host), shown as ticks


def _intervals(att: dict, attempt_dir: Path) -> list[tuple[float, float, str]]:
    t0 = att["started_at"]
    out = []
    for c in parse_trace(attempt_dir / "trace.tsv"):
        out.append((c.start - t0, c.end - t0, "prover"))
    for c in att["api_calls"]:
        if not _is_api(c, att):
            continue
        s, e = c["start"] - t0, c["end"] - t0
        if c["first"] is None:
            out.append((s, max(e, s), "model_wait"))
        else:
            f = c["first"] - t0
            out.append((s, f, "model_wait"))
            out.append((f, e, "model_stream"))
    for s, e in att["harness"].get("tool_intervals") or []:
        out.append((s - t0, e - t0, "tool"))
    return [(s, e, k) for s, e, k in out if e > s]


def _is_api(call: dict, att: dict) -> bool:
    return call["host"] in att["_api_hosts"]


def _segments(ivs: list[tuple[float, float, str]], wall: float) -> list[Segment]:
    cuts = sorted({0.0, wall, *(s for s, _, _ in ivs), *(e for _, e, _ in ivs)})
    cuts = [c for c in cuts if 0.0 <= c <= wall]
    segs: list[Segment] = []
    for a, b in zip(cuts, cuts[1:]):
        active = [k for s, e, k in ivs if s <= a and e >= b]
        cat = min(active, key=lambda k: PRECEDENCE[k]) if active else "other"
        if segs and segs[-1].cat == cat and abs(segs[-1].end - a) < 1e-9:
            segs[-1].end = b
        else:
            segs.append(Segment(a, b, cat))
    return segs


def load_rows(run_dirs: list[Path], invocation: str | None = None) -> list[Row]:
    rows = []
    for run in run_dirs:
        for rec in sorted(run.glob("*/*/r*/attempt.json")):
            att = reinterpret(json.loads(rec.read_text()), rec.parent)
            if invocation is not None and att.get("invocation") != invocation:
                continue
            if att.get("schema") != "rlb.attempt/2" or att.get("invalid"):
                continue  # pre-capture attempts have no network timeline; provider refusals are not attempts
            att["_api_hosts"] = _api_hosts_of(att)
            ivs = _intervals(att, rec.parent)
            segs = _segments(ivs, att["wall_s"])
            totals = {k: 0.0 for k in CATEGORIES}
            for s in segs:
                totals[s.cat] += s.end - s.start
            t0 = att["started_at"]
            rows.append(Row(
                label=att["config"]["name"], problem=att["problem"], sub=f"{att['problem']} r{att['rep']}",
                solved=att["solved"], timed_out=att["timed_out"], wall=att["wall_s"], segments=segs, totals=totals,
                api_calls=att["net"]["api_calls"], harness_inference=att["harness"].get("inference_s"),
                net_other=[(c["start"] - t0, c["end"] - t0, c["host"]) for c in att["api_calls"] if c["host"] not in att["_api_hosts"]],
            ))
    return rows


def _api_hosts_of(att: dict) -> set[str]:
    from .config import config_from_record
    from .harness import HARNESSES
    cfg = config_from_record(att["config"])
    return set(HARNESSES[cfg.harness].api_hosts(cfg))


# --- rendering ---------------------------------------------------------------

_FILL = {
    "prover": "var(--c-prover)",
    "model_wait": "url(#hatch)",
    "model_stream": "var(--c-model)",
    "tool": "var(--c-tool)",
    "other": "var(--track)",
}


def _fmt(s: float) -> str:
    return f"{s:.1f}s" if s < 100 else f"{s:.0f}s"


def _sort_key(r: Row):
    """Fastest to slowest; solved attempts before failures (a fast failure is not fast)."""
    return (0 if r.solved else 1, r.wall)


def _render_svg(rows: list[Row], svg_id: str) -> str:
    tmax = max(r.wall for r in rows)
    label_w, plot_w, row_h, bar_h = 300, 900, 44, 22
    width = label_w + plot_w + 24
    height = 40 + row_h * len(rows) + 8
    x = lambda t: label_w + t / tmax * plot_w

    # axis ticks: a round step giving 6-10 ticks
    step = next(s for s in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900) if tmax / s <= 10)
    ticks = [t for t in range(0, int(tmax) + step, step) if t <= tmax]

    svg = [f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="attempt timelines">']
    svg.append(f'<defs><pattern id="hatch-{svg_id}" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
               '<rect width="6" height="6" fill="var(--c-model-soft)"/><line x1="0" y1="0" x2="0" y2="6" stroke="var(--c-model)" stroke-width="2"/></pattern></defs>')
    for t in ticks:
        svg.append(f'<line class="grid" x1="{x(t):.1f}" y1="30" x2="{x(t):.1f}" y2="{height - 8}"/>')
        svg.append(f'<text class="tick" x="{x(t):.1f}" y="22" text-anchor="middle">{t}s</text>')
    for i, r in enumerate(rows):
        y = 40 + i * row_h
        cy = y + row_h / 2
        badge = "timeout" if r.timed_out else ("solved" if r.solved else "failed")
        svg.append(f'<text class="label" x="12" y="{cy - 3:.1f}">{html.escape(r.label)}</text>')
        svg.append(f'<text class="sublabel" x="12" y="{cy + 12:.1f}">{html.escape(r.sub)} · <tspan class="b-{badge}">{badge}</tspan> · {_fmt(r.wall)}</text>')
        svg.append(f'<rect class="track" x="{label_w}" y="{cy - bar_h / 2:.1f}" width="{plot_w}" height="{bar_h}" rx="3"/>')
        for s in r.segments:
            if s.cat == "other":
                continue
            w = max(x(s.end) - x(s.start), 0.5)
            tip = f"{LABELS[s.cat]}: {s.start:.2f}s – {s.end:.2f}s ({s.end - s.start:.2f}s)"
            fill = f"url(#hatch-{svg_id})" if s.cat == "model_wait" else _FILL[s.cat]
            svg.append(f'<rect class="seg" data-tip="{html.escape(tip)}" x="{x(s.start):.2f}" y="{cy - bar_h / 2:.1f}" '
                       f'width="{w:.2f}" height="{bar_h}" fill="{fill}"/>')
        for s, e, host in r.net_other:
            tip = f"{host}: {s:.2f}s – {e:.2f}s"
            svg.append(f'<rect class="tickmark" data-tip="{html.escape(tip)}" x="{x(s):.2f}" y="{cy + bar_h / 2 + 2:.1f}" width="{max(x(e) - x(s), 1.5):.2f}" height="4"/>')
        svg.append(f'<rect class="wall" x="{x(r.wall):.2f}" y="{cy - bar_h / 2 - 3:.1f}" width="1.5" height="{bar_h + 6}"/>')
    svg.append("</svg>")
    return "".join(svg)


def _render_table(rows: list[Row]) -> str:
    head = "".join(f"<th>{h}</th>" for h in ("config", "attempt", "result", "wall", "model", "of which waiting", "prover", "other tools", "other", "API calls", "harness's own model time"))
    body = []
    for r in rows:
        model = r.totals["model_wait"] + r.totals["model_stream"]
        badge = "timeout" if r.timed_out else ("solved" if r.solved else "failed")
        body.append("<tr>" + "".join(f"<td>{c}</td>" for c in (
            html.escape(r.label), html.escape(r.sub), f'<span class="b-{badge}">{badge}</span>',
            _fmt(r.wall), _fmt(model), _fmt(r.totals["model_wait"]), _fmt(r.totals["prover"]), _fmt(r.totals["tool"]),
            _fmt(r.totals["other"]), str(r.api_calls), _fmt(r.harness_inference) if r.harness_inference is not None else "—",
        )) + "</tr>")
    return f'<table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def render_html(rows: list[Row], title: str) -> str:
    """One tab per problem; within a tab, attempts fastest to slowest."""
    if not rows:
        raise SystemExit("no attempts with a network capture (schema rlb.attempt/2) in the given runs")
    problems = sorted({r.problem for r in rows})
    tabs, panels = [], []
    for i, prob in enumerate(problems):
        prows = sorted((r for r in rows if r.problem == prob), key=_sort_key)
        solved = sum(r.solved for r in prows)
        short = prob.removeprefix("lean_workbook_")
        tabs.append(f'<button class="tab" role="tab" data-tab="{i}" aria-selected="{"true" if i == 0 else "false"}">'
                    f'{html.escape(short)} <span class="tabcount">{solved}/{len(prows)}</span></button>')
        panels.append(f'<section class="tabpanel" role="tabpanel" data-tab="{i}"{"" if i == 0 else " hidden"}>'
                      f'<h2>{html.escape(prob)} <span class="muted">· {solved} of {len(prows)} solved · fastest first</span></h2>'
                      f'<div class="panel">{_render_svg(prows, str(i))}</div><div class="wrap">{_render_table(prows)}</div></section>')
    legend = "".join(
        f'<span class="key"><i style="background:{_swatch(k)}"></i>{LABELS[k]}</span>' for k in CATEGORIES
    ) + '<span class="key"><i class="tickmark-key"></i>non-API traffic (below bar)</span>'
    return (_TEMPLATE.replace("%TITLE%", html.escape(title)).replace("%LEGEND%", legend)
            .replace("%TABS%", "".join(tabs)).replace("%PANELS%", "".join(panels)))


def _swatch(k: str) -> str:
    return {"prover": "var(--c-prover)", "model_wait": "repeating-linear-gradient(45deg,var(--c-model) 0 2px,var(--c-model-soft) 2px 6px)",
            "model_stream": "var(--c-model)", "tool": "var(--c-tool)", "other": "var(--track)"}[k]


_TEMPLATE = """<title>%TITLE%</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root {
  color-scheme: light;
  --bg: #f7f8fa; --panel: #ffffff; --ink: #14171c; --ink-2: #4f5661; --ink-3: #7c8491;
  --track: #e6e9ee; --grid: #dfe3e9; --line: #cfd4dc;
  --c-model: #2a78d6; --c-model-soft: #d6e5f8; --c-prover: #eb6834; --c-tool: #1baf7a;
  --good: #1f7a3a; --bad: #b3261e; --warn: #8a5a00;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #15171b; --panel: #1d2026; --ink: #eef0f3; --ink-2: #b5bcc7; --ink-3: #8a929e;
    --track: #2b3039; --grid: #2e333c; --line: #3a404a;
    --c-model: #3987e5; --c-model-soft: #26364d; --c-prover: #d95926; --c-tool: #199e70;
    --good: #4cc07a; --bad: #f0706a; --warn: #e0a640;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #15171b; --panel: #1d2026; --ink: #eef0f3; --ink-2: #b5bcc7; --ink-3: #8a929e;
  --track: #2b3039; --grid: #2e333c; --line: #3a404a;
  --c-model: #3987e5; --c-model-soft: #26364d; --c-prover: #d95926; --c-tool: #199e70;
  --good: #4cc07a; --bad: #f0706a; --warn: #e0a640;
}
body { background: var(--bg); color: var(--ink); font: 14px/1.5 "IBM Plex Sans", system-ui, sans-serif; margin: 0; padding: 32px 28px 48px; }
h1 { font-size: 22px; font-weight: 600; margin: 0 0 4px; letter-spacing: -0.01em; text-wrap: balance; }
p.lede { color: var(--ink-2); margin: 0 0 20px; max-width: 68ch; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 20px; margin: 0 0 14px; font-size: 13px; color: var(--ink-2); }
.key { display: inline-flex; align-items: center; gap: 7px; }
.key i { width: 14px; height: 14px; border-radius: 2px; display: inline-block; }
.key i.tickmark-key { height: 4px; background: var(--ink-3); border-radius: 1px; }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 12px 8px 8px; overflow-x: auto; }
svg { display: block; max-width: 100%; height: auto; }
.grid { stroke: var(--grid); stroke-width: 1; }
.tick { fill: var(--ink-3); font: 11px "IBM Plex Mono", ui-monospace, monospace; }
.label { fill: var(--ink); font: 500 13px "IBM Plex Sans", system-ui, sans-serif; }
.sublabel { fill: var(--ink-3); font: 11px "IBM Plex Mono", ui-monospace, monospace; }
.track { fill: var(--track); }
.seg { stroke: var(--panel); stroke-width: 1; }
.seg:hover, .tickmark:hover { filter: brightness(1.12); }
.tickmark { fill: var(--ink-3); }
.wall { fill: var(--ink-2); }
.b-solved { fill: var(--good); color: var(--good); font-weight: 500; }
.b-failed { fill: var(--bad); color: var(--bad); font-weight: 500; }
.b-timeout { fill: var(--warn); color: var(--warn); font-weight: 500; }
#tip { position: fixed; pointer-events: none; background: var(--ink); color: var(--bg); padding: 5px 8px; border-radius: 4px; font: 12px "IBM Plex Mono", ui-monospace, monospace; white-space: nowrap; z-index: 2; }
table { border-collapse: collapse; margin-top: 22px; font-size: 13px; width: 100%; }
th, td { text-align: right; padding: 6px 10px; border-bottom: 1px solid var(--line); font-variant-numeric: tabular-nums; white-space: nowrap; }
th { color: var(--ink-3); font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; }
td:nth-child(-n+3), th:nth-child(-n+3) { text-align: left; }
td:nth-child(2) { font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 12px; color: var(--ink-2); }
.wrap { overflow-x: auto; }
p.note { color: var(--ink-3); font-size: 12px; max-width: 80ch; margin-top: 14px; }
.tabs { display: flex; flex-wrap: wrap; gap: 4px; border-bottom: 1px solid var(--line); margin: 0 0 16px; }
.tab { font: 500 13px "IBM Plex Mono", ui-monospace, monospace; color: var(--ink-2); background: none; border: 0; border-bottom: 2px solid transparent; padding: 8px 10px; cursor: pointer; margin-bottom: -1px; }
.tab:hover { color: var(--ink); }
.tab[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--c-model); }
.tab:focus-visible { outline: 2px solid var(--c-model); outline-offset: -2px; border-radius: 3px; }
.tabcount { color: var(--ink-3); font-weight: 400; margin-left: 4px; }
h2 { font-size: 15px; font-weight: 600; margin: 0 0 10px; }
h2 .muted { color: var(--ink-3); font-weight: 400; font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 12px; }
@media (prefers-reduced-motion: no-preference) { .seg { transition: filter 80ms; } }
</style>
<h1>%TITLE%</h1>
<p class="lede">Where each attempt's wall-clock time went. Model time comes from the packet capture (request sent to last response byte), prover time from the PATH shims, tool time from the harness's event stream. Precedence when they overlap: prover, model, tool.</p>
<div class="legend">%LEGEND%</div>
<nav class="tabs" role="tablist">%TABS%</nav>
%PANELS%
<p class="note">"Other" is wall time not covered by any interval: process startup, context assembly, JSON I/O, and any API traffic the capture could not attribute. Hover a segment for its exact interval. The last column is what the harness itself reports (Claude's <code>duration_api_ms</code>), for comparison with the capture.</p>
<div id="tip" hidden></div>
<script>
(function(){
  const tabs = document.querySelectorAll('.tab'), panels = document.querySelectorAll('.tabpanel');
  function show(i) {
    tabs.forEach(t => t.setAttribute('aria-selected', t.dataset.tab === i ? 'true' : 'false'));
    panels.forEach(p => { p.hidden = p.dataset.tab !== i; });
    try { localStorage.setItem('rlb-gantt-tab', i); } catch (e) {}
  }
  tabs.forEach(t => t.addEventListener('click', () => show(t.dataset.tab)));
  try { const saved = localStorage.getItem('rlb-gantt-tab'); if (saved !== null && document.querySelector('.tab[data-tab="' + saved + '"]')) show(saved); } catch (e) {}
  const tip = document.getElementById('tip');
  document.querySelectorAll('[data-tip]').forEach(el => {
    el.addEventListener('mousemove', e => { tip.textContent = el.dataset.tip; tip.hidden = false; tip.style.left = (e.clientX + 14) + 'px'; tip.style.top = (e.clientY + 14) + 'px'; });
    el.addEventListener('mouseleave', () => { tip.hidden = true; });
  });
})();
</script>
"""
