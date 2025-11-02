#!/bin/bash
# Start-Script für lighting.ai

# Wechsle ins Projektverzeichnis
cd "/home/thepact/development projects/lighting.ai" || exit 1

# Starte die Anwendung
exec python3 main.py "$@"
