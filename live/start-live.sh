#!/bin/bash
# lighting.ai Live Controller — Desktop Launcher
# Aktiviert die venv unter /opt und startet den Server.

VENV="/opt/lighting-venv"
REPO="/home/thepact/git/lighting.ai_neu"

echo "=== lighting.ai Live Controller ==="
echo ""

# Activate virtual environment
source "$VENV/bin/activate" || { echo "ERROR: venv nicht gefunden unter $VENV"; echo "Drücke Enter zum Schliessen..."; read; exit 1; }
echo "Virtual environment activated ($VENV)"

cd "$REPO/live" || { echo "ERROR: Repo nicht gefunden unter $REPO"; echo "Drücke Enter zum Schliessen..."; read; exit 1; }

# Check dependencies
python3 -c "import fastapi, uvicorn, pythonosc, yaml, httpx" 2>/dev/null
if [ $? -ne 0 ]; then
  echo "Installing dependencies..."
  pip install -r requirements.txt
fi

# Sync DB from GitHub
echo ""
echo "Syncing DB from GitHub..."
cd "$REPO"
git pull origin main 2>/dev/null && echo "Git pull OK" || echo "WARNING: git pull fehlgeschlagen — verwende lokale Daten"
cd "$REPO/live"

# Read port from config
PORT=$(python3 -c "
from server.config import load_config
cfg = load_config()
print(cfg.server.port)
" 2>/dev/null || echo "8080")

HOST=$(python3 -c "
from server.config import load_config
cfg = load_config()
print(cfg.server.host)
" 2>/dev/null || echo "0.0.0.0")

IP=$(hostname -I 2>/dev/null | awk '{print $1}')

echo ""
echo "Server startet auf ${HOST}:${PORT}..."
echo "iPad: http://${IP}:${PORT}"
echo ""

# Open browser automatically
xdg-open "http://localhost:${PORT}" 2>/dev/null &

cd "$REPO"
uvicorn live.server.main:app --host "$HOST" --port "$PORT"

# Keep terminal open on error
echo ""
echo "Server beendet. Drücke Enter zum Schliessen..."
read
