#!/usr/bin/env python3
"""
Importiert Moods in die Datenbank
"""
import logging
import re

from database import Database

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def natural_sort_key(name):
    """Natürliche Sortierung für Strings mit Nummern"""
    if not name:
        return []
    parts = re.split(r'(\d+)', name.lower())
    result = []
    for part in parts:
        if part.isdigit():
            result.append(int(part))
        else:
            result.append(part)
    return result


def import_moods():
    """Importiert Moods in die Datenbank"""
    db = Database()
    
    moods_list = [
        "stimulated",
        "energized",
        "lively",
        "awake",
        "excited",
        "happy",
        "joyful",
        "grateful",
        "cheerful",
        "relieved",
        "optimistic",
        "relaxed",
        "calm",
        "peaceful",
        "content",
        "loving",
        "compassionate",
        "safe",
        "supported",
        "connected",
        "confident",
        "courageous",
        "recognized",
        "powerful",
        "inspired",
        "afraid",
        "anxious",
        "worried",
        "insecure",
        "overwhelmed",
        "helpless",
        "sad",
        "disappointed",
        "exhausted",
        "depressed",
        "resigned",
        "angry",
        "annoyed",
        "frustrated",
        "irritated",
        "outraged",
        "ashamed",
        "guilty",
        "embarrassed",
        "uneasy",
        "lonely",
        "isolated",
        "misunderstood",
        "unloved",
        "uncertain",
        "confused",
        "puzzled",
        "disoriented"
    ]
    
    logger.info(f'Gefunden: {len(moods_list)} Moods zum Importieren')
    
    # Sortiere alphabetisch mit natürlicher Sortierung
    sorted_moods = sorted(moods_list, key=natural_sort_key)
    
    imported_count = 0
    skipped_count = 0
    
    for mood_name in sorted_moods:
        # Prüfe ob Mood bereits existiert
        existing = db.get_mood(name=mood_name)
        if existing:
            logger.debug(f'Mood "{mood_name}" bereits vorhanden, überspringe')
            skipped_count += 1
            continue
        
        try:
            # Erstelle neuen Mood
            mood_id = db.create_mood(
                name=mood_name,
                description=None,
                category=None
            )
            logger.info(f'Mood "{mood_name}" importiert (ID: {mood_id})')
            imported_count += 1
        except Exception as e:
            logger.error(f'Fehler beim Importieren von "{mood_name}": {e}')
    
    logger.info(f'Import abgeschlossen: {imported_count} neue Moods importiert, {skipped_count} übersprungen')


if __name__ == '__main__':
    import_moods()

