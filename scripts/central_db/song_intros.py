"""Build song_intros rows from the hand-authored db/song-intros.json.

Authoring format (keyed by song_id; notes listed in playing order, idx derived):
    {
      "5iZfKj": [
        {"midi": 38, "beat": 0.0, "duration_beats": 0.5, "string": 3, "fret": 0, "note_name": "D2"},
        ...
      ]
    }
Keys starting with "_" are ignored (templates / notes-to-self). Unknown song_ids
are skipped (reported), so a typo can't break the sync.

Pure / offline.
"""

from __future__ import annotations

from typing import Any

_NOTE_FIELDS = ("midi", "beat", "duration_beats", "string", "fret", "note_name")


def song_intros_rows(intros: dict[str, Any], valid_song_ids: set[str]) -> tuple[list[dict], list[str]]:
    """Return (rows, skipped_song_ids). idx is derived 1..N from list order."""
    rows: list[dict] = []
    skipped: list[str] = []
    for sid, notes in intros.items():
        if sid.startswith("_"):
            continue
        if sid not in valid_song_ids:
            skipped.append(sid)
            continue
        for i, n in enumerate(notes, start=1):
            rows.append({
                "song_id": sid,
                "idx": i,
                "midi": n["midi"],
                "beat": n["beat"],
                "duration_beats": n.get("duration_beats"),
                "string": n.get("string"),
                "fret": n.get("fret"),
                "note_name": n.get("note_name"),
            })
    return rows, skipped
