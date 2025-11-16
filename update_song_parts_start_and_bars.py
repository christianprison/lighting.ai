"""
Skript zum einmaligen Update aller Songteile:
- Setzt Startzeit auf 0:00 für Position 1, 2 oder 3 ohne Startzeit
- Berechnet Takte basierend auf BPM
"""

from database import Database


def update_all_song_parts():
    """Aktualisiert alle Songteile: Startzeiten und Takte."""
    db = Database()
    
    all_songs = db.get_all_songs()
    updated_start_count = 0
    updated_bars_count = 0
    
    print(f"Verarbeite {len(all_songs)} Songs...\n")
    
    for song in all_songs:
        song_id = song["id"]
        song_name = song["name"]
        bpm = song.get("bpm")
        
        parts = db.get_song_parts(song_id)
        parts = sorted(parts, key=lambda p: p.get("start_segment", 0))
        
        print(f"Song: {song_name} (BPM: {bpm})")
        
        for part in parts:
            start_segment = part.get("start_segment", 0)
            start_ms = part.get("start_ms")
            end_ms = part.get("end_ms")
            duration_ms = part.get("duration_ms")
            bars = part.get("bars")
            part_name = part.get("part_name", "")
            
            # Setze Startzeit auf 0:00 für Position 1, 2 oder 3 ohne Startzeit
            if (start_segment in [1, 2, 3] and 
                (start_ms is None or start_ms == 0) and 
                end_ms is not None and end_ms > 0):
                db.update_song_part(part["id"], start_ms=0)
                # Berechne end_ms neu, falls duration_ms vorhanden ist
                if duration_ms:
                    db.update_song_part(part["id"], end_ms=duration_ms)
                updated_start_count += 1
                print(f"  ✓ Position {start_segment} ({part_name}): Startzeit auf 0:00 gesetzt")
            
            # Berechne Takte basierend auf BPM
            if bpm and bpm > 0 and duration_ms and duration_ms > 0:
                # Dauer einer Viertelnote in ms
                quarter_note_ms = 60000.0 / bpm
                # Anzahl der Viertelnoten
                quarter_notes = duration_ms / quarter_note_ms
                # Anzahl der Takte (4/4-Takt: 4 Viertelnoten pro Takt)
                calculated_bars = round(quarter_notes / 4.0)
                
                # Aktualisiere nur wenn bars fehlt oder abweicht
                if bars is None or abs(bars - calculated_bars) > 0.5:
                    db.update_song_part(part["id"], bars=calculated_bars)
                    updated_bars_count += 1
                    old_bars = bars if bars is not None else "None"
                    print(f"  ✓ {part_name}: Takte von {old_bars} auf {calculated_bars} aktualisiert")
    
    db.close()
    
    print("\n" + "="*60)
    print(f"Zusammenfassung:")
    print(f"  Startzeiten aktualisiert: {updated_start_count}")
    print(f"  Takte aktualisiert: {updated_bars_count}")


if __name__ == "__main__":
    update_all_song_parts()

