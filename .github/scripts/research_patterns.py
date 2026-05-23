#!/usr/bin/env python3
"""Fortnightly pattern research run.

For each pattern in patterns.csv that is due for review (last_reviewed older than
REVIEW_INTERVAL_DAYS), Claude + web_search checks the pattern's sources/queries for
fresh data and reports:
  - OBSERVATION  : a metric reading + materialisation assessment -> appended to observations.csv
  - CANDIDATE_PATTERN : a newly discovered recurring pattern -> appended to patterns.csv (status=candidate)
  - MATERIALIZATION : whether an existing pattern is taking off vs expectation

This is how we see patterns "take off": the observation log accumulates metric readings
over time (e.g. Atlantic named-storm count climbing through hurricane season).

Discipline: candidate patterns must affect MULTIPLE industries / nodes / countries / regions
and cite a Tier 1-3 source. One-off events are NOT patterns and must not be added.

Usage:
  python research_patterns.py            # review patterns due (>=14 days since last_reviewed)
  python research_patterns.py --all      # review every active pattern
  python research_patterns.py --max 8    # cap number reviewed this run
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from anthropic import Anthropic

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
PATTERNS_CSV = DATA / "patterns.csv"
OBS_CSV = DATA / "observations.csv"

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_OUTPUT_TOKENS = int(os.environ.get("CLAUDE_RESEARCH_MAX_TOKENS", "16000"))
MAX_WEB_SEARCHES = int(os.environ.get("CLAUDE_RESEARCH_MAX_SEARCHES", "12"))
REVIEW_INTERVAL_DAYS = 14
DEFAULT_MAX_REVIEW = 12

OBS_FIELDS = ["observation_date", "run_id", "pattern_id", "category", "search_query",
              "source", "metric_name", "metric_value", "unit", "region",
              "window_phase", "materialization", "source_tier", "notes"]

BLOCK_RE = re.compile(r"###BEGIN:([A-Z_]+)###\s*\n(.*?)\n\s*###END:\1###", re.DOTALL)


def read_patterns() -> tuple[list[str], list[dict]]:
    text = PATTERNS_CSV.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(text))
    return reader.fieldnames, list(reader)


def write_patterns(fieldnames: list[str], rows: list[dict]) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    PATTERNS_CSV.write_text(buf.getvalue(), encoding="utf-8")


def append_observations(obs_rows: list[dict]) -> None:
    existing = OBS_CSV.read_text(encoding="utf-8") if OBS_CSV.exists() else ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=OBS_FIELDS, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    if not existing.strip():
        writer.writeheader()
    for r in obs_rows:
        writer.writerow({k: r.get(k, "") for k in OBS_FIELDS})
    with OBS_CSV.open("a", encoding="utf-8") as fh:
        fh.write(buf.getvalue())


def due_for_review(row: dict, today: date, review_all: bool) -> bool:
    if row.get("status", "active").strip() not in ("active", "candidate"):
        return False
    if review_all:
        return True
    try:
        last = datetime.strptime(row.get("last_reviewed", "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return True
    return (today - last).days >= REVIEW_INTERVAL_DAYS


def parse_kv_block(text: str) -> dict:
    """Parse a simple key: value block (one per line; values may contain colons)."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def build_prompt(due_rows: list[dict], today_iso: str) -> tuple[str, str]:
    lines = []
    for r in due_rows:
        lines.append(
            f"- {r['pattern_id']} | {r['name']} | {r['category']} | metric: {r.get('materialization_metric','')} "
            f"| queries: {r.get('search_queries','')} | sources: {r.get('sources','')}"
        )
    due_block = "\n".join(lines)

    system_prompt = f"""You are the WoV Pattern-Research Agent. Today: {today_iso}.

You review recurring risk patterns against fresh public data and report findings. You also
propose NEW recurring patterns you find strong evidence for. You do NOT compute scores or
render anything.

DISCIPLINE — only REAL patterns:
A pattern qualifies only if it (a) recurs on a calendar/seasonal cycle, (b) affects MULTIPLE
industries OR logistics nodes OR countries OR regions, and (c) has a Tier 1-3 source. One-off
events, single-company incidents, and pure trends without seasonality are NOT patterns. When in
doubt, do not propose it.

OUTPUT — delimiter blocks only, no JSON wrapper, no markdown fences.

For each reviewed pattern, emit one or more observation readings (the current real-world value of
its materialisation metric, if you can find it):
###BEGIN:OBSERVATION###
pattern_id: atl-hurricane
metric_name: named_storms_atlantic_ytd
metric_value: 3
unit: count
region: NA-Gulf
window_phase: ramp
materialization: on_track
source: NOAA NHC
source_tier: 1
notes: 3 named storms by mid-May, slightly above the 1991-2020 pace
###END:OBSERVATION###

window_phase is one of: pre | ramp | peak | decline | off.
materialization is one of: emerging | on_track | accelerating | below_expectation | n/a.

For a genuinely new recurring pattern (rare — hold the bar high):
###BEGIN:CANDIDATE_PATTERN###
pattern_id: cyber-quarter-end-bec
name: Quarter-end BEC payment-fraud spike
category: cyber
subtype: bec_quarter_end
recurrence: cyclical
start_month: 3
peak_start_month: 3
peak_end_month: 3
end_month: 4
regions: NA-Gulf|EU-Industrial
countries_iso3: USA|GBR
industries: warehousing|food_processing
commodities:
chokepoints:
baseline_severity: 2
confidence: low
sources: fbi_ic3
search_queries: quarter end business email compromise spike
materialization_metric: bec_complaints_quarter_end
methodology_note: IC3 data suggests BEC payment fraud clusters at quarter-end close cycles
###END:CANDIDATE_PATTERN###

Region IDs must come from: ME-PersianGulf, ME-RedSea, AS-Malacca, AS-TaiwanStrait, AS-NWPacific,
AS-South, EU-Industrial, EU-North, EU-Med, NA-Gulf, NA-Panama, GL-Arctic, NA-USWest, AF-Sahel,
EU-BlackSea. If a candidate needs a region not in this list, note it in methodology_note and pick
the closest; do not invent region IDs.

If nothing material found for the batch:
###BEGIN:RESEARCH_STATUS###
status: no_material_findings
reason: <one line>
###END:RESEARCH_STATUS###

Cap at ~{MAX_WEB_SEARCHES} searches. The first three characters of your response must be "###".
"""

    user_prompt = f"""## Patterns due for review

{due_block}

## Your task

For each pattern above, run its search queries (and judgement) to find the current value of its
materialisation metric and assess whether it is on track, accelerating, emerging, or below
expectation versus its recurring baseline. Emit one OBSERVATION block per metric reading you can
substantiate with a Tier 1-3 source.

Separately, if you encounter strong evidence of a NEW recurring, multi-industry/multi-region
pattern not in the list, emit a CANDIDATE_PATTERN block (hold the bar high).

Output only delimiter blocks.
"""
    return system_prompt, user_prompt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--max", type=int, default=DEFAULT_MAX_REVIEW)
    args = parser.parse_args()

    if "ANTHROPIC_API_KEY" not in os.environ:
        print("[research] ANTHROPIC_API_KEY missing — skipping.", file=sys.stderr)
        return 0

    today = datetime.now(timezone.utc).date()
    today_iso = today.isoformat()
    run_id = f"{today_iso}-research"

    fieldnames, rows = read_patterns()
    due = [r for r in rows if due_for_review(r, today, args.all)][: args.max]
    if not due:
        print("[research] no patterns due for review.")
        return 0
    print(f"[research] reviewing {len(due)} pattern(s).", flush=True)

    system_prompt, user_prompt = build_prompt(due, today_iso)
    client = Anthropic()
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_WEB_SEARCHES}],
    ) as stream:
        final = stream.get_final_message()
    text = "\n".join(b.text for b in final.content if getattr(b, "type", None) == "text").strip()
    if not text:
        print("[research] empty response.", file=sys.stderr)
        return 0

    observations: list[dict] = []
    candidates: list[dict] = []
    for m in BLOCK_RE.finditer(text):
        kind, body = m.group(1), m.group(2).strip()
        kv = parse_kv_block(body)
        if kind == "OBSERVATION":
            cat = next((r["category"] for r in rows if r["pattern_id"] == kv.get("pattern_id")), "")
            observations.append({
                "observation_date": today_iso, "run_id": run_id,
                "pattern_id": kv.get("pattern_id", ""), "category": cat,
                "search_query": kv.get("search_query", ""), "source": kv.get("source", ""),
                "metric_name": kv.get("metric_name", ""), "metric_value": kv.get("metric_value", ""),
                "unit": kv.get("unit", ""), "region": kv.get("region", ""),
                "window_phase": kv.get("window_phase", ""), "materialization": kv.get("materialization", ""),
                "source_tier": kv.get("source_tier", ""), "notes": kv.get("notes", ""),
            })
        elif kind == "CANDIDATE_PATTERN":
            if not kv.get("pattern_id") or any(r["pattern_id"] == kv["pattern_id"] for r in rows):
                continue
            row = {fn: kv.get(fn, "") for fn in fieldnames}
            row["pattern_id"] = kv["pattern_id"]
            row["status"] = "candidate"
            row["first_identified"] = today_iso
            row["last_reviewed"] = today_iso
            candidates.append(row)

    # Update last_reviewed on the patterns we reviewed.
    reviewed_ids = {r["pattern_id"] for r in due}
    for r in rows:
        if r["pattern_id"] in reviewed_ids:
            r["last_reviewed"] = today_iso
    rows.extend(candidates)
    write_patterns(fieldnames, rows)

    if observations:
        append_observations(observations)

    print(f"[research] observations appended={len(observations)} candidates added={len(candidates)} "
          f"patterns reviewed={len(reviewed_ids)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
