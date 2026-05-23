#!/usr/bin/env python3
"""Inject BRIEF:* blocks into index.html and brief.html.

Most of the calendar is rendered client-side from data/*.json fetched at page load.
This script only updates a small set of HTML blocks: LAST_UPDATED, DATA_VERSION,
TODAY_HUMAN, TOP_OVERLAPS (server-rendered top-5 cards for fast first paint).

Marker-balance sanity check enforced at end.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

PAGES = ("index.html", "brief.html")

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def humanize_date(dt: datetime) -> str:
    return f"{dt.day} {MONTHS[dt.month - 1]} {dt.year}"


def replace_block(html: str, key: str, content: str) -> tuple[str, int]:
    pattern = re.compile(
        rf"(<!-- BRIEF:{re.escape(key)}_START -->)(.*?)(<!-- BRIEF:{re.escape(key)}_END -->)",
        re.DOTALL,
    )
    inner = "\n" + content.strip() + "\n"
    return pattern.subn(lambda m: m.group(1) + inner + m.group(3), html)


AXIS_LABEL = {"region": "geographic area", "industry": "industry sector", "commodity": "commodity flow", "chokepoint": "transit chokepoint"}
AXIS_GLOSS = {
    "region": "Multiple risks stacking in the same geographic area in the same time window. Watch for cascading logistics impact.",
    "industry": "An industry sector exposed from multiple directions at once. Buyers in this sector should expect supplier strain.",
    "commodity": "A single commodity flow under compound pressure. Spot prices typically move first; physical availability follows.",
    "chokepoint": "A maritime transit chokepoint with active disruption. By Theory-of-Constraints logic, anything affecting the chokepoint affects all flow through it.",
}


def render_top_overlaps(clusters: list[dict], names: dict[str, dict[str, str]]) -> str:
    surfaced = [c for c in clusters if c["convergence_score"] >= 5.5][:5]
    if not surfaced:
        return '<p class="empty">No convergence clusters above surface threshold today.</p>'
    parts: list[str] = []
    for c in surfaced:
        axis = c["axis"]
        axis_label = html_lib.escape(AXIS_LABEL.get(axis, axis))
        display = html_lib.escape(names.get(axis, {}).get(c["axis_value"], c["axis_value"]))
        gloss = html_lib.escape(AXIS_GLOSS.get(axis, ""))
        score = f"{c['convergence_score']:.1f}"
        window = f"{c['time_window'][0]} → {c['time_window'][1]}"
        n_members = len(c["member_event_ids"])
        seed = html_lib.escape(c.get("narrative_seed") or "(narrative pending)")
        parts.append(
            f'<article class="cluster-card" data-cluster-id="{html_lib.escape(c["id"])}">'
            f'<div class="cluster-head">'
            f'<span class="axis-label">{axis_label} · {display}</span>'
            f'<span class="score" title="Convergence score 0-10. Threshold for surfacing is 5.5.">{score}</span>'
            f'</div>'
            f'<p class="cluster-window">{window} · <strong>{n_members}</strong> band(s)</p>'
            f'<p class="cluster-meaning"><strong>What this means:</strong> {gloss}</p>'
            f'<p class="cluster-seed">{seed}</p>'
            f'<a class="cluster-link" href="brief.html#cluster-{html_lib.escape(c["id"])}">open in brief →</a>'
            f'</article>'
        )
    return "\n".join(parts)


def render_chokepoint_board(tiles: list[dict]) -> str:
    if not tiles:
        return '<p class="empty">No maritime chokepoints in vocabulary.</p>'
    parts = ['<p class="board-intro">Theory-of-Constraints view: a chokepoint <em>is</em> the constraint. Every maritime chokepoint is monitored individually — even a single touching event surfaces it here.</p>']
    parts.append('<div class="chokepoint-grid">')
    state_label = {"red": "Active disruption", "amber": "Watching", "green": "Clear"}
    for t in tiles:
        state = html_lib.escape(t["state"])
        name = html_lib.escape(t["name"])
        throughput = html_lib.escape(t.get("throughput_note", ""))
        exposure = html_lib.escape(t.get("exposure", ""))
        watch = html_lib.escape(t.get("what_to_watch", ""))
        label = html_lib.escape(state_label[t["state"]])
        parts.append(
            f'<article class="cp-tile cp-{state}">'
            f'<header class="cp-header"><span class="cp-pip"></span><h3>{name}</h3><span class="cp-state-label">{label}</span></header>'
            f'<p class="cp-throughput">{throughput}</p>'
            f'<p class="cp-exposure"><strong>Exposure:</strong> {exposure}</p>'
            f'<p class="cp-watch"><strong>What to watch:</strong> {watch}</p>'
            f'</article>'
        )
    parts.append('</div>')
    return "\n".join(parts)


def render_today_glance(executive: dict) -> str:
    if not executive:
        return '<p class="empty">No summary yet — first daily run still pending.</p>'
    headline = html_lib.escape(executive.get("headline", ""))
    cp_phrase = html_lib.escape(executive.get("chokepoint_phrase", ""))
    kpis = executive.get("kpis", {})
    return (
        f'<p class="tg-headline">{headline}</p>'
        f'<p class="tg-chokepoint">{cp_phrase}</p>'
        f'<p class="tg-kpis">'
        f'{kpis.get("bands_tracked", 0)} bands tracked · '
        f'{kpis.get("clusters_detected", 0)} clusters detected · '
        f'{kpis.get("clusters_above_threshold", 0)} above threshold · '
        f'top score {kpis.get("top_score", 0):.1f}/10'
        f'</p>'
    )


def update_titles(s: str, date_human: str, prefix: str) -> str:
    return re.sub(
        rf"(<title>{re.escape(prefix)}).*?(</title>)",
        lambda m: m.group(1) + date_human + m.group(2),
        s, count=1,
    )


def main() -> int:
    now_utc = datetime.now(timezone.utc)
    today_iso = now_utc.date().isoformat()
    human_date = humanize_date(now_utc)
    last_updated = now_utc.strftime("%H:%M") + " UTC"

    overlaps = json.loads((DATA / "overlaps.json").read_text(encoding="utf-8"))
    regions = json.loads((DATA / "vocab" / "regions.json").read_text(encoding="utf-8"))["regions"]
    industries = json.loads((DATA / "vocab" / "industries.json").read_text(encoding="utf-8"))["industries"]
    commodities = json.loads((DATA / "vocab" / "commodities.json").read_text(encoding="utf-8"))["commodities"]
    chokepoints = json.loads((DATA / "vocab" / "chokepoints.json").read_text(encoding="utf-8"))["chokepoints"]
    seasonal = json.loads((DATA / "seasonal_bands.json").read_text(encoding="utf-8"))
    active = json.loads((DATA / "active_events.json").read_text(encoding="utf-8"))
    fm = json.loads((DATA / "fm_events.json").read_text(encoding="utf-8"))
    pattern_path = DATA / "pattern_bands.json"
    pattern_bands = json.loads(pattern_path.read_text(encoding="utf-8"))["bands"] if pattern_path.exists() else []

    names = {
        "region": {r["id"]: r["name"] for r in regions},
        "industry": {i["id"]: i["name"] for i in industries},
        "commodity": {c["id"]: c["name"] for c in commodities},
        "chokepoint": {c["id"]: c["name"] for c in chokepoints},
    }

    n_total_bands = len(seasonal["bands"]) + len(pattern_bands) + len(active["events"]) + len(fm["events"])
    n_clusters = len(overlaps["clusters"])
    n_surfaced = sum(1 for c in overlaps["clusters"] if c["convergence_score"] >= 5.5)
    top_score = max((c["convergence_score"] for c in overlaps["clusters"]), default=0.0)

    summary_html = (
        f'<span class="kpi"><strong>{n_total_bands}</strong> bands tracked<small>seasonal + active + FM</small></span>'
        f'<span class="kpi"><strong>{n_clusters}</strong> clusters detected<small>before / after threshold</small></span>'
        f'<span class="kpi"><strong>{n_surfaced}</strong> above threshold<small>score &ge; 5.5/10</small></span>'
        f'<span class="kpi"><strong>{top_score:.1f}</strong> top score<small>highest convergence today</small></span>'
    )

    overlaps_html = render_top_overlaps(overlaps["clusters"], names)
    chokepoint_html = render_chokepoint_board(overlaps.get("chokepoint_board", []))
    today_glance_html = render_today_glance(overlaps.get("executive_summary", {}))

    shared_blocks = {
        "TODAY_HUMAN": human_date,
        "TODAY_ISO": today_iso,
        "LAST_UPDATED": f"{last_updated}",
        "DATA_VERSION": json.dumps({"computed_at": overlaps["computed_at"], "today": today_iso}),
    }
    index_only_blocks = {
        "HERO_KPIS": summary_html,
        "TOP_OVERLAPS": overlaps_html,
        "CHOKEPOINT_BOARD": chokepoint_html,
        "TODAY_GLANCE": today_glance_html,
    }
    blocks_by_page = {
        "index.html": {**shared_blocks, **index_only_blocks},
        "brief.html": shared_blocks,
    }

    for page in PAGES:
        path = ROOT / page
        if not path.exists():
            print(f"[render] WARN: {page} missing — skipping.", file=sys.stderr)
            continue
        s = path.read_text(encoding="utf-8")
        for key, content in blocks_by_page[page].items():
            s, n = replace_block(s, key, content)
            if n == 0:
                print(f"[render] WARN: {page}: marker BRIEF:{key}_START not found.", file=sys.stderr)
        prefix = "Window of Vulnerability — " if page == "index.html" else "WoV — deep view · "
        s = update_titles(s, human_date, prefix)
        path.write_text(s, encoding="utf-8")

        starts = len(re.findall(r"<!-- BRIEF:[A-Z0-9_]+_START -->", s))
        ends = len(re.findall(r"<!-- BRIEF:[A-Z0-9_]+_END -->", s))
        if starts != ends:
            print(f"[render] FAIL: marker imbalance in {page}: {starts} starts vs {ends} ends.", file=sys.stderr)
            return 5

    print(f"[render] updated {len(PAGES)} page(s); {n_surfaced} clusters surfaced; top score {top_score:.1f}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
