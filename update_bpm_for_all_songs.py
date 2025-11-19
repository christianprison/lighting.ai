#!/usr/bin/env python3
"""
Script zum Aktualisieren der BPM für alle Songs mit Audiofiles
mittels Beat-Detection.
"""

import sys
import tempfile
from pathlib import Path
from database import Database
from audio_beat_detection import detect_beats_from_audio
import logging

# Logger konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def update_bpm_for_all_songs():
    """Aktualisiert die BPM für alle Songs mit Audiofiles."""
    db = Database()
    
    # Hole alle Songs
    all_songs = db.get_all_songs()
    logger.info(f"Gefundene Songs: {len(all_songs)}")
    
    songs_with_audio = []
    songs_without_audio = []
    songs_updated = 0
    songs_failed = 0
    songs_skipped = 0
    
    for song in all_songs:
        song_id = song['id']
        song_name = song.get('name', 'Unbekannt')
        current_bpm = song.get('bpm')
        
        # Hole Audiofiles für diesen Song
        audio_files = db.get_audio_files_for_song(song_id)
        
        if not audio_files:
            songs_without_audio.append(song_name)
            logger.info(f"Song '{song_name}' (ID: {song_id}): Keine Audiofiles")
            continue
        
        songs_with_audio.append((song_id, song_name, audio_files))
        logger.info(f"Song '{song_name}' (ID: {song_id}): {len(audio_files)} Audiofile(s)")
    
    logger.info(f"\n{'='*80}")
    logger.info(f"Songs ohne Audiofiles: {len(songs_without_audio)}")
    logger.info(f"Songs mit Audiofiles: {len(songs_with_audio)}")
    logger.info(f"{'='*80}\n")
    
    # Verarbeite jeden Song mit Audiofiles
    for song_id, song_name, audio_files in songs_with_audio:
        logger.info(f"\n{'='*80}")
        logger.info(f"Verarbeite Song: '{song_name}' (ID: {song_id})")
        logger.info(f"{'='*80}")
        
        # Verwende das erste/neueste Audiofile
        audio_file = audio_files[0]
        audio_file_id = audio_file['id']
        file_name = audio_file.get('file_name', 'unknown')
        offset_sec = audio_file.get('offset_sec', 0.0) or 0.0
        
        logger.info(f"Verwende Audiofile: {file_name} (ID: {audio_file_id})")
        logger.info(f"Offset: {offset_sec}s")
        
        # Hole aktuelles BPM (als Hint)
        song = db.get_song(song_id)
        bpm_hint = song.get('bpm') if song else None
        
        if bpm_hint:
            logger.info(f"Aktuelles BPM: {bpm_hint} (wird als Hint verwendet)")
        else:
            logger.info("Kein aktuelles BPM vorhanden")
        
        # Erstelle temporäre Datei aus BLOB
        temp_file = None
        try:
            audio_data = audio_file.get('audio_data')
            if not audio_data:
                logger.warning(f"Audiofile {audio_file_id} hat keine Daten (BLOB ist None)")
                songs_skipped += 1
                continue
            
            # Erstelle temporäre Datei
            temp_dir = Path(tempfile.gettempdir())
            temp_file = temp_dir / f"lighting_ai_{song_id}_{audio_file_id}_{file_name}"
            
            logger.info(f"Schreibe temporäre Datei: {temp_file}")
            temp_file.write_bytes(audio_data)
            logger.info(f"Temporäre Datei erstellt: {len(audio_data)} Bytes")
            
            # Führe Beat-Detection durch
            logger.info("Starte Beat-Detection...")
            beat_times, detected_bpm, audio_duration = detect_beats_from_audio(
                temp_file,
                bpm_hint=bpm_hint,
                offset_sec=offset_sec
            )
            
            if detected_bpm and detected_bpm > 0:
                logger.info(f"✓ BPM erkannt: {detected_bpm:.2f}")
                logger.info(f"  Beats erkannt: {len(beat_times) if beat_times else 0}")
                logger.info(f"  Audio-Dauer: {audio_duration:.2f}s" if audio_duration else "  Audio-Dauer: unbekannt")
                
                # Aktualisiere BPM in der Datenbank
                db.update_song(song_id, bpm=detected_bpm)
                
                logger.info(f"✓ BPM in Datenbank aktualisiert: {detected_bpm:.2f}")
                songs_updated += 1
            else:
                logger.warning(f"✗ Kein BPM erkannt für Song '{song_name}'")
                if beat_times and len(beat_times) > 0:
                    logger.warning(f"  Aber {len(beat_times)} Beats wurden erkannt")
                songs_failed += 1
        
        except Exception as e:
            logger.error(f"✗ Fehler bei Song '{song_name}': {e}", exc_info=True)
            songs_failed += 1
        
        finally:
            # Lösche temporäre Datei
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                    logger.debug(f"Temporäre Datei gelöscht: {temp_file}")
                except Exception as e:
                    logger.warning(f"Konnte temporäre Datei nicht löschen: {e}")
    
    # Zusammenfassung
    logger.info(f"\n{'='*80}")
    logger.info("ZUSAMMENFASSUNG")
    logger.info(f"{'='*80}")
    logger.info(f"Songs ohne Audiofiles: {len(songs_without_audio)}")
    logger.info(f"Songs mit Audiofiles: {len(songs_with_audio)}")
    logger.info(f"  ✓ Erfolgreich aktualisiert: {songs_updated}")
    logger.info(f"  ✗ Fehlgeschlagen: {songs_failed}")
    logger.info(f"  ⊘ Übersprungen: {songs_skipped}")
    logger.info(f"{'='*80}")
    
    db.close()

if __name__ == "__main__":
    try:
        update_bpm_for_all_songs()
    except KeyboardInterrupt:
        logger.info("\nAbgebrochen durch Benutzer")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fehler: {e}", exc_info=True)
        sys.exit(1)

