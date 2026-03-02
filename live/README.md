# lighting.ai Live Controller

Touch-optimierter Live Controller für THE PACT Bühnenbeleuchtung mit QLC+ Anbindung.

## Voraussetzungen

- **Python 3.11+**
- **QLC+ 4** mit OSC Input konfiguriert
- Netzwerkverbindung zum QLC+ Rechner (oder lokal)

## Installation

```bash
cd live/
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Konfiguration

Bearbeite `config.yaml`:

```yaml
github:
  repo: christianprison/lighting.ai
  # token: github_pat_...  # Oder per Env: GITHUB_TOKEN

qlc:
  osc_host: "127.0.0.1"   # QLC+ Rechner IP
  osc_port: 7700           # QLC+ OSC Input Port
  osc_universe: 0          # OSC Universe (0-basiert)

server:
  host: "0.0.0.0"
  port: 8080
```

### Umgebungsvariablen (alternativ)

```bash
export GITHUB_TOKEN=github_pat_...
export GITHUB_REPO=christianprison/lighting.ai
```

## QLC+ OSC Konfiguration

1. **QLC+** starten
2. **Inputs/Outputs** öffnen
3. Ein freies Universe wählen (z.B. Universe 9)
4. **OSC** als Input-Plugin aktivieren
5. Port auf `7700` setzen (oder wie in `config.yaml`)
6. **Virtual Console** einrichten:
   - CueList-Widget für Song-Chasers
   - Buttons für Accents (Blinder, Strobe, Fog, Blackout)
   - Jedem Widget einen External Input zuweisen (Universe + Channel)
7. Die Channel-Nummern müssen mit den Werten in `qlc_osc.py` (`DEFAULT_CHANNEL_MAP`) übereinstimmen

### Standard Channel-Mapping

| Funktion       | Channel | QLC+ Widget           |
|----------------|--------:|------------------------|
| CueList Play   |       1 | CueList Playback       |
| CueList Stop   |       2 | CueList Stop           |
| CueList Next   |       3 | CueList Next Step      |
| CueList Prev   |       4 | CueList Previous Step  |
| Blinder        |      10 | Button → Function 212  |
| Blackout       |      11 | Button → Function 36   |
| Strobe         |      12 | Button → Function 81   |
| Alarm          |      13 | Button → Function 80   |
| Fog On         |      14 | Button → Function 38   |
| Fog Off        |      15 | Button → Function 39   |
| Fog 5s         |      16 | Button → Function 40   |
| Fog 10s        |      17 | Button → Function 37   |
| Tap Tempo      |      20 | Tap Tempo Button       |

## Starten

```bash
./start.sh
```

Oder manuell:

```bash
cd ..  # Repo-Root
uvicorn live.server.main:app --host 0.0.0.0 --port 8080
```

## Zugriff

- **iPad:** `http://<linux-ip>:8080` in Safari
- **Laptop:** `http://localhost:8080`
- Safari → "Zum Home-Bildschirm" für Fullscreen-App

## API Endpunkte

| Method | Pfad                          | Beschreibung              |
|--------|-------------------------------|---------------------------|
| GET    | `/api/songs`                  | Alle Songs                |
| GET    | `/api/setlist`                | Aktive Setlist            |
| GET    | `/api/qlc/mapping`            | QLC+ Song-Chaser Mapping  |
| GET    | `/api/qlc/status`             | QLC+ Verbindungsstatus    |
| POST   | `/api/sync`                   | DB manuell synchronisieren|
| POST   | `/api/qlc/function/{id}/start`| QLC+ Funktion starten     |
| POST   | `/api/qlc/accent/{type}`      | Accent triggern           |
| POST   | `/api/qlc/tap`                | Tap Tempo                 |
| WS     | `/ws`                         | WebSocket (Echtzeit)      |

## WebSocket Kommandos

```json
{"action": "select_song", "song_id": "UNIriZ"}
{"action": "next"}
{"action": "prev"}
{"action": "goto", "step": 3}
{"action": "accent", "type": "blind"}
{"action": "tap"}
{"action": "get_state"}
```

## Architektur

```
iPad/Browser ──WebSocket──► FastAPI Server ──OSC──► QLC+ 4
                             │
                             ├── db_cache.py  (GitHub → local JSON)
                             ├── qlc_parser.py (QXW → Song Chasers)
                             ├── qlc_osc.py   (OSC → QLC+)
                             └── ws_handler.py (WebSocket State)
```

## Offline-Betrieb

Beim Start versucht der Server die DB von GitHub zu synchronisieren. Wenn kein Internet verfügbar ist, wird der lokale Cache unter `data/` verwendet. Im laufenden Betrieb ist keine Internetverbindung nötig.
