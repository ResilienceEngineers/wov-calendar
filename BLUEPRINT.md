# Window of Vulnerability — Blueprint

Build manual for the WoV risk calendar. Derived from `hormuz-tracker/BLUEPRINT.md` with one fundamental adaptation: the unit of work is **set intersection over time-bounded typed records**, not narrative generation. JSON is canonical; prose appears only where it earns its place.

## Use-case profile

```
TRACKER NAME:           Window of Vulnerability — Global Risk Calendar
TOPIC ONE-LINER:        Aggregates seasonal hazards, active geopolitical events, strikes, FM declarations, and custom commodity-impact analyses into a 12-month calendar with convergence detection.
PRIMARY AUDIENCE:       Supply-chain executives and resilience officers in EU industrials, chemicals, automotive, energy.
GEOGRAPHIC SCOPE:       Global, with 12 curated supply-chain priority regions at launch (see data/vocab/regions.json).
TIME WINDOW:            Rolling 12 months — today minus 30 days, today plus 335 days.
DAY-COUNT ANCHOR:       None (continuous calendar, no episode-bound).

PRIMARY VISUALIZATIONS:
  1. 12-month Gantt ribbon stack (executive view, pure SVG)
  2. Month heatmap by hazard type (deep view)
  3. Geographic Leaflet map with seasonal polygons, active pins, FM pins, analysis overlays
  4. Convergence cluster cards (top 5 on index, full list on brief)
  5. Industry-chain cascade visual for user analyses

DOMAIN WIDGETS:
  - Live events ticker (auto-scroll, hard/medium signal_tier only)
  - FM pulse bar chart (active FM count by industry)
  - User analyses strip (cards linking to brief.html anchors)
  - Source tier legend (auto-generated from sources.json)

SEVERITY DOMAIN:        "Severity" 1–5; triggers in data/vocab/severity.json. Cluster "convergence score" 0–10.

KEY SOURCES (PRIVATE):  See sources.md. Tier 1: NOAA, JMA, IMD, Météo-France, ECMWF, Copernicus, UKMTO, MARAD, OFAC, IMF PortWatch, upstream trackers (hormuz-tracker, fm-tracker). Tier 2: ACLED, GDELT, UCDP, IMB, Kpler, Lloyd's. Tier 3: ICG, ISW, CSIS, OIES.

BRAND:                  Resilience Engineers
CONTACT EMAIL:          marco.felsberger@resilience-engineers.com
GITHUB OWNER:           resilienceengineers
GITHUB REPO NAME:       wov-calendar
SCHEDULE PRIMARY:       06:00 UTC (08:00 CEST in summer / 07:00 CET in winter)
ACCENT COLOR:           Deep red #a4242a (matches hormuz-tracker family)
```

## What this gets you

- A public GitHub Pages site at `https://resilienceengineers.github.io/wov-calendar/`
- An executive one-pager (`index.html`) with a 12-month Gantt, top-5 convergence cards, live ticker, FM pulse
- A deep view (`brief.html`) with heatmap, Leaflet map, full convergence clusters, user analyses gallery
- Daily auto-update via GitHub Actions calling the Claude API (Sonnet 4.6)
- Triage-shaped pipeline: ingest → triage → compute overlaps → render → validate → commit
- A 10-slide "Export PDF for management" button via print CSS
- A private calibration loop scoring convergence clusters at T+7 / T+14 / T+30

## Architectural rules (non-negotiable, inherited from hormuz-tracker)

1. **Claude output uses `###BEGIN:KEY###...###END:KEY###` delimiter blocks, NOT JSON-wrapped responses.** Escape errors on large strings fail at scale. JSON data is allowed *inside* a delimiter block — the wrapper is the delimiter; the block contents are raw JSON text the script parses.
2. **Streaming required** when `max_tokens >= 24000`.
3. **Sonnet 4.6 for daily ops** (`claude-sonnet-4-6`). Opus 4.7 reserved for weekly Brier review.
4. **Six-cron + skip-guard** on GitHub Actions (06:00, 06:23, 07:11, 07:45, 08:30, 10:00 UTC). Single slots drop silently.
5. **HTML compression before sending to Claude** — strip `<style>`, `<script>`, long inline `style=`, blank lines.
6. **Lambda for `re.sub`** when replacement strings contain digits (date string `re.error` bug).
7. **Marker-balance sanity check** after every HTML edit — `<!-- BRIEF:*_START -->` count must equal `_END` count, fail loud.
8. **Bot-owned vs human-owned files**. Bot writes: `data/active_events.json`, `data/fm_events.json`, `data/hormuz_snapshot.json`, `data/overlaps.json`, HTML BRIEF:* blocks, `daily-briefs/`, `backtest-log.md`. Human owns: workflows, scripts, methodology, sources, seasonal_bands, vocabularies, schemas, uploads. Always `git pull --rebase` before local push.
9. **Methodology stays private**. Public page shows one meta paragraph only.
10. **Source/signal tiering reused verbatim**. Hard ×5 / Medium ×3 / Soft ×1 / Noise ×0; Tier 1–6.

## What's different from hormuz-tracker

- **Data layer is first-class**: `data/*.json` with JSON Schema validation, FK integrity to `data/vocab/*.json`. The HTML files read these JSONs at load time and render client-side.
- **Pipeline is multi-stage**: `update_brief.py` is an orchestrator; the real work happens in dedicated scripts (`ingest_*`, `triage_with_claude.py`, `compute_overlaps.py`, `render_pages.py`, `validate_schemas.py`).
- **Claude has a narrow role**: only triage (classify candidates into typed records). Not scraping, not scoring, not rendering. Output is `JSON_EVENT` blocks containing raw JSON text.
- **Prose is rationed**: methodology paragraph, weekly Friday delta, user-analysis `narrative_md`, cluster `narrative_seed`. Everywhere else, structured data wins.
- **Convergence engine** (`compute_overlaps.py`) is the calendar's value-add — deterministic sweep-line + Jaccard scoring. Score formula in `methodology.md` §5.

## Pitfalls (real failures from upstream builds — save yourself the time)

1. **JSON wrapping fails on large strings.** Use delimiters; raw JSON allowed *inside* blocks.
2. **`re.error: invalid group reference`** when date strings start with a digit. Use lambda for `re.sub`.
3. **`max_tokens >= 24000`** triggers SDK 10-min timeout. Use `client.messages.stream()`.
4. **Single scheduled cron drops** silently. Use 6 off-the-hour slots + skip-guard on today's commit message.
5. **Hand-coded SVG coastlines look amateur.** Use Leaflet + CartoDB Positron for the brief.html map.
6. **Blank pages in print PDF.** Only `page-break-after: always` per slide; `:last-child { page-break-after: auto }` on the last slide.
7. **html2canvas chokes on Leaflet tiles** (CORS). Don't try to print the live map; render a "Key sites" table built from pins.
8. **Race conditions** between local edits and bot commits. Always `git pull --rebase` before pushing local changes. Treat bot-owned files as authoritative; your edits go to human-owned files only.
9. **Drift between `sources.md` and `data/sources.json`.** The MD file is for humans; the JSON is the source of truth for the renderer. Update both in the same commit.
10. **Inventing vocabulary during triage.** Claude must flag gaps via `VOCAB_GAP` blocks, never invent IDs. Friday review handles vocab additions.

## What's NOT in this blueprint

- Open-API ingestion (ACLED, GDELT, IMF PortWatch) — wired in v2 once the spine is proven
- Custom domain (CNAME) setup
- Email / Slack notifications when high-score clusters appear
- Authentication / paywall
- Mobile app
- Multilingual versions

## Build stages

### Stage 1 — Repo setup
1. `git init` in `wov-calendar/`
2. Create `.gitignore`, `LICENSE` (MIT), `robots.txt`, `README.md`
3. Verify `gh` CLI authenticated
4. First commit: scaffold
5. Create public GitHub repo: `gh repo create resilienceengineers/wov-calendar --public --source . --remote origin --push`
6. Enable Pages: `gh api -X POST /repos/resilienceengineers/wov-calendar/pages -f "source[branch]=main" -f "source[path]=/"`

### Stage 2 — Operating files (markdown, repo root)
- `methodology.md`, `sources.md`, `knowledge-base.md`, `daily-update-prompt.md`, `backtest-log.md`

### Stage 3 — Data layer
- `data/vocab/*.json` — controlled vocabularies (regions, chokepoints, commodities, industries, severity)
- `data/schema/*.schema.json` — JSON Schema Draft 2020-12 per data file
- `data/seasonal_bands.json` — hand-curated annual seasonality for 2026
- `data/sources.json` — machine-readable mirror of `sources.md`
- Empty seed: `data/active_events.json`, `data/fm_events.json`, `data/hormuz_snapshot.json`, `data/user_analyses.json`, `data/overlaps.json`

### Stage 4 — Python scripts
- `.github/scripts/requirements.txt`
- `.github/scripts/validate_schemas.py`
- `.github/scripts/ingest_user_yaml.py`
- `.github/scripts/ingest_hormuz.py`
- `.github/scripts/ingest_fm_tracker.py`
- `.github/scripts/compute_overlaps.py`
- `.github/scripts/triage_with_claude.py`
- `.github/scripts/render_pages.py`
- `.github/scripts/update_brief.py` (orchestrator)

### Stage 5 — HTML pages
- `index.html` — executive view with Gantt SVG + top convergences + live ticker + FM pulse + PDF print export
- `brief.html` — deep view with month heatmap + Leaflet map + full clusters + user analyses gallery

### Stage 6 — Workflows
- `.github/workflows/daily-update.yml` — six-cron + skip-guard
- `.github/workflows/ingest-uploads.yml` — on push to `uploads/**`
- `.github/workflows/weekly-rebuild.yml` — Fridays 06:30 UTC

### Stage 7 — Templates and tests
- `uploads/_template.analysis.yaml`
- `daily-briefs/_template.md`
- `tests/fixtures/sample_bands.json` + `tests/fixtures/expected_overlaps.json` for deterministic overlap-engine test

### Stage 8 — Final
1. Push initial commit
2. Add `ANTHROPIC_API_KEY` to repo secrets at `github.com/resilienceengineers/wov-calendar/settings/secrets/actions/new`
3. Trigger first run: `gh workflow run daily-update.yml`
4. Watch: `gh run watch <id> --exit-status`
5. Verify live URL renders Gantt + ticker + cards
