"""
Import-Skript: Importiert MP3-Dateien aus "/home/thepact/git/PACT Songs mp3"
als BLOB in die audio_files Tabelle.

Dateiname-Format: YYYYMMDD Songtitel.mp3
"""

import re
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime

from database import Database


AUDIO_DIR = Path("/home/thepact/git/PACT Songs mp3")


def parse_filename(filename: str) -> Optional[Tuple[str, str]]:
    """
    Parst Dateinamen im Format YYYYMMDD Songtitel.mp3
    
    Returns:
        (recording_date, song_title) oder None wenn Format nicht passt
    """
    # Entferne .mp3 Extension
    name_without_ext = filename.replace(".mp3", "").strip()
    
    # Regex: 8 Ziffern am Anfang (YYYYMMDD), dann Leerzeichen, dann Rest
    match = re.match(r"^(\d{8})\s+(.+)$", name_without_ext)
    if not match:
        return None
    
    date_str = match.group(1)
    song_title = match.group(2).strip()
    
    # Validiere Datum
    try:
        datetime.strptime(date_str, "%Y%m%d")
    except ValueError:
        return None
    
    # Formatiere Datum als ISO-String (YYYY-MM-DD)
    recording_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    
    return (recording_date, song_title)


def find_song_by_title(db: Database, title: str) -> Optional[int]:
    """
    Findet einen Song in der DB anhand des Titels.
    Versucht exakte Übereinstimmung, dann case-insensitive, dann Teilstring.
    """
    all_songs = db.get_all_songs()
    
    # Exakte Übereinstimmung
    for song in all_songs:
        if song["name"] == title:
            return song["id"]
    
    # Case-insensitive
    title_lower = title.lower()
    for song in all_songs:
        if song["name"].lower() == title_lower:
            return song["id"]
    
    # Teilstring-Matching (Songtitel enthält den gesuchten Titel oder umgekehrt)
    for song in all_songs:
        song_name_lower = song["name"].lower()
        if title_lower in song_name_lower or song_name_lower in title_lower:
            return song["id"]
    
    return None


def import_audio_files():
    """Importiert alle MP3-Dateien aus dem Verzeichnis."""
    if not AUDIO_DIR.exists():
        print(f"Fehler: Verzeichnis nicht gefunden: {AUDIO_DIR}")
        return
    
    db = Database()
    
    mp3_files = list(AUDIO_DIR.glob("*.mp3"))
    print(f"Gefundene MP3-Dateien: {len(mp3_files)}")
    
    imported_count = 0
    skipped_count = 0
    not_found_songs = []
    
    for mp3_file in sorted(mp3_files):
        filename = mp3_file.name
        print(f"\nVerarbeite: {filename}")
        
        # Parse Dateiname
        parsed = parse_filename(filename)
        if not parsed:
            print(f"  ✗ Konnte Dateinamen nicht parsen")
            skipped_count += 1
            continue
        
        recording_date, song_title = parsed
        print(f"  Datum: {recording_date}, Titel: {song_title}")
        
        # Finde Song in DB
        song_id = find_song_by_title(db, song_title)
        if not song_id:
            print(f"  ✗ Song nicht in DB gefunden: {song_title}")
            not_found_songs.append((filename, song_title))
            skipped_count += 1
            continue
        
        # Lese Datei als BLOB
        try:
            audio_data = mp3_file.read_bytes()
            print(f"  Dateigröße: {len(audio_data)} Bytes")
        except Exception as e:
            print(f"  ✗ Fehler beim Lesen der Datei: {e}")
            skipped_count += 1
            continue
        
        # Speichere in DB
        try:
            audio_file_id = db.add_audio_file(
                song_id=song_id,
                audio_data=audio_data,
                file_name=filename,
                recording_date=recording_date,
                notes=f"Importiert aus {AUDIO_DIR}"
            )
            print(f"  ✓ Importiert (ID: {audio_file_id})")
            imported_count += 1
        except Exception as e:
            print(f"  ✗ Fehler beim Speichern: {e}")
            skipped_count += 1
            continue
    
    db.close()
    
    print(f"\n{'='*60}")
    print(f"Zusammenfassung:")
    print(f"  Importiert: {imported_count}")
    print(f"  Übersprungen: {skipped_count}")
    if not_found_songs:
        print(f"\nNicht gefundene Songs:")
        for filename, title in not_found_songs:
            print(f"  - {filename} -> '{title}'")


if __name__ == "__main__":
    import_audio_files()

