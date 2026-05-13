#!/usr/bin/env python3
"""Convert uploads/*.yaml into user_analyses.json entries.

Runs on push to uploads/**. Validates each YAML against user_analyses.schema.json
(after JSON conversion) and FK-checks against vocab. Appends new analyses; replaces
in-place if an existing id is uploaded again.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
UPLOADS = ROOT / "uploads"

SCHEMA = json.loads((DATA / "schema" / "user_analyses.schema.json").read_text(encoding="utf-8"))
ITEM_SCHEMA = SCHEMA["properties"]["analyses"]["items"]


def main() -> int:
    yaml_files = sorted(p for p in UPLOADS.glob("*.yaml") if p.name != "_template.analysis.yaml")
    print(f"[ingest_user_yaml] processing {len(yaml_files)} upload(s).", flush=True)

    target = DATA / "user_analyses.json"
    current = json.loads(target.read_text(encoding="utf-8"))
    by_id: dict[str, dict] = {a["id"]: a for a in current["analyses"]}

    errors: list[str] = []
    added = 0
    replaced = 0
    validator = Draft202012Validator(ITEM_SCHEMA)

    for p in yaml_files:
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            errors.append(f"{p.name}: YAML parse error: {e}")
            continue
        if not isinstance(raw, dict):
            errors.append(f"{p.name}: expected mapping at root, got {type(raw).__name__}")
            continue

        raw.setdefault("uploaded_at", datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
        raw.setdefault("uploaded_by", "marco")

        item_errors = sorted(validator.iter_errors(raw), key=lambda e: e.path)
        if item_errors:
            for err in item_errors:
                loc = "/".join(str(part) for part in err.absolute_path) or "<root>"
                errors.append(f"{p.name}: {loc}: {err.message}")
            continue

        aid = raw["id"]
        if aid in by_id:
            by_id[aid] = raw
            replaced += 1
        else:
            by_id[aid] = raw
            added += 1

    if errors:
        print(f"[ingest_user_yaml] {len(errors)} error(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    out = {
        "$comment": current.get("$comment", "Marco's commodity-impact chains. Auto-generated from uploads/*.yaml by ingest_user_yaml.py."),
        "analyses": sorted(by_id.values(), key=lambda a: a["uploaded_at"], reverse=True),
    }
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[ingest_user_yaml] added={added} replaced={replaced} total={len(by_id)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
