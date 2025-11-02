# lighting.ai

Eine wartungsarme Offline-Applikation zur Steuerung von Licht-Fixtures via Artnet auf Basis von Signalen eines Behringer XR18.

## Übersicht

Diese Anwendung ermöglicht die automatische Lichtsteuerung basierend auf Live-Audio-Signalen vom Behringer XR18 Mixer. Die Kommunikation erfolgt über OSC (Open Sound Control) über das WLAN-Netzwerk "PACT".

## Features

- **Drei Betriebsmodi:**
  - **Wartung:** Pflege der Referenzdatenbank und Testen
  - **Probe:** Ad-hoc Songerkennung und Verbesserung der Referenzdaten
  - **Show:** Robuster Modus für Live-Auftritte mit vorher festgelegtem Repertoire

- **Songerkennung:** Automatische Erkennung von Songs basierend auf Meter-Values
- **Beat Detection:** Echtzeit-Beat-Erkennung aus Bassdrum, Snare und Bassgitarre
- **Multi-Universen Artnet:** Unterstützung für bis zu 20 DMX-Universen
- **Offline-Fähig:** Show-Modus funktioniert komplett offline

## Anforderungen

- Python 3.8+
- Linux (getestet auf Linux Mint 21.3 / Ubuntu 22.04)
- Verbindung zum WLAN "PACT" für OSC-Kommunikation mit XR18
- Behringer XR18 Mixer

## Installation

```bash
# Abhängigkeiten installieren
pip install -r requirements.txt

# Datenbank initialisieren (wird beim ersten Start automatisch erstellt)
python main.py
```

## Verwendung

```bash
python main.py
```

Die Anwendung startet mit der Modus-Auswahl. Wählen Sie zwischen:
- **Wartung:** Für die Verwaltung des Repertoires
- **Probe:** Für Songerkennung und Datenerfassung
- **Show:** Für Live-Auftritte

## Projektstruktur

```
lighting.ai/
├── main.py                 # Hauptanwendung
├── config.py               # Konfigurationsverwaltung
├── database.py             # SQLite-Datenbank-Modul
├── osc_listener.py         # OSC-Empfänger für XR18
├── artnet_controller.py    # Artnet/DMX-Steuerung
├── mode_manager.py         # Modus-Verwaltung
├── beat_detection.py       # Beat-Erkennung
├── song_recognition.py     # Song-Erkennung
├── gui/                    # Kivy GUI-Module
│   ├── __init__.py
│   ├── main_screen.py      # Hauptbildschirm
│   ├── maintenance_screen.py
│   ├── probe_screen.py
│   └── show_screen.py
├── data/                   # Datenbank und Konfiguration
│   └── lighting.db         # SQLite-Datenbank (wird automatisch erstellt)
└── requirements.txt
```

## Konfiguration

Die Konfiguration erfolgt über `config.py`. Wichtige Einstellungen:
- OSC-Port (Standard: 10024 für XR18)
- Artnet-Universen-Konfiguration
- WLAN-SSID-Prüfung ("PACT")
- Datenbank-Pfad

## Lizenz

LGPL v2.1

