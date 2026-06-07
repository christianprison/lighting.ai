#!/usr/bin/env python3
"""Phase 1 import: lighting-ai-db.json -> central-DB (Supabase).

Single-writer note (docs §12, invariant A): run this ONLY during the pre-cutover
migration, while Git is still master. After cutover the flow reverses and only
``export_from_supabase.py`` runs. Never both at once.

Usage:
    # offline sanity check (no DB, no creds needed):
    python -m scripts.central_db.import_to_supabase --dry-run

    # real import (needs `pip install supabase` + env vars):
    SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
        python -m scripts.central_db.import_to_supabase

The transform is pure; this module only adds the Supabase I/O.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.central_db.transform import db_json_to_rows  # noqa: E402

DEFAULT_DB = REPO_ROOT / "db" / "lighting-ai-db.json"


def _load_rows(db_path: Path) -> dict:
    db = json.loads(db_path.read_text(encoding="utf-8"))
    return db_json_to_rows(db)


def _summary(rows: dict) -> str:
    return (
        f"  songs                {len(rows['songs']):>5}\n"
        f"  song_detail_lighting {len(rows['song_detail_lighting']):>5}\n"
        f"  bars                 {len(rows['bars']):>5}\n"
        f"  accents              {len(rows['accents']):>5}\n"
        f"  app_state                1"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="path to lighting-ai-db.json")
    ap.add_argument("--dry-run", action="store_true", help="print row counts, do not touch any DB")
    args = ap.parse_args(argv)

    rows = _load_rows(args.db)
    print(f"Transformed {args.db.name} into central-DB rows:")
    print(_summary(rows))

    if args.dry_run:
        print("\n[dry-run] no database written.")
        return 0

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("\nERROR: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or use --dry-run).",
              file=sys.stderr)
        return 2
    try:
        from supabase import create_client
    except ImportError:
        print("\nERROR: `pip install supabase` to run the real import.", file=sys.stderr)
        return 2

    client = create_client(url, key)
    # Upsert in FK-safe order. on_conflict keeps the import idempotent (re-runnable).
    client.table("songs").upsert(rows["songs"]).execute()
    client.table("song_detail_lighting").upsert(rows["song_detail_lighting"]).execute()
    client.table("bars").upsert(rows["bars"]).execute()
    client.table("accents").upsert(rows["accents"]).execute()
    client.table("app_state").upsert(rows["app_state"]).execute()
    print("\nImport complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
