#!/usr/bin/env python3
"""Validate every data/*.json against its schema and check FK integrity against vocab.

Run as CI gate after every ingest / triage / overlap rebuild. Exits non-zero on any
schema violation or unresolved vocab reference.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SCHEMA = DATA / "schema"
VOCAB = DATA / "vocab"

DATA_FILES = {
    "seasonal_bands.json": "seasonal_bands.schema.json",
    "pattern_bands.json":  "pattern_bands.schema.json",
    "active_events.json":  "active_events.schema.json",
    "user_analyses.json":  "user_analyses.schema.json",
    "fm_events.json":      "fm_events.schema.json",
    "hormuz_snapshot.json":"hormuz_snapshot.schema.json",
    "sources.json":        "sources.schema.json",
    "overlaps.json":       "overlaps.schema.json",
}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def vocab_ids(filename: str, key: str) -> set[str]:
    return {item["id"] for item in load(VOCAB / filename)[key]}


def check_fk(label: str, refs: list[str], universe: set[str], errors: list[str]) -> None:
    for r in refs:
        if r not in universe:
            errors.append(f"{label}: unknown id '{r}'")


def main() -> int:
    errors: list[str] = []

    regions = vocab_ids("regions.json", "regions")
    chokepoints = vocab_ids("chokepoints.json", "chokepoints")
    commodities = vocab_ids("commodities.json", "commodities")
    industries = vocab_ids("industries.json", "industries")
    severity_levels = {lvl["level"] for lvl in load(VOCAB / "severity.json")["levels"]}
    source_ids = {s["id"] for s in load(DATA / "sources.json")["sources"]}

    for data_file, schema_file in DATA_FILES.items():
        data_path = DATA / data_file
        schema_path = SCHEMA / schema_file
        if not data_path.exists():
            errors.append(f"missing data file: {data_path}")
            continue
        if not schema_path.exists():
            errors.append(f"missing schema file: {schema_path}")
            continue

        instance = load(data_path)
        schema = load(schema_path)
        v = Draft202012Validator(schema)
        for err in sorted(v.iter_errors(instance), key=lambda e: e.path):
            loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
            errors.append(f"{data_file}: {loc}: {err.message}")

    seasonal = load(DATA / "seasonal_bands.json")
    for b in seasonal["bands"]:
        check_fk(f"seasonal_bands[{b['id']}].regions", b["regions"], regions, errors)
        check_fk(f"seasonal_bands[{b['id']}].affected_chokepoints", b["affected_chokepoints"], chokepoints, errors)
        check_fk(f"seasonal_bands[{b['id']}].affected_commodities", b["affected_commodities"], commodities, errors)
        check_fk(f"seasonal_bands[{b['id']}].affected_industries", b["affected_industries"], industries, errors)
        check_fk(f"seasonal_bands[{b['id']}].source_ids", b["source_ids"], source_ids, errors)
        if b["baseline_severity"] not in severity_levels:
            errors.append(f"seasonal_bands[{b['id']}].baseline_severity: {b['baseline_severity']} not in vocab")

    if (DATA / "pattern_bands.json").exists():
        patterns = load(DATA / "pattern_bands.json")
        for b in patterns["bands"]:
            check_fk(f"pattern_bands[{b['id']}].regions", b["regions"], regions, errors)
            check_fk(f"pattern_bands[{b['id']}].industries", b.get("industries", []), industries, errors)
            check_fk(f"pattern_bands[{b['id']}].commodities", b.get("commodities", []), commodities, errors)
            check_fk(f"pattern_bands[{b['id']}].chokepoints", b.get("chokepoints", []), chokepoints, errors)
            check_fk(f"pattern_bands[{b['id']}].source_ids", b["source_ids"], source_ids, errors)
            if b["baseline_severity"] not in severity_levels:
                errors.append(f"pattern_bands[{b['id']}].baseline_severity: {b['baseline_severity']} not in vocab")

    active = load(DATA / "active_events.json")
    for e in active["events"]:
        check_fk(f"active_events[{e['id']}].regions", e["regions"], regions, errors)
        check_fk(f"active_events[{e['id']}].industries", e.get("industries", []), industries, errors)
        check_fk(f"active_events[{e['id']}].commodities", e.get("commodities", []), commodities, errors)
        check_fk(f"active_events[{e['id']}].chokepoints", e.get("chokepoints", []), chokepoints, errors)
        check_fk(f"active_events[{e['id']}].source_ids", e["source_ids"], source_ids, errors)
        if e["severity"] not in severity_levels:
            errors.append(f"active_events[{e['id']}].severity: {e['severity']} not in vocab")

    fm = load(DATA / "fm_events.json")
    for e in fm["events"]:
        check_fk(f"fm_events[{e['id']}].regions_affected", e["regions_affected"], regions, errors)
        check_fk(f"fm_events[{e['id']}].industries_downstream", e.get("industries_downstream", []), industries, errors)

    analyses = load(DATA / "user_analyses.json")
    for a in analyses["analyses"]:
        check_fk(f"user_analyses[{a['id']}].regions_affected", a["regions_affected"], regions, errors)
        for stage in a["industry_chain"]:
            check_fk(f"user_analyses[{a['id']}].industry_chain.industry", [stage["industry"]], industries, errors)

    overlaps = load(DATA / "overlaps.json")
    valid_axis_ids = {"region": regions, "industry": industries, "commodity": commodities, "chokepoint": chokepoints}
    for c in overlaps["clusters"]:
        universe = valid_axis_ids[c["axis"]]
        if c["axis_value"] not in universe:
            errors.append(f"overlaps[{c['id']}].axis_value '{c['axis_value']}' not in {c['axis']} vocab")
        check_fk(f"overlaps[{c['id']}].shared_industries", c.get("shared_industries", []), industries, errors)
        check_fk(f"overlaps[{c['id']}].shared_commodities", c.get("shared_commodities", []), commodities, errors)
        check_fk(f"overlaps[{c['id']}].shared_regions", c.get("shared_regions", []), regions, errors)
        check_fk(f"overlaps[{c['id']}].shared_chokepoints", c.get("shared_chokepoints", []), chokepoints, errors)

    if errors:
        print(f"[validate] {len(errors)} validation issue(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"[validate] OK. All {len(DATA_FILES)} data files validate; vocab FKs resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
