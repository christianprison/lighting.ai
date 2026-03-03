# Übergabe — Chat 1 → Chat 2

**Datum:** 2026-03-03
**Projekt:** lighting.ai — Automatisierte Lichtsteuerung für THE PACT
**Branch:** `claude/lighting-ai-db-app-UJawx`

---

## Was existiert — Gesamtübersicht

Das Projekt hat zwei große Teile:

### 1. DB-Pflege-App (GitHub Pages, Phase 1 — FERTIG)

Eine reine Client-Web-App unter `index.html` + `js/` + `css/` + `ui/`, die direkt über die GitHub API die Songdatenbank verwaltet. Läuft auf `christianprison.github.io/lighting.ai`.

**Alle Meilensteine 1–4 sind abgeschlossen:**
- Song-Verwaltung (65+ Songs)
- Parts, Bars, Accents (16tel-Raster)
- Audio Split (Tap-to-Split, Waveform, Drag & Drop Marker, Export nach GitHub)
- Lyrics-Tab (Rohtext verteilen, collapsible Parts, Instrumental-Checkbox)
- Takte-Tab (Mini-Waveforms, "Alle Takte löschen")
- Setlist-Verwaltung (Drag & Drop, Pausen, HTML-Export)
- GitHub-Sync (Token in localStorage, SHA-Tracking, Auto-Save)

### 2. Live Controller (FastAPI Backend, Meilenstein 5 — FERTIG gebaut, QLC+ Anbindung in Test)

Ein Python-Backend unter `live/` das auf dem Linux-Mint-Steuerrechner läuft und QLC+ 4 über OSC steuert.

---

## Live Controller — Detailstatus

### Architektur

```
iPad/Browser ──WebSocket──► FastAPI (Port 8080) ──OSC──► QLC+ 4 (Port 7700)
                              │
                              ├── config.py      Config aus config.yaml + env
                              ├── db_cache.py    GitHub/git/lokal → JSON Cache
                              ├── qlc_parser.py  QXW-Datei → Song-Chasers parsen
                              ├── qlc_osc.py     OSC-Client für QLC+ Steuerung
                              └── ws_handler.py  WebSocket State Management
```

### Dateien unter `live/`

| Datei | Beschreibung |
|---|---|
| `config.yaml` | OSC: 127.0.0.1:7700, Universe 0, Server: 0.0.0.0:8080 |
| `requirements.txt` | fastapi, uvicorn, python-osc, pyyaml, httpx, websockets |
| `start.sh` | Starter-Script (venv auto-detect) |
| `start-live.sh` | Desktop-Launcher (venv unter /opt/lighting-venv) |
| `lighting-ai.desktop` | Linux Mint Desktop-Shortcut |
| `server/__init__.py` | Package init |
| `server/config.py` | Dataclasses: GitHubConfig, QlcConfig, ServerConfig, Config |
| `server/db_cache.py` | Sync: git pull → GitHub API → local copy → cache fallback |
| `server/qlc_parser.py` | QXW XML Parser: Chasers, Steps, Function-Matching |
| `server/qlc_osc.py` | OSC Client: CueList play/stop/next/prev, Accents, Tap |
| `server/ws_handler.py` | WebSocket: LiveState broadcast, action handler |
| `server/main.py` | FastAPI App: REST + WS Endpoints, Startup-Logik |
| `ui/index.html` | Live-UI: 3-Spalten-Layout (Parts, Center, Setlist) + Timeline |
| `UI/lighting-ai-ui.html` | Referenz-UI-Prototyp (Standalone, wurde als Vorlage genutzt) |
| `data/.gitkeep` | Cache-Verzeichnis für lokale DB/QXW Kopien |

### QLC+ QXW Parser (`qlc_parser.py`)

- Parst die QXW-Datei (`db/ThePact.qxw`) als XML
- Extrahiert **Song-Chasers** (Path="Pact Songs", Type="Chaser")
- Jeder Chaser hat Steps mit: function_id, function_name, note (Part-Name), hold_ms, fade_in/out
- INFINITE_HOLD (0xFFFFFFFE) = manueller Step-Wechsel
- STOP_FUNCTION_ID (82) = "11 Stop" Title/End-Marker
- **Fuzzy-Matching** der Chaser-Namen zu DB-Songs (normalize + substring)
- Known Collections: BASE_COLLECTIONS (70-83, 181-182), SPOT_COLLECTIONS (224-229)
- Known Accents: blind(212), blackout(36), strobe(81), alarm(80), fog_on(38), fog_off(39), fog_5s(40), fog_10s(37)

### OSC Channel-Mapping (`qlc_osc.py`)

```python
DEFAULT_CHANNEL_MAP = {
    "cuelist_play": 1,   "cuelist_stop": 2,
    "cuelist_next": 3,   "cuelist_prev": 4,
    "blind": 10,         "blackout": 11,
    "strobe": 12,        "alarm": 13,
    "fog_on": 14,        "fog_off": 15,
    "fog_5s": 16,        "fog_10s": 17,
    "tap_tempo": 20,
}
```

OSC-Pfad-Format: `/{universe}/dmx/{channel}` — Trigger = 255.0, 50ms Pause, 0.0

### WebSocket State (`ws_handler.py`)

LiveState-Felder:
- `current_song_id`, `current_song_name`, `current_artist`, `current_bpm`
- `chaser_id`, `current_step`, `total_steps`
- `current_part_name`, `current_function_name`
- `qlc_connected`, `db_synced`, `db_sync_time`, `db_sync_method`
- `is_playing`

### REST API Endpoints

| Method | Pfad | Beschreibung |
|---|---|---|
| GET | `/api/songs` | Alle Songs (gefiltert) |
| GET | `/api/setlist` | Aktive Setlist mit has_chaser Flag |
| GET | `/api/qlc/mapping` | QXW Song-Chaser Mapping |
| GET | `/api/qlc/status` | OSC Verbindungsstatus |
| POST | `/api/sync` | DB neu synchronisieren |
| POST | `/api/qlc/function/{id}/start` | QLC+ Funktion starten |
| POST | `/api/qlc/accent/{type}` | Accent triggern |
| POST | `/api/qlc/tap` | Tap Tempo |
| WS | `/ws` | WebSocket (select_song, next, prev, goto, accent, tap, get_state) |

### Live-UI (`live/ui/index.html`)

3-Spalten Touch-Layout:
- **Links:** Parts-Liste (Steps aus Chaser, done/active/next Styling, klickbar für goto)
- **Mitte:** Song-Header, Badges (LIVE/QLC+), Beat-Visualisierung mit Tap-Tempo, Accent-Buttons (Blinder, Strobe, Fog 5s/10s, Blackout, Alarm, Fog An/Aus), PREV/NEXT Navigation
- **Rechts:** Setlist (klickbar für Song-Auswahl, no-chaser dimmed)
- **Unten:** Timeline (Step-Blöcke, QLC+ Status, DB Sync Status, Sync-Button)
- Connection-Overlay bei WebSocket-Disconnect

---

## Aktueller Stand: QLC+ OSC-Anbindung testen

### Was zuletzt passiert ist

Wir waren dabei, die OSC-Verbindung zwischen dem FastAPI-Server und QLC+ 4 zu testen. Der Benutzer (Christian) hat einen Screenshot der QLC+ Inputs/Outputs-Konfiguration gezeigt:

- **OSC Input** ist konfiguriert auf `127.0.0.1`, Port `7700`, Status: Open
- OSC ist dem Universe "Input" (erstes Universe in QLC+) zugewiesen
- In der Plugin-Konfiguration steht "Universe: 2" (interne Referenz)
- QLC+ zeigt E1.31 Outputs auf 192.168.178.174 (Showtec NET-2/3)
- Loopback, MIDI, OS2L sind ebenfalls konfiguriert

### Nächster Schritt: OSC Schnelltest

Der folgende Test war geplant, aber noch nicht durchgeführt:

```bash
source /opt/lighting-venv/bin/activate
python3 -c "
from pythonosc.udp_client import SimpleUDPClient
import time
c = SimpleUDPClient('127.0.0.1', 7700)
c.send_message('/0/dmx/3', 255.0)
time.sleep(0.05)
c.send_message('/0/dmx/3', 0.0)
print('Gesendet!')
"
```

**Erwartung:** In QLC+ Inputs/Outputs sollte "Packets received" von 0 auf 2 springen.

**Falls es nicht funktioniert:** Den Universe-Index im Pfad variieren:
- `/0/dmx/3` (aktuell konfiguriert, osc_universe: 0)
- `/1/dmx/3`
- `/2/dmx/3`
- QLC+ "Channel number calculator" im Plugin-Dialog nutzen, um den richtigen Pfad zu ermitteln

### Was danach kommt (wenn OSC Packets ankommen)

1. **External Input Assignments** in QLC+ Virtual Console einrichten:
   - CueList-Widget: Play/Stop/Next/Prev auf Channel 1-4
   - Accent-Buttons: Blinder(10), Blackout(11), Strobe(12), Alarm(13), Fog(14-17)
   - Tap Tempo: Channel 20
2. **End-to-End Test:** Server starten → UI im Browser öffnen → Song auswählen → Next/Prev klicken → QLC+ muss reagieren
3. **iPad Test:** iPad im gleichen Netzwerk, `http://<linux-ip>:8080`

---

## Setup auf dem Linux-Rechner

- **Repo:** `/home/thepact/git/lighting.ai_neu`
- **venv:** `/opt/lighting-venv`
- **Desktop Launcher:** `lighting-ai.desktop` → `start-live.sh`
- Start: `./start-live.sh` oder Desktop-Icon doppelklicken
- Server lauscht auf `0.0.0.0:8080`
- QLC+ muss separat laufen mit geladener `ThePact.qxw`

---

## Bekannte Einschränkungen / Offene Punkte

1. **osc_universe** in `config.yaml` steht auf `0` — muss ggf. auf `1` oder `2` angepasst werden, je nachdem was der QLC+ Schnelltest ergibt
2. **CueList-Steuerung** in QLC+ muss noch über External Input verbunden werden (Channel 1-4 → CueList Widget)
3. **Song-Auswahl** im Live Controller: Aktuell wählt man Songs über die Setlist-Spalte rechts. Es gibt noch keinen Mechanismus, automatisch die richtige CueList in QLC+ auszuwählen (das wird über "cuelist_play" angetriggert, aber QLC+ muss die richtige CueList aktiv haben)
4. **goto-Action**: Navigiert via sequenziellen next/prev Aufrufen zum Ziel-Step — funktioniert, ist bei großen Sprüngen aber langsam
5. **Beat-Visualisierung**: Ist aktuell eine reine Simulation basierend auf BPM, nicht synchron zum tatsächlichen Audio/QLC+
6. **Kein Feedback-Kanal**: Der Server sendet Befehle an QLC+, empfängt aber keine Bestätigung (OSC ist unidirektional in unserer Konfig)

---

## Projektstruktur (Zusammenfassung)

```
lighting.ai/
├── CLAUDE.md                      # Projekt-Dokumentation (ausführlich)
├── Übergabe12.md                  # Diese Datei
├── index.html                     # DB-Pflege-App Entry Point
├── css/style.css                  # Shared Dark Theme
├── js/
│   ├── app.js                     # Haupt-App-Logik (6 Tabs, Routing)
│   ├── db.js                      # GitHub API Wrapper
│   ├── audio-engine.js            # Web Audio API
│   └── utils.js                   # Hilfsfunktionen
├── db/
│   ├── lighting-ai-db.json        # Songdatenbank (65+ Songs)
│   └── ThePact.qxw                # QLC+ Workspace
├── audio/                         # Full Songs + geschnittene Bars
├── live/                          # Meilenstein 5: Live Controller
│   ├── config.yaml
│   ├── requirements.txt
│   ├── start.sh / start-live.sh
│   ├── lighting-ai.desktop
│   ├── server/
│   │   ├── main.py                # FastAPI App
│   │   ├── config.py              # Config Dataclasses
│   │   ├── db_cache.py            # DB Sync
│   │   ├── qlc_parser.py          # QXW Parser
│   │   ├── qlc_osc.py             # OSC Client
│   │   └── ws_handler.py          # WebSocket Handler
│   ├── ui/index.html              # Live-UI (produktiv)
│   └── UI/lighting-ai-ui.html     # Referenz-UI (Prototyp)
└── scripts/
    ├── import_pact_html.py
    └── add_parts.py
```

---

## Quick Reference: Wie man den Live Controller startet

```bash
# Auf dem Linux-Rechner:
cd /home/thepact/git/lighting.ai_neu
source /opt/lighting-venv/bin/activate
uvicorn live.server.main:app --host 0.0.0.0 --port 8080

# Oder einfach:
./live/start-live.sh
```

Dann QLC+ 4 mit `db/ThePact.qxw` laden und im Browser `http://localhost:8080` öffnen.
