# Datenbank-Backup

Die Datenbank wird nicht in Git gesichert (zu groß: ~306MB), sondern extern in der iCloud.

## Manuelles Backup

```bash
python3 backup_database.py
```

Das Skript:
- Kopiert die Datenbank nach `~/iCloud Drive/lighting.ai-backups/`
- Erstellt einen Dateinamen mit Timestamp: `lighting.db.backup_YYYYMMDD_HHMMSS`
- Behält die letzten 10 Backups (älteste werden automatisch gelöscht)

## Automatisches Backup (Cron)

Um täglich automatisch ein Backup zu erstellen:

1. Öffne den Crontab-Editor:
```bash
crontab -e
```

2. Füge folgende Zeile hinzu (Backup täglich um 2:00 Uhr):
```cron
0 2 * * * cd "/home/thepact/development projects/lighting.ai" && python3 backup_database.py >> /tmp/lighting_backup.log 2>&1
```

3. Oder wöchentlich (jeden Sonntag um 2:00 Uhr):
```cron
0 2 * * 0 cd "/home/thepact/development projects/lighting.ai" && python3 backup_database.py >> /tmp/lighting_backup.log 2>&1
```

## Backup-Verzeichnis ändern

Falls das iCloud-Verzeichnis an einem anderen Ort liegt, editiere `backup_database.py`:

```python
BACKUP_DIR = Path.home() / "iCloud Drive" / "lighting.ai-backups"
```

Zum Beispiel für Nextcloud:
```python
BACKUP_DIR = Path.home() / "Nextcloud" / "lighting.ai-backups"
```

## Wiederherstellung

Um ein Backup wiederherzustellen:

```bash
# Finde das gewünschte Backup
ls -lh ~/iCloud\ Drive/lighting.ai-backups/

# Kopiere es zurück (ersetze YYYYMMDD_HHMMSS mit dem tatsächlichen Timestamp)
cp ~/iCloud\ Drive/lighting.ai-backups/lighting.db.backup_YYYYMMDD_HHMMSS \
   data/lighting.db
```

