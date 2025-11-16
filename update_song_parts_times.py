"""
Update-Skript: Aktualisiert Start- und Endzeiten in der song_parts Tabelle
aus chaser_pact_songs.json für bereits importierte Songteile.
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


def update_song_parts_times():
    """Aktualisiert Start- und Endzeiten für bereits importierte Songteile."""
    db = Database()
    json_data = load_json(JSON_PATH)

    # Hole existierende Songs in ein Dict: name -> id
    songs_by_name = {s["name"]: s["id"] for s in db.get_all_songs()}

    updated_count = 0
    not_found_count = 0

    for song_name, parts in json_data.items():
        song_id = songs_by_name.get(song_name)
        if not song_id:
            print(f"[WARN] Song nicht in DB gefunden, übersprungen: {song_name}")
            not_found_count += 1
            continue

        # Hole alle existierenden Songteile für diesen Song
        existing_parts = db.get_song_parts(song_id)
        # Erstelle ein Dict: start_segment -> part
        parts_by_segment = {p.get("start_segment"): p for p in existing_parts}

        for entry in parts:
            step = entry.get("step")
            start_ms = entry.get("start_ms", 0)
            duration_ms = entry.get("duration_ms", 0)

            # Finde den entsprechenden Songteil
            part = parts_by_segment.get(int(step))
            if not part:
                continue  # Songteil existiert nicht in DB

            # Endzeit berechnen: start_ms + duration_ms
            end_ms = None
            if start_ms and duration_ms:
                end_ms = int(start_ms) + int(duration_ms)
            elif start_ms:
                end_ms = int(start_ms)

            # Update des Songteils
            db.update_song_part(
                part["id"],
                start_ms=int(start_ms) if start_ms else None,
                end_ms=end_ms,
                duration_ms=int(duration_ms) if duration_ms else None,
            )
            updated_count += 1

    db.close()
    print(f"Songteile aktualisiert: {updated_count}")
    if not_found_count > 0:
        print(f"Songs nicht gefunden: {not_found_count}")


if __name__ == "__main__":
    if not JSON_PATH.exists():
        raise SystemExit(f"JSON-Datei nicht gefunden: {JSON_PATH}")
    update_song_parts_times()

