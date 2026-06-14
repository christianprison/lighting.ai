#!/usr/bin/env python3
"""Auto-sync the catalog from db/lighting-ai-db.json INTO Supabase.

Git stays the single source of truth (docs §12). This makes Supabase follow:
upsert everything (adds + modifications), then PRUNE rows that no longer exist
in the JSON (deletions). Idempotent and safe to re-run. Runs in GitHub Actions
on every change to the DB file — no laptop, no service-key in any client.

Does NOT upload audio binaries (see upload-snippets workflow); it only keeps the
audio_assets *registry* in step with the metadata.

    SUPABASE_URL=… SUPABASE_SERVICE_ROLE_KEY=… python -m scripts.central_db.sync_to_supabase
    python -m scripts.central_db.sync_to_supabase --dry-run   # offline, counts only
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

from scripts.central_db.audio_assets import audio_assets_rows  # noqa: E402
from scripts.central_db.transform import db_json_to_rows  # noqa: E402

DEFAULT_DB = REPO_ROOT / "db" / "lighting-ai-db.json"


def _client():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
    try:
        from supabase import create_client
    except ImportError:
        raise SystemExit("ERROR: `pip install supabase` first.")
    return create_client(url, key)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    db = json.loads(args.db.read_text(encoding="utf-8"))
    rows = db_json_to_rows(db)
    aa = audio_assets_rows(db, REPO_ROOT)

    print("Catalog to sync:")
    for t in ("songs", "song_detail_lighting", "bars", "accents"):
        print(f"  {t:<22} {len(rows[t]):>5}")
    print(f"  app_state                  1")
    print(f"  audio_assets           {len(aa):>5}")

    # Safety: an empty catalog must never reach the pruners.
    if not rows["songs"]:
        raise SystemExit("ERROR: 0 songs in source — refusing to sync (would prune everything).")

    if args.dry_run:
        print("\n[dry-run] no network calls.")
        return 0

    client = _client()

    def _upsert(table: str, data, on_conflict: str | None = None, batch: int = 500) -> None:
        rowlist = data if isinstance(data, list) else [data]
        for i in range(0, len(rowlist), batch):
            chunk = rowlist[i : i + batch]
            q = client.table(table).upsert(chunk, on_conflict=on_conflict) if on_conflict \
                else client.table(table).upsert(chunk)
            q.execute()
        print(f"  upserted {table:<22} ({len(rowlist)})")

    # 1) Upsert adds + modifications, FK-safe order.
    _upsert("songs", rows["songs"])
    _upsert("song_detail_lighting", rows["song_detail_lighting"])
    _upsert("bars", rows["bars"])
    _upsert("accents", rows["accents"])
    _upsert("app_state", rows["app_state"])
    _upsert("audio_assets", aa, on_conflict="bucket,storage_path")

    # 2) Prune deletions (rows in Supabase no longer present in the JSON).
    client.rpc("prune_catalog", {
        "p_song_ids":   [r["id"] for r in rows["songs"]],
        "p_bar_ids":    [r["bar_id"] for r in rows["bars"]],
        "p_accent_ids": [r["accent_id"] for r in rows["accents"]],
    }).execute()
    client.rpc("prune_audio_assets", {
        "p_paths": [r["storage_path"] for r in aa],
    }).execute()
    print("  pruned stale rows (catalog + audio_assets)")

    print("\nSync complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
