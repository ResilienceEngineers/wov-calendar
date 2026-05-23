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
SURFACE_THRESHOLD = 5.0  # clusters at or above this surface on the executive view
# Modulator subtypes that provide context but must NOT drive clusters (they are
# near-year-long and would dilute every window). They still render on the Gantt.
EXCLUDE_FROM_CLUSTERS = {"enso_modulator"}


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
    peak_start: date | None = None
    peak_end: date | None = None

    @property
    def is_live(self) -> bool:
        return self.kind in ("active", "fm", "analysis")

    def peak(self) -> tuple[date, date]:
        return (self.peak_start or self.start, self.peak_end or self.end)


def _parse_date(s: str | None, default: date) -> date:
    if s is None:
        return default
    return datetime.strptime(s, "%Y-%m-%d").date()


def load_bands(today: date) -> list[Band]:
    bands: list[Band] = []

    def peak_dates(b):
        pw = b.get("peak_window")
        if pw and len(pw) == 2:
            return _parse_date(pw[0], today), _parse_date(pw[1], today)
        return None, None

    seasonal = json.loads((DATA / "seasonal_bands.json").read_text(encoding="utf-8"))
    for b in seasonal["bands"]:
        if b.get("hazard_type") in EXCLUDE_FROM_CLUSTERS:
            continue  # modulator: context only, never a cluster member
        ps, pe = peak_dates(b)
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
            peak_start=ps, peak_end=pe,
        ))

    # Non-weather patterns (cargo crime, cyber, conflict cycle, labor) from patterns.csv.
    pattern_path = DATA / "pattern_bands.json"
    if pattern_path.exists():
        confidence_to_signal = {"high": "hard", "medium": "medium", "low": "soft"}
        patterns = json.loads(pattern_path.read_text(encoding="utf-8"))
        for b in patterns["bands"]:
            if b.get("subtype") in EXCLUDE_FROM_CLUSTERS:
                continue
            ps, pe = peak_dates(b)
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
                peak_start=ps, peak_end=pe,
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


def jaccard_multi(sets: list[frozenset]) -> float:
    """Intersection-over-union across >=2 sets. 0 if fewer than 2 non-context sets or empty union."""
    sets = [s for s in sets]
    if len(sets) < 2:
        return 0.0
    union = frozenset().union(*sets)
    if not union:
        return 0.0
    inter = frozenset(sets[0]).intersection(*sets[1:])
    return len(inter) / len(union)


def densest_overlap(items: list[tuple[date, date, Band]]) -> tuple[int, date | None, date | None, list[Band]]:
    """Find the window of maximum simultaneous overlap.

    Returns (depth, window_start, window_end, active_bands) where depth is the max number
    of intervals active at once, the window spans the segments achieving that depth, and
    active_bands is the union of bands active in those peak segments.
    """
    if not items:
        return (0, None, None, [])
    pts = sorted(set([s for s, _, _ in items] + [e + timedelta(days=1) for _, e, _ in items]))
    segments: list[tuple[date, date, list[Band]]] = []
    for i in range(len(pts) - 1):
        seg_start = pts[i]
        seg_end = pts[i + 1] - timedelta(days=1)
        if seg_end < seg_start:
            continue
        active = [b for (s, e, b) in items if s <= seg_start and e >= seg_start]
        if active:
            segments.append((seg_start, seg_end, active))
    if not segments:
        return (0, None, None, [])
    best_depth = max(len(a) for _, _, a in segments)
    peak_segs = [(s, e, a) for s, e, a in segments if len(a) == best_depth]
    win_start = min(s for s, _, _ in peak_segs)
    win_end = max(e for _, e, _ in peak_segs)
    seen: set[str] = set()
    active_bands: list[Band] = []
    for _, _, a in peak_segs:
        for b in a:
            if b.id not in seen:
                seen.add(b.id)
                active_bands.append(b)
    return (best_depth, win_start, win_end, active_bands)


def score_cluster(active: list[Band], depth: int, axis: str, axis_value: str) -> tuple[float, dict]:
    """Bounded 0-10 score from five additive components. Returns (score, component_breakdown).

    depth          0-3  how many bands peak simultaneously (log2 curve)
    severity       0-3  mean severity of the peak-overlapping bands
    concentration  0-2  shared industries x commodities (jaccard) — how tightly impact concentrates
    signal         0-1  reliability: fraction hard-tier + fraction Tier-1
    chokepoint     0-1  additive criticality bonus (NOT a multiplier)
    """
    n = max(1, len(active))
    depth_c = min(3.0, 1.2 * math.log2(depth)) if depth >= 1 else 0.0
    mean_sev = sum(m.severity for m in active) / n
    sev_c = 0.6 * mean_sev
    j_ind = jaccard_multi([m.industries for m in active])
    j_com = jaccard_multi([m.commodities for m in active])
    conc_c = 2.0 * (0.5 * j_ind + 0.5 * j_com)
    frac_hard = sum(1 for m in active if m.signal_tier == "hard") / n
    frac_t1 = sum(1 for m in active if m.source_tier == 1) / n
    sig_c = 0.5 * frac_hard + 0.5 * frac_t1
    if axis == "chokepoint":
        choke_c = 1.0 if axis_value in MAJOR_CHOKEPOINTS else 0.5
    else:
        shared_cp = frozenset.intersection(*(m.chokepoints for m in active)) if all(m.chokepoints for m in active) else frozenset()
        choke_c = 0.5 if (shared_cp & MAJOR_CHOKEPOINTS) else 0.0
    raw = depth_c + sev_c + conc_c + sig_c + choke_c
    breakdown = {"depth": round(depth_c, 2), "severity": round(sev_c, 2), "concentration": round(conc_c, 2),
                 "signal": round(sig_c, 2), "chokepoint": round(choke_c, 2)}
    return (max(SCORE_FLOOR, min(SCORE_CEIL, raw)), breakdown)


def connected_groups(members: list[Band]) -> list[list[Band]]:
    """Group members into temporally-connected components (full-window overlap)."""
    members = sorted(members, key=lambda b: b.start)
    groups: list[list[Band]] = []
    current: list[Band] = []
    current_end: date | None = None
    for m in members:
        if not current:
            current = [m]; current_end = m.end; continue
        if m.start <= current_end:
            current.append(m)
            current_end = max(current_end, m.end)
        else:
            groups.append(current); current = [m]; current_end = m.end
    if current:
        groups.append(current)
    return groups


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
        for grp in connected_groups(members):
            if len(grp) < 2:
                continue
            # Actionable window = where the most members PEAK simultaneously.
            depth, ws, we, active = densest_overlap([(m.peak()[0], m.peak()[1], m) for m in grp])
            if depth < 2:
                # peaks don't overlap — fall back to densest full-window overlap
                depth, ws, we, active = densest_overlap([(m.start, m.end, m) for m in grp])
            if depth < 2 or ws is None:
                continue
            score, breakdown = score_cluster(active, depth, axis, axis_value)
            shared_ind = frozenset.intersection(*(m.industries for m in active)) if all(m.industries for m in active) else frozenset()
            shared_com = frozenset.intersection(*(m.commodities for m in active)) if all(m.commodities for m in active) else frozenset()
            shared_reg = frozenset.intersection(*(m.regions for m in active)) if all(m.regions for m in active) else frozenset()
            shared_cp  = frozenset.intersection(*(m.chokepoints for m in active)) if all(m.chokepoints for m in active) else frozenset()
            out.append({
                "axis": axis,
                "axis_value": axis_value,
                "time_window": [ws.isoformat(), we.isoformat()],
                "convergence_score": round(score, 2),
                "peak_depth": depth,
                "score_breakdown": breakdown,
                "member_event_ids": [m.id for m in grp],
                "peak_member_ids": [m.id for m in active],
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
    depth = cluster.get("peak_depth", len(cluster.get("peak_member_ids", [])) or 2)
    total = len(cluster["member_event_ids"])
    score = cluster["convergence_score"]
    window = f"{cluster['time_window'][0]} to {cluster['time_window'][1]}"

    peak_ids = cluster.get("peak_member_ids") or cluster["member_event_ids"]
    member_names = [titles.get(mid, mid) for mid in peak_ids[:3]]
    members_phrase = " + ".join(member_names)
    if len(peak_ids) > 3:
        members_phrase += f" + {len(peak_ids) - 3} more"

    industries = ", ".join(sorted(cluster.get("shared_industries", []))[:3]) or "none shared"
    commodities = ", ".join(sorted(cluster.get("shared_commodities", []))[:3]) or "none shared"

    if axis == "chokepoint":
        lead = f"Transit chokepoint {display}:"
    elif axis == "region":
        lead = f"Region {display}:"
    elif axis == "industry":
        lead = f"Industry {display}:"
    else:
        lead = f"Commodity {display}:"

    extra = f" (of {total} related bands in this {axis})" if total > depth else ""
    return (
        f"{lead} {depth} risks peak together {window}{extra}, score {score:.1f}/10. "
        f"Peak-window members: {members_phrase}. "
        f"Shared industries: {industries}; shared commodities: {commodities}."
    )


def build_executive_summary(clusters: list[dict], bands: list[Band], names: dict[str, dict[str, str]]) -> dict:
    """One-paragraph plain-language summary for the page hero."""
    n_total = len(bands)
    n_clusters = len(clusters)
    n_surfaced = sum(1 for c in clusters if c["convergence_score"] >= SURFACE_THRESHOLD)
    top = max((c["convergence_score"] for c in clusters), default=0.0)

    chokepoint_clusters = [c for c in clusters if c["axis"] == "chokepoint"]
    chokepoints_active = sorted({c["axis_value"] for c in chokepoint_clusters})
    chokepoint_names = [names["chokepoint"].get(cp, cp) for cp in chokepoints_active]

    top_cluster = clusters[0] if clusters else None
    headline = "Calendar quiet — no convergence above surface threshold."
    if top_cluster and top_cluster["convergence_score"] >= SURFACE_THRESHOLD:
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
    above_threshold = sum(1 for c in clusters if c["convergence_score"] >= SURFACE_THRESHOLD)
    n_red = sum(1 for t in chokepoint_board if t["state"] == "red")
    n_amber = sum(1 for t in chokepoint_board if t["state"] == "amber")
    print(f"[overlaps] wrote {len(clusters)} clusters; {above_threshold} at score >= {SURFACE_THRESHOLD}; chokepoint board {n_red} red / {n_amber} amber.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
