# Daily Update Procedure — Window of Vulnerability

This is the prompt the scheduled task runs each morning at 06:00 UTC primary slot. Also the manual-run prompt: paste into a fresh Claude session at any time to triage today's new candidates.

The triage pass is **deterministic-shaped, Claude-classified**. Claude does not invent events, does not invent vocabulary, does not score overlaps, does not render HTML. Claude reads candidate signals, maps them onto the controlled vocabulary, and returns typed JSON records that the orchestrator validates and persists.

---

## 0. Before you classify a single event

Read these inputs (the orchestrator passes them as user-message context — do not re-fetch):

1. `methodology.md` §1 (signal tiers), §3 (sources), §5 (convergence scoring), §6 (anti-bias).
2. `sources.md` — six-tier list.
3. `knowledge-base.md` — Marco's project context.
4. `data/vocab/*.json` — controlled vocabulary IDs for regions, industries, commodities, chokepoints, severity bands.
5. Current `data/active_events.json` — for dedup.
6. The new candidate signals from today's ingestion (hormuz-tracker scrape, fm-tracker scrape, anything else the orchestrator collected).

---

## 1. For each candidate signal

### 1.1 Classify the signal tier
- **Hard** — verified physical event, ratified order, agency advisory, FM declaration filed, AIS-confirmed movement
- **Medium** — authorized order not yet effective, formal closure announcement, certified strike vote
- **Soft** — forecast, preliminary outlook, statement not yet acted on
- **Noise** — anonymous attribution, op-ed, social, repeat-statement

Discard Noise. Soft tier appears in `notes` but does not create a band.

### 1.2 Determine if it is net-new
Compare against existing `active_events.json`:
- Exact ID match (computed deterministically) → skip
- Same `start_date` + overlapping `regions` + Jaccard(title-tokens) > 0.7 → return `supersedes: <existing-id>` field with updated severity/notes only
- Otherwise → net-new event

### 1.3 Map onto controlled vocabulary
Pull from `data/vocab/`. Do NOT invent IDs.
- `regions` — from `vocab/regions.json` (12 priority regions at launch)
- `industries` — from `vocab/industries.json`
- `commodities` — from `vocab/commodities.json`
- `chokepoints` — from `vocab/chokepoints.json`
- `severity` 1–5 — from `vocab/severity.json` triggers

If a candidate signal does not map cleanly to a vocab ID, return the event with the corresponding field as an empty array AND add a one-line `notes` entry flagging the gap. Friday review will add the vocab entry if warranted.

### 1.4 Source attribution
At least one Tier 1–3 `source_id` is required. If only Tier 4–6 sources back the candidate, do NOT create a band — flag it under a single `JSON_LEAD` block instead (the orchestrator logs leads, does not surface them).

---

## 2. Output format

Use delimiter blocks. One block per output. Raw JSON inside each block. No JSON wrapping the outer response. No markdown fences.

```
###BEGIN:JSON_EVENT###
{
  "id": "evt-2026-05-13-houthi-redsea-resumption",
  "event_type": "geopolitical_threat",
  "title": "Houthi spokesperson signals resumption of Red Sea strikes",
  "start_date": "2026-05-13",
  "end_date": null,
  "est_end": "2026-06-13",
  "regions": ["ME-RedSea"],
  "countries_iso3": ["YEM"],
  "industries": ["shipping", "insurance_marine"],
  "commodities": ["containerized_general", "crude_oil"],
  "chokepoints": ["bab_mandeb", "suez"],
  "severity": 3,
  "source_tier": 1,
  "signal_tier": "medium",
  "source_ids": ["al_masirah", "ukmto"],
  "upstream_tracker": null,
  "supersedes": null,
  "notes": "Statement on Saba; verbatim translation from al-Masirah broadcast."
}
###END:JSON_EVENT###
```

Emit one `JSON_EVENT` block per net-new or superseding event. Emit a separate block per event — do NOT combine into an array. The orchestrator parses block-by-block so a single malformed block does not break the run.

Optional blocks:
```
###BEGIN:JSON_LEAD###
{ "candidate": "...", "reason_excluded": "Tier 5 only; awaiting Tier 1-3 corroboration", "source_url": "..." }
###END:JSON_LEAD###
```
```
###BEGIN:VOCAB_GAP###
field: industries
suggested_id: pharma_active_ingredients
context: "Hubei API plant flooding affects EU generics — no existing pharma_api ID in vocab"
###END:VOCAB_GAP###
```

---

## 3. Severity guidance (see `data/vocab/severity.json` for full triggers)

| Severity | Label | Trigger |
|---|---|---|
| 1 | Routine | Baseline volatility, no operational disruption |
| 2 | Elevated | Heightened rhetoric or limited incidents, no flow impact |
| 3 | Concerning | Operational disruption visible (delays, queues, premium >0.5%) |
| 4 | Severe | Sustained multi-front escalation; >30% volume reduction OR alternative routes activated under stress |
| 5 | Crisis | Sustained de-facto closure (>80% volume reduction >7 days) AND any of: formal closure announcement, critical-infra strike, alt-route saturation, insurance unobtainable |

A band's severity does not move daily. It is structural. Change requires a documented trigger flip.

---

## 4. Stop conditions — return empty (no JSON_EVENT blocks) and one explicit block:

```
###BEGIN:TRIAGE_STATUS###
status: insufficient_signal
reason: <one line>
###END:TRIAGE_STATUS###
```

If:
- Today's ingestion returned zero new candidates
- All candidates failed the Tier 1–3 corroboration requirement
- The vocab is so misaligned with today's candidates that no event can be created without inventing IDs

The orchestrator logs this and exits 0 (clean — no new events today is itself a signal).

---

## 5. Tone rules (for `notes` and `narrative_seed`)

Apply these to every line:
- Be a practitioner, not a narrator. Talk to peers.
- Lead with the fact, then the why, then the so-what.
- No hedge-everything language. Pick one based on evidence.
- No filler ("it is important to note"), no synonym cycling, no em-dash chains, no "moreover/furthermore," no "in today's complex environment."
- Numbers when available, ranges when not.
- Distinguish "we observe X" from "we believe X."

---

## 6. Output checklist before returning

- [ ] One `JSON_EVENT` block per net-new or superseding event (separately, not in an array)
- [ ] Every `regions` / `industries` / `commodities` / `chokepoints` value resolves into `data/vocab/*` (or field is empty + `VOCAB_GAP` block emitted)
- [ ] At least one Tier 1–3 `source_id` per event
- [ ] Severity matches a `vocab/severity.json` trigger
- [ ] `signal_tier` justified by source tier + nature of evidence
- [ ] Tier-4/5/6-only candidates routed to `JSON_LEAD`, not `JSON_EVENT`
- [ ] No prose outside delimiter blocks. First three characters of response: `###`. Last three: `###`.

The orchestrator's `validate_schemas.py` runs after parsing. Any field that doesn't validate fails the run. Be precise.
