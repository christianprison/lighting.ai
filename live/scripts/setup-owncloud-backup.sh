#!/bin/bash
# =============================================================================
# lighting.ai — OwnCloud-Backup einrichten
#
# Richtet rclone für automatische Sicherung der Probe-Aufnahmen ein.
# Muss einmalig mit sudo ausgeführt werden (wegen NetworkManager-Dispatcher).
#
# Verwendung:
#   chmod +x live/scripts/setup-owncloud-backup.sh
#   sudo live/scripts/setup-owncloud-backup.sh
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
RECORDINGS_DIR="$REPO_DIR/live/data/recordings"
RCLONE_REMOTE="lighting-owncloud"
OWNCLOUD_TARGET_DIR="lighting-ai/recordings"
NM_DISPATCHER="/etc/NetworkManager/dispatcher.d/99-lighting-backup"
BACKUP_SCRIPT="$SCRIPT_DIR/rclone-backup.sh"
LOG_FILE="/var/log/lighting-ai-backup.log"

# --- Farben ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC}  $1"; }
err()  { echo -e "${RED}✗${NC} $1"; exit 1; }

echo ""
echo "=== lighting.ai OwnCloud-Backup Setup ==="
echo ""

# --- Root-Check ---
if [ "$EUID" -ne 0 ]; then
  err "Bitte mit sudo ausführen: sudo $0"
fi

# --- rclone installieren falls nötig ---
if ! command -v rclone &>/dev/null; then
  echo "rclone nicht gefunden — wird installiert..."
  curl -s https://rclone.org/install.sh | bash
  ok "rclone installiert: $(rclone --version | head -1)"
else
  ok "rclone gefunden: $(rclone --version | head -1)"
fi

echo ""
echo "--- OwnCloud-Zugangsdaten ---"
echo ""

# --- Interaktive Eingabe ---
read -rp "OwnCloud-URL (z.B. https://cloud.beispiel.de): " OWNCLOUD_URL
OWNCLOUD_URL="${OWNCLOUD_URL%/}"  # trailing slash entfernen

read -rp "Benutzername: " OWNCLOUD_USER

read -rsp "Passwort (wird verschlüsselt gespeichert): " OWNCLOUD_PASS
echo ""

# --- WebDAV-URL zusammenbauen ---
WEBDAV_URL="${OWNCLOUD_URL}/remote.php/webdav/"

# --- rclone-Remote konfigurieren ---
echo ""
echo "Konfiguriere rclone-Remote '$RCLONE_REMOTE'..."

# Passwort verschlüsseln
RCLONE_PASS_ENCRYPTED=$(echo "$OWNCLOUD_PASS" | rclone obscure -)

# Config schreiben (für den Laptop-User, nicht root)
REAL_USER="${SUDO_USER:-$USER}"
REAL_HOME=$(eval echo "~$REAL_USER")
RCLONE_CONFIG_DIR="$REAL_HOME/.config/rclone"
RCLONE_CONFIG="$RCLONE_CONFIG_DIR/rclone.conf"

mkdir -p "$RCLONE_CONFIG_DIR"
chown "$REAL_USER:$REAL_USER" "$RCLONE_CONFIG_DIR"

# Bestehenden Remote entfernen falls vorhanden
if grep -q "^\[$RCLONE_REMOTE\]" "$RCLONE_CONFIG" 2>/dev/null; then
  warn "Remote '$RCLONE_REMOTE' existiert bereits — wird überschrieben"
  # Alten Block entfernen
  python3 -c "
import re, sys
txt = open('$RCLONE_CONFIG').read()
txt = re.sub(r'\[$RCLONE_REMOTE\][^\[]*', '', txt, flags=re.DOTALL)
open('$RCLONE_CONFIG', 'w').write(txt)
"
fi

cat >> "$RCLONE_CONFIG" <<EOF

[$RCLONE_REMOTE]
type = webdav
url = $WEBDAV_URL
vendor = owncloud
user = $OWNCLOUD_USER
pass = $RCLONE_PASS_ENCRYPTED
EOF

chown "$REAL_USER:$REAL_USER" "$RCLONE_CONFIG"
chmod 600 "$RCLONE_CONFIG"
ok "rclone-Remote konfiguriert"

# --- Verbindung testen ---
echo "Teste Verbindung zu OwnCloud..."
if sudo -u "$REAL_USER" rclone lsd "$RCLONE_REMOTE": &>/dev/null; then
  ok "Verbindung erfolgreich"
else
  warn "Verbindungstest fehlgeschlagen — Zugangsdaten prüfen!"
  warn "Manuell testen: rclone lsd $RCLONE_REMOTE:"
fi

# --- Zielordner anlegen ---
echo "Lege Zielordner '$OWNCLOUD_TARGET_DIR' an..."
sudo -u "$REAL_USER" rclone mkdir "$RCLONE_REMOTE:$OWNCLOUD_TARGET_DIR" 2>/dev/null && \
  ok "Zielordner bereit" || warn "Zielordner konnte nicht angelegt werden (evtl. existiert er schon)"

# --- NetworkManager-Dispatcher installieren ---
echo ""
echo "Installiere NetworkManager-Dispatcher..."

cat > "$NM_DISPATCHER" <<EOF
#!/bin/bash
# lighting.ai — automatisches OwnCloud-Backup bei WLAN-Verbindung
# Installiert von: $0

INTERFACE="\$1"
EVENT="\$2"

[ "\$EVENT" = "up" ] || exit 0

# Nur bei WLAN-Interface (wlan0, wlp*) triggern
[[ "\$INTERFACE" == wlan* ]] || [[ "\$INTERFACE" == wlp* ]] || exit 0

# Kurz warten bis Routing stabil ist
sleep 5

# Backup als Laptop-User starten
REAL_USER="$REAL_USER"
sudo -u "\$REAL_USER" "$BACKUP_SCRIPT" >> "$LOG_FILE" 2>&1 &

exit 0
EOF

chmod +x "$NM_DISPATCHER"
ok "Dispatcher installiert: $NM_DISPATCHER"

# --- Log-Datei anlegen ---
touch "$LOG_FILE"
chown "$REAL_USER:$REAL_USER" "$LOG_FILE"
ok "Log-Datei: $LOG_FILE"

# --- Zusammenfassung ---
echo ""
echo "=== Setup abgeschlossen ==="
echo ""
echo "  Aufnahmen:    $RECORDINGS_DIR"
echo "  OwnCloud:     $OWNCLOUD_URL"
echo "  Zielordner:   $OWNCLOUD_TARGET_DIR"
echo "  Backup-Log:   $LOG_FILE"
echo ""
echo "Das Backup startet automatisch wenn der Laptop ins WLAN kommt."
echo "Manuell starten: $BACKUP_SCRIPT"
echo ""
