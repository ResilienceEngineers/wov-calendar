#!/usr/bin/env python3
"""Scrape fm-tracker for force-majeure declarations.

Pulls index.html from raw.githubusercontent.com (main branch). Looks for FM-event rows
in the BRIEF:RECENT_FM table (or equivalent) and the BRIEF:MAP_PINS array. Computes
stable IDs as sha1(declared_at + declarant + facility + commodity_class)[:12].

Upsert semantics: existing IDs are kept; new IDs added; nothing removed (FM events have
implicit decay through estimated_duration_days, not deletion).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

RAW_URL = "https://raw.githubusercontent.com/resilienceengineers/fm-tracker/main/index.html"
PUBLIC_URL = "https://resilienceengineers.github.io/fm-tracker/"

BLOCK_RE = re.compile(
    r"<!--\s*BRIEF:([A-Z0-9_]+)_START\s*-->(.*?)<!--\s*BRIEF:\1_END\s*-->",
    re.DOTALL | re.IGNORECASE,
)

REGION_HINTS = {
    "DEU": "EU-Industrial", "BEL": "EU-Industrial", "NLD": "EU-Industrial", "FRA": "EU-Industrial", "LUX": "EU-Industrial",
    "GBR": "EU-North", "NOR": "EU-North", "DNK": "EU-North", "SWE": "EU-North", "FIN": "EU-North",
    "ESP": "EU-Med", "ITA": "EU-Med", "GRC": "EU-Med", "TUR": "EU-Med",
    "USA": "NA-Gulf", "MEX": "NA-Gulf", "CAN": "NA-Gulf",
    "PAN": "NA-Panama",
    "IRN": "ME-PersianGulf", "OMN": "ME-PersianGulf", "ARE": "ME-PersianGulf", "QAT": "ME-PersianGulf", "KWT": "ME-PersianGulf", "SAU": "ME-PersianGulf", "BHR": "ME-PersianGulf",
    "YEM": "ME-RedSea", "EGY": "ME-RedSea",
    "CHN": "AS-NWPacific", "JPN": "AS-NWPacific", "KOR": "AS-NWPacific",
    "TWN": "AS-TaiwanStrait",
    "MYS": "AS-Malacca", "IDN": "AS-Malacca", "SGP": "AS-Malacca", "THA": "AS-Malacca",
    "IND": "AS-South", "BGD": "AS-South", "PAK": "AS-South",
}


def fetch_html(url: str) -> str:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def parse_blocks(html: str) -> dict[str, str]:
    return {m.group(1).upper(): m.group(2).strip() for m in BLOCK_RE.finditer(html)}


def stable_id(declared_at: str, declarant: str, facility: str, commodity_class: str) -> str:
    raw = f"{declared_at}|{declarant}|{facility}|{commodity_class}".lower()
    return "fm-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def parse_country(text: str) -> str:
    m = re.search(r"\b([A-Z]{3})\b", text)
    return m.group(1) if m else ""


def find_fm_table(html: str) -> list[dict]:
    blocks = parse_blocks(html)
    table_html = blocks.get("RECENT_FM") or blocks.get("FM_TABLE") or blocks.get("FM")
    if not table_html:
        return []
    soup = BeautifulSoup(table_html, "html.parser")
    rows = soup.select("tr")
    if not rows:
        rows = soup.select("li")
    out: list[dict] = []
    for row in rows:
        cells = [c.get_text(" ", strip=True) for c in row.select("td,span,div")]
        if not cells:
            continue
        date_m = re.search(r"\b\d{4}-\d{2}-\d{2}\b", " ".join(cells))
        if not date_m:
            continue
        declared_at = date_m.group(0)
        text_join = " | ".join(cells)
        parts = [p.strip() for p in text_join.split("|") if p.strip()]
        declarant = parts[1] if len(parts) > 1 else "unknown"
        facility = parts[2] if len(parts) > 2 else ""
        commodity_class = parts[3] if len(parts) > 3 else ""
        country = parse_country(text_join) or "ZZZ"
        wave_m = re.search(r"\bW([123])\b", text_join)
        wave = int(wave_m.group(1)) if wave_m else None
        status_m = re.search(r"\b(red|amber|green)\b", text_join, re.IGNORECASE)
        status = status_m.group(1).lower() if status_m else None

        region = REGION_HINTS.get(country, "EU-Industrial")
        out.append({
            "id": stable_id(declared_at, declarant, facility, commodity_class),
            "declarant": declarant,
            "facility": facility,
            "country_iso3": country,
            "declared_at": declared_at,
            "commodity_class": commodity_class or "unknown",
            "products": [],
            "wave": wave,
            "fm_type": None,
            "status": status,
            "signal_tier": "hard",
            "source_tier": 1,
            "regions_affected": [region],
            "industries_downstream": [],
            "estimated_duration_days": 30,
            "source_doc_url": None,
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"[ingest_fm] fetching {RAW_URL}", flush=True)
    try:
        html = fetch_html(RAW_URL)
    except requests.RequestException as e:
        print(f"[ingest_fm] fetch failed: {e}", file=sys.stderr)
        return 2

    new_events = find_fm_table(html)
    print(f"[ingest_fm] parsed {len(new_events)} FM rows from upstream.", flush=True)

    target = DATA / "fm_events.json"
    current = json.loads(target.read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in current["events"]}
    added = 0
    for ev in new_events:
        if ev["id"] not in by_id:
            by_id[ev["id"]] = ev
            added += 1

    out = {
        "$comment": current.get("$comment", "Force-majeure events scraped from fm-tracker. Bot-owned."),
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source_url": PUBLIC_URL,
        "events": sorted(by_id.values(), key=lambda e: e["declared_at"], reverse=True),
    }

    if args.dry_run:
        out_path = DATA / ".staging" / "fm_events.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_path = target
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[ingest_fm] added={added} total={len(by_id)} -> {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
