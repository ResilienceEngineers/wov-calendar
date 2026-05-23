#!/usr/bin/env python3
"""Generate iCalendar (.ics) subscription feeds from the pattern bands.

Outputs (served by GitHub Pages, so they are auto-updating subscription feeds):
  - calendar.ics                  all pre-analysed patterns (every family)
  - calendar-weather.ics          weather only
  - calendar-cargo_crime.ics      cargo crime only
  - calendar-cyber.ics            cyber only
  - calendar-conflict_cycle.ics   conflict-cycle only
  - calendar-labor_cycle.ics      labour-cycle only

Each pattern becomes one all-day multi-day VEVENT spanning its season. The peak
window is stated in the description. UIDs are stable per band so that when a
subscriber's calendar app re-polls the feed, it UPDATES the event in place rather
than duplicating it. SEQUENCE increments daily so changes propagate.

The user-facing one-time download (with private custom windows) is built client-side
in index.html; this script only produces the shared, auto-updating feeds.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
DOMAIN = "resilienceengineers.github.io"

FAMILIES = ["weather", "cargo_crime", "cyber", "conflict_cycle", "labor_cycle"]
FAMILY_LABEL = {"weather": "Weather", "cargo_crime": "Cargo crime", "cyber": "Cyber",
                "conflict_cycle": "Conflict cycle", "labor_cycle": "Labour cycle"}


def esc(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n").replace("\r", "")


def fold(line: str) -> str:
    """Fold lines >75 octets per RFC 5545 (continuation = CRLF + single space)."""
    out = []
    while len(line.encode("utf-8")) > 73:
        # take a 73-char chunk (ASCII-safe; our content is ASCII)
        chunk = line[:73]
        out.append(chunk)
        line = " " + line[73:]
    out.append(line)
    return "\r\n".join(out)


def normalize_bands() -> list[dict]:
    bands: list[dict] = []
    seasonal = json.loads((DATA / "seasonal_bands.json").read_text(encoding="utf-8"))
    for b in seasonal["bands"]:
        bands.append({
            "id": b["id"], "name": b["name"], "category": "weather", "subtype": b.get("hazard_type", ""),
            "start_date": b["start_date"], "end_date": b["end_date"], "peak_window": b.get("peak_window"),
            "severity": b["baseline_severity"], "regions": b.get("regions", []),
            "industries": b.get("affected_industries", []), "chokepoints": b.get("affected_chokepoints", []),
            "sources": b.get("source_ids", []), "metric": "", "note": b.get("notes", ""),
        })
    pp = DATA / "pattern_bands.json"
    if pp.exists():
        for b in json.loads(pp.read_text(encoding="utf-8"))["bands"]:
            bands.append({
                "id": b["id"], "name": b["name"], "category": b["category"], "subtype": b.get("subtype", ""),
                "start_date": b["start_date"], "end_date": b["end_date"], "peak_window": b.get("peak_window"),
                "severity": b["baseline_severity"], "regions": b.get("regions", []),
                "industries": b.get("industries", []), "chokepoints": b.get("chokepoints", []),
                "sources": b.get("source_ids", []), "metric": b.get("materialization_metric", ""),
                "note": b.get("methodology_note", ""),
            })
    return bands


def vevent(b: dict, seq: int, dtstamp: str, region_names: dict[str, str]) -> str:
    start = datetime.strptime(b["start_date"], "%Y-%m-%d").date()
    end_excl = datetime.strptime(b["end_date"], "%Y-%m-%d").date() + timedelta(days=1)
    fam = FAMILY_LABEL.get(b["category"], b["category"])
    summary = f"[{fam}] {b['name']} (sev {b['severity']}/5)"
    regions = ", ".join(region_names.get(r, r) for r in b["regions"]) or "—"
    peak = ""
    if b.get("peak_window"):
        peak = f"Peak window: {b['peak_window'][0]} to {b['peak_window'][1]}. "
    desc_parts = [
        f"Family: {fam} ({b.get('subtype','')}).",
        f"Severity {b['severity']}/5.",
        peak.strip(),
        f"Regions: {regions}.",
        (f"Industries: {', '.join(b['industries'][:6])}." if b.get("industries") else ""),
        (f"Chokepoints: {', '.join(b['chokepoints'])}." if b.get("chokepoints") else ""),
        (f"Tracked metric: {b['metric']}." if b.get("metric") else ""),
        (b["note"] if b.get("note") else ""),
        "Source: Window of Vulnerability — resilienceengineers.github.io/wov-calendar",
    ]
    description = " ".join(p for p in desc_parts if p)
    lines = [
        "BEGIN:VEVENT",
        f"UID:{b['id']}@{DOMAIN}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{end_excl.strftime('%Y%m%d')}",
        fold(f"SUMMARY:{esc(summary)}"),
        fold(f"DESCRIPTION:{esc(description)}"),
        f"CATEGORIES:{esc(fam)}",
        f"SEQUENCE:{seq}",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ]
    return "\r\n".join(lines)


def build_calendar(bands: list[dict], scope_label: str, seq: int, dtstamp: str, region_names: dict[str, str]) -> str:
    head = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Resilience Engineers//Window of Vulnerability//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        fold(f"X-WR-CALNAME:Window of Vulnerability - {scope_label}"),
        fold("X-WR-CALDESC:Recurring windows of vulnerability (weather, cargo crime, cyber, conflict, labour). Auto-updates daily."),
        "X-WR-TIMEZONE:UTC",
        "REFRESH-INTERVAL;VALUE=DURATION:PT24H",
        "X-PUBLISHED-TTL:PT24H",
    ]
    body = [vevent(b, seq, dtstamp, region_names) for b in bands]
    return "\r\n".join(head + body + ["END:VCALENDAR"]) + "\r\n"


def main() -> int:
    bands = normalize_bands()
    now = datetime.now(timezone.utc)
    dtstamp = now.strftime("%Y%m%dT%H%M%SZ")
    seq = (now.date() - date(2026, 1, 1)).days  # increments daily so updates propagate

    region_names = {r["id"]: r["name"] for r in json.loads((DATA / "vocab" / "regions.json").read_text(encoding="utf-8"))["regions"]}

    (ROOT / "calendar.ics").write_text(build_calendar(bands, "all patterns", seq, dtstamp, region_names), encoding="utf-8")
    counts = {"all": len(bands)}
    for fam in FAMILIES:
        fam_bands = [b for b in bands if b["category"] == fam]
        (ROOT / f"calendar-{fam}.ics").write_text(
            build_calendar(fam_bands, FAMILY_LABEL[fam], seq, dtstamp, region_names), encoding="utf-8")
        counts[fam] = len(fam_bands)

    print(f"[ics] wrote calendar.ics ({counts['all']} events) + {len(FAMILIES)} family feeds: "
          + ", ".join(f"{k}={v}" for k, v in counts.items() if k != "all"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
