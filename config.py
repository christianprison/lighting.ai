"""
Konfigurationsmodul für lighting.ai
"""
import os
from pathlib import Path

# Projektverzeichnis
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# Datenbank
DB_PATH = DATA_DIR / "lighting.db"

# OSC-Konfiguration (Behringer XR18)
OSC_LISTEN_PORT = 10024  # Standard-Port für XR18
OSC_TIMEOUT = 1.0  # Timeout in Sekunden

# Artnet-Konfiguration
ARTNET_BROADCAST_IP = "255.255.255.255"  # Broadcast für alle Geräte
ARTNET_PORT = 6454
ARTNET_UNIVERSES = 20  # Anzahl der Universen

REQUIRED_WLAN_SSID = "PACT"  # SSID die im Show-Modus erwartet wird

# Beat Detection
BEAT_DETECTION_CHANNELS = {
    "bassdrum": 0,  # Kanal-Index (wird später konfigurierbar)
    "snare": 1,
    "bass": 2
}

# Songerkennung
SONG_RECOGNITION_WINDOW_SIZE = 4.0  # Sekunden für Vergleichs-Fenster
SONG_RECOGNITION_GRANULARITY = "bar"  # "beat", "bar", "second"

# UI-Konfiguration
UI_LANGUAGE = "de"  # Deutsch
UI_THEME = "dark"

# Logging
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_LEVEL = "INFO"

