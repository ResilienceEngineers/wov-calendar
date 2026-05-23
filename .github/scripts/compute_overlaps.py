#!/usr/bin/env python3
"""Convergence-cluster engine + chokepoint constraint board (Theory of Constraints).

Reads union of seasonal_bands, active_events, fm_events, user_analyses into typed
Band records. For each axis in {region, industry, commodity, chokepoint}, for each
axis_value, sweeps temporal overlaps and emits clusters.

**Theory-of-Constraints rule for chokepoints (Marco's directive):** a chokepoint IS
the constraint. Any event touching a maritime chokepoint matters disproportionately.
We therefore surface chokepoint-axis clusters with n>=1 members (not n>=2 like other
axes). For region/industry/commodity axes the normal n>=2 convergence rule applies.

Score formula:
    score = 2.0 * log(n + 1)
          + mean(severity)
          + 1.5 * jaccard(industries) * jaccard(commodities)
          + tier_bonus              (+0.8 Tier-1, +0.5 Tier-2, +0.6 per Hard signal)
          - 0.5 * count(signal_tier == "soft")
          + chokepoint_multiplier   (x1.4 if axis_value in major chokepoints)
    clamp [0, 10]

Surface threshold: 5.5. Top 5 by score → index.html executive view.
Single-member chokepoint observations surface separately on the chokepoint board.
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
    kind: str = "seasonal"  # seasonal | pattern | active | fm | analysis

    @property
    def is_live(self) -> bool:
        return self.kind in ("active", "fm", "analysis")


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
            kind="seasonal",
        ))

    # Non-weather patterns (cargo crime, cyber, conflict cycle, labor) from patterns.csv.
    pattern_path = DATA / "pattern_bands.json"
    if pattern_path.exists():
        confidence_to_signal = {"high": "hard", "medium": "medium", "low": "soft"}
        patterns = json.loads(pattern_path.read_text(encoding="utf-8"))
        for b in patterns["bands"]:
            bands.append(Band(
                id=b["id"],
                start=_parse_date(b["start_date"], today),
                end=_parse_date(b["end_date"], today + timedelta(days=NULL_END_DEFAULT_DAYS)),
                regions=frozenset(b["regions"]),
                industries=frozenset(b["industries"]),
                commodities=frozenset(b["commodities"]),
                chokepoints=frozenset(b["chokepoints"]),
                severity=b["baseline_severity"],
                source_tier=2,
                signal_tier=confidence_to_signal.get(b.get("confidence", "medium"), "medium"),
                kind="pattern",
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
            kind="active",
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
            kind="fm",
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
            kind="analysis",
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

    # Theory of Constraints rule: chokepoint axis surfaces single-member observations.
    min_members = 1 if axis == "chokepoint" else 2

    for axis_value in sorted(values):
        members = [b for b in bands if axis_value in getattr(b, attr)]
        if len(members) < min_members:
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
            if len(grp) < min_members:
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


def vocab_name_lookup() -> dict[str, dict[str, str]]:
    """{kind: {id: display_name}}."""
    out: dict[str, dict[str, str]] = {}
    for kind, fname, key in [
        ("region", "regions.json", "regions"),
        ("industry", "industries.json", "industries"),
        ("commodity", "commodities.json", "commodities"),
        ("chokepoint", "chokepoints.json", "chokepoints"),
    ]:
        items = json.loads((DATA / "vocab" / fname).read_text(encoding="utf-8"))[key]
        out[kind] = {item["id"]: item["name"] for item in items}
    return out


def all_band_titles(today: date) -> dict[str, str]:
    """{band_id: human title} so narrative seeds can reference members by name."""
    titles: dict[str, str] = {}
    for b in json.loads((DATA / "seasonal_bands.json").read_text(encoding="utf-8"))["bands"]:
        titles[b["id"]] = b["name"]
    pattern_path = DATA / "pattern_bands.json"
    if pattern_path.exists():
        for b in json.loads(pattern_path.read_text(encoding="utf-8"))["bands"]:
            titles[b["id"]] = b["name"]
    for e in json.loads((DATA / "active_events.json").read_text(encoding="utf-8"))["events"]:
        titles[e["id"]] = e["title"]
    for e in json.loads((DATA / "fm_events.json").read_text(encoding="utf-8"))["events"]:
        titles[e["id"]] = f"FM · {e.get('declarant', '?')} · {e.get('facility', '?')}"
    for a in json.loads((DATA / "user_analyses.json").read_text(encoding="utf-8"))["analyses"]:
        titles[a["id"]] = f"Analysis · {a.get('trigger_commodity', '?')}"
    return titles


def narrate(cluster: dict, names: dict[str, dict[str, str]], titles: dict[str, str]) -> str:
    """Deterministic plain-language seed. Claude can elevate later."""
    axis = cluster["axis"]
    value = cluster["axis_value"]
    display = names.get(axis, {}).get(value, value)
    n = len(cluster["member_event_ids"])
    score = cluster["convergence_score"]
    window = f"{cluster['time_window'][0]} → {cluster['time_window'][1]}"

    member_names = [titles.get(mid, mid) for mid in cluster["member_event_ids"][:3]]
    members_phrase = " + ".join(member_names)
    if len(cluster["member_event_ids"]) > 3:
        members_phrase += f" + {len(cluster['member_event_ids']) - 3} more"

    industries = ", ".join(sorted(cluster.get("shared_industries", []))[:3]) or "—"
    commodities = ", ".join(sorted(cluster.get("shared_commodities", []))[:3]) or "—"

    if axis == "chokepoint":
        lead = f"Transit chokepoint {display} is the bottleneck."
    elif axis == "region":
        lead = f"Region {display} has multiple risks stacking in the same window."
    elif axis == "industry":
        lead = f"Industry sector {display} is exposed from multiple directions at once."
    else:
        lead = f"Commodity flow {display} faces compound pressure."

    return (
        f"{lead} {n} band(s) converging {window} (score {score:.1f}/10). "
        f"Members: {members_phrase}. "
        f"Shared industries: {industries}. Shared commodities: {commodities}."
    )


def build_executive_summary(clusters: list[dict], bands: list[Band], names: dict[str, dict[str, str]]) -> dict:
    """One-paragraph plain-language summary for the page hero."""
    n_total = len(bands)
    n_clusters = len(clusters)
    n_surfaced = sum(1 for c in clusters if c["convergence_score"] >= 5.5)
    top = max((c["convergence_score"] for c in clusters), default=0.0)

    chokepoint_clusters = [c for c in clusters if c["axis"] == "chokepoint"]
    chokepoints_active = sorted({c["axis_value"] for c in chokepoint_clusters})
    chokepoint_names = [names["chokepoint"].get(cp, cp) for cp in chokepoints_active]

    top_cluster = clusters[0] if clusters else None
    headline = "Calendar quiet — no convergence above surface threshold."
    if top_cluster and top_cluster["convergence_score"] >= 5.5:
        axis = top_cluster["axis"]
        display = names.get(axis, {}).get(top_cluster["axis_value"], top_cluster["axis_value"])
        headline = (
            f"Top pressure: {display} ({axis}, score {top_cluster['convergence_score']:.1f}/10) "
            f"between {top_cluster['time_window'][0]} and {top_cluster['time_window'][1]}."
        )

    chokepoint_phrase = (
        f"{len(chokepoints_active)} maritime chokepoint(s) under active pressure"
        + (f": {', '.join(chokepoint_names)}." if chokepoint_names else ".")
    )

    return {
        "headline": headline,
        "chokepoint_phrase": chokepoint_phrase,
        "kpis": {
            "bands_tracked": n_total,
            "clusters_detected": n_clusters,
            "clusters_above_threshold": n_surfaced,
            "top_score": round(top, 2),
            "chokepoints_active": len(chokepoints_active),
        },
    }


def build_chokepoint_board(bands: list[Band], titles: dict[str, str]) -> list[dict]:
    """One tile per maritime chokepoint: name, state, exposure summary, what to watch.

    Theory-of-Constraints: a chokepoint IS the constraint, so it is monitored even with a
    single touching band. State logic distinguishes LIVE bands (active events, FM
    declarations, user analyses) from baseline recurring patterns (seasonal + pattern):
      red    = a LIVE band touches it with severity >=4 or a hard signal
      amber  = any LIVE band touches it, OR a baseline pattern at severity >=3 is in window
      green  = only low-severity baseline patterns touch it (or none at all)
    """
    cp_meta = json.loads((DATA / "vocab" / "chokepoints.json").read_text(encoding="utf-8"))["chokepoints"]
    tiles: list[dict] = []
    for cp in cp_meta:
        cpid = cp["id"]
        if cp["kind"] != "maritime":
            continue
        members = [b for b in bands if cpid in b.chokepoints]
        if not members:
            tiles.append({
                "id": cpid, "name": cp["name"], "kind": cp["kind"],
                "lat": cp["lat"], "lon": cp["lon"],
                "throughput_note": cp.get("throughput_note", ""),
                "state": "green",
                "exposure": "No live events or recurring patterns currently touching this chokepoint.",
                "what_to_watch": "Clear — no action required.",
                "member_count": 0,
            })
            continue
        max_sev = max(m.severity for m in members)
        any_hard = any(m.signal_tier == "hard" for m in members)
        live = [m for m in members if m.is_live]
        if live and (max_sev >= 4 or any_hard):
            state = "red"
        elif live or max_sev >= 3:
            state = "amber"
        else:
            state = "green"
        n_live = len(live)
        n_pattern = len(members) - n_live
        top_member = max(members, key=lambda b: (b.is_live, b.severity, b.signal_tier == "hard"))
        top_name = titles.get(top_member.id, top_member.id)
        kind_word = {"active": "live event", "fm": "force-majeure", "analysis": "analysis", "seasonal": "seasonal pattern", "pattern": "recurring pattern"}.get(top_member.kind, "band")
        exposure = (
            f"{n_live} live event(s) + {n_pattern} recurring pattern(s) in window. "
            f"Max severity {max_sev}/5."
        )
        if state == "red":
            watch = f"Active disruption from {top_name} ({kind_word}, sev {top_member.severity}). Treat as constraint on all flow through {cp['name']}."
        elif state == "amber":
            watch = f"Watching {top_name} ({kind_word}, sev {top_member.severity}). No confirmed flow impact yet."
        else:
            watch = f"Baseline seasonal exposure only ({top_name}). Normal operations."
        tiles.append({
            "id": cpid, "name": cp["name"], "kind": cp["kind"],
            "lat": cp["lat"], "lon": cp["lon"],
            "throughput_note": cp.get("throughput_note", ""),
            "state": state,
            "exposure": exposure,
            "what_to_watch": watch,
            "member_count": len(members),
        })
    tiles.sort(key=lambda t: ({"red": 0, "amber": 1, "green": 2}[t["state"]], -t["member_count"]))
    return tiles


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

    names = vocab_name_lookup()
    titles = all_band_titles(today)
    for c in clusters:
        c["narrative_seed"] = narrate(c, names, titles)

    executive_summary = build_executive_summary(clusters, bands, names)
    chokepoint_board = build_chokepoint_board(bands, titles)

    out = {
        "$comment": "Derived convergence clusters + chokepoint constraint board. Bot-owned. Rebuilt from scratch every daily run.",
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "executive_summary": executive_summary,
        "chokepoint_board": chokepoint_board,
        "clusters": clusters,
    }
    (DATA / "overlaps.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    above_threshold = sum(1 for c in clusters if c["convergence_score"] >= 5.5)
    n_red = sum(1 for t in chokepoint_board if t["state"] == "red")
    n_amber = sum(1 for t in chokepoint_board if t["state"] == "amber")
    print(f"[overlaps] wrote {len(clusters)} clusters; {above_threshold} at score >= 5.5; chokepoint board {n_red} red / {n_amber} amber.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
