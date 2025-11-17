#!/bin/bash
# Start-Script für lighting.ai

# Wechsle ins Projektverzeichnis
cd "/home/thepact/development projects/lighting.ai" || exit 1

# Setze Fenstergröße über Umgebungsvariablen
export KIVY_WINDOW_WIDTH=1920
export KIVY_WINDOW_HEIGHT=1080

# Starte die Anwendung
exec python3 main.py "$@"
