#!/usr/bin/env python3
"""Build JSON band files from data/patterns.csv (the single source of truth).

patterns.csv holds one row per recurring pattern (weather + cargo_crime + cyber +
conflict_cycle + labor_cycle). This script resolves the month-level windows into
concrete dates for the current 12-month horizon and emits:

  - data/seasonal_bands.json   (category == "weather"; matches seasonal_bands.schema)
  - data/pattern_bands.json    (all other categories; matches pattern_bands.schema)

Month windows wrap across the year boundary when end_month < start_month. geo_bbox is
read from the CSV if present (s;w;n;e) else derived from the union of the pattern's
region bounding boxes in vocab/regions.json.

Edit patterns.csv (or let research_patterns.py append rows), then run this. The daily
orchestrator runs it before compute_overlaps.py so the calendar always reflects the CSV.
"""
from __future__ import annotations

import calendar
import csv
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
PATTERNS_CSV = DATA / "patterns.csv"

WINDOW_BACK_DAYS = 30
WINDOW_FWD_DAYS = 335


def split_pipe(value: str) -> list[str]:
    return [v.strip() for v in (value or "").split("|") if v.strip()]


def last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def region_bboxes() -> dict[str, list[float]]:
    regions = json.loads((DATA / "vocab" / "regions.json").read_text(encoding="utf-8"))["regions"]
    return {r["id"]: r["geo_bbox"] for r in regions}


def derive_bbox(regions: list[str], bboxes: dict[str, list[float]]) -> list[float]:
    valid = [bboxes[r] for r in regions if r in bboxes]
    if not valid:
        return [-60.0, -180.0, 80.0, 180.0]
    s = min(b[0] for b in valid)
    w = min(b[1] for b in valid)
    n = max(b[2] for b in valid)
    e = max(b[3] for b in valid)
    return [s, w, n, e]


def resolve_occurrence(start_m: int, end_m: int, peak_s: int, peak_e: int, today: date) -> tuple[date, date, date, date] | None:
    """Pick the single occurrence whose window intersects [today-30d, today+335d]."""
    win_start = date.fromordinal(today.toordinal() - WINDOW_BACK_DAYS)
    win_end = date.fromordinal(today.toordinal() + WINDOW_FWD_DAYS)

    candidates: list[tuple[date, date, date, date]] = []
    for base_year in (today.year - 1, today.year, today.year + 1):
        start = date(base_year, start_m, 1)
        end_year = base_year if end_m >= start_m else base_year + 1
        end = date(end_year, end_m, last_day(end_year, end_m))
        peak_start_year = base_year if peak_s >= start_m else base_year + 1
        peak_end_year = base_year if peak_e >= start_m else base_year + 1
        peak_start = date(peak_start_year, peak_s, 1)
        peak_end = date(peak_end_year, peak_e, last_day(peak_end_year, peak_e))
        if end >= win_start and start <= win_end:
            candidates.append((start, peak_start, peak_end, end))

    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    for c in candidates:
        if c[3] >= win_start:
            return c
    return candidates[0]


def main() -> int:
    today = datetime.now(timezone.utc).date()
    bboxes = region_bboxes()

    rows = list(csv.DictReader(PATTERNS_CSV.read_text(encoding="utf-8").splitlines()))
    weather_bands: list[dict] = []
    pattern_bands: list[dict] = []
    skipped = 0

    for row in rows:
        if row.get("status", "active").strip() not in ("active", "candidate"):
            skipped += 1
            continue
        try:
            sm = int(row["start_month"]); em = int(row["end_month"])
            ps = int(row["peak_start_month"]); pe = int(row["peak_end_month"])
        except (ValueError, KeyError):
            print(f"[build] skipping {row.get('pattern_id')}: bad month columns", file=sys.stderr)
            skipped += 1
            continue

        occ = resolve_occurrence(sm, em, ps, pe, today)
        if occ is None:
            skipped += 1
            continue
        start, peak_start, peak_end, end = occ

        regions = split_pipe(row["regions"])
        if row.get("geo_bbox", "").strip():
            bbox = [float(x) for x in row["geo_bbox"].split(";")]
        else:
            bbox = derive_bbox(regions, bboxes)

        band_id = f"{row['pattern_id']}-{start.year}"
        category = row["category"].strip()
        severity = int(row["baseline_severity"])
        sources = split_pipe(row["sources"])

        if category == "weather":
            weather_bands.append({
                "id": band_id,
                "hazard_type": row["subtype"].strip(),
                "name": row["name"].strip(),
                "regions": regions,
                "geo_bbox": bbox,
                "start_date": start.isoformat(),
                "peak_window": [peak_start.isoformat(), peak_end.isoformat()],
                "end_date": end.isoformat(),
                "baseline_severity": severity,
                "affected_industries": split_pipe(row["industries"]),
                "affected_commodities": split_pipe(row["commodities"]),
                "affected_chokepoints": split_pipe(row["chokepoints"]),
                "source_ids": sources,
                "confidence": row["confidence"].strip(),
                "notes": row.get("methodology_note", "").strip(),
            })
        else:
            pattern_bands.append({
                "id": band_id,
                "pattern_id": row["pattern_id"].strip(),
                "name": row["name"].strip(),
                "category": category,
                "subtype": row["subtype"].strip(),
                "recurrence": row["recurrence"].strip(),
                "regions": regions,
                "countries_iso3": split_pipe(row["countries_iso3"]),
                "industries": split_pipe(row["industries"]),
                "commodities": split_pipe(row["commodities"]),
                "chokepoints": split_pipe(row["chokepoints"]),
                "geo_bbox": bbox,
                "start_date": start.isoformat(),
                "peak_window": [peak_start.isoformat(), peak_end.isoformat()],
                "end_date": end.isoformat(),
                "baseline_severity": severity,
                "confidence": row["confidence"].strip(),
                "source_ids": sources,
                "search_queries": split_pipe(row["search_queries"]),
                "materialization_metric": row.get("materialization_metric", "").strip(),
                "methodology_note": row.get("methodology_note", "").strip(),
                "first_identified": row.get("first_identified", today.isoformat()).strip(),
                "last_reviewed": row.get("last_reviewed", today.isoformat()).strip(),
                "status": row.get("status", "active").strip(),
            })

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    seasonal_out = {
        "$comment": "GENERATED from data/patterns.csv by build_patterns.py. Do not hand-edit; edit patterns.csv (weather rows) and rebuild.",
        "version": f"{today.year}.{today.timetuple().tm_yday}",
        "generated_at": now_iso,
        "bands": weather_bands,
    }
    (DATA / "seasonal_bands.json").write_text(json.dumps(seasonal_out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    pattern_out = {
        "$comment": "GENERATED from data/patterns.csv by build_patterns.py. Single source of truth is patterns.csv.",
        "generated_at": now_iso,
        "source_of_truth": "data/patterns.csv",
        "bands": pattern_bands,
    }
    (DATA / "pattern_bands.json").write_text(json.dumps(pattern_out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"[build] {len(weather_bands)} weather bands -> seasonal_bands.json; "
          f"{len(pattern_bands)} pattern bands -> pattern_bands.json; {skipped} skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
