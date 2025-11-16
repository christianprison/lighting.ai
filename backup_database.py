#!/usr/bin/env python3
"""
Backup-Skript für die lighting.ai Datenbank.
Kopiert die Datenbank in ein Backup-Verzeichnis (z.B. iCloud-synchronisiertes Verzeichnis).
"""

import shutil
from pathlib import Path
from datetime import datetime
from config import DB_PATH

# Konfiguration: Backup-Verzeichnis
# Für iCloud: Verwende ein Verzeichnis, das mit iCloud synchronisiert wird
# Beispiel: ~/iCloud Drive/lighting.ai-backups/
# Oder: ~/Nextcloud/lighting.ai-backups/
BACKUP_DIR = Path.home() / "iCloud Drive" / "lighting.ai-backups"
# Alternative: Falls iCloud Drive nicht verfügbar ist, verwende ein lokales Verzeichnis
# BACKUP_DIR = Path.home() / "Documents" / "lighting.ai-backups"

# Anzahl der Backups, die behalten werden sollen (älteste werden gelöscht)
KEEP_BACKUPS = 10


def backup_database():
    """Erstellt ein Backup der Datenbank."""
    if not DB_PATH.exists():
        print(f"Fehler: Datenbank nicht gefunden: {DB_PATH}")
        return False
    
    # Erstelle Backup-Verzeichnis falls es nicht existiert
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    
    # Erstelle Dateiname mit Timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"lighting.db.backup_{timestamp}"
    backup_path = BACKUP_DIR / backup_filename
    
    try:
        # Kopiere Datenbank
        print(f"Erstelle Backup: {backup_path}")
        shutil.copy2(DB_PATH, backup_path)
        
        # Prüfe Dateigröße
        size_mb = backup_path.stat().st_size / (1024 * 1024)
        print(f"✓ Backup erstellt: {backup_filename} ({size_mb:.1f} MB)")
        
        # Lösche alte Backups (behalte nur die neuesten KEEP_BACKUPS)
        cleanup_old_backups(BACKUP_DIR, KEEP_BACKUPS)
        
        return True
        
    except Exception as e:
        print(f"✗ Fehler beim Erstellen des Backups: {e}")
        return False


def cleanup_old_backups(backup_dir: Path, keep: int):
    """Löscht alte Backups und behält nur die neuesten."""
    backups = sorted(
        backup_dir.glob("lighting.db.backup_*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    
    if len(backups) > keep:
        to_delete = backups[keep:]
        for old_backup in to_delete:
            try:
                old_backup.unlink()
                print(f"  Gelöscht: {old_backup.name}")
            except Exception as e:
                print(f"  Warnung: Konnte {old_backup.name} nicht löschen: {e}")


if __name__ == "__main__":
    print("="*60)
    print("lighting.ai Datenbank-Backup")
    print("="*60)
    print(f"Quelle: {DB_PATH}")
    print(f"Ziel: {BACKUP_DIR}")
    print()
    
    if backup_database():
        print("\n✓ Backup erfolgreich abgeschlossen!")
    else:
        print("\n✗ Backup fehlgeschlagen!")
        exit(1)

