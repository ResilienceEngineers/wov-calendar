#!/usr/bin/env python3
"""Convergence-cluster engine.

Reads union of seasonal_bands, active_events, fm_events, user_analyses into typed
Band records. For each axis in {region, industry, commodity, chokepoint}, for each
axis_value, sweeps temporal overlaps and emits clusters with >=2 members.

Score formula:
    score = 2.0 * log(n + 1)
          + mean(severity)
          + 1.5 * jaccard(industries) * jaccard(commodities)
          + tier_bonus              (+0.8 Tier-1, +0.5 Tier-2, +0.6 per Hard signal)
          - 0.5 * count(signal_tier == "soft")
          + chokepoint_multiplier   (x1.4 if axis_value in major chokepoints)
    clamp [0, 10]

Surface threshold: 5.5. Top 5 by score → index.html executive view.
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

MAJOR_CHOKEPOINTS = {"hormuz", "suez", "bab_mandeb", "panama_canal", "malacca", "taiwan_strait"}
NULL_END_DEFAULT_DAYS = 30
SCORE_FLOOR = 0.0
SCORE_CEIL = 10.0


@dataclass(frozen=True)
class Band:
    id: str
    start: date
    end: date
    regions: frozenset[str]
    industries: frozenset[str]
    commodities: frozenset[str]
    chokepoints: frozenset[str]
    severity: int
    source_tier: int
    signal_tier: str  # hard|medium|soft|noise


def _parse_date(s: str | None, default: date) -> date:
    if s is None:
        return default
    return datetime.strptime(s, "%Y-%m-%d").date()


def load_bands(today: date) -> list[Band]:
    bands: list[Band] = []

    seasonal = json.loads((DATA / "seasonal_bands.json").read_text(encoding="utf-8"))
    for b in seasonal["bands"]:
        bands.append(Band(
            id=b["id"],
            start=_parse_date(b["start_date"], today),
            end=_parse_date(b["end_date"], today + timedelta(days=NULL_END_DEFAULT_DAYS)),
            regions=frozenset(b["regions"]),
            industries=frozenset(b["affected_industries"]),
            commodities=frozenset(b["affected_commodities"]),
            chokepoints=frozenset(b["affected_chokepoints"]),
            severity=b["baseline_severity"],
            source_tier=1,
            signal_tier="hard",
        ))

    active = json.loads((DATA / "active_events.json").read_text(encoding="utf-8"))
    for e in active["events"]:
        end = _parse_date(e.get("end_date"), _parse_date(e.get("est_end"), today + timedelta(days=NULL_END_DEFAULT_DAYS)))
        bands.append(Band(
            id=e["id"],
            start=_parse_date(e["start_date"], today),
            end=end,
            regions=frozenset(e.get("regions", [])),
            industries=frozenset(e.get("industries", [])),
            commodities=frozenset(e.get("commodities", [])),
            chokepoints=frozenset(e.get("chokepoints", [])),
            severity=e["severity"],
            source_tier=e["source_tier"],
            signal_tier=e["signal_tier"],
        ))

    fm = json.loads((DATA / "fm_events.json").read_text(encoding="utf-8"))
    for e in fm["events"]:
        start = _parse_date(e["declared_at"], today)
        duration = e.get("estimated_duration_days") or NULL_END_DEFAULT_DAYS
        end = start + timedelta(days=duration)
        bands.append(Band(
            id=e["id"],
            start=start,
            end=end,
            regions=frozenset(e["regions_affected"]),
            industries=frozenset(e.get("industries_downstream", [])),
            commodities=frozenset(),
            chokepoints=frozenset(),
            severity=3,  # FM declaration default; upstream tracker scores wave-intensity separately
            source_tier=e.get("source_tier") or 1,
            signal_tier=e.get("signal_tier") or "hard",
        ))

    analyses = json.loads((DATA / "user_analyses.json").read_text(encoding="utf-8"))
    for a in analyses["analyses"]:
        horizons = [h["horizon_days"] for h in a["timeline_projection"]]
        start = datetime.fromisoformat(a["uploaded_at"].replace("Z", "+00:00")).date()
        end = start + timedelta(days=max(horizons) if horizons else NULL_END_DEFAULT_DAYS)
        industries = frozenset(stage["industry"] for stage in a["industry_chain"])
        bands.append(Band(
            id=a["id"],
            start=start,
            end=end,
            regions=frozenset(a["regions_affected"]),
            industries=industries,
            commodities=frozenset([a["trigger_commodity"]]) if a.get("trigger_commodity") else frozenset(),
            chokepoints=frozenset(),
            severity=3,
            source_tier=1,  # Marco-curated
            signal_tier="medium",
        ))

    return bands


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 0.0
    u = a | b
    if not u:
        return 0.0
    return len(a & b) / len(u)


def score_cluster(members: list[Band], axis_value: str) -> float:
    n = len(members)
    s = 2.0 * math.log(n + 1)
    s += sum(m.severity for m in members) / n
    industries_union = frozenset().union(*(m.industries for m in members))
    industries_inter = frozenset.intersection(*(m.industries for m in members)) if all(m.industries for m in members) else frozenset()
    commodities_union = frozenset().union(*(m.commodities for m in members))
    commodities_inter = frozenset.intersection(*(m.commodities for m in members)) if all(m.commodities for m in members) else frozenset()
    j_ind = (len(industries_inter) / len(industries_union)) if industries_union else 0.0
    j_com = (len(commodities_inter) / len(commodities_union)) if commodities_union else 0.0
    s += 1.5 * j_ind * j_com

    tier_bonus = 0.0
    for m in members:
        if m.source_tier == 1:
            tier_bonus += 0.8
        elif m.source_tier == 2:
            tier_bonus += 0.5
        if m.signal_tier == "hard":
            tier_bonus += 0.6
    s += tier_bonus

    s -= 0.5 * sum(1 for m in members if m.signal_tier == "soft")

    if axis_value in MAJOR_CHOKEPOINTS:
        s *= 1.4

    return max(SCORE_FLOOR, min(SCORE_CEIL, s))


def cluster_by_axis(bands: list[Band], axis: str) -> list[dict]:
    out: list[dict] = []
    field_map = {"region": "regions", "industry": "industries", "commodity": "commodities", "chokepoint": "chokepoints"}
    attr = field_map[axis]

    values: set[str] = set()
    for b in bands:
        values |= getattr(b, attr)

    for axis_value in sorted(values):
        members = [b for b in bands if axis_value in getattr(b, attr)]
        if len(members) < 2:
            continue
        # Sweep: sort by start, walk, group connected by interval overlap.
        members.sort(key=lambda b: b.start)
        groups: list[list[Band]] = []
        current: list[Band] = []
        current_end: date | None = None
        for m in members:
            if not current:
                current = [m]
                current_end = m.end
                continue
            if m.start <= current_end:
                current.append(m)
                if m.end > current_end:
                    current_end = m.end
            else:
                groups.append(current)
                current = [m]
                current_end = m.end
        if current:
            groups.append(current)

        for grp in groups:
            if len(grp) < 2:
                continue
            score = score_cluster(grp, axis_value)
            t_start = min(m.start for m in grp)
            t_end = max(m.end for m in grp)
            shared_ind = frozenset.intersection(*(m.industries for m in grp)) if all(m.industries for m in grp) else frozenset()
            shared_com = frozenset.intersection(*(m.commodities for m in grp)) if all(m.commodities for m in grp) else frozenset()
            shared_reg = frozenset.intersection(*(m.regions for m in grp)) if all(m.regions for m in grp) else frozenset()
            shared_cp  = frozenset.intersection(*(m.chokepoints for m in grp)) if all(m.chokepoints for m in grp) else frozenset()
            out.append({
                "axis": axis,
                "axis_value": axis_value,
                "time_window": [t_start.isoformat(), t_end.isoformat()],
                "convergence_score": round(score, 2),
                "member_event_ids": [m.id for m in grp],
                "shared_industries": sorted(shared_ind),
                "shared_commodities": sorted(shared_com),
                "shared_regions": sorted(shared_reg),
                "shared_chokepoints": sorted(shared_cp),
                "narrative_seed": None,
            })
    return out


def cross_axis_dedup(clusters: list[dict]) -> list[dict]:
    clusters = sorted(clusters, key=lambda c: -c["convergence_score"])
    kept: list[dict] = []
    for c in clusters:
        c_members = set(c["member_event_ids"])
        if not c_members:
            continue
        is_dup = False
        for k in kept:
            k_members = set(k["member_event_ids"])
            overlap = len(c_members & k_members) / max(len(c_members), len(k_members))
            if overlap >= 0.8:
                is_dup = True
                break
        if not is_dup:
            kept.append(c)
    return kept


def main() -> int:
    today = datetime.now(timezone.utc).date()
    bands = load_bands(today)
    print(f"[overlaps] loaded {len(bands)} bands.", flush=True)

    clusters: list[dict] = []
    for axis in ("region", "industry", "commodity", "chokepoint"):
        clusters.extend(cluster_by_axis(bands, axis))

    clusters = cross_axis_dedup(clusters)
    clusters.sort(key=lambda c: -c["convergence_score"])

    today_iso = today.isoformat()
    for i, c in enumerate(clusters, start=1):
        c["id"] = f"cluster-{today_iso}-{i:03d}"

    out = {
        "$comment": "Derived convergence clusters. Bot-owned. Rebuilt from scratch every daily run.",
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "clusters": clusters,
    }
    (DATA / "overlaps.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    above_threshold = sum(1 for c in clusters if c["convergence_score"] >= 5.5)
    print(f"[overlaps] wrote {len(clusters)} clusters; {above_threshold} at score >= 5.5.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
