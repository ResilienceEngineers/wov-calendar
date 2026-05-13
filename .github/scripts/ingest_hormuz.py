#!/usr/bin/env python3
"""Scrape hormuz-tracker daily brief and update hormuz_snapshot.json.

Pulls `index.html` from raw.githubusercontent.com (main branch), parses BRIEF:* blocks
and the BRIEF:MAP_PINS JS array. Writes snapshot with brief_date, trend, threat_level,
oneliner, watchlist, map_pins.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

RAW_URL = "https://raw.githubusercontent.com/resilienceengineers/hormuz-tracker/main/index.html"
PUBLIC_URL = "https://resilienceengineers.github.io/hormuz-daily-brief/"

BLOCK_RE = re.compile(
    r"<!--\s*BRIEF:([A-Z0-9_]+)_START\s*-->(.*?)<!--\s*BRIEF:\1_END\s*-->",
    re.DOTALL | re.IGNORECASE,
)
MAP_PINS_RE = re.compile(
    r"//\s*BRIEF:MAP_PINS_START\s*(.*?)//\s*BRIEF:MAP_PINS_END",
    re.DOTALL,
)


def fetch_html(url: str) -> str:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def parse_blocks(html: str) -> dict[str, str]:
    return {m.group(1).upper(): m.group(2).strip() for m in BLOCK_RE.finditer(html)}


def strip_tags(html_fragment: str) -> str:
    return BeautifulSoup(html_fragment, "html.parser").get_text(" ", strip=True)


def parse_threat(html_fragment: str) -> tuple[int | None, str | None]:
    text = strip_tags(html_fragment)
    m = re.search(r"(\d)\s*/\s*5", text)
    level = int(m.group(1)) if m else None
    label_m = re.search(r"(Routine|Elevated|Concerning|Severe|Crisis)", text, re.IGNORECASE)
    label = label_m.group(1).title() if label_m else None
    return level, label


def parse_trend(html_fragment: str) -> tuple[str | None, str | None]:
    text = strip_tags(html_fragment)
    m = re.search(r"(Worse|Same|Better)", text, re.IGNORECASE)
    trend = m.group(1).title() if m else None
    conf_m = re.search(r"Confidence:\s*(Low|Medium|High)", text, re.IGNORECASE)
    conf = conf_m.group(1).title() if conf_m else None
    return trend, conf


def parse_watchlist(html_fragment: str) -> list[dict]:
    soup = BeautifulSoup(html_fragment, "html.parser")
    items: list[dict] = []
    for li in soup.select("li"):
        label = li.get_text(" ", strip=True)
        deadline_el = li.select_one(".deadline")
        imp_el = li.select_one(".imp")
        items.append({
            "label": label,
            "deadline": deadline_el.get_text(" ", strip=True) if deadline_el else "",
            "implication": imp_el.get_text(" ", strip=True) if imp_el else "",
        })
    return items


def parse_map_pins(html: str) -> list[dict]:
    m = MAP_PINS_RE.search(html)
    if not m:
        return []
    body = m.group(1).strip().rstrip(",")
    # Convert JS object literals to JSON-ish by quoting unquoted keys and replacing single quotes.
    s = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', body)
    s = s.replace("'", '"')
    s = re.sub(r",(\s*[}\]])", r"\1", s)
    try:
        pins = json.loads("[" + s + "]")
    except json.JSONDecodeError as e:
        print(f"[ingest_hormuz] WARN: map-pins parse failed: {e}", file=sys.stderr)
        return []
    out: list[dict] = []
    for p in pins:
        if not isinstance(p, dict):
            continue
        lat = p.get("lat")
        lng = p.get("lng") or p.get("lon")
        if lat is None or lng is None or not p.get("name"):
            continue
        out.append({
            "lat": float(lat),
            "lng": float(lng),
            "name": str(p["name"]),
            "color": str(p.get("color", "")),
            "status": str(p.get("status", "")),
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"[ingest_hormuz] fetching {RAW_URL}", flush=True)
    try:
        html = fetch_html(RAW_URL)
    except requests.RequestException as e:
        print(f"[ingest_hormuz] fetch failed: {e}", file=sys.stderr)
        return 2

    blocks = parse_blocks(html)
    brief_date = strip_tags(blocks.get("DATE", "")) or "unknown"
    day = strip_tags(blocks.get("DAY", "")) or ""
    day_n: int | None = None
    if day.isdigit():
        day_n = int(day)
    trend, conf = parse_trend(blocks.get("TREND", ""))
    threat_level, threat_label = parse_threat(blocks.get("THREAT", ""))
    oneliner = strip_tags(blocks.get("ONELINER", "")) or "(no oneliner found)"
    watchlist = parse_watchlist(blocks.get("WATCHLIST", ""))
    pins = parse_map_pins(html)

    snapshot = {
        "$comment": "Snapshot of hormuz-tracker daily brief. Bot-owned. Refreshed daily by ingest_hormuz.py.",
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source_url": PUBLIC_URL,
        "snapshot": {
            "brief_date": brief_date,
            "day_of_war": day_n,
            "trend": trend or "Same",
            "trend_confidence": conf,
            "threat_level": threat_level or 1,
            "threat_label": threat_label,
            "oneliner": oneliner,
            "watchlist": watchlist,
            "map_pins": pins,
        },
    }

    if args.dry_run:
        out_path = DATA / ".staging" / "hormuz_snapshot.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_path = DATA / "hormuz_snapshot.json"
    out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[ingest_hormuz] threat={threat_level} trend={trend} pins={len(pins)} watchlist={len(watchlist)} -> {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
