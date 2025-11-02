"""
Datenbankmodul für lighting.ai - SQLite-Verwaltung
"""
import sqlite3
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import json

from config import DB_PATH

logger = logging.getLogger(__name__)


class Database:
    """Verwaltung der SQLite-Datenbank für Referenzdaten"""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.conn = None
        self._initialize_database()
    
    def _initialize_database(self):
        """Initialisiert die Datenbank mit den notwendigen Tabellen"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row  # Ermöglicht dict-ähnlichen Zugriff
        
        cursor = self.conn.cursor()
        
        # Tabelle für Songs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                artist TEXT,
                duration REAL,  -- Dauer in Sekunden
                bpm REAL,       -- Beats per Minute
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT
            )
        """)
        
        # Tabelle für Song-Referenzdaten (Meter-Values pro Takt/Segment)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS song_reference_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                song_id INTEGER NOT NULL,
                segment_index INTEGER NOT NULL,  -- Index des Segments (Takt/Beat/etc.)
                timestamp REAL NOT NULL,  -- Zeitpunkt im Song
                meter_values TEXT NOT NULL,  -- JSON-Array mit allen Kanal-Meter-Values
                FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE,
                UNIQUE(song_id, segment_index)
            )
        """)
        
        # Tabelle für Song-Teile (Vers, Refrain, Bridge, etc.)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS song_parts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                song_id INTEGER NOT NULL,
                part_name TEXT NOT NULL,  -- "verse", "chorus", "bridge", etc.
                start_segment INTEGER NOT NULL,
                end_segment INTEGER NOT NULL,
                FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE
            )
        """)
        
        # Tabelle für Licht-Programme (DMX-Werte pro Segment)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS light_programs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                song_id INTEGER NOT NULL,
                segment_index INTEGER NOT NULL,
                universe INTEGER NOT NULL,
                dmx_values TEXT NOT NULL,  -- JSON-Array mit DMX-Werten (512 Kanäle)
                FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE,
                UNIQUE(song_id, segment_index, universe)
            )
        """)
        
        # Tabelle für Manuelle Akzente (Strobe, Blackout, Fog, etc.)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS manual_accents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                dmx_values TEXT NOT NULL,  -- JSON-Array pro Universe
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabelle für Show-Setlists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS show_setlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                songs_order TEXT NOT NULL,  -- JSON-Array mit Song-IDs in Reihenfolge
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Indizes für bessere Performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_song_ref_song_id ON song_reference_data(song_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_song_ref_timestamp ON song_reference_data(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_song_parts_song_id ON song_parts(song_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_light_programs_song_id ON light_programs(song_id)")
        
        self.conn.commit()
        logger.info(f"Datenbank initialisiert: {self.db_path}")
    
    def get_connection(self):
        """Gibt die Datenbankverbindung zurück"""
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
        return self.conn
    
    # Song-Verwaltung
    def add_song(self, name: str, artist: str = None, duration: float = None, 
                 bpm: float = None, notes: str = None) -> int:
        """Fügt einen neuen Song hinzu und gibt die ID zurück"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO songs (name, artist, duration, bpm, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (name, artist, duration, bpm, notes))
        conn.commit()
        return cursor.lastrowid
    
    def get_song(self, song_id: int) -> Optional[Dict]:
        """Lädt einen Song nach ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM songs WHERE id = ?", (song_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def get_all_songs(self) -> List[Dict]:
        """Gibt alle Songs zurück"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM songs ORDER BY name")
        return [dict(row) for row in cursor.fetchall()]
    
    def update_song(self, song_id: int, **kwargs):
        """Aktualisiert Song-Daten"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Nur erlaubte Felder aktualisieren
        allowed_fields = ['name', 'artist', 'duration', 'bpm', 'notes']
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if not updates:
            return
        
        updates['updated_at'] = datetime.now().isoformat()
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [song_id]
        
        cursor.execute(f"UPDATE songs SET {set_clause} WHERE id = ?", values)
        conn.commit()
    
    def delete_song(self, song_id: int):
        """Löscht einen Song und alle zugehörigen Daten"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM songs WHERE id = ?", (song_id,))
        conn.commit()
    
    # Referenzdaten-Verwaltung
    def add_reference_data(self, song_id: int, segment_index: int, 
                          timestamp: float, meter_values: List[float]):
        """Fügt Referenzdaten (Meter-Values) für einen Song hinzu"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO song_reference_data 
            (song_id, segment_index, timestamp, meter_values)
            VALUES (?, ?, ?, ?)
        """, (song_id, segment_index, timestamp, json.dumps(meter_values)))
        conn.commit()
    
    def get_reference_data(self, song_id: int) -> List[Dict]:
        """Gibt alle Referenzdaten für einen Song zurück"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM song_reference_data 
            WHERE song_id = ? 
            ORDER BY segment_index
        """, (song_id,))
        rows = cursor.fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data['meter_values'] = json.loads(data['meter_values'])
            result.append(data)
        return result
    
    # Song-Teile
    def add_song_part(self, song_id: int, part_name: str, 
                     start_segment: int, end_segment: int):
        """Fügt einen Song-Teil hinzu"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO song_parts (song_id, part_name, start_segment, end_segment)
            VALUES (?, ?, ?, ?)
        """, (song_id, part_name, start_segment, end_segment))
        conn.commit()
    
    def get_song_parts(self, song_id: int) -> List[Dict]:
        """Gibt alle Teile eines Songs zurück"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM song_parts 
            WHERE song_id = ? 
            ORDER BY start_segment
        """, (song_id,))
        return [dict(row) for row in cursor.fetchall()]
    
    # Licht-Programme
    def save_light_program(self, song_id: int, segment_index: int, 
                          universe: int, dmx_values: List[int]):
        """Speichert DMX-Werte für einen Song-Segment"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO light_programs 
            (song_id, segment_index, universe, dmx_values)
            VALUES (?, ?, ?, ?)
        """, (song_id, segment_index, universe, json.dumps(dmx_values)))
        conn.commit()
    
    def get_light_program(self, song_id: int, segment_index: int) -> Dict[int, List[int]]:
        """Gibt DMX-Werte für einen Segment zurück (nach Universe organisiert)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT universe, dmx_values FROM light_programs
            WHERE song_id = ? AND segment_index = ?
        """, (song_id, segment_index))
        result = {}
        for row in cursor.fetchall():
            result[row['universe']] = json.loads(row['dmx_values'])
        return result
    
    # Manuelle Akzente
    def add_manual_accent(self, name: str, description: str, 
                         dmx_values_per_universe: Dict[int, List[int]]):
        """Fügt einen manuellen Akzent hinzu"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO manual_accents (name, description, dmx_values)
            VALUES (?, ?, ?)
        """, (name, description, json.dumps(dmx_values_per_universe)))
        conn.commit()
    
    def get_manual_accent(self, name: str) -> Optional[Dict]:
        """Lädt einen manuellen Akzent"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM manual_accents WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row:
            result = dict(row)
            result['dmx_values'] = json.loads(result['dmx_values'])
            return result
        return None
    
    def get_all_manual_accents(self) -> List[Dict]:
        """Gibt alle manuellen Akzente zurück"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM manual_accents ORDER BY name")
        rows = cursor.fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data['dmx_values'] = json.loads(data['dmx_values'])
            result.append(data)
        return result
    
    # Setlists
    def create_setlist(self, name: str, song_ids: List[int], description: str = None) -> int:
        """Erstellt eine neue Setlist"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO show_setlists (name, description, songs_order)
            VALUES (?, ?, ?)
        """, (name, description, json.dumps(song_ids)))
        conn.commit()
        return cursor.lastrowid
    
    def get_setlist(self, setlist_id: int) -> Optional[Dict]:
        """Lädt eine Setlist"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM show_setlists WHERE id = ?", (setlist_id,))
        row = cursor.fetchone()
        if row:
            result = dict(row)
            result['songs_order'] = json.loads(result['songs_order'])
            return result
        return None
    
    def get_all_setlists(self) -> List[Dict]:
        """Gibt alle Setlists zurück"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM show_setlists ORDER BY name")
        rows = cursor.fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data['songs_order'] = json.loads(data['songs_order'])
            result.append(data)
        return result
    
    def close(self):
        """Schließt die Datenbankverbindung"""
        if self.conn:
            self.conn.close()
            self.conn = None

