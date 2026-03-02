#!/bin/bash
cd "$(dirname "$0")"

echo "=== lighting.ai Live Controller ==="
echo ""

# Activate virtual environment if present
if [ -d ".venv" ]; then
  source .venv/bin/activate 2>/dev/null
  echo "Virtual environment activated"
elif [ -d "../.venv" ]; then
  source ../.venv/bin/activate 2>/dev/null
  echo "Virtual environment activated (parent)"
fi

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "ERROR: Python 3 not found!"
  exit 1
fi

# Check dependencies
python3 -c "import fastapi, uvicorn, pythonosc, yaml, httpx" 2>/dev/null
if [ $? -ne 0 ]; then
  echo "Installing dependencies..."
  pip install -r requirements.txt
fi

# Sync DB from GitHub
echo ""
echo "Syncing DB from GitHub..."
python3 -c "
import sys
sys.path.insert(0, '..')
from live.server.config import load_config
from live.server.db_cache import sync
cfg = load_config()
result = sync(cfg)
if result['ok']:
    print('DB synced (' + result['method'] + ')')
else:
    print('WARNING: Offline mode - using cached data')
" && echo "Done." || echo "WARNING: Sync script failed, continuing..."

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

echo ""
echo "Starting server on ${HOST}:${PORT}..."
echo "Open in browser: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):${PORT}"
echo ""

cd ..
uvicorn live.server.main:app --host "$HOST" --port "$PORT"
