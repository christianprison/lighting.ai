"""
Skript zum Setzen fehlender Startzeiten auf 0:00 für Songteile mit Endzeit aber ohne Startzeit.
"""

from database import Database


def set_missing_start_times():
    """Setzt fehlende Startzeiten auf 0:00."""
    db = Database()
    
    all_songs = db.get_all_songs()
    updated_count = 0
    
    print(f"Verarbeite {len(all_songs)} Songs...\n")
    
    for song in all_songs:
        song_id = song["id"]
        song_name = song["name"]
        
        parts = db.get_song_parts(song_id)
        
        for part in parts:
            start_ms = part.get("start_ms")
            end_ms = part.get("end_ms")
            duration_ms = part.get("duration_ms")
            part_name = part.get("part_name", "")
            
            # Setze Startzeit auf 0, wenn:
            # 1. Startzeit fehlt (None oder 0) UND
            # 2. (Endzeit vorhanden ODER Dauer vorhanden)
            needs_update = False
            new_start_ms = 0
            new_end_ms = end_ms
            
            if (start_ms is None or start_ms == 0):
                if (end_ms is not None and end_ms > 0):
                    # Endzeit vorhanden, aber keine Startzeit -> setze Startzeit auf 0
                    needs_update = True
                    new_start_ms = 0
                    new_end_ms = end_ms
                elif (duration_ms is not None and duration_ms > 0):
                    # Nur Dauer vorhanden, keine Startzeit -> setze Startzeit auf 0, berechne Endzeit
                    needs_update = True
                    new_start_ms = 0
                    new_end_ms = duration_ms
            
            if needs_update:
                # Update mit beiden Werten
                db.update_song_part(part["id"], start_ms=new_start_ms, end_ms=new_end_ms)
                updated_count += 1
                print(f"  ✓ {song_name} - {part_name}: Startzeit auf 0:00 gesetzt, Endzeit: {new_end_ms}ms")
    
    db.close()
    
    print("\n" + "="*60)
    print(f"Zusammenfassung:")
    print(f"  Startzeiten aktualisiert: {updated_count}")


if __name__ == "__main__":
    set_missing_start_times()

