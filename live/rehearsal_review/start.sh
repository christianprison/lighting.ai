#!/usr/bin/env bash
# Rehearsal Post-Preparation — start script
# Usage:  ./start.sh [path/to/session.jsonl]

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="/opt/lighting-venv"

# ── System libraries (run once, needs sudo) ───────────────────────────────────
_APT_PKGS="libportaudio2 libegl1 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-render-util0 libxcb-xinerama0"
_MISSING=""
for _pkg in $_APT_PKGS; do
    dpkg -s "$_pkg" >/dev/null 2>&1 || _MISSING="$_MISSING $_pkg"
done
if [ -n "$_MISSING" ]; then
    echo "Fehlende System-Bibliotheken: $_MISSING"
    echo "Installiere (sudo erforderlich)..."
    sudo apt-get install -y $_MISSING
fi

# ── Activate venv if present ──────────────────────────────────────────────────
if [ -d "$VENV" ]; then
    source "$VENV/bin/activate"
fi

# ── Python packages ───────────────────────────────────────────────────────────
python3 -c "import PyQt6" 2>/dev/null || {
    echo "PyQt6 nicht gefunden — installiere..."
    pip install PyQt6
}
python3 -c "import sounddevice" 2>/dev/null || {
    echo "sounddevice nicht gefunden — installiere..."
    pip install sounddevice
}
python3 -c "import soundfile" 2>/dev/null || {
    echo "soundfile nicht gefunden — installiere..."
    pip install soundfile
}
python3 -c "import numpy" 2>/dev/null || {
    echo "numpy nicht gefunden — installiere..."
    pip install numpy
}

exec python3 "$SCRIPT_DIR/main.py" "$@"
