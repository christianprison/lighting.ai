#!/usr/bin/env python3
"""
Importiert Narratives aus fixture_scenes.json in die Datenbank
"""
import json
import logging
import re
from pathlib import Path

from config import DATA_DIR
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


def import_narratives():
    """Importiert Narratives aus fixture_scenes.json in die Datenbank"""
    db = Database()
    
    scenes_json_path = DATA_DIR / 'fixture_scenes.json'
    
    if not scenes_json_path.exists():
        logger.error(f'JSON-Datei nicht gefunden: {scenes_json_path}')
        return
    
    with open(scenes_json_path, 'r', encoding='utf-8') as f:
        scenes_data = json.load(f)
    
    if 'all_scenes' not in scenes_data:
        logger.error('Kein "all_scenes" Feld in JSON-Datei gefunden')
        return
    
    scenes_list = scenes_data['all_scenes']
    logger.info(f'Gefunden: {len(scenes_list)} Scenes in JSON')
    
    # Sortiere alphabetisch mit natürlicher Sortierung
    sorted_scenes = sorted(scenes_list, key=natural_sort_key)
    
    imported_count = 0
    skipped_count = 0
    
    for scene_name in sorted_scenes:
        # Prüfe ob Narrative bereits existiert
        existing = db.get_narrative(name=scene_name)
        if existing:
            logger.debug(f'Narrative "{scene_name}" bereits vorhanden, überspringe')
            skipped_count += 1
            continue
        
        try:
            # Erstelle neue Narrative
            narrative_id = db.create_narrative(
                name=scene_name,
                description=None,
                mood=None
            )
            logger.info(f'Narrative "{scene_name}" importiert (ID: {narrative_id})')
            imported_count += 1
        except Exception as e:
            logger.error(f'Fehler beim Importieren von "{scene_name}": {e}')
    
    logger.info(f'Import abgeschlossen: {imported_count} neue Narratives importiert, {skipped_count} übersprungen')


if __name__ == '__main__':
    import_narratives()

