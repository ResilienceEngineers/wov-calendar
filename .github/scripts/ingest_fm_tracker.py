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


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

# Operator / site / type keyword -> (country_iso3, region_id, commodity_class, industries_downstream)
# region_id and industries_downstream MUST be valid vocab IDs (FK-checked by validate_schemas.py).
OPERATOR_HINTS: list[tuple[tuple[str, ...], str, str, str, list[str]]] = [
    (("qatarenergy", "ras laffan", "lng"),                 "QAT", "ME-PersianGulf", "lng",             ["energy_lng"]),
    (("kpc", "kuwait"),                                     "KWT", "ME-PersianGulf", "crude_oil",       ["energy_oil"]),
    (("sabic", "jubail", "petrochem"),                      "SAU", "ME-PersianGulf", "petrochemicals",  ["chem_petrochem", "chem_basic"]),
    (("ega", "taweelah", "aluminium", "aluminum"),          "ARE", "ME-PersianGulf", "aluminium",       ["metals_aluminium"]),
    (("aramco",),                                           "SAU", "ME-PersianGulf", "crude_oil",       ["energy_oil"]),
    (("irgc", "pgsa", "iran", "tehran"),                    "IRN", "ME-PersianGulf", "crude_oil",       ["shipping_tanker", "energy_oil"]),
    (("windward", "vlcc", "vessel"),                        "ARE", "ME-PersianGulf", "crude_oil",       ["shipping_tanker"]),
    (("maersk", "msc", "hapag", "cma cgm", "container"),    "ARE", "ME-PersianGulf", "containerized_general", ["shipping_container"]),
    (("lufthansa", "airspace", "airline", "easa", "air"),   "DEU", "ME-PersianGulf", "jet_fuel",        ["air_freight"]),
    (("bunker", "singapore"),                               "SGP", "AS-Malacca",     "fuel_oil",        ["shipping"]),
    (("spr", "strategic petroleum", "doe"),                 "USA", "NA-Gulf",        "crude_oil",       ["energy_oil"]),
    (("eia", "iea"),                                        "USA", "ME-PersianGulf", "crude_oil",       ["energy_oil", "energy_lng"]),
    (("trump", "state dept", "state department"),           "USA", "ME-PersianGulf", "crude_oil",       ["energy_oil"]),
]
FM_TYPE_WORDS = {"production": "Production", "shipping": "Shipping", "downstream": "Downstream",
                 "distribution": "Distribution", "restart": "Restart", "cascade": "Cascade"}
AMBER_HINTS = ("negotiat", "reject", "price", "osp", "pricing", "spr", "release", "no hurry",
               "toll proposal", "indicator", "observed")


def parse_human_date(text: str) -> str | None:
    """Parse '12 May 2026', '~4 Apr 2026', '28 Feb - 4 Mar 2026' -> first date as YYYY-MM-DD."""
    t = text.replace("–", "-").replace("—", "-")
    matches = re.findall(r"(\d{1,2})\s+([A-Za-z]{3,9})\.?\s*(\d{4})?", t)
    if not matches:
        return None
    year = next((y for _, _, y in reversed(matches) if y), None)
    if not year:
        return None
    d, mon, _ = matches[0]
    mnum = MONTHS.get(mon[:3].lower())
    if not mnum:
        return None
    try:
        return f"{int(year):04d}-{mnum:02d}-{int(d):02d}"
    except ValueError:
        return None


def infer(operator: str, site: str, type_cell: str) -> tuple[str, str, str, list[str]]:
    blob = f"{operator} {site} {type_cell}".lower()
    for keys, country, region, commodity, inds in OPERATOR_HINTS:
        if any(k in blob for k in keys):
            return country, region, commodity, inds
    return "ZZZ", "ME-PersianGulf", "unknown", []


def map_fm_type(type_cell: str) -> str | None:
    low = type_cell.lower()
    for word, val in FM_TYPE_WORDS.items():
        if word in low:
            return val
    return None


def infer_status(status_cell: str, type_cell: str) -> str:
    low = (status_cell + " " + type_cell).lower()
    if any(h in low for h in AMBER_HINTS):
        return "amber"
    return "red"


def infer_duration(status_cell: str) -> int:
    low = status_cell.lower()
    if "12-month" in low or "12 month" in low or "rebuild" in low or "year" in low:
        return 365
    if "month" in low:
        return 30
    return 45


def find_fm_table(html: str) -> list[dict]:
    blocks = parse_blocks(html)
    table_html = blocks.get("FM_TABLE") or blocks.get("RECENT_FM") or blocks.get("FM")
    if not table_html:
        return []
    soup = BeautifulSoup(table_html, "html.parser")
    out: list[dict] = []
    for row in soup.find_all("tr"):
        tds = [c.get_text(" ", strip=True) for c in row.find_all("td")]
        if len(tds) < 6:  # header uses <th>; data rows have >=6 <td>
            continue
        operator, site, wave_c, type_c, status_c, date_c = tds[0], tds[1], tds[2], tds[3], tds[4], tds[5]
        declared_at = parse_human_date(date_c)
        if not declared_at or not operator:
            continue
        country, region, commodity, industries = infer(operator, site, type_c)
        wave_m = re.search(r"[123]", wave_c)
        wave = int(wave_m.group(0)) if wave_m else None
        out.append({
            "id": stable_id(declared_at, operator, site, commodity),
            "declarant": operator,
            "facility": site,
            "country_iso3": country,
            "declared_at": declared_at,
            "commodity_class": commodity or "unknown",
            "products": [],
            "wave": wave,
            "fm_type": map_fm_type(type_c),
            "status": infer_status(status_c, type_c),
            "signal_tier": "hard",
            "source_tier": 1,
            "regions_affected": [region],
            "industries_downstream": industries,
            "estimated_duration_days": infer_duration(status_c),
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
