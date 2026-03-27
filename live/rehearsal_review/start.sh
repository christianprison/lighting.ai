#!/usr/bin/env bash
# Rehearsal Post-Preparation — start script
# Usage:  ./start.sh [path/to/session.jsonl]

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="/opt/lighting-venv"

# Activate venv if present
if [ -d "$VENV" ]; then
    source "$VENV/bin/activate"
fi

# Install PyQt6 if missing (only needed once)
python3 -c "import PyQt6" 2>/dev/null || {
    echo "PyQt6 nicht gefunden — installiere..."
    pip install PyQt6
}

exec python3 "$SCRIPT_DIR/main.py" "$@"
