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
        
        # Tabelle für Kanalzuordnungen (Instrument -> OSC-Kanal)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS channel_mapping (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_name TEXT NOT NULL UNIQUE,
                channel_index INTEGER NOT NULL,  -- OSC-Kanal-Index (0-17 für XR18)
                display_name TEXT NOT NULL,  -- Anzeigename
                musician_name TEXT,  -- Musiker (Axel, Pete, Tim, Bibo)
                position INTEGER,  -- Position von links (1-4)
                icon_path TEXT,  -- Pfad zum Icon-Bild
                color_r REAL DEFAULT 0.5,  -- Farbe RGB (0-1)
                color_g REAL DEFAULT 0.5,
                color_b REAL DEFAULT 0.5,
                -- Position auf Hintergrundbild (relativ 0.0-1.0 oder absolut in Pixel)
                bg_pos_x REAL,  -- X-Position auf Hintergrundbild (0.0-1.0 für Prozent, >1 für Pixel)
                bg_pos_y REAL,  -- Y-Position auf Hintergrundbild (0.0-1.0 für Prozent, >1 für Pixel)
                icon_width REAL,  -- Breite des Icons (relativ 0.0-1.0 oder absolut)
                icon_height REAL,  -- Höhe des Icons (relativ 0.0-1.0 oder absolut)
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Migration: Füge neue Spalten hinzu falls sie fehlen
        try:
            cursor.execute("ALTER TABLE channel_mapping ADD COLUMN musician_name TEXT")
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits
        
        try:
            cursor.execute("ALTER TABLE channel_mapping ADD COLUMN position INTEGER")
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits
        
        try:
            cursor.execute("ALTER TABLE channel_mapping ADD COLUMN icon_path TEXT")
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits
        
        try:
            cursor.execute("ALTER TABLE channel_mapping ADD COLUMN bg_pos_x REAL")
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits
        
        try:
            cursor.execute("ALTER TABLE channel_mapping ADD COLUMN bg_pos_y REAL")
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits
        
        try:
            cursor.execute("ALTER TABLE channel_mapping ADD COLUMN icon_width REAL")
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits
        
        try:
            cursor.execute("ALTER TABLE channel_mapping ADD COLUMN icon_height REAL")
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits
        
        # Indizes für bessere Performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_song_ref_song_id ON song_reference_data(song_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_song_ref_timestamp ON song_reference_data(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_song_parts_song_id ON song_parts(song_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_light_programs_song_id ON light_programs(song_id)")
        
        # Initialisiere Standard-Kanalzuordnungen falls Tabelle leer ist
        # ODER wenn alle Einträge keine musician_name haben (alte Datenbank)
        cursor.execute("SELECT COUNT(*) as count FROM channel_mapping")
        count = cursor.fetchone()['count']
        
        if count == 0:
            self._initialize_default_channel_mappings(cursor)
        else:
            # Prüfe ob Migration nötig ist (alle musician_name sind NULL)
            cursor.execute("SELECT COUNT(*) as count FROM channel_mapping WHERE musician_name IS NULL")
            null_count = cursor.fetchone()['count']
            if null_count == count:
                # Alle Einträge haben keine musician_name - lösche und neu initialisieren
                cursor.execute("DELETE FROM channel_mapping")
                self._initialize_default_channel_mappings(cursor)
        
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
    
    def _initialize_default_channel_mappings(self, cursor):
        """Initialisiert Standard-Kanalzuordnungen nach Bandaufstellung"""
        # v.l.n.r.: Axel (1), Pete (2), Tim (3), Bibo (4)
        # Axel: Lead-Gitarre (8), Gesang Gitarrist (12)
        # Pete: Lead-Gesang (10), Rhythmusgitarre (9)
        # Tim: Drums (0-6)
        # Bibo: Bass (7), Gesang Bassist (11), Synthesizer (13)
        
        default_mappings = [
            # Tim (Position 3) - Drums
            ("bassdrum", 0, "Bassdrum", "Tim", 3, None, 0.8, 0.2, 0.2),
            ("snare", 1, "Snare Drum", "Tim", 3, None, 0.2, 0.8, 0.2),
            ("tom1", 2, "Tom 1", "Tim", 3, None, 0.6, 0.6, 0.2),
            ("tom2", 3, "Tom 2", "Tim", 3, None, 0.6, 0.4, 0.2),
            ("tom3", 4, "Tom 3", "Tim", 3, None, 0.4, 0.6, 0.2),
            ("overhead1", 5, "Becken Overhead 1", "Tim", 3, None, 0.4, 0.4, 0.8),
            ("overhead2", 6, "Becken Overhead 2", "Tim", 3, None, 0.3, 0.3, 0.9),
            # Bibo (Position 4) - Bass/Gesang/Synth
            ("bass", 7, "Bassgitarre", "Bibo", 4, None, 0.2, 0.8, 0.8),
            ("vocals_bassist", 11, "Gesang Bassist", "Bibo", 4, None, 0.8, 0.8, 0.5),
            ("synthesizer", 13, "Synthesizer", "Bibo", 4, None, 0.6, 0.2, 0.9),
            # Axel (Position 1) - Lead-Gitarre/Gesang
            ("lead_guitar", 8, "Lead-Gitarre", "Axel", 1, None, 0.8, 0.4, 0.2),
            ("vocals_guitarist", 12, "Gesang Gitarrist", "Axel", 1, None, 0.9, 0.7, 0.3),
            # Pete (Position 2) - Lead-Gesang/Gitarre
            ("vocals_frontman", 10, "Gesang Frontman", "Pete", 2, None, 0.9, 0.9, 0.3),
            ("rhythm_guitar", 9, "Rhythmusgitarre", "Pete", 2, None, 0.8, 0.6, 0.2),
        ]
        
        for inst_name, ch_idx, display_name, musician, position, icon_path, r, g, b in default_mappings:
            cursor.execute("""
                INSERT INTO channel_mapping 
                (instrument_name, channel_index, display_name, musician_name, position, icon_path, color_r, color_g, color_b)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (inst_name, ch_idx, display_name, musician, position, icon_path, r, g, b))
    
    # Kanalzuordnungen
    def get_channel_mapping(self, instrument_name: str) -> Optional[Dict]:
        """Gibt die Kanalzuordnung für ein Instrument zurück"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM channel_mapping WHERE instrument_name = ?
        """, (instrument_name,))
        row = cursor.fetchone()
        if row:
            result = dict(row)
            result['color'] = (result['color_r'], result['color_g'], result['color_b'])
            return result
        return None
    
    def get_all_channel_mappings(self) -> List[Dict]:
        """Gibt alle Kanalzuordnungen zurück, sortiert nach Position und Musiker"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM channel_mapping 
            ORDER BY position, musician_name, channel_index
        """)
        rows = cursor.fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data['color'] = (data['color_r'], data['color_g'], data['color_b'])
            result.append(data)
        return result
    
    def update_channel_mapping(self, instrument_name: str, channel_index: int = None,
                              display_name: str = None, color: tuple = None,
                              icon_path: str = None, bg_pos_x: float = None,
                              bg_pos_y: float = None, icon_width: float = None,
                              icon_height: float = None):
        """Aktualisiert eine Kanalzuordnung"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        updates = []
        values = []
        
        if channel_index is not None:
            updates.append("channel_index = ?")
            values.append(channel_index)
        if display_name is not None:
            updates.append("display_name = ?")
            values.append(display_name)
        if color is not None:
            updates.append("color_r = ?")
            updates.append("color_g = ?")
            updates.append("color_b = ?")
            values.extend(color)
        if icon_path is not None:
            updates.append("icon_path = ?")
            values.append(icon_path)
        if bg_pos_x is not None:
            updates.append("bg_pos_x = ?")
            values.append(bg_pos_x)
        if bg_pos_y is not None:
            updates.append("bg_pos_y = ?")
            values.append(bg_pos_y)
        if icon_width is not None:
            updates.append("icon_width = ?")
            values.append(icon_width)
        if icon_height is not None:
            updates.append("icon_height = ?")
            values.append(icon_height)
        
        if not updates:
            return
        
        updates.append("updated_at = CURRENT_TIMESTAMP")
        values.append(instrument_name)
        
        set_clause = ", ".join(updates)
        cursor.execute(f"""
            UPDATE channel_mapping SET {set_clause} WHERE instrument_name = ?
        """, values)
        conn.commit()
    
    def close(self):
        """Schließt die Datenbankverbindung"""
        if self.conn:
            self.conn.close()
            self.conn = None

