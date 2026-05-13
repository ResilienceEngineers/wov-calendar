#!/usr/bin/env python3
"""Triage new candidate signals into typed active_events.json records.

Inputs (gathered by the orchestrator):
  - hormuz_snapshot.json (today's brief from upstream)
  - fm_events.json (today's FM scrape)
  - active_events.json (existing, for dedup)
  - data/vocab/*.json (controlled vocabulary)

Sends to Claude (Sonnet 4.6, streaming, web_search). Claude returns
###BEGIN:JSON_EVENT### blocks containing one full active_events record each.
Script parses, dedups, validates, appends.
"""
from __future__ import annotations

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

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_OUTPUT_TOKENS = int(os.environ.get("CLAUDE_MAX_TOKENS", "16000"))
MAX_WEB_SEARCHES = int(os.environ.get("CLAUDE_MAX_SEARCHES", "8"))

EVENT_SCHEMA = json.loads((DATA / "schema" / "active_events.schema.json").read_text(encoding="utf-8"))
EVENT_ITEM = EVENT_SCHEMA["properties"]["events"]["items"]

BLOCK_RE = re.compile(
    r"###BEGIN:([A-Z_]+)###\s*\n(.*?)\n\s*###END:\1###",
    re.DOTALL,
)


def load_json(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def vocab_summary() -> str:
    regions = load_json("data/vocab/regions.json")["regions"]
    industries = load_json("data/vocab/industries.json")["industries"]
    commodities = load_json("data/vocab/commodities.json")["commodities"]
    chokepoints = load_json("data/vocab/chokepoints.json")["chokepoints"]
    severity = load_json("data/vocab/severity.json")["levels"]
    return (
        "REGIONS:\n" + "\n".join(f"- {r['id']}: {r['name']}" for r in regions) +
        "\n\nINDUSTRIES:\n" + "\n".join(f"- {i['id']}: {i['name']}" for i in industries) +
        "\n\nCOMMODITIES:\n" + "\n".join(f"- {c['id']}: {c['name']}" for c in commodities) +
        "\n\nCHOKEPOINTS:\n" + "\n".join(f"- {c['id']}: {c['name']}" for c in chokepoints) +
        "\n\nSEVERITY:\n" + "\n".join(f"- {s['level']} ({s['label']}): {s['trigger']}" for s in severity)
    )


def build_prompts(today_iso: str) -> tuple[str, str]:
    procedure = (ROOT / "daily-update-prompt.md").read_text(encoding="utf-8")
    methodology_short = "Signal tiers: Hard x5 (verified physical event), Medium x3 (authorized order not yet effective), Soft x1 (statement/forecast), Noise x0. Required: >=1 Tier 1-3 source per event. Severity 1-5 must match a vocab/severity.json trigger. Map every region/industry/commodity/chokepoint onto controlled vocab (no invented IDs)."
    knowledge = (ROOT / "knowledge-base.md").read_text(encoding="utf-8")[:4000]
    sources = (ROOT / "sources.md").read_text(encoding="utf-8")[:1500]
    vocab = vocab_summary()
    hormuz = json.dumps(load_json("data/hormuz_snapshot.json")["snapshot"], indent=2)[:4000]
    fm = json.dumps(load_json("data/fm_events.json")["events"][:25], indent=2)[:4000]
    existing = json.dumps([{"id": e["id"], "title": e["title"], "start_date": e["start_date"]} for e in load_json("data/active_events.json")["events"]], indent=2)[:4000]

    system_prompt = f"""You are the WoV Triage Agent. Today: {today_iso}.

You read candidate signals and return typed JSON event records for the WoV calendar.
You DO NOT invent vocabulary IDs. You DO NOT compute overlap scores. You DO NOT render HTML.
You DO classify, dedup, severity-grade, and source-attribute.

**Theory-of-Constraints rule for maritime chokepoints — non-negotiable.**
The named maritime chokepoints (Hormuz, Bab el-Mandeb, Suez, Malacca, Panama Canal,
Taiwan Strait, Bosphorus) are the constraint of global maritime flow. ANY event that
touches one of these — even a single statement, even from a Tier-3 source — must be
returned as a JSON_EVENT with the chokepoint ID in its `chokepoints` field. Do not
suppress events for "low severity" or "single source" if the event touches a chokepoint.
The downstream overlap engine surfaces single-event chokepoint observations on the
constraint board. Your job is to feed that board, not to filter it.

For non-chokepoint signals (strikes at non-chokepoint ports, generic geopolitical
unrest, etc.), the normal Tier 1-3 corroboration rule applies.

OUTPUT FORMAT — delimiter blocks, no JSON wrapping the outer response, no markdown fences.

For each net-new or superseding event:
###BEGIN:JSON_EVENT###
{{ raw JSON object matching the active_events schema }}
###END:JSON_EVENT###

For each Tier-4/5/6-only candidate (lead, not band):
###BEGIN:JSON_LEAD###
{{ "candidate": "...", "reason_excluded": "...", "source_url": "..." }}
###END:JSON_LEAD###

For vocab gaps:
###BEGIN:VOCAB_GAP###
field: industries
suggested_id: pharma_active_ingredients
context: "Hubei API plant flooding affects EU generics — no existing pharma_api ID in vocab"
###END:VOCAB_GAP###

If no net-new events:
###BEGIN:TRIAGE_STATUS###
status: insufficient_signal
reason: <one line>
###END:TRIAGE_STATUS###

Methodology (compact):
{methodology_short}

CONTROLLED VOCABULARY — every regions/industries/commodities/chokepoints value MUST come from this list:
{vocab}

The first three characters of your response must be "###". The last three must be "###".
"""

    user_prompt = f"""## Procedure (canonical)

{procedure}

## Knowledge base (Marco's context)

{knowledge}

## Sources

{sources}

## Today's hormuz-tracker snapshot

```json
{hormuz}
```

## Today's FM events (top 25)

```json
{fm}
```

## Existing active events (for dedup; full file at data/active_events.json)

```json
{existing}
```

Now: produce JSON_EVENT blocks for any net-new geopolitical / strike / port-closure /
infrastructure-attack / sanctions / cyber / natural-realized event you can substantiate
with >=1 Tier 1-3 source. Use web_search to corroborate. Cap at ~{MAX_WEB_SEARCHES} searches.
Output only delimiter blocks.
"""
    return system_prompt, user_prompt


def parse_blocks(text: str) -> dict[str, list[str]]:
    by_kind: dict[str, list[str]] = {"JSON_EVENT": [], "JSON_LEAD": [], "VOCAB_GAP": [], "TRIAGE_STATUS": []}
    for m in BLOCK_RE.finditer(text):
        kind = m.group(1)
        if kind in by_kind:
            by_kind[kind].append(m.group(2).strip())
    return by_kind


def main() -> int:
    if "ANTHROPIC_API_KEY" not in os.environ:
        print("[triage] ANTHROPIC_API_KEY missing.", file=sys.stderr)
        return 1

    today_iso = datetime.now(timezone.utc).date().isoformat()
    system_prompt, user_prompt = build_prompts(today_iso)

    print(f"[triage] calling {MODEL} with web_search (max {MAX_WEB_SEARCHES} searches)...", flush=True)
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
    print(f"[triage] response length: {len(text)} chars; stop={final.stop_reason}", flush=True)
    if not text:
        print("[triage] empty response; aborting", file=sys.stderr)
        return 2

    blocks = parse_blocks(text)
    print(f"[triage] parsed JSON_EVENT={len(blocks['JSON_EVENT'])} JSON_LEAD={len(blocks['JSON_LEAD'])} VOCAB_GAP={len(blocks['VOCAB_GAP'])} TRIAGE_STATUS={len(blocks['TRIAGE_STATUS'])}", flush=True)

    target = DATA / "active_events.json"
    current = json.loads(target.read_text(encoding="utf-8"))
    by_id: dict[str, dict] = {e["id"]: e for e in current["events"]}

    validator = Draft202012Validator(EVENT_ITEM)
    added = 0
    superseded = 0
    skipped = 0

    for raw in blocks["JSON_EVENT"]:
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"[triage] skipping malformed JSON_EVENT: {e}", file=sys.stderr)
            skipped += 1
            continue
        item_errors = sorted(validator.iter_errors(ev), key=lambda e: e.path)
        if item_errors:
            for err in item_errors:
                loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
                print(f"[triage] schema error in {ev.get('id', '<no-id>')}: {loc}: {err.message}", file=sys.stderr)
            skipped += 1
            continue
        eid = ev["id"]
        if ev.get("supersedes") and ev["supersedes"] in by_id:
            by_id[ev["supersedes"]] = {**by_id[ev["supersedes"]], **{k: v for k, v in ev.items() if k not in ("id",)}}
            superseded += 1
        else:
            by_id[eid] = ev
            added += 1

    out = {
        "$comment": current.get("$comment", "Live geopolitical / strike / port-closure events. Bot-owned."),
        "events": sorted(by_id.values(), key=lambda e: e["start_date"], reverse=True),
    }
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    leads_path = DATA / ".leads"
    leads_path.mkdir(exist_ok=True)
    if blocks["JSON_LEAD"]:
        (leads_path / f"{today_iso}.jsonl").write_text("\n".join(blocks["JSON_LEAD"]) + "\n", encoding="utf-8")
    if blocks["VOCAB_GAP"]:
        (leads_path / f"{today_iso}-vocab-gaps.txt").write_text("\n\n".join(blocks["VOCAB_GAP"]) + "\n", encoding="utf-8")

    print(f"[triage] added={added} superseded={superseded} skipped={skipped} total={len(by_id)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
