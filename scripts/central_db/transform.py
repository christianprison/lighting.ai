"""Lossless bidirectional transform: lighting-ai-db.json <-> central-DB rows.

Schema v3.1 (refinement of docs/architektur-zentrale-db.md §5):
- ``songs``                 — shared core columns (queryable by all projects)
- ``song_detail_lighting``  — lighting-only fields as a sparse JSONB ``detail``
- ``bars``                  — normalised (FK songs, UNIQUE(song_id, bar_num))
- ``accents``               — normalised (FK bars)
- ``app_state``             — singleton row for the global bits
                              (version, band, setlist, meta)

Why a refinement: §5 of the doc modelled songs/audio/features but had no home
for the top-level ``bars``/``accents`` collections nor the global
``setlist``/``meta``. Field-presence analysis of the real DB showed bars and
accents are perfectly regular, so they are normalised into tables (keeping the
UNIQUE(song_id, bar_num) the live pipeline relies on) rather than buried in
JSONB. Only the genuinely sparse, lighting-specific song fields stay in JSONB.

The two functions are exact inverses: ``rows_to_db_json(db_json_to_rows(db))``
reproduces ``db`` **byte-for-byte** when re-serialised with
``json.dumps(indent=2, ensure_ascii=False)`` — see tests/python/test_roundtrip.py.
"""

from __future__ import annotations

from typing import Any

# Shared core song fields -> Postgres ``songs`` columns.
# (json_field, column_name) — verified present on ALL songs, so no null/absence
# ambiguity. Order matches the JSON key order for byte-identical round-trips.
CORE_FIELDS: list[tuple[str, str]] = [
    ("name", "name"),
    ("artist", "artist"),
    ("bpm", "bpm"),
    ("key", "music_key"),
    ("year", "year"),
    ("pick", "pick"),
    ("gema_nr", "gema_nr"),
    ("duration", "duration"),
    ("duration_sec", "duration_sec"),
    ("notes", "notes"),
]
_CORE_JSON_FIELDS = {f for f, _ in CORE_FIELDS}

# Bar columns. The existing file has four historical key orderings; we emit the
# MAJORITY one (song_id first, 1747/2562 bars) so the first export canonicalises
# the fewest bars. ``instrumental`` is emitted last and only when truthy
# (198/2562 bars, always True). Key order is cosmetic — round-trip equality is
# order-independent; canonicalisation only matters for clean export diffs.
_BAR_PLAIN_FIELDS = ["song_id", "bar_num", "lyrics", "audio", "has_accents"]
_ACCENT_FIELDS = ["bar_id", "pos_16th", "type", "notes"]


def db_json_to_rows(db: dict[str, Any]) -> dict[str, Any]:
    """Split the monolithic db dict into central-DB table rows."""
    songs_rows: list[dict] = []
    detail_rows: list[dict] = []
    for sid, s in db.get("songs", {}).items():
        row = {"id": sid}
        for jf, col in CORE_FIELDS:
            row[col] = s[jf]
        songs_rows.append(row)
        detail = {k: v for k, v in s.items() if k not in _CORE_JSON_FIELDS}
        detail_rows.append({"song_id": sid, "detail": detail})

    bars_rows: list[dict] = []
    for bid, b in db.get("bars", {}).items():
        row = {"bar_id": bid}
        for f in _BAR_PLAIN_FIELDS:
            row[f] = b[f]
        row["instrumental"] = bool(b.get("instrumental", False))
        bars_rows.append(row)

    accents_rows: list[dict] = []
    for aid, a in db.get("accents", {}).items():
        row = {"accent_id": aid}
        for f in _ACCENT_FIELDS:
            row[f] = a[f]
        accents_rows.append(row)

    app_state = {
        "id": 1,
        "version": db.get("version"),
        "band": db.get("band"),
        "setlist": db.get("setlist"),
        "meta": db.get("meta"),
    }

    return {
        "songs": songs_rows,
        "song_detail_lighting": detail_rows,
        "bars": bars_rows,
        "accents": accents_rows,
        "app_state": app_state,
    }


def rows_to_db_json(rows: dict[str, Any]) -> dict[str, Any]:
    """Reassemble the monolithic db dict from central-DB table rows.

    Rebuilds keys in the original order so the result re-serialises
    byte-identically to the source file.
    """
    app = rows["app_state"]
    db: dict[str, Any] = {
        "version": app["version"],
        "band": app["band"],
        "setlist": app["setlist"],
        "songs": {},
        "bars": {},
        "accents": {},
        "meta": app["meta"],
    }

    detail_by_id = {r["song_id"]: r["detail"] for r in rows["song_detail_lighting"]}
    for srow in rows["songs"]:
        sid = srow["id"]
        s: dict[str, Any] = {}
        for jf, col in CORE_FIELDS:          # core first, original order
            s[jf] = srow[col]
        s.update(detail_by_id.get(sid, {}))  # then sparse detail, original order
        db["songs"][sid] = s

    for brow in rows["bars"]:
        b = {f: brow[f] for f in _BAR_PLAIN_FIELDS}
        if brow.get("instrumental"):         # emit only when True (matches source)
            b["instrumental"] = True
        db["bars"][brow["bar_id"]] = b

    for arow in rows["accents"]:
        db["accents"][arow["accent_id"]] = {f: arow[f] for f in _ACCENT_FIELDS}

    return db
