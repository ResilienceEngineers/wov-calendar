# Backtest Log — Window of Vulnerability

The discipline lives here. Every weekly review makes falsifiable convergence-cluster predictions; this file scores them.

---

## How this works

Each daily entry logs:
1. **Top-5 convergence clusters surfaced** — axis, axis_value, score, member event IDs
2. **Any cluster crossing the surface threshold (5.5) for the first time** — flagged for T+7/T+14/T+30 scoring
3. **Any cluster falling below threshold** — exit log

Each Friday entry adds:
4. **T+7 / T+14 / T+30 scoring** — Hit / Miss / False alarm / Surprise for clusters surfaced 7, 14, 30 days ago
5. **Brier score** on probabilistic `cluster.confidence` predictions
6. **Source reliability tally** — which sources surfaced Hard signal early, which generated noise
7. **One methodology delta** — heuristic added, removed, or sharpened (logged in `methodology.md` §11)

Scoring happens **before** the new triage pass each morning. No commit lands without scoring the prior week's clusters on Fridays.

---

## Calibration metrics

- **Cluster materialization rate** — % of clusters at score >7 that produced realized supply-chain impact within 30 days. Target: >50%.
- **False alarm rate** — % of clusters at score >7 that produced no realized impact within 30 days. Target: <30%.
- **Surprise rate** — number of materialized impacts with no member cluster at T-7. Target: <1 per week.
- **Brier score** on cluster `confidence` (computed weekly). Target: <0.20.
- **Source noise ratio** — per source, ratio of "Hard signal early" to "false alarm" contributions. Logged in `data/sources.json`.

---

## Daily entries

---

### 2026-05-13 (tracker launch — day 0)

**Top-5 convergence clusters at launch:** (none yet — seasonal_bands populated; active_events and fm_events start empty; first triage pass runs at 06:00 UTC on 2026-05-14)

**Predictions to score at T+7 (2026-05-20), T+14 (2026-05-27), T+30 (2026-06-12):**
- No cluster predictions yet — first daily run will populate

**Source notes:**
- Initial tier weights as listed in `sources.md`. No calibration history yet.

---

## Source reliability tally (running)

When a source materially helps or hurts cluster calibration, log it here. Mirrors `data/sources.json.reliability_score`.

| Source | Hard signal early | False alarm | Net |
|--------|-------------------|-------------|-----|
| (initial — no entries yet) | | | |

---

## Methodology deltas (running)

When a Friday Week-in-Review identifies a methodology change, append it here with date and reason.

| Date | Delta | Reason |
|------|-------|--------|
| 2026-05-13 | Initial methodology established | Tracker launch |
