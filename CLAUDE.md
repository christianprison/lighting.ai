# CLAUDE.md — lighting.ai

## Projektübersicht

**lighting.ai** ist ein automatisiertes Lichtsteuerungssystem für die Coverband **THE PACT** aus Haan. Das System steuert Bühnenbeleuchtung basierend auf einer Songdatenbank, die das komplette Repertoire (65+ Songs) mit Songstruktur, Parts, Bars und Licht-Cues enthält.

### Ausbaustufen

1. **Phase 1 (AKTUELL):** DB-Pflege-App (WebApp) + QLC+ 4 Ansteuerung im Hintergrund
1. **Phase 2:** Tempo-Synchronisation aus OSC-Daten des Behringer XR18 (BD, Snare, Bass)
1. **Phase 3:** QLC+ ablösen — lighting.ai steuert DMX nativ über sACN
1. **Phase 4:** Vollautomatisierung über Meter Values des XR18 via OSC

### Was wir jetzt bauen: Die DB-Pflege-App

Eine komfortable Web-Oberfläche für den Lichttechniker **Timo**, die:

- Songdatenbank verwaltet (Songs, Parts, Bars, Accents, Setlists)
- Audio-Dateien in Parts/Bars zerlegt per Tap-to-Split
- Daten auf GitHub persistiert (JSON + Audio-Schnipsel)
- Im Live-Betrieb auf dem iPad im Browser läuft

-----

## Architektur

### Service-Architektur (Headless + WebApp)

```
┌─────────────────────────────────────────────────┐
│                    Browser (iPad)                │
│          lighting.ai WebApp (HTML/JS)            │
│    ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│    │ DB Editor│  │Audio Split│  │ Live UI  │    │
│    └────┬─────┘  └────┬─────┘  └────┬─────┘    │
└─────────┼──────────────┼────────────┼───────────┘
          │ WebSocket    │ REST+WS    │ WebSocket
          ▼              ▼            ▼
┌─────────────────────────────────────────────────┐
│             FastAPI Backend (Python)             │
│                  Linux Mint                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ DB Svc   │  │Audio Svc │  │Light Svc │      │
│  │ (CRUD)   │  │(Split/   │  │(DMX Out) │      │
│  │          │  │ Encode)  │  │          │      │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘      │
│       │              │             │             │
│       ▼              ▼             ▼             │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐       │
│  │GitHub   │  │GitHub    │  │ sACN/DMX │       │
│  │JSON DB  │  │Audio     │  │ (Eth)    │       │
│  └─────────┘  └──────────┘  └──────────┘       │
└─────────────────────────────────────────────────┘
```

Services laufen unter **Linux Mint** auf dem Steuer-Laptop. DMX-Hardware ist per Ethernet angeschlossen. UIs sind WebApps, bedienbar von jedem Gerät im Netzwerk.

### Netzwerk

|Netz    |Interface|Zweck                            |
|--------|---------|---------------------------------|
|WLAN    |wlan0    |OSC-Kommunikation mit XR18 Mixer |
|Ethernet|eth0     |sACN/DMX-Output an Showtec/ENTTEC|
|LAN/WLAN|beide    |WebApp-Zugriff (iPad, Laptop)    |

### Daten-Storage

- **Songdatenbank:** `db/lighting-ai-db.json` auf GitHub (Repo: `christianprison/lighting.ai`)
- **Audio-Schnipsel:** `audio/{song_id}/{part_id}/bar_NNN.mp3` auf GitHub
- **Linux-Rechner:** Cached beim Start per `git pull`
- **Kein Excel** — alles JSON-basiert

-----

## Tech Stack

|Komponente      |Technologie            |Begründung                       |
|----------------|-----------------------|---------------------------------|
|Backend         |Python 3.11+ / FastAPI |Async, WebSocket-Support, schnell|
|Realtime        |WebSocket (FastAPI)    |Low-latency UI-Updates           |
|Frontend        |Vanilla HTML/CSS/JS    |Single-file, kein Build-Step     |
|Persistenz      |GitHub API (REST)      |Versionierung gratis, Audio+JSON |
|Audio Processing|Web Audio API (Browser)|Waveform, Playback, Splitting    |
|DMX (Phase 3)   |sacn (Python)          |sACN/E1.31 direkt                |
|OSC (Phase 2)   |python-osc             |XR18 Meter-Daten                 |
|OS              |Linux Mint             |Vorhandener Steuer-Laptop        |

-----

## Datenbank-Schema (JSON)

```json
{
  "version": "1.0",
  "band": "The Pact",
  "setlist": {
    "name": "Setlist-Name",
    "items": [
      {"type": "song", "pos": 1, "song_id": "5Ij0Ns"},
      {"type": "pause"}
    ]
  },
  "songs": {
    "5Ij0Ns": {
      "name": "Animal",
      "artist": "Neon Trees",
      "bpm": 164,
      "key": "D dur",
      "year": "2009",
      "pick": "",
      "gema_nr": "11739277-001",
      "duration": "3:30",
      "duration_sec": 210,
      "notes": "",
      "parts": {
        "5Ij0Ns_P001": {
          "pos": 1,
          "name": "Intro",
          "bars": 8,
          "duration_sec": 12,
          "light_template": "intro_buildup",
          "notes": ""
        }
      }
    }
  },
  "bars": {
    "B001": {
      "part_id": "5Ij0Ns_P003",
      "bar_num": 1,
      "lyrics": "Here we go again...",
      "audio": "audio/5Ij0Ns/5Ij0Ns_P003/bar_001.mp3",
      "has_accents": true
    }
  },
  "accents": {
    "A001": {
      "bar_id": "B001",
      "pos_16th": 1,
      "type": "bl",
      "notes": "Blinder on downbeat"
    }
  },
  "meta": {
    "accent_types": {"bl": "Blinder", "bo": "Blackout", "hl": "Highlight", "st": "Strobe", "fg": "Fog"},
    "pos_16th_map": "1=eins,2=e,3=und,4=e,5=zwei,...,13=vier,14=e,15=und,16=e",
    "storage": "github",
    "audio_path": "audio/{song_id}/{part_id}/"
  }
}
```

### 16th-Note Position System

Accents werden auf 16tel-Noten-Ebene pro Takt positioniert (1-16):

```
Position: 1   2   3   4   5   6   7   8   9   10  11  12  13  14  15  16
Zählweise: 1   e   +   e   2   e   +   e   3   e   +   e   4   e   +   e
```

### Light Templates

Vordefinierte Lichtprogramm-Vorlagen, die Parts zugewiesen werden:

```
intro_buildup, intro_hit, verse_minimal, verse_driving, verse_dark,
prechorus_rise, chorus_half, chorus_full, chorus_anthem,
bridge_atmospheric, bridge_breakdown, solo_spotlight, solo_intense,
breakdown_minimal, buildup_8bars, drop_impact,
outro_fadeout, outro_cut, ballad_warm, generic_bpm
```

-----

## Projektstruktur

```
lighting.ai/
├── CLAUDE.md                      # Diese Datei
├── README.md
├── pyproject.toml                 # Python-Projekt-Config
├── db/
│   └── lighting-ai-db.json       # Songdatenbank (GitHub-synced)
├── audio/                         # Audio-Schnipsel (GitHub-synced)
│   └── {song_id}/{part_id}/
│       └── bar_NNN.mp3
├── server/
│   ├── __init__.py
│   ├── main.py                    # FastAPI Entry Point
│   ├── config.py                  # Settings, GitHub-Config
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── songs.py               # REST: CRUD Songs, Parts
│   │   ├── setlist.py             # REST: Setlist-Verwaltung
│   │   ├── audio.py               # REST: Audio Upload/Download
│   │   └── ws.py                  # WebSocket: Live-Updates
│   ├── services/
│   │   ├── __init__.py
│   │   ├── db_service.py          # JSON DB lesen/schreiben
│   │   ├── github_service.py      # GitHub API Wrapper
│   │   └── audio_service.py       # Audio-Splitting, Encoding
│   └── models/
│       ├── __init__.py
│       └── schema.py              # Pydantic Models
├── ui/
│   ├── index.html                 # Haupt-Entry (Tab-Router)
│   ├── db-editor.html             # DB Editor Tab
│   ├── audio-split.html           # Audio Split Tab
│   ├── live.html                  # Live-UI für Timo (Phase 1)
│   └── assets/
│       └── style.css              # Shared Dark Theme
├── tests/
│   ├── test_db_service.py
│   ├── test_github_service.py
│   └── test_audio_service.py
└── scripts/
    └── import_pact_json.py        # Import aus BandHelper-Export
```

-----

## Entwicklungsrichtlinien

### Python

- Python 3.11+
- Type Hints überall
- async/await für I/O-Operationen
- Pydantic v2 für Datenmodelle
- `ruff` für Linting + Formatting
- Tests mit `pytest` + `pytest-asyncio`

### Frontend

- **Kein Framework, kein Build-Step** — Vanilla HTML/CSS/JS
- Single-file-HTML für Prototypen, modulare Dateien für Produktion
- Touch-optimiert: alle Tap-Targets ≥ 36px
- Dark Theme: `#08090d` Hintergrund, `#00dc82` (Green) als Akzent
- Fonts: **Sora** (UI) + **DM Mono** (Daten/Monospace)
- WebSocket für Echtzeit-Updates vom Server

### Design-System

```css
:root {
  --bg: #08090d;       /* Haupthintergrund */
  --bg2: #0e1017;      /* Panels */
  --bg3: #151820;      /* Inputs, Cards */
  --bg4: #1c1f2b;      /* Hover */
  --border: #1e2230;   /* Hauptrand */
  --border2: #2a2e40;  /* Sekundärrand */
  --t1: #eef0f6;       /* Haupttext */
  --t2: #a0a4b8;       /* Sekundärtext */
  --t3: #5c6080;       /* Tertiärtext */
  --t4: #363a52;       /* Placeholder */
  --green: #00dc82;    /* Primärakzent (aktiv, Bestätigung) */
  --amber: #f0a030;    /* Warnung, Part-Marker */
  --cyan: #38bdf8;     /* Info, Bar-Marker, Templates */
  --red: #ff3b5c;      /* Fehler, Löschen */
}
```

### Git Workflow

- Commit Messages auf Deutsch oder Englisch — egal, Hauptsache klar
- Feature-Branches für größere Änderungen
- `db/lighting-ai-db.json` wird auch durch die App committed (auto-save)
- Audio-Dateien kommen als Binary Blobs rein (kein LFS nötig, Dateien sind klein)

-----

## GitHub API Integration

### Authentifizierung

- Personal Access Token (Fine-grained) mit **Contents: read/write**
- Token wird im Browser `localStorage` gespeichert (Settings-Modal)
- Backend nutzt denselben Token aus Environment Variable

### Endpunkte

```
GET  /repos/{owner}/{repo}/contents/{path}  → Datei lesen (Base64)
PUT  /repos/{owner}/{repo}/contents/{path}  → Datei schreiben/updaten (SHA required)
```

### Wichtig

- Beim PUT muss immer der aktuelle `sha` der Datei mitgesendet werden
- UTF-8 Encoding: `btoa(unescape(encodeURIComponent(json)))` im Browser
- Audio als Base64 hochladen (MP3s sind ~30KB pro Takt)

-----

## Hardware (für spätere Phasen)

### Licht-Rig

|Fixture                     |Anzahl|DMX Universes|
|----------------------------|------|-------------|
|Expolite TourSpot 50 Mini   |2     |Universe 2   |
|Eurolite LED TMH Bar 120    |2     |Universe 2   |
|LED PARs (diverse)          |6     |Universe 1   |
|Blinder (Eigenbau)          |1     |Universe 1   |
|LED-Säulen WS2812 (Eigenbau)|2     |Universe 3-6 |
|Stairville LED Bar 240/8    |1     |Universe 1   |
|Hazer                       |1     |Universe 1   |
|Nebelmaschinen              |2     |Universe 1   |

### DMX-Nodes

- Showtec NET-2/3 (sACN → DMX)
- 2× ENTTEC OCTO (sACN → WS2812 Pixel)

### Mixer

- Behringer XR18 (OSC über WLAN, 18 Kanäle, ~25 Hz Meter-Rate)

-----

## Bestehende Prototypen

Im Repo befinden sich HTML-Prototypen aus der Designphase:

- **`lighting-ai-db-editor.html`** — DB Editor + Audio Split Tab mit eingebetteten Songdaten und GitHub-Sync (Referenz-Implementierung der UI)
- **`lighting-ai-ui.html`** — Live-UI-Prototyp für Timo (iPad, 3-Spalten-Layout)

Diese Prototypen zeigen das finale Look & Feel. Der Produktionscode soll die gleiche Ästhetik übernehmen, aber sauberer strukturiert sein (modulare Dateien statt Single-File).

-----

## Aufgaben Phase 1 (DB-Pflege-App)

### Meilenstein 1: Backend Grundgerüst

- [ ] FastAPI Projekt aufsetzen mit WebSocket-Support
- [ ] Pydantic Models für Song, Part, Bar, Accent, Setlist
- [ ] DB Service: JSON laden/speichern (lokal + GitHub)
- [ ] GitHub Service: Lesen, Schreiben, Audio-Upload
- [ ] REST Routen: CRUD für Songs, Parts, Setlists

### Meilenstein 2: DB Editor UI

- [ ] Song-Liste mit Suchfunktion
- [ ] Song-Detail: Felder inline editierbar
- [ ] Parts-Tabelle: Add, Delete, Move, Duplicate
- [ ] Bar-Editor: Lyrics, Accents auf 16tel-Raster
- [ ] Template-Picker für Light-Programme
- [ ] Auto-Save bei Änderungen, Sync-Status-Anzeige

### Meilenstein 3: Audio Split

- [ ] Audio-Datei laden (Drag & Drop, File-Picker)
- [ ] Waveform-Darstellung (Web Audio API)
- [ ] Transport: Play, Pause, Seek
- [ ] Part-Tap: Markiert Part-Grenzen
- [ ] Bar-Tap: Markiert Taktgrenzen
- [ ] BPM-Schätzung aus Bar-Intervallen
- [ ] Audio-Schnipsel extrahieren und auf GitHub speichern

### Meilenstein 4: Setlist-Verwaltung

- [ ] Setlist erstellen, bearbeiten, Songs per Drag ordnen
- [ ] Pausen einfügen
- [ ] Setlist-Export (PDF für die Band)

-----

## Referenz: Datenquelle

Die Songdaten stammen aus einem **BandHelper-Export** (`The_Pact.json`), der im Projekt-Knowledge liegt. Der Import-Script (`scripts/import_pact_json.py`) transformiert die BandHelper-Struktur in unser JSON-Schema. Custom Fields Mapping:

|BandHelper Field|Unser Feld   |
|----------------|-------------|
|`custom_HJV7Of` |year         |
|`custom_ufURoQ` |gema_nr      |
|`custom_zXQ5Fy` |pick         |
|`custom_B8s0D8` |notes (Axel) |
|`custom_prtQDP` |notes (Axel2)|
|`tempo`         |bpm          |
|`key`           |key          |
|`duration`      |duration_sec |
