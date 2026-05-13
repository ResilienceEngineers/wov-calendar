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


def render_top_overlaps(clusters: list[dict], regions: list[dict]) -> str:
    region_name = {r["id"]: r["name"] for r in regions}
    surfaced = [c for c in clusters if c["convergence_score"] >= 5.5][:5]
    if not surfaced:
        return '<p class="empty">No convergence clusters above surface threshold today.</p>'
    parts: list[str] = []
    for c in surfaced:
        axis = html_lib.escape(c["axis"])
        axis_value = html_lib.escape(region_name.get(c["axis_value"], c["axis_value"]))
        score = f"{c['convergence_score']:.1f}"
        window = f"{c['time_window'][0]} → {c['time_window'][1]}"
        n_members = len(c["member_event_ids"])
        seed = html_lib.escape(c.get("narrative_seed") or "(narrative pending)")
        parts.append(
            f'<article class="cluster-card" data-cluster-id="{html_lib.escape(c["id"])}">'
            f'<div class="cluster-head">'
            f'<span class="axis-label">{axis} · {axis_value}</span>'
            f'<span class="score">{score}</span>'
            f'</div>'
            f'<p class="cluster-window">{window}</p>'
            f'<p class="cluster-seed">{seed}</p>'
            f'<p class="cluster-members"><strong>{n_members}</strong> bands converging</p>'
            f'<a class="cluster-link" href="brief.html#cluster-{html_lib.escape(c["id"])}">open in brief →</a>'
            f'</article>'
        )
    return "\n".join(parts)


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
    seasonal = json.loads((DATA / "seasonal_bands.json").read_text(encoding="utf-8"))
    active = json.loads((DATA / "active_events.json").read_text(encoding="utf-8"))
    fm = json.loads((DATA / "fm_events.json").read_text(encoding="utf-8"))

    n_total_bands = len(seasonal["bands"]) + len(active["events"]) + len(fm["events"])
    n_clusters = len(overlaps["clusters"])
    n_surfaced = sum(1 for c in overlaps["clusters"] if c["convergence_score"] >= 5.5)
    top_score = max((c["convergence_score"] for c in overlaps["clusters"]), default=0.0)

    summary_html = (
        f'<span class="kpi"><strong>{n_total_bands}</strong> bands tracked</span>'
        f'<span class="kpi"><strong>{n_clusters}</strong> clusters detected</span>'
        f'<span class="kpi"><strong>{n_surfaced}</strong> above surface threshold</span>'
        f'<span class="kpi"><strong>{top_score:.1f}</strong> top convergence score</span>'
    )

    overlaps_html = render_top_overlaps(overlaps["clusters"], regions)

    blocks = {
        "TODAY_HUMAN": human_date,
        "TODAY_ISO": today_iso,
        "LAST_UPDATED": f"{last_updated}",
        "DATA_VERSION": json.dumps({"computed_at": overlaps["computed_at"], "today": today_iso}),
        "HERO_KPIS": summary_html,
        "TOP_OVERLAPS": overlaps_html,
    }

    for page in PAGES:
        path = ROOT / page
        if not path.exists():
            print(f"[render] WARN: {page} missing — skipping.", file=sys.stderr)
            continue
        s = path.read_text(encoding="utf-8")
        for key, content in blocks.items():
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
