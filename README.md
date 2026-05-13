# Window of Vulnerability — Global Risk Calendar

A 12-month risk calendar synthesising seasonal hazards, active geopolitical events, supply-chain strikes, force-majeure declarations, and custom commodity-impact analyses onto a single timeline. Surfaces convergences where multiple risks stack on the same region, industry, commodity, or chokepoint.

Live site: <https://resilienceengineers.github.io/wov-calendar/>

## What this is

This is the third instance of the daily-intelligence-tracker template (after [hormuz-tracker](https://github.com/resilienceengineers/hormuz-tracker) and [fm-tracker](https://github.com/resilienceengineers/fm-tracker)). It differs in one fundamental way: the unit of work is not narrative generation but **set intersection over time-bounded typed records**. Structured JSON is canonical; prose appears only where it earns its place (user analyses, methodology, weekly deltas).

## Two pages

- **`index.html`** — executive view. 12-month Gantt ribbon stack, "now" line, top 5 convergence cards, live events ticker, FM pulse, user analyses strip.
- **`brief.html`** — deep view. Month heatmap, geographic Leaflet map, full convergence clusters faceted by axis, user analyses gallery with industry-chain cascade, methodology + sources.

## Data layout (`data/`)

| File | Owner | Refresh | Purpose |
|---|---|---|---|
| `seasonal_bands.json` | Human | Quarterly | Annual seasonality (hurricane, monsoon, flood, wildfire, cyclone) with start/peak/end |
| `active_events.json` | Bot | Daily | Live geopolitical / strike / port-closure events |
| `fm_events.json` | Bot | Daily | Scraped from fm-tracker |
| `hormuz_snapshot.json` | Bot | Daily | Scraped from hormuz-tracker |
| `user_analyses.json` | Auto from `uploads/` | On push | Marco's commodity-impact chains |
| `sources.json` | Human | As needed | Source registry mirroring `sources.md` |
| `overlaps.json` | Bot derived | Every run | Pre-computed convergence clusters |
| `vocab/*.json` | Human | As needed | Controlled vocabularies (regions, commodities, industries, chokepoints, severity) |
| `schema/*.schema.json` | Human | As needed | JSON Schema Draft 2020-12 |

Bot-owned files are not hand-edited; the daily run regenerates them. Human-owned files (workflows, scripts, methodology, sources, seasonal_bands, vocabularies, schemas, uploads) need `git pull --rebase` before local push.

## How updates work

### Daily — 06:00 UTC primary cron, six off-the-hour slots with skip-guard
The orchestrator (`update_brief.py`) runs:
1. `ingest_hormuz.py` — scrape upstream tracker, write `hormuz_snapshot.json`
2. `ingest_fm_tracker.py` — scrape upstream tracker, upsert `fm_events.json`
3. `triage_with_claude.py` — Sonnet 4.6 + web search; classify new candidate events into typed records via delimiter blocks
4. `compute_overlaps.py` — rebuild `overlaps.json` deterministically
5. `render_pages.py` — inject `BRIEF:*` blocks into both HTML files
6. `validate_schemas.py` — JSON Schema + FK integrity, CI gate
7. Marker-balance sanity check
8. Commit + push

### On YAML upload — `ingest-uploads.yml`
Push to `uploads/**` → `ingest_user_yaml.py` validates and appends to `user_analyses.json` → triggers `compute_overlaps.py`.

### Weekly — Fridays 06:30 UTC
Brier score on last week's convergence predictions, source reliability tally, methodology delta, narrative `daily-briefs/YYYY-MM-DD.md`.

### Quarterly — Jan/Apr/Jul/Oct 1
Manual PR reviewing `seasonal_bands.json` against authoritative outlooks (NOAA, JMA, IMD, Météo-France, Copernicus).

## Claude's role — explicit boundary

Claude is the interpreter, not the engine. It is used **only** for:
1. Triaging raw signals into typed event records (classification, dedup, severity)
2. Writing weekly narrative deltas
3. Generating `narrative_seed` strings for high-scoring overlap clusters

Claude does **not** scrape, compute overlaps, or render HTML structure. Those are deterministic Python.

## Uploading a custom analysis

1. Copy `uploads/_template.analysis.yaml` to `uploads/YYYY-MM-DD-shortname.yaml`
2. Fill in trigger event, industry chain, timeline projection, narrative
3. Commit + push
4. `ingest-uploads.yml` validates the YAML against `data/schema/user_analyses.schema.json` and appends to `user_analyses.json`
5. `compute_overlaps.py` re-runs; the analysis appears on `brief.html` and as a card on `index.html`

## File ownership cheat-sheet

| Human-owned | Bot-owned |
|---|---|
| `workflows/`, `scripts/`, `data/schema/`, `data/vocab/`, `data/seasonal_bands.json`, `data/sources.json`, `methodology.md`, `sources.md`, `BLUEPRINT.md`, `knowledge-base.md`, `uploads/` | `data/active_events.json`, `data/fm_events.json`, `data/hormuz_snapshot.json`, `data/overlaps.json`, `data/user_analyses.json`, `index.html` (BRIEF:* blocks), `brief.html` (BRIEF:* blocks), `daily-briefs/`, `backtest-log.md` |

Always `git pull --rebase` before pushing local changes.

## See also

- `BLUEPRINT.md` — full build manual
- `methodology.md` — operating doctrine (signal tiers, anti-bias, scoring, learning loop)
- `sources.md` — six-tier source list
- `backtest-log.md` — calibration log (internal)
