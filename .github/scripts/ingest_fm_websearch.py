#!/usr/bin/env python3
"""Web-search FM ingestion supplement.

Two ingestion paths for force-majeure declarations:
  1. Upstream fm-tracker scrape (ingest_fm_tracker.py) — primary path
  2. THIS script — Claude + web_search hunting for FM statements in global press
     (Reuters, FT, Bloomberg, S&P Platts, Argus, ICIS, sector trades, company
     press releases). Used as supplement OR fallback when upstream returns thin.

Output: ###BEGIN:JSON_FM_EVENT### delimiter blocks. Script parses, validates, upserts
into fm_events.json using the same hash-based ID scheme as ingest_fm_tracker.py.

Usage:
  python ingest_fm_websearch.py              # always runs
  python ingest_fm_websearch.py --if-thin    # only runs if upstream produced < 3 new events
                                              # (cheaper; reads the orchestrator's marker)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
PUBLIC_URL = "https://resilienceengineers.github.io/fm-tracker/"

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_OUTPUT_TOKENS = int(os.environ.get("CLAUDE_FM_MAX_TOKENS", "12000"))
MAX_WEB_SEARCHES = int(os.environ.get("CLAUDE_FM_MAX_SEARCHES", "8"))

EVENT_SCHEMA = json.loads((DATA / "schema" / "fm_events.schema.json").read_text(encoding="utf-8"))
ITEM_SCHEMA = EVENT_SCHEMA["properties"]["events"]["items"]

BLOCK_RE = re.compile(
    r"###BEGIN:([A-Z_]+)###\s*\n(.*?)\n\s*###END:\1###",
    re.DOTALL,
)


def load_json(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def stable_id(declared_at: str, declarant: str, facility: str, commodity_class: str) -> str:
    raw = f"{declared_at}|{declarant}|{facility}|{commodity_class}".lower()
    return "fm-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def vocab_summary() -> str:
    regions = load_json("data/vocab/regions.json")["regions"]
    industries = load_json("data/vocab/industries.json")["industries"]
    commodities = load_json("data/vocab/commodities.json")["commodities"]
    return (
        "REGIONS:\n" + "\n".join(f"- {r['id']}: {r['name']}" for r in regions) +
        "\n\nINDUSTRIES:\n" + "\n".join(f"- {i['id']}: {i['name']}" for i in industries) +
        "\n\nCOMMODITIES:\n" + "\n".join(f"- {c['id']}: {c['name']}" for c in commodities)
    )


def build_prompts(today_iso: str, existing_fm_titles: list[str]) -> tuple[str, str]:
    existing_block = "\n".join(f"- {t}" for t in existing_fm_titles[:30]) or "(none yet)"
    vocab = vocab_summary()

    system_prompt = f"""You are the WoV FM Web-Search Agent. Today: {today_iso}.

Your job: find force-majeure declarations issued or reported in the trailing 14 days that
are NOT already in our database. Sources to prioritise (Tier 1-3 first):
  - Reuters, FT, Bloomberg, AP, Argus, S&P Platts, ICIS
  - Industry trade press: Chemical Week, OPIS, Lloyd's List, Hellenic Shipping News
  - Company press releases / 8-K filings
  - Sector regulatory notices (FERC for energy, EPA, equivalents)

You DO NOT invent vocabulary. You DO NOT score. You DO classify by commodity_class and
infer downstream industries from the controlled vocabulary below.

OUTPUT FORMAT — delimiter blocks, no JSON wrapping the outer response, no markdown fences.

For each NEW FM event you find with a Tier 1-3 source:
###BEGIN:JSON_FM_EVENT###
{{
  "declarant": "BASF",
  "facility": "Ludwigshafen",
  "country_iso3": "DEU",
  "declared_at": "2026-05-12",
  "commodity_class": "industrial_gases",
  "products": ["ammonia", "acetylene"],
  "wave": 1,
  "fm_type": "Production",
  "status": "red",
  "signal_tier": "hard",
  "source_tier": 1,
  "regions_affected": ["EU-Industrial"],
  "industries_downstream": ["chem_basic", "fertilizers"],
  "estimated_duration_days": 21,
  "source_doc_url": "https://reuters.com/..."
}}
###END:JSON_FM_EVENT###

Notes:
- DO NOT include an "id" field — the orchestrator computes it as hash(declared_at + declarant + facility + commodity_class).
- declared_at MUST be YYYY-MM-DD.
- country_iso3 MUST be 3 uppercase letters (ISO 3166-1 alpha-3).
- regions_affected, industries_downstream MUST use the vocab below.
- commodity_class is free-text but should align with the commodities vocab where possible (e.g. "industrial_gases", "crude_oil", "lng").
- wave is 1, 2, or 3 (Production / Allocation / Physical-absence per the Three Waves model).
- status: red = declared and active; amber = likely / imminent; green = restart / lifted.

If you find NO new FM events for today:
###BEGIN:JSON_FM_STATUS###
status: nothing_new
reason: <one line — e.g. "all 14-day FM declarations already tracked", "no Tier 1-3 sources found">
###END:JSON_FM_STATUS###

CONTROLLED VOCAB (use these IDs only):
{vocab}

The first three characters of your response must be "###". The last three must be "###".
Cap at ~{MAX_WEB_SEARCHES} searches. Be disciplined.
"""

    user_prompt = f"""## Already-tracked FM events (skip these — find net-new only)

{existing_block}

## Your task

Search the global press for force-majeure declarations issued or reported in the
last 14 days. Aim for the materially significant ones — operators with global supply
exposure, named commodities or chemicals, refineries / petrochem complexes / chemical
plants / mines / smelters / mills / large agricultural facilities, port facilities.

Skip rumours. Skip op-eds. Skip "force majeure" used metaphorically. Only declared
or imminent force-majeure events with a verifiable source (corporate notice, regulatory
filing, or Tier 1-3 wire / specialist publication reporting on one).

Output only delimiter blocks per the system prompt.
"""
    return system_prompt, user_prompt


def parse_blocks(text: str) -> dict[str, list[str]]:
    by_kind: dict[str, list[str]] = {"JSON_FM_EVENT": [], "JSON_FM_STATUS": []}
    for m in BLOCK_RE.finditer(text):
        kind = m.group(1)
        if kind in by_kind:
            by_kind[kind].append(m.group(2).strip())
    return by_kind


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--if-thin", action="store_true",
                        help="Only run if upstream fm-tracker scrape added <3 events today (cheaper).")
    args = parser.parse_args()

    if "ANTHROPIC_API_KEY" not in os.environ:
        print("[fm_web] ANTHROPIC_API_KEY missing — skipping.", file=sys.stderr)
        return 0

    target = DATA / "fm_events.json"
    current = json.loads(target.read_text(encoding="utf-8"))
    by_id: dict[str, dict] = {e["id"]: e for e in current["events"]}

    if args.if_thin:
        today_iso = datetime.now(timezone.utc).date().isoformat()
        added_today = sum(1 for e in current["events"] if e.get("declared_at", "").startswith(today_iso))
        if added_today >= 3:
            print(f"[fm_web] upstream already added {added_today} today — skipping web-search (--if-thin).")
            return 0

    existing_titles = [f"{e.get('declared_at')} · {e.get('declarant')} · {e.get('facility')} · {e.get('commodity_class')}" for e in current["events"][:50]]
    today_iso = datetime.now(timezone.utc).date().isoformat()

    system_prompt, user_prompt = build_prompts(today_iso, existing_titles)

    print(f"[fm_web] calling {MODEL} with web_search (max {MAX_WEB_SEARCHES})...", flush=True)
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
        print("[fm_web] empty response.", file=sys.stderr)
        return 0

    blocks = parse_blocks(text)
    print(f"[fm_web] parsed JSON_FM_EVENT={len(blocks['JSON_FM_EVENT'])} JSON_FM_STATUS={len(blocks['JSON_FM_STATUS'])}", flush=True)

    validator = Draft202012Validator(ITEM_SCHEMA)
    added = 0
    skipped = 0
    for raw in blocks["JSON_FM_EVENT"]:
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"[fm_web] malformed JSON_FM_EVENT skipped: {e}", file=sys.stderr)
            skipped += 1
            continue
        if "id" not in ev:
            ev["id"] = stable_id(ev.get("declared_at", ""), ev.get("declarant", ""), ev.get("facility", ""), ev.get("commodity_class", ""))
        if ev["id"] in by_id:
            continue
        item_errors = sorted(validator.iter_errors(ev), key=lambda e: e.path)
        if item_errors:
            for err in item_errors:
                loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
                print(f"[fm_web] schema error in {ev['id']}: {loc}: {err.message}", file=sys.stderr)
            skipped += 1
            continue
        by_id[ev["id"]] = ev
        added += 1

    out = {
        "$comment": current.get("$comment", "Force-majeure events scraped from fm-tracker. Bot-owned."),
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source_url": current.get("source_url", PUBLIC_URL),
        "events": sorted(by_id.values(), key=lambda e: e["declared_at"], reverse=True),
    }
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[fm_web] added={added} skipped={skipped} total={len(by_id)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
