#!/usr/bin/env python3
"""Verify a Supabase import against the local lighting-ai-db.json.

The strongest possible check: fetch every row back from Supabase, rebuild the
db dict via the inverse transform, and compare it semantically to the local
JSON. If this prints OK, the central DB holds the data without loss.

Usage:
    SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
        python -m scripts.central_db.verify_supabase [--db db/lighting-ai-db.json]
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

from scripts.central_db.transform import db_json_to_rows, rows_to_db_json  # noqa: E402

DEFAULT_DB = REPO_ROOT / "db" / "lighting-ai-db.json"
_TABLES = ["songs", "song_detail_lighting", "bars", "accents"]
_PAGE = 1000  # Supabase caps select() at 1000 rows/request -> paginate


def _client():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
    try:
        from supabase import create_client
    except ImportError:
        raise SystemExit("ERROR: `pip install supabase` to run verification.")
    return create_client(url, key)


def _fetch_all(client, table: str) -> list[dict]:
    out: list[dict] = []
    start = 0
    while True:
        chunk = client.table(table).select("*").range(start, start + _PAGE - 1).execute().data
        out.extend(chunk)
        if len(chunk) < _PAGE:
            return out
        start += _PAGE


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args(argv)

    local = json.loads(args.db.read_text(encoding="utf-8"))
    expected = db_json_to_rows(local)
    client = _client()

    # ── 1) Row-count check ─────────────────────────────────────────────
    print("Row counts (local -> supabase):")
    counts_ok = True
    fetched: dict = {}
    for t in _TABLES:
        fetched[t] = _fetch_all(client, t)
        exp = len(expected[t])
        got = len(fetched[t])
        flag = "ok" if exp == got else "MISMATCH"
        if exp != got:
            counts_ok = False
        print(f"  {t:<22} {exp:>5} -> {got:>5}  {flag}")
    app = client.table("app_state").select("*").eq("id", 1).single().execute().data
    fetched["app_state"] = app

    # ── 2) Full semantic round-trip from the REAL database ─────────────
    rebuilt = rows_to_db_json({
        "songs": fetched["songs"],
        "song_detail_lighting": [
            {"song_id": r["song_id"], "detail": r["detail"]} for r in fetched["song_detail_lighting"]
        ],
        "bars": fetched["bars"],
        "accents": fetched["accents"],
        "app_state": fetched["app_state"],
    })
    # Compare against a normalised local copy (json-roundtrip drops nothing,
    # only normalises tuple/key types the DB driver may return).
    local_norm = json.loads(json.dumps(local))
    rebuilt_norm = json.loads(json.dumps(rebuilt))

    if rebuilt_norm == local_norm and counts_ok:
        print("\n✅ OK — Supabase reproduces lighting-ai-db.json losslessly.")
        return 0

    print("\n❌ MISMATCH — central DB does not match the local JSON.")
    if rebuilt_norm != local_norm:
        # Pinpoint where it diverges to make debugging quick.
        for key in ("songs", "bars", "accents", "setlist", "meta", "version", "band"):
            if rebuilt_norm.get(key) != local_norm.get(key):
                print(f"   diverges in: {key}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
