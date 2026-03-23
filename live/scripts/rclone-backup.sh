#!/bin/bash
# =============================================================================
# lighting.ai — Probe-Aufnahmen zu OwnCloud synchronisieren
#
# Wird automatisch vom NetworkManager-Dispatcher aufgerufen wenn der
# Laptop ins WLAN kommt. Kann auch manuell gestartet werden.
#
# Verwendung:
#   live/scripts/rclone-backup.sh
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
RECORDINGS_DIR="$REPO_DIR/live/data/recordings"
RCLONE_REMOTE="lighting-owncloud"
OWNCLOUD_TARGET_DIR="lighting-ai/recordings"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === lighting.ai Backup gestartet ==="

# --- Prüfen ob Aufnahmen vorhanden ---
if [ ! -d "$RECORDINGS_DIR" ] || [ -z "$(ls -A "$RECORDINGS_DIR" 2>/dev/null)" ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Keine Aufnahmen vorhanden — nichts zu tun"
  exit 0
fi

# --- Prüfen ob rclone verfügbar ---
if ! command -v rclone &>/dev/null; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] FEHLER: rclone nicht installiert"
  exit 1
fi

# --- Prüfen ob OwnCloud erreichbar ---
if ! rclone lsd "$RCLONE_REMOTE": &>/dev/null; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] OwnCloud nicht erreichbar — Backup übersprungen"
  exit 1
fi

# --- Sync starten ---
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Synchronisiere nach $RCLONE_REMOTE:$OWNCLOUD_TARGET_DIR ..."

rclone sync "$RECORDINGS_DIR/" \
  "$RCLONE_REMOTE:$OWNCLOUD_TARGET_DIR/" \
  --progress \
  --transfers 2 \
  --checkers 4 \
  --log-level INFO \
  2>&1

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup erfolgreich abgeschlossen"
else
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] FEHLER: Backup fehlgeschlagen (Exit-Code $EXIT_CODE)"
fi

exit $EXIT_CODE
