"""
Einmaliges Import-Skript:

Liest Songteile aus `chaser_pact_songs.json` (Struktur: Songtitel -> Liste von
{step, function_name, note, start_ms, duration_ms}) und befüllt die Tabelle
`song_parts` in der lighting.db.

Mapping:
  - JSON-Key (Songtitel) -> `songs.name`
  - `step`             -> `segment_index` / Reihenfolge
  - `note`             -> `part_name` (wenn None -> wird übersprungen)
  - `start_ms`         -> zusätzliche Felder in song_parts (optional, falls erweitert)

Hinweis: Dieses Script wird typischerweise einmalig ausgeführt:

    python3 import_song_parts_from_json.py
"""

import json
from pathlib import Path
from typing import Dict, Any, List

from database import Database
from config import PROJECT_ROOT


JSON_PATH = Path.home() / "Downloads" / "chaser_pact_songs.json"


def load_json(path: Path) -> Dict[str, List[Dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def import_song_parts():
    db = Database()
    json_data = load_json(JSON_PATH)

    # Hole existierende Songs in ein Dict: name -> id
    songs_by_name = {s["name"]: s["id"] for s in db.get_all_songs()}

    imported_count = 0
    skipped_count = 0

    for song_name, parts in json_data.items():
        song_id = songs_by_name.get(song_name)
        if not song_id:
            print(f"[WARN] Song nicht in DB gefunden, übersprungen: {song_name}")
            continue

        # Hole BPM des Songs für Takte-Berechnung
        song = db.get_song(song_id)
        bpm = song.get("bpm") if song else None

        for entry in parts:
            step = entry.get("step")
            note = entry.get("note")
            start_ms = entry.get("start_ms", 0)
            duration_ms = entry.get("duration_ms", 0)

            # Part-Name bestimmen:
            # Wenn keine Note vorhanden ist, verwenden wir einen generischen Namen,
            # damit keine Lücken im Song entstehen.
            if note is None or str(note).strip() == "":
                part_name = f"Segment {step}"
            else:
                part_name = str(note).strip()

            # Endzeit berechnen: start_ms + duration_ms
            end_ms = None
            if start_ms and duration_ms:
                end_ms = int(start_ms) + int(duration_ms)
            elif start_ms:
                end_ms = int(start_ms)

            # Takte berechnen: duration_ms / (60000 / bpm) = bars
            bars = None
            if bpm and duration_ms and bpm > 0:
                # Ein Takt = 4/4 = 4 Schläge, also 4 * (60 / bpm) Sekunden
                # In Millisekunden: 4 * (60000 / bpm) ms
                ms_per_bar = 4 * (60000.0 / bpm)
                bars = round(duration_ms / ms_per_bar)

            # `song_parts`-Tabelle: song_id, part_name, start_segment, end_segment, start_ms, end_ms, duration_ms, bars
            db.add_song_part(
                song_id=song_id,
                part_name=part_name,
                start_segment=int(step),
                end_segment=int(step),
                start_ms=int(start_ms) if start_ms else None,
                end_ms=end_ms,
                duration_ms=int(duration_ms) if duration_ms else None,
                bars=bars,
            )
            imported_count += 1

    db.close()
    print(f"Songteile importiert: {imported_count}, übersprungen (ohne Note): {skipped_count}")


if __name__ == "__main__":
    if not JSON_PATH.exists():
        raise SystemExit(f"JSON-Datei nicht gefunden: {JSON_PATH}")
    import_song_parts()


