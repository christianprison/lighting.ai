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

### Phase 1: Reine Client-App (GitHub Pages)

```
┌─────────────────────────────────────────────────┐
│           Browser (iPad / Laptop / Handy)        │
│           lighting.ai WebApp (HTML/JS)           │
│    ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│    │ DB Editor│  │Audio Split│  │ Live UI  │    │
│    └────┬─────┘  └────┬─────┘  └────┬─────┘    │
│         │ GitHub API   │ GitHub API  │           │
│         │ (REST)       │ (REST)      │           │
└─────────┼──────────────┼────────────┼───────────┘
          ▼              ▼            │
┌─────────────────────────────────┐  │ (Phase 2+)
│         GitHub Repository       │  │
│  christianprison/lighting.ai    │  │
│  ┌──────────┐  ┌──────────┐    │  │
│  │ db/      │  │ audio/   │    │  │
│  │ *.json   │  │ *.mp3    │    │  │
│  └──────────┘  └──────────┘    │  │
└─────────────────────────────────┘  │
                                     ▼
                        ┌──────────────────────┐
                        │ Linux Mint (Phase 2+)│
                        │ FastAPI + DMX/sACN   │
                        │ OSC (XR18 Mixer)     │
                        └──────────────────────┘
```

**Kein Backend in Phase 1!** Der Browser kommuniziert direkt mit der GitHub API. Audio-Processing (Waveform, Splitting) läuft komplett client-seitig über die Web Audio API. Das FastAPI-Backend kommt erst in Phase 2 dazu, wenn OSC und DMX-Steuerung gebraucht werden.

### Hosting

- **GitHub Pages**: `christianprison.github.io/lighting.ai`
- Automatisches Deploy bei jedem Push
- HTTPS, CDN, immer erreichbar, kostenlos
- Einrichtung: Repo Settings → Pages → Source: `main`, Root `/`

### Phase 2+: Lokaler Server (zusätzlich)

Ab Phase 2 läuft ein FastAPI-Backend auf dem **Linux Mint** Steuer-Laptop:

- OSC-Empfang vom XR18 über WLAN
- sACN/DMX-Output über Ethernet an Showtec/ENTTEC
- WebSocket für Live-UI-Updates
- Die DB-Pflege-App (GitHub Pages) bleibt unabhängig davon nutzbar

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

|Komponente       |Technologie              |Begründung                        |
|-----------------|-------------------------|----------------------------------|
|Frontend         |Vanilla HTML/CSS/JS      |Single-file, kein Build-Step      |
|Persistenz       |GitHub API (REST, direkt)|Versionierung gratis, Audio+JSON  |
|Audio Processing |Web Audio API (Browser)  |Waveform, Playback, Splitting     |
|Hosting          |GitHub Pages             |Kostenlos, HTTPS, immer erreichbar|
|Backend (Phase 2)|Python 3.11+ / FastAPI   |Async, WebSocket, OSC, DMX        |
|DMX (Phase 3)    |sacn (Python)            |sACN/E1.31 direkt                 |
|OSC (Phase 2)    |python-osc               |XR18 Meter-Daten                  |
|OS (Phase 2+)    |Linux Mint               |Vorhandener Steuer-Laptop         |

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
├── index.html                     # Entry Point (Tab-Router)
├── db/
│   └── lighting-ai-db.json       # Songdatenbank (GitHub-synced)
├── audio/                         # Audio-Schnipsel (GitHub-synced)
│   └── {song_id}/{part_id}/
│       └── bar_NNN.mp3
├── ui/
│   ├── db-editor.html             # DB Editor Tab
│   ├── audio-split.html           # Audio Split Tab
│   ├── live.html                  # Live-UI für Timo (Phase 1)
│   └── components/                # Wiederverwendbare UI-Module
│       ├── song-list.js           # Song-Liste mit Filter
│       ├── part-table.js          # Parts-Tabelle
│       ├── waveform.js            # Waveform-Rendering
│       ├── transport.js           # Play/Pause/Seek
│       └── github-sync.js         # GitHub API Wrapper
├── css/
│   └── style.css                  # Shared Dark Theme
├── js/
│   ├── app.js                     # Haupt-App-Logik, Routing
│   ├── db.js                      # DB Laden/Speichern via GitHub API
│   ├── audio-engine.js            # Web Audio API Wrapper
│   └── utils.js                   # Hilfsfunktionen
├── scripts/
│   └── import_pact_json.py        # Import aus BandHelper-Export
└── server/                        # Phase 2+ (FastAPI, OSC, DMX)
    └── README.md                  # Platzhalter
```

-----

## Entwicklungsrichtlinien

### JavaScript (Phase 1)

- Vanilla ES6+ — kein Framework, kein Bundler, kein npm
- ES Modules (`import`/`export`) wo sinnvoll, ansonsten einfache Script-Tags
- `async/await` für GitHub API Calls
- JSDoc-Kommentare für komplexere Funktionen
- Keine externen Dependencies außer Google Fonts (Sora, DM Mono)

### Python (Phase 2+)

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

- **Deploy-Branch: `main`** — GitHub Pages deployt aus `main`, Root `/`
- Feature-Branches (z.B. `claude/...`) werden in `main` gemergt für Deploy
- Commit Messages auf Deutsch oder Englisch — egal, Hauptsache klar
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

## Lokale Entwicklung

### Setup

```bash
git clone git@github.com:christianprison/lighting.ai.git
cd lighting.ai
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Dev-Server starten

```bash
# Backend + statische UI-Dateien
uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
```

Dann im Browser: `http://localhost:8000` (oder vom iPad: `http://<ip-des-rechners>:8000`)

### Umgebungsvariablen

```bash
# .env (nicht ins Repo!)
GITHUB_TOKEN=github_pat_...
GITHUB_REPO=christianprison/lighting.ai
GITHUB_DB_PATH=db/lighting-ai-db.json
```

### Hosting (später)

Die App ist bewusst so gebaut, dass sie später einfach deployed werden kann:

- **GitHub Pages:** Nur die UI-Dateien aus `ui/` — Browser spricht direkt mit GitHub API (kein Backend nötig für reine DB-Pflege)
- **Render / fly.io / Hetzner:** Für Vollbetrieb mit Backend (Audio-Processing, WebSocket, DMX-Steuerung)
- **Lokal im Proberaum / Live:** FastAPI auf dem Linux-Rechner, iPad greift über LAN zu

-----

## Aufgaben Phase 1 (DB-Pflege-App, reine Client-App)

### Meilenstein 1: Grundgerüst + GitHub Pages

- [x] Repo-Struktur anlegen (index.html, css/, js/, ui/)
- [x] GitHub Pages aktivieren
- [x] GitHub API Wrapper (`js/db.js`): Lesen, Schreiben, SHA-Tracking
- [x] Settings-Modal: Token + Repo konfigurieren (localStorage)
- [x] DB laden und im Speicher halten, Sync-Status-Anzeige

### Meilenstein 2: DB Editor UI

- [x] Song-Liste mit Suchfunktion (links)
- [x] Song-Detail: Felder inline editierbar (Name, Artist, BPM, Key, Jahr, GEMA, Pick)
- [x] Parts-Tabelle: Add, Delete, Move, Duplicate, Bars editierbar
- [x] Template-Picker Dropdown für Light-Programme
- [x] Auto-Berechnung: Duration pro Part und Song aus Bars + BPM
- [x] Bar-Editor: Lyrics-Eingabe, Accents auf 16tel-Raster
- [x] Auto-Save / manueller Save-Button → GitHub Commit
- [x] Parts-Tab: Mini-Waveform pro Part-Zeile (grün, aus Referenz-Audio)
- [x] Takte-Tab: Mini-Waveform pro Takt-Zeile (cyan, aus Referenz-Audio + Bar-Markern)
- [x] Takte-Tab: "Alle Takte löschen" Button mit Bestätigung
- [x] Lyrics-Tab: Parts ein-/ausklappen (einzeln + alle auf einmal)
- [x] Lyrics-Tab: Instrumental-Checkbox pro Part

### Meilenstein 3: Audio Split

- [x] Audio-Datei laden (Drag & Drop, File-Picker)
- [x] Waveform-Darstellung (Web Audio API + Canvas)
- [x] Transport: Play, Pause, Seek (Klick auf Waveform)
- [x] Part-Tap: Markiert Part-Grenzen (übernimmt Part-Namen aus Song)
- [x] Bar-Tap: Markiert Taktgrenzen innerhalb Parts
- [x] BPM-Schätzung aus Bar-Intervallen
- [x] Undo-Funktion für Taps
- [x] Audio-Schnipsel extrahieren (OfflineAudioContext) und auf GitHub speichern
- [x] Referenz-Audio automatisch aus DB laden (`audio_ref`)
- [x] Part-Tap setzt automatisch ersten Bar-Marker (Takt 1 = Part-Start)
- [x] Marker per Drag & Drop verschiebbar (Part + Bar, Maus + Touch/iPad)
- [x] Visuelles Feedback beim Drag: Marker-Hervorhebung + Zeitanzeige
- [x] Erster Bar-Marker folgt automatisch beim Verschieben des Part-Markers
- [x] Zoom-Stufen bis 6× für präzises Marker-Editing

### Meilenstein 4: Setlist-Verwaltung

- [x] Setlist erstellen, bearbeiten, Songs per Drag ordnen
- [x] Pausen einfügen
- [x] Setlist-Export (druckbares HTML/PDF für die Band)

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
