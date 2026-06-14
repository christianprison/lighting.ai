"""Build song_intros rows from the hand-authored db/song-intros.json.

Authoring is bass-player friendly: per note you give the BEAT plus the pitch in
whichever form is easiest — pick ONE:
  - string + fret   (e.g. {"string": 3, "fret": 2, "beat": 0.0})   ← easiest
  - note_name        (e.g. {"note_name": "D2", "beat": 0.0})
  - midi             (e.g. {"midi": 38, "beat": 0.0})
The canonical SOUNDING `midi` (and a `note_name`) is computed for the DB either
way, so BassTrainer always gets a clean midi.

    {
      "5iJ0Ns": [
        {"string": 3, "fret": 0, "beat": 0.0, "duration_beats": 0.5},
        {"string": 4, "fret": 2, "beat": 1.0}
      ]
    }

Keys starting with "_" are ignored (templates). Unknown song_ids are skipped.
A song whose notes can't be resolved is skipped whole (so idx stays gap-free and
no half/wrong intro is shown) and reported — it never aborts the catalog sync.

Pure / offline.
"""

from __future__ import annotations

import re
from typing import Any

# Open-string SOUNDING midi (4-string bass): E1=28, A1=33, D2=38, G2=43.
_OPEN = {1: 28, 2: 33, 3: 38, 4: 43}
_PITCH_CLASS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_NOTE_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")


def _note_to_midi(name: str) -> int:
    m = _NOTE_RE.match(name.strip())
    if not m:
        raise ValueError(f"bad note_name '{name}'")
    letter, accidental, octave = m.group(1).upper(), m.group(2), int(m.group(3))
    semis = _PITCH_CLASS[letter] + (1 if accidental == "#" else -1 if accidental == "b" else 0)
    return (octave + 1) * 12 + semis


def _midi_to_name(midi: int) -> str:
    return f"{_NAMES[midi % 12]}{midi // 12 - 1}"


def _resolve_midi(n: dict) -> int:
    if "midi" in n:
        midi = int(n["midi"])
    elif "string" in n and "fret" in n:
        s = int(n["string"])
        if s not in _OPEN:
            raise ValueError(f"string must be 1..4 (E..G), got {s}")
        midi = _OPEN[s] + int(n["fret"])
    elif n.get("note_name") or n.get("note"):
        midi = _note_to_midi(n.get("note_name") or n["note"])
    else:
        raise ValueError("note needs one of: string+fret, note_name, or midi")
    if not (0 <= midi <= 127):
        raise ValueError(f"midi {midi} out of range")
    return midi


def song_intros_rows(
    intros: dict[str, Any], valid_song_ids: set[str]
) -> tuple[list[dict], list[str], list[str]]:
    """Return (rows, skipped_unknown_song_ids, problems). idx derived 1..N."""
    rows: list[dict] = []
    skipped: list[str] = []
    problems: list[str] = []
    for sid, notes in intros.items():
        if sid.startswith("_"):
            continue
        if sid not in valid_song_ids:
            skipped.append(sid)
            continue
        try:
            song_rows = []
            for i, n in enumerate(notes, start=1):
                midi = _resolve_midi(n)
                song_rows.append({
                    "song_id": sid,
                    "idx": i,
                    "midi": midi,
                    "beat": n["beat"],
                    "duration_beats": n.get("duration_beats"),
                    "string": n.get("string"),
                    "fret": n.get("fret"),
                    "note_name": n.get("note_name") or _midi_to_name(midi),
                })
            rows.extend(song_rows)
        except (KeyError, ValueError, TypeError) as exc:
            problems.append(f"{sid}: {exc}")
    return rows, skipped, problems
