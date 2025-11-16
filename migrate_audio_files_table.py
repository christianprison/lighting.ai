"""
Migration: Entfernt file_path NOT NULL Constraint von audio_files Tabelle.
Da SQLite kein ALTER COLUMN unterstützt, wird die Tabelle neu erstellt.
"""

import sqlite3
from pathlib import Path
from config import DB_PATH


def migrate_audio_files_table():
    """Migriert audio_files Tabelle: entfernt file_path NOT NULL."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Prüfe ob Migration nötig ist
    cursor.execute("PRAGMA table_info(audio_files)")
    columns = cursor.fetchall()
    has_file_path_not_null = any(
        col['name'] == 'file_path' and col['notnull'] 
        for col in columns
    )
    
    if not has_file_path_not_null:
        print("Migration nicht nötig: file_path ist bereits optional")
        conn.close()
        return
    
    print("Starte Migration: Entferne file_path NOT NULL Constraint...")
    
    # Sichere vorhandene Daten (falls vorhanden)
    cursor.execute("SELECT * FROM audio_files")
    existing_data = cursor.fetchall()
    print(f"Gefundene Einträge: {len(existing_data)}")
    
    # Erstelle neue Tabelle ohne file_path NOT NULL
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audio_files_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id INTEGER NOT NULL,
            audio_data BLOB NOT NULL,
            file_name TEXT,
            song_part TEXT,
            start_sec REAL,
            end_sec REAL,
            recording_date TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE
        )
    """)
    
    # Kopiere Daten (ohne file_path, da es jetzt optional ist)
    if existing_data:
        for row in existing_data:
            cursor.execute("""
                INSERT INTO audio_files_new
                (id, song_id, audio_data, file_name, song_part, start_sec, end_sec, recording_date, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row['id'],
                row['song_id'],
                row.get('audio_data'),
                row.get('file_name'),
                row.get('song_part'),
                row.get('start_sec'),
                row.get('end_sec'),
                row.get('recording_date'),
                row.get('notes'),
                row.get('created_at')
            ))
        print(f"  {len(existing_data)} Einträge kopiert")
    
    # Ersetze alte Tabelle
    cursor.execute("DROP TABLE audio_files")
    cursor.execute("ALTER TABLE audio_files_new RENAME TO audio_files")
    
    conn.commit()
    conn.close()
    
    print("Migration abgeschlossen!")


if __name__ == "__main__":
    migrate_audio_files_table()

