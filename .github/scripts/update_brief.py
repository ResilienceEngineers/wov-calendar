#!/usr/bin/env python3
"""Daily orchestrator for the Window of Vulnerability calendar.

Pipeline:
  1. ingest_hormuz.py        -> data/hormuz_snapshot.json
  2. ingest_fm_tracker.py    -> data/fm_events.json
  3. triage_with_claude.py   -> data/active_events.json
  4. compute_overlaps.py     -> data/overlaps.json
  5. render_pages.py         -> index.html, brief.html (BRIEF:* blocks only)
  6. validate_schemas.py     -> CI gate

Each step is a separate script invoked here. If any step exits non-zero, the
orchestrator exits with the same code; the workflow surfaces the failure; no
commit lands.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github" / "scripts"

STEPS = [
    ("ingest hormuz",    "ingest_hormuz.py",     True),
    ("ingest FM tracker","ingest_fm_tracker.py", True),
    ("triage signals",   "triage_with_claude.py",False),  # requires ANTHROPIC_API_KEY
    ("compute overlaps", "compute_overlaps.py",  True),
    ("render pages",     "render_pages.py",      True),
    ("validate",         "validate_schemas.py",  True),
]


def run(name: str, script: str) -> int:
    print(f"\n[orchestrator] === {name} ({script}) ===", flush=True)
    rc = subprocess.call([sys.executable, str(SCRIPTS / script)])
    if rc != 0:
        print(f"[orchestrator] step '{name}' failed with exit {rc}", file=sys.stderr)
    return rc


def main() -> int:
    has_api = "ANTHROPIC_API_KEY" in os.environ

    for name, script, always_run in STEPS:
        if not always_run and not has_api:
            print(f"\n[orchestrator] === {name} ({script}) === SKIPPED (no ANTHROPIC_API_KEY)", flush=True)
            continue
        rc = run(name, script)
        if rc != 0:
            return rc

    print("\n[orchestrator] all steps complete.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
