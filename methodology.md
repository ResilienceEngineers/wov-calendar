# Window of Vulnerability — Methodology

**Purpose:** Produce a daily, signal-disciplined risk calendar that supply-chain and resilience leaders can act on without caveat. The calendar's unit of work is the **typed time-bounded band**; the calendar's value is **convergence detection** — naming when multiple bands stack on the same region, industry, commodity, or chokepoint.

This document is the operating manual. The daily-update prompt enforces it. The backtest log measures whether it works.

---

## 1. Operating principles (Taleb-grounded)

### 1.1 Signal vs noise — the four-tier weighting

Every input is classified before it can shape the calendar.

| Tier | What | Examples | Weight |
|------|------|----------|--------|
| **Hard** | Verified physical event, ratified order, agency advisory issued, FM declaration filed, AIS-confirmed movement | NOAA NHC bulletin, UKMTO incident, OFAC designation, BASF Ludwigshafen FM filed, port-authority closure notice | ×5 |
| **Medium** | Authorized order not yet effective, formal closure announcement, certified strike vote | IRGC commander order, MFA closure of airspace, dock-workers' strike authorization | ×3 |
| **Soft** | Forecast, preliminary outlook, statement from authorized voice not yet acted on | Seasonal outlook from CPC, "officials say" attribution, parliamentary resolution | ×1 |
| **Noise** | Anonymous attribution, op-ed, social media chatter, AI summaries, repeat-statements | X/Telegram OSINT, columnist speculation, leaked drafts | ×0 |

**Rule:** A claim that creates or modifies a band must be supported by at least one **Hard** source and one independent **Tier 1–3** corroboration. Lower-tier inputs are leads, not bands.

### 1.2 Base rates before exceptions

Seasonal bands are climatological — the **baseline** is the 30-year normal from the issuing agency. A 2026 deviation only matters if the agency itself flags it (e.g., NOAA "60% above-normal" Atlantic outlook). One above-normal forecast is not a trend; three consecutive seasonal authorities agreeing is.

### 1.3 Convexity beats consensus

Tail risks dominate. A 5% probability of Hormuz formal closure × catastrophic impact > 80% probability of "broadly stable." Convergence scoring (§5) deliberately rewards clusters that contain low-probability / high-severity members, not just frequency.

### 1.4 Lindy on patterns, anti-Lindy on novelty

- Long-running seasonal patterns (hurricane, monsoon) have inertia; bands hold until an agency revises the window.
- Novelty (a new chokepoint disruption type, an unprecedented strike, a force-majeure on a previously stable supplier) is a regime-change signal. Triage weights it.

### 1.5 Distinguish "no events" from "no detection"

A region with zero active_events in trailing 30 days is signal **only if** ingesters returned successful runs reporting nil. A failed scrape is not silence.

### 1.6 Asymmetric updating (Popper)

Every weekly Friday delta makes falsifiable convergence-cluster predictions: "By T+7, cluster X members will all still be active." Brier scores them. Methodology updates when predictions fail, not when they succeed.

### 1.7 No hindsight reframing

Once a convergence cluster is scored and surfaced, the score cannot be retroactively softened. Calibration is meaningless if "we surfaced cluster X at score 8.4" gets re-described as "we flagged it as worth watching" after the materialization fails.

---

## 2. Bands — what counts, what doesn't

A **band** is any time-bounded typed record in the calendar:
- **Pattern band** — recurring, evidence-based windows. Five families: `weather`, `cargo_crime`, `cyber`, `conflict_cycle`, `labor_cycle`. The single source of truth is **`data/patterns.csv`** (see §2.1). `build_patterns.py` resolves each pattern's month-level window into concrete dates and emits `seasonal_bands.json` (weather rows, geo-rich) + `pattern_bands.json` (the other four families).
- **Active event** (from `active_events.json`) — `start_date / est_end`, populated by the daily triage pass from ingested signals.
- **FM event** (from `fm_events.json`) — `declared_at / declared_at + estimated_duration_days`, dual-path ingestion (§9).
- **Hormuz snapshot** (from `hormuz_snapshot.json`) — sustained-state representation of upstream hormuz-tracker threat level + watchlist.
- **User analysis** (from `user_analyses.json`) — `uploaded_at` + per-horizon timeline projection (T+7, T+30, T+90).

Every band declares its industries, commodities, chokepoints, regions — pulled from `data/vocab/*.json`, no free text. FK integrity is enforced by `validate_schemas.py`. Severity is 1–5 per `data/vocab/severity.json`; `signal_tier` is `hard | medium | soft | noise`; `source_tier` is 1–6.

### 2.1 Patterns — the single source of truth, and the "real pattern" bar

`data/patterns.csv` is the canonical registry. One row per pattern, with: category, month windows (start/peak/end), regions, countries, industries, commodities, chokepoints, baseline severity, confidence, **sources**, **search_queries**, **materialization_metric**, methodology note, first_identified, last_reviewed, status.

A row qualifies as a **real pattern** only if it:
1. recurs on a calendar/seasonal cycle (not a one-off, not a pure trend),
2. affects **multiple** industries OR logistics nodes OR countries OR regions, and
3. carries at least one Tier 1–3 source and a measurable materialization metric.

Chronic-but-aseasonal phenomena (e.g. Mexico highway hijacking) are documented in notes but are **not** calendar bands, because they have no temporal pattern to plot. The pattern families and their authorities:
- **weather** — NOAA NHC/CPC/SPC, JMA, JTWC, IMD, Météo-France, ECMWF, DWD, Copernicus EFFIS/EFAS, NIFC, FAO Locust.
- **cargo_crime** — Verisk CargoNet, TAPA EMEA, BSI, FBI IC3, NICB. (Q4 holiday surge, summer long-weekend spikes, EU festive period.)
- **cyber** — CISA, FBI IC3, ENISA, Recorded Future, Check Point. (Holiday/weekend ransomware, tax-season phishing, Black Friday e-commerce surge.)
- **conflict_cycle** — ACLED, UCDP, CFR Global Conflict Tracker. (Sahel dry-season violence, Black Sea grain-corridor harvest/escalation window.)
- **labor_cycle** — Reuters + ACLED + sector trackers. (German spring wage round, French autumn strike season, US West Coast port-contract tension.)

### 2.2 Materialization tracking — the observation log

`data/observations.csv` is an append-only longitudinal log. Every research run (§8.3) appends rows: `observation_date, run_id, pattern_id, category, search_query, source, metric_name, metric_value, unit, region, window_phase, materialization, source_tier, notes`. This is how we see a pattern "take off" — e.g. the Atlantic named-storm count climbing through September against the climatological baseline. `window_phase ∈ {pre, ramp, peak, decline, off}`; `materialization ∈ {emerging, on_track, accelerating, below_expectation, n/a}`.

---

## 3. Sources — six-tier structure

Reused verbatim from the hormuz-tracker pattern. See `sources.md` for the full list and `data/sources.json` for the machine-readable mirror.

- **Tier 1** — Primary, official, verifiable (NOAA NHC, JMA RSMC, IMD, Météo-France, ECMWF, Copernicus EFFIS/GloFAS, FAO Locust, UKMTO, MARAD, OFAC, port-authority bulletins, upstream trackers' raw outputs)
- **Tier 2** — Specialized commercial/operational intelligence with track record (ACLED, GDELT, IMF PortWatch, Kpler, Vortexa, Lloyd's List, IMB Piracy Centre)
- **Tier 3** — Analytical institutions (ICG, ISW, IISS, Chatham, RUSI, CSIS, Oxford Energy)
- **Tier 4** — Commercial analysts with multi-year track records (Kemp, Croft, Alhajji, Eurasia Group)
- **Tier 5** — Wire services and reputable regional/sector press (Reuters, AP, FT, Bloomberg, AFP)
- **Tier 6** — Excluded by default (anonymous OSINT, op-eds, social, AI-summaries) — admitted only after Tier 1–3 corroboration

A claim that survives into the calendar requires at least one Tier 1–3 source. Tier 4–5 are confirming, not originating. Tier 6 is a lead, never a basis.

---

## 4. The triage pass (`triage_with_claude.py`)

Daily, after ingestion, Claude (Sonnet 4.6, streaming, web-search ≤12 uses) is given:
- The new candidate signals from ingestion
- The existing `active_events.json` (for dedup)
- The vocab files (so it can map free-text mentions onto controlled vocabulary IDs)
- The methodology summary

It returns one `###BEGIN:JSON_EVENT###` block per **net-new** event. Each block contains a complete `active_events.json` record. Dedup logic in the script:
1. Exact ID match → skip
2. Same `start_date` + same `regions` ∩ + Jaccard(title-tokens) > 0.7 → mark `supersedes` on the older record
3. Otherwise → new event

Claude does **not** invent industries, commodities, or chokepoints. If the candidate signal does not map cleanly to a vocab ID, Claude returns the event with the field empty and a `notes` line flagging the gap. The Friday review adds vocab entries as needed.

---

## 5. Convergence scoring (`compute_overlaps.py`)

Input: union of seasonal + active + FM + hormuz + user-analysis bands.

For each `axis in {region, industry, commodity, chokepoint}`, for each `axis_value`:
1. Filter bands containing that value.
2. Sweep-line on date intervals to find connected components.
3. Components with ≥N members → candidate cluster. **N = 1 for `axis == "chokepoint"`** (Theory-of-Constraints rule — see §5.1). **N = 2 for all other axes** (normal convergence rule).
4. Cross-axis dedup: if two clusters share ≥80% members, keep the higher-scoring one.

### 5.1 Theory-of-Constraints rule for maritime chokepoints

A maritime chokepoint *is* the constraint of global flow through that geography. There is no substitute path of equivalent capacity. Hormuz, Bab el-Mandeb, Suez, Malacca, Panama Canal, Taiwan Strait, Bosphorus — each carries a single-digit-percent of global trade through a single point. The system therefore monitors every named maritime chokepoint individually and surfaces any single event touching one. That observation appears on the `chokepoint_board` in `overlaps.json` (rendered as the "Chokepoint constraint board" on `index.html`) regardless of cluster convergence.

This rule applies only to maritime chokepoints. For strikes at non-chokepoint ports, generic geopolitical events, or labour disputes inland, the standard 2-or-more convergence requirement applies. A non-chokepoint port strike must intersect another band on a shared region/industry/commodity to surface as a cluster.

Triage prompt enforces the upstream half: Claude must return a JSON_EVENT for any candidate signal that touches a chokepoint ID, even from a single Tier-3 source. The downstream half is encoded in `compute_overlaps.py` via the per-axis minimum-member threshold.

**Score** (clamp [0, 10]):
```
score =   2.0 * log(n_members + 1)
        + mean(severity_i)
        + 1.5 * jaccard(industries) * jaccard(commodities)
        + tier_bonus   # +0.8 per Tier-1, +0.5 per Tier-2, +0.6 per Hard signal
        - 0.5 * count(signal_tier == "soft")
        + chokepoint_multiplier   # ×1.4 if axis_value in {hormuz, suez, bab_mandeb, panama, malacca, taiwan}
```

Surface threshold for executive view: `score ≥ 5.5`. Top 5 by score on `index.html`. Full sorted list on `brief.html`.

---

## 6. Anti-bias defaults

- **Recency bias.** Seasonal bands are climatological — a single off-baseline storm does not move the band. Active events have inherent recency, but the convergence engine cares about temporal overlap, not freshness rank.
- **Confirmation bias.** Every high-scoring cluster (>7) must surface at least one disconfirming signal in its `notes`, if one exists. If none does, say so explicitly.
- **Authority bias.** A senior official saying X without observable change is Soft tier, not Hard. The calendar never elevates a quote to a band.
- **Availability bias.** Coverage volume is excluded from scoring. A region with one Tier-1 advisory beats a region with 50 Tier-6 noise hits.
- **Narrative bias.** Each cluster's `narrative_seed` is one sentence describing the convergence, not a story arc. "Q3 2026 Gulf chokepoint + Atlantic hurricane peak + EU industrial-gas FM converge on energy/chem chain" — not "as tensions mount..."

---

## 7. What the calendar does NOT do

- It does not predict markets.
- It does not recommend specific trades, hedges, or financial positions.
- It does not forecast beyond 90 days (user analyses can; the calendar can't).
- It does not name individual companies as exposed unless an FM declaration is filed.
- It does not assign moral judgment to actors. Behavior is described, not evaluated.

---

## 8. The learning loop

### 8.1 Daily backtest hooks
Every run logs in `backtest-log.md`: the top-5 convergence clusters surfaced, their scores, their member event IDs.

### 8.2 T+7 / T+14 / T+30 checks
Each Friday review scores clusters surfaced 7, 14, and 30 days ago:
- **Hit** — at ≥80% of original members still active or materialized as predicted impact
- **Miss** — cluster dissolved (members ended, regions disconnected, score dropped below threshold)
- **False alarm** — high score (>7), no realized impact in any member region
- **Surprise** — major realized event with no member cluster at T-7

### 8.2a Fortnightly pattern research (1st & 15th)

`research_patterns.py` (workflow `pattern-research.yml`) reviews every pattern whose `last_reviewed` is ≥14 days old. For each, Claude + web_search checks the pattern's sources/queries for the current value of its materialization metric and grades it (`window_phase`, `materialization`). Readings append to `observations.csv`; `last_reviewed` is bumped in `patterns.csv`. Claude may also propose new patterns as `status=candidate` rows (held to the §2.1 bar) for Marco to promote or retire. The run then rebuilds the band JSON, recomputes overlaps, re-renders, and validates.

### 8.3 Weekly calibration (Friday)
- Brier score on probabilistic cluster-materialization (the `confidence` field on each cluster, expressed as %)
- Hit / miss / false-alarm counts
- Source-by-source reliability tally → updates `data/sources.json.reliability_score`
- One concrete methodology delta logged in §11 below

### 8.4 Source weight adjustment
Sources that consistently signal noise get downweighted in `data/sources.json`. Sources that surface Hard signal early get upweighted. Logged.

### 8.5 No silent learning
Every methodology change is logged in §11 with date and reason. Marco audits drift.

---

## 9. The FM ingestion — dual path

Force-majeure declarations enter the calendar through two complementary paths:

**Path 1 — upstream fm-tracker scrape (`ingest_fm_tracker.py`).** Pulls `index.html` from the `resilienceengineers/fm-tracker` `main` branch. Upstream stores events in delimited `BRIEF:*` HTML blocks, not in a JSON sidecar. We compute stable IDs as `sha1(declared_at + declarant + facility + commodity_class)[:12]`. This is sufficient for dedup but brittle if the upstream changes its display fields. A proposed upstream contribution: a `BRIEF:DATA_START/END` block emitting `data/events.json` with stable upstream IDs. Until then, parser changes are logged with a Friday delta.

**Path 2 — web-search supplement (`ingest_fm_websearch.py`).** Claude + `web_search` searches global press (Reuters, FT, Bloomberg, Argus, S&P Platts, ICIS, Chemical Week, OPIS, Lloyd's List, Hellenic Shipping News, sector trade press, corporate press releases, regulatory filings) for FM declarations issued in the trailing 14 days that are not already in our database. Claude returns `###BEGIN:JSON_FM_EVENT###` delimiter blocks; the script computes IDs via the same hash scheme and upserts. Schema-validated before persist.

The orchestrator runs Path 2 with `--if-thin`: it only fires when Path 1 added <3 events on the same day. This makes Path 2 a cheap fallback rather than a duplicating supplement on busy days. Marco can remove the flag in `update_brief.py` to make Path 2 run every day. Both paths converge into the same `data/fm_events.json` keyed by the same ID scheme — no separation of provenance beyond `source_doc_url`. Dedup keeps the first arriver.

---

## 10. Stop conditions — do NOT publish if:

- Today's daily run could not reach Tier 1 sources at all (network failure, all upstream trackers 404)
- `validate_schemas.py` failed (FK integrity violation, schema mismatch)
- Marker-balance sanity check failed on either HTML file
- The triage pass returned zero new events for ≥3 consecutive days (likely scraping break)

In any of these, the run exits non-zero; the workflow surfaces the failure; no commit lands.

---

## 11. Methodology changelog

| Date | Change | Reason |
|------|--------|--------|
| 2026-05-13 | Initial methodology established | Tracker launch |
| 2026-05-13 | Theory-of-Constraints rule added for maritime chokepoints: single-event chokepoint observations surface on a dedicated constraint board, bypassing the 2-or-more convergence requirement | Marco directive: any disruption on the constraint is a disruption on the whole flow |
| 2026-05-13 | FM ingestion split into dual path: upstream fm-tracker scrape + Claude-driven web-search supplement | Resilience against upstream parser drift + coverage of FM events the upstream tracker has not yet ingested |
| 2026-05-13 | Renderer now emits "Today at a glance" deterministic summary, per-cluster "What this means" translations, and "How to read this page" disclosures on both HTML pages | Marco directive: site must be self-explanatory and easy to read at one glance |
| 2026-05-23 | Pattern model generalised to five families (weather + cargo_crime + cyber + conflict_cycle + labor_cycle); `data/patterns.csv` made the single source of truth; `build_patterns.py` generates the band JSON; `data/observations.csv` append-only materialization log added | Marco directive: research all real patterns, add conflict/cargo-crime/cyber data, CSV single source of truth tracking whether patterns take off |
| 2026-05-23 | Fortnightly `research_patterns.py` + `pattern-research.yml` added (1st & 15th); calendar filter bar (family / region / chokepoints-only) added to index.html | Marco directive: regular 14-day check + filterable calendar view |
| 2026-05-23 | Added regions NA-USWest, AF-Sahel, EU-BlackSea and chokepoint la_long_beach; added sources CISA, FBI IC3, ENISA, Recorded Future, Check Point, TAPA EMEA, BSI, CargoNet, NICB, CFR Global Conflict Tracker; added `cyber` + `cargo_crime` source domains | Required to map the new pattern families onto controlled vocabulary |
| 2026-05-23 | Added 8 main-region weather patterns: Central European + Mediterranean (DANA) + China Meiyu + SE Asia monsoon floods, US spring river flood, US West Coast atmospheric river, North American winter storm, Arabian/Gulf dust storm | Audit of main-region weather coverage; flood season was missing entirely |
| 2026-05-23 | iCalendar export added (`build_ics.py`): `calendar.ics` + 5 per-family feeds, regenerated each build, served via GitHub Pages as auto-updating subscription feeds (stable per-event UID). Client-side "Build & export your calendar" panel: add private custom windows, choose which pre-analysed windows to include, one-time .ics download + subscribe links for Outlook/Google/Apple | Marco directive: users add their own windows, choose which to see, export to calendars, and auto-update when something changes |

(Future changes appended here with date and reason.)
