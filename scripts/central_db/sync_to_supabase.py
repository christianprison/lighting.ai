#!/usr/bin/env python3
"""Manueller Not-Aus/Restore-Weg: db/lighting-ai-db.<band>.json -> Supabase.

⚠️ SEIT DEM SUPABASE-CUTOVER NICHT DER NORMALE WEG (siehe .github/workflows/
sync-db.yml — Auto-Trigger dort ist deshalb entfernt). Git ist nicht mehr
Master, Supabase ist es. Nur zur Wiederherstellung aus einem Git-Stand nutzen.

Multi-Band (0012, 2026-08-07): `--band` ist Pflicht, die JSON-Datei enthält
nur den Katalog EINER Band. Upsert (Adds/Mods) ist bereits automatisch
band-scoped (db_json_to_rows liest band_id aus jedem Song). Die PRUNE-Stufe
(löscht Zeilen, die im JSON fehlen) ist es NICHT — `prune_catalog` kennt kein
Band-Scoping und würde bei mehr als einer Band in `bands` fälschlich auch die
Songs/Bars/Accents der JEWEILS ANDEREN Band(s) löschen. Deshalb: Prune wird
automatisch übersprungen, sobald mehr als eine Band existiert (reiner Upsert
bleibt möglich). Für einen band-sicheren Prune müsste `prune_catalog` erst um
ein `p_band_id`-Argument erweitert werden — bislang nicht gebaut (siehe
docs/multiband-uebergabe.md).

    SUPABASE_URL=… SUPABASE_SERVICE_ROLE_KEY=… python -m scripts.central_db.sync_to_supabase --band the_pact
    python -m scripts.central_db.sync_to_supabase --band the_pact --dry-run   # offline, counts only
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

# NOTE: song_intros is NOT synced here. It is curator-authored directly in
# Supabase via BassTrainer (see 0008_curators.sql) — Supabase is its master,
# like practice_markers. Including it here would prune those writes.

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
    ap.add_argument("--band", required=True, help="band_id, z.B. the_pact oder stringbreak")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    db = json.loads(args.db.read_text(encoding="utf-8"))
    if db.get("band_id") and db["band_id"] != args.band:
        raise SystemExit(
            f"ERROR: --band {args.band} passt nicht zu band_id \"{db['band_id']}\" in {args.db} — "
            f"falsche Datei für diese Band?"
        )
    db["band_id"] = args.band  # --band ist die Autorität, auch wenn im JSON schon vorhanden
    for s in db.get("songs", {}).values():
        s.setdefault("band_id", args.band)  # Backfill für Alt-Dateien von vor 0012
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

    # 2) Prune deletions (rows in Supabase no longer present in the source).
    # prune_catalog kennt kein Band-Scoping (löscht global, was nicht in den
    # p_*_ids-Listen steht) — mit mehr als einer Band in `bands` würde das
    # fälschlich auch die Songs/Bars/Accents der jeweils anderen Band(s)
    # löschen, da diese Datei nur EINE Band enthält. Deshalb: Prune nur, wenn
    # aktuell genau eine Band existiert (Upsert oben bleibt unabhängig davon).
    band_count = len(client.table("bands").select("id").execute().data)
    if band_count > 1:
        print(f"  ⚠️  {band_count} Bands in Supabase — PRUNE übersprungen (prune_catalog ist "
              f"nicht band-scoped, würde die anderen Bands löschen). Nur Upsert wurde ausgeführt.")
    else:
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
