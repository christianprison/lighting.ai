#!/usr/bin/env python3
"""Post-cutover export: central-DB (Supabase) -> db/lighting-ai-db.<band>.json.

Strictly unidirectional (docs §12, invariant A). After cutover Supabase is
master; this regenerates the local snapshot that db_cache.py / GitHub Pages
consume, so the live light control keeps working fully offline.

Multi-Band (0012, 2026-08-07): one snapshot file PER BAND — `songs` filtered
by `band_id`, `bars` filtered via the resulting song-id list (the table that
actually gets large), `song_detail_lighting`/`accents` fetched in full and
filtered client-side (small in absolute terms regardless of band count,
and `accents` doesn't carry `song_id` directly so a second-hop filter would
need a potentially huge `bar_id in (...)` list — not worth it at this scale).

The generated file carries provenance markers so the live app can detect a
stale snapshot:
    "_generated": true, "_generated_at": "<iso>", "_source": "supabase"

Usage:
    SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
        python -m scripts.central_db.export_from_supabase --band the_pact --out db/lighting-ai-db.json
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
_PAGE = 1000  # Supabase caps select() at 1000 rows/request -> paginate
_IN_BATCH = 200  # keep .in_() filter lists a sane size


def _fetch_all(client, table: str, eq: tuple[str, str] | None = None) -> list[dict]:
    out: list[dict] = []
    start = 0
    while True:
        q = client.table(table).select("*")
        if eq:
            q = q.eq(*eq)
        chunk = q.range(start, start + _PAGE - 1).execute().data
        out.extend(chunk)
        if len(chunk) < _PAGE:
            return out
        start += _PAGE


def _fetch_by_ids(client, table: str, id_col: str, ids: list[str]) -> list[dict]:
    out: list[dict] = []
    for i in range(0, len(ids), _IN_BATCH):
        chunk_ids = ids[i : i + _IN_BATCH]
        out.extend(client.table(table).select("*").in_(id_col, chunk_ids).execute().data)
    return out


def _fetch_rows(band: str) -> dict:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
    try:
        from supabase import create_client
    except ImportError:
        raise SystemExit("ERROR: `pip install supabase` to run the export.")

    client = create_client(url, key)

    songs = _fetch_all(client, "songs", eq=("band_id", band))
    song_ids = [r["id"] for r in songs]

    song_detail_all = _fetch_all(client, "song_detail_lighting")
    song_id_set = set(song_ids)
    song_detail = [r for r in song_detail_all if r["song_id"] in song_id_set]

    bars = _fetch_by_ids(client, "bars", "song_id", song_ids) if song_ids else []
    bar_id_set = {r["bar_id"] for r in bars}

    accents_all = _fetch_all(client, "accents")
    accents = [r for r in accents_all if r["bar_id"] in bar_id_set]

    app = client.table("app_state").select("*").eq("band_id", band).single().execute().data

    return {
        "songs": songs,
        "song_detail_lighting": song_detail,
        "bars": bars,
        "accents": accents,
        "app_state": app,
    }


def build_snapshot(rows: dict) -> dict:
    # Safety: an empty/partial read must never overwrite the Git snapshot the
    # Live-App relies on (mirrors the same guard in sync_to_supabase.py).
    if not rows["songs"]:
        raise SystemExit("ERROR: 0 songs read from Supabase — refusing to export (would wipe the Git snapshot).")
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
    ap.add_argument("--band", required=True, help="band_id, z.B. the_pact oder stringbreak")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    snapshot = build_snapshot(_fetch_rows(args.band))
    text = json.dumps(snapshot, indent=2, ensure_ascii=False)
    args.out.write_text(text, encoding="utf-8")
    print(f"Wrote {args.out} ({len(snapshot.get('songs', {}))} songs, "
          f"{len(snapshot.get('bars', {}))} bars).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
