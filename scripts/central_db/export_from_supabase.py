#!/usr/bin/env python3
"""Post-cutover export: central-DB (Supabase) -> db/lighting-ai-db.json.

Strictly unidirectional (docs §12, invariant A). After cutover Supabase is
master; this regenerates the local snapshot that db_cache.py / GitHub Pages
consume, so the live light control keeps working fully offline.

The generated file carries provenance markers so the live app can detect a
stale snapshot:
    "_generated": true, "_generated_at": "<iso>", "_source": "supabase"

Usage:
    SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
        python -m scripts.central_db.export_from_supabase --out db/lighting-ai-db.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.central_db.transform import rows_to_db_json  # noqa: E402

DEFAULT_OUT = REPO_ROOT / "db" / "lighting-ai-db.json"
_TABLES = ["songs", "song_detail_lighting", "bars", "accents"]


def _fetch_rows() -> dict:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
    try:
        from supabase import create_client
    except ImportError:
        raise SystemExit("ERROR: `pip install supabase` to run the export.")

    client = create_client(url, key)
    rows = {t: client.table(t).select("*").execute().data for t in _TABLES}
    app = client.table("app_state").select("*").eq("id", 1).single().execute().data
    rows["app_state"] = app
    return rows


def build_snapshot(rows: dict) -> dict:
    db = rows_to_db_json(rows)
    # Provenance markers up front (do not collide with the schema's data keys).
    return {
        "_generated": True,
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "_source": "supabase",
        **db,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    snapshot = build_snapshot(_fetch_rows())
    text = json.dumps(snapshot, indent=2, ensure_ascii=False)
    args.out.write_text(text, encoding="utf-8")
    print(f"Wrote {args.out} ({len(snapshot.get('songs', {}))} songs, "
          f"{len(snapshot.get('bars', {}))} bars).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
