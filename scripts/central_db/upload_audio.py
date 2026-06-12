#!/usr/bin/env python3
"""Phase 2 — upload snippet/playalong audio to Supabase Storage + register it.

Designed to run in GitHub Actions (the repo, incl. the audio/ folder, is already
checked out there), so no laptop or local files are needed. Reads credentials
from the environment:

    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

What it does (idempotent — safe to re-run):
1. Ensure a PUBLIC bucket ``snippets`` exists.
2. Upload every referenced+existing audio file (audio_assets_rows) to the bucket
   under the same key as its repo path (upsert).
3. Upsert the matching ``audio_assets`` rows (ON CONFLICT (bucket, storage_path)).

    python -m scripts.central_db.upload_audio            # real upload
    python -m scripts.central_db.upload_audio --dry-run  # just count, no network
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

from scripts.central_db.audio_assets import BUCKET, audio_assets_rows  # noqa: E402

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


def _ensure_bucket(client) -> None:
    existing = set()
    for b in client.storage.list_buckets():
        existing.add(getattr(b, "name", None) or getattr(b, "id", None) or
                     (b.get("name") if isinstance(b, dict) else None))
    if BUCKET in existing:
        print(f"bucket '{BUCKET}' already exists")
        return
    client.storage.create_bucket(BUCKET, options={"public": True})
    print(f"created public bucket '{BUCKET}'")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    db = json.loads(args.db.read_text(encoding="utf-8"))
    rows = audio_assets_rows(db, REPO_ROOT)
    total = sum((REPO_ROOT / r["storage_path"]).stat().st_size for r in rows)
    print(f"{len(rows)} files to upload ({total / 1048576:.0f} MB) into bucket '{BUCKET}'.")

    if args.dry_run:
        print("[dry-run] no network calls.")
        return 0

    client = _client()
    _ensure_bucket(client)

    store = client.storage.from_(BUCKET)
    for i, r in enumerate(rows, 1):
        key = r["storage_path"]
        data = (REPO_ROOT / key).read_bytes()
        store.upload(
            path=key,
            file=data,
            file_options={"content-type": "audio/mpeg", "upsert": "true"},
        )
        if i % 50 == 0 or i == len(rows):
            print(f"  uploaded {i}/{len(rows)}")

    # Register audio_assets (idempotent on the natural key).
    for i in range(0, len(rows), 500):
        client.table("audio_assets").upsert(
            rows[i : i + 500], on_conflict="bucket,storage_path", ignore_duplicates=True
        ).execute()
    print(f"registered {len(rows)} audio_assets rows.")
    print("\nDone. Verify:  select kind, count(*) from audio_assets group by kind;")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
