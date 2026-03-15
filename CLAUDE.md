# CLAUDE.md — lighting.ai

## Projektübersicht

**lighting.ai** ist ein automatisiertes Lichtsteuerungssystem für die Coverband **THE PACT** aus Haan. Das System steuert Bühnenbeleuchtung basierend auf einer Songdatenbank, die das komplette Repertoire (65+ Songs) mit Songstruktur, Parts, Bars und Licht-Cues enthält.

Das Projekt besteht aus **zwei unabhängigen Teilprojekten**, die in separaten Chat-Sessions entwickelt werden:

| Teilprojekt | Beschreibung | Verzeichnis | Branch-Konvention |
|-------------|-------------|-------------|-------------------|
| **DB-Pflege-App** | WebApp zur Songdatenbank-Pflege | `/` (Root: `index.html`, `js/`, `css/`) | Branch MUSS "DB-Pflege-App" enthalten |
| **Live-App** | Live-Lichtsteuerung mit QLC+ | `/live/` | Branch MUSS "Live-App" enthalten |

### Ausbaustufen

1. **Phase 1 (AKTUELL):** DB-Pflege-App (WebApp) + QLC+ 4 Ansteuerung im Hintergrund
1. **Phase 2:** Tempo-Synchronisation aus OSC-Daten des Behringer XR18 (BD, Snare, Bass)
1. **Phase 3:** QLC+ ablösen — lighting.ai steuert DMX nativ über sACN
1. **Phase 4:** Vollautomatisierung über Meter Values des XR18 via OSC

-----

## Regeln für ALLE Chat-Sessions

### Git Workflow

- **Deploy-Branch: `main`** — GitHub Pages deployt aus `main`, Root `/`
- Feature-Branches (z.B. `claude/...`) werden in `main` gemergt für Deploy
- **WICHTIG: Branch-Namen MÜSSEN immer das Teilprojekt enthalten:**
  - DB-Pflege-App: `claude/DB-Pflege-App-...`
  - Live-App: `claude/Live-App-...`
  - **Niemals einen Branch ohne diese Kennzeichnung anlegen!**
- Commit Messages auf Deutsch oder Englisch — egal, Hauptsache klar
- `db/lighting-ai-db.json` wird auch durch die App committed (auto-save)
- Audio-Dateien kommen als Binary Blobs rein (kein LFS nötig, Dateien sind klein)

### Versionierung

- **Bei jeder Änderung an der DB-Pflege-App die Version in `js/app.js` hochsetzen** (Konstante `APP_VERSION` am Anfang der Datei)
- **Bei jeder Änderung an der Live-App die Version in `live/ui/index.html` hochsetzen**
- Patch-Version hochzählen (z.B. v0.9.7 → v0.9.8) bei normalen Änderungen
- Minor-Version bei größeren Features (z.B. v0.9.x → v0.10.0)

### Entwicklungsrichtlinien

- Vanilla ES6+ — kein Framework, kein Bundler, kein npm
- ES Modules (`import`/`export`) wo sinnvoll, ansonsten einfache Script-Tags
- `async/await` für GitHub API Calls
- JSDoc-Kommentare für komplexere Funktionen
- Keine externen Dependencies außer Google Fonts (Sora, DM Mono)
- Touch-optimiert: alle Tap-Targets >= 36px
- Dark Theme: `#08090d` Hintergrund, `#00dc82` (Green) als Akzent
- Fonts: **Sora** (UI) + **DM Mono** (Daten/Monospace)

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

-----

## DB-Pflege-App (nur für DB-Pflege-App-Sessions relevant)

### Was ist die DB-Pflege-App?

Eine komfortable Web-Oberfläche für den Lichttechniker **Timo**, die:

- Songdatenbank verwaltet (Songs, Parts, Bars, Accents, Setlists)
- Audio-Dateien in Parts/Bars zerlegt per Tap-to-Split
- Daten auf GitHub persistiert (JSON + Audio-Schnipsel)
- Im Live-Betrieb auf dem iPad im Browser läuft

### Architektur: Reine Client-App (GitHub Pages)

```
Browser (iPad / Laptop / Handy)
  lighting.ai WebApp (HTML/JS)
    ├── DB Editor Tab
    ├── Audio Split Tab
    └── Live UI Tab (Phase 1)
         │
         ▼ GitHub API (REST, direkt)
    GitHub Repository
      ├── db/*.json
      └── audio/*.mp3
```

**Kein Backend!** Der Browser kommuniziert direkt mit der GitHub API. Audio-Processing (Waveform, Splitting) läuft komplett client-seitig über die Web Audio API.

### Hosting

- **GitHub Pages**: `christianprison.github.io/lighting.ai`
- Automatisches Deploy bei jedem Push auf `main`

### Dateien der DB-Pflege-App

```
lighting.ai/
├── index.html                     # Entry Point (Tab-Router)
├── css/
│   └── style.css                  # Shared Dark Theme
├── js/
│   ├── app.js                     # Haupt-App-Logik, Routing
│   ├── db.js                      # DB Laden/Speichern via GitHub API
│   ├── integrity.js               # DB-Integritätsfunktionen (deleteSong etc.)
│   ├── audio-engine.js            # Web Audio API Wrapper
│   └── utils.js                   # Hilfsfunktionen
├── db/
│   └── lighting-ai-db.json       # Songdatenbank (GitHub-synced)
└── audio/                         # Audio-Schnipsel (GitHub-synced)
    └── {song_name}/{part}/
        └── bar_NNN.mp3
```

### Tech Stack (DB-Pflege-App)

|Komponente       |Technologie              |Begründung                        |
|-----------------|-------------------------|----------------------------------|
|Frontend         |Vanilla HTML/CSS/JS      |Single-file, kein Build-Step      |
|Persistenz       |GitHub API (REST, direkt)|Versionierung gratis, Audio+JSON  |
|Audio Processing |Web Audio API (Browser)  |Waveform, Playback, Splitting     |
|Hosting          |GitHub Pages             |Kostenlos, HTTPS, immer erreichbar|

### GitHub API Integration

- Personal Access Token (Fine-grained) mit **Contents: read/write**
- Token wird im Browser `localStorage` gespeichert (Settings-Modal)
- `GET /repos/{owner}/{repo}/contents/{path}` → Datei lesen (Base64)
- `PUT /repos/{owner}/{repo}/contents/{path}` → Datei schreiben (SHA required)
- UTF-8 Encoding: `btoa(unescape(encodeURIComponent(json)))` im Browser

### Datenbank-Schema (JSON)

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

### Parts-Konzept (ab v1.7.0)

Ein **Part** entsteht durch die Qualifizierung eines Taktes als **Partstart**. Das Partende ist definiert durch entweder den nächsten Takt, der ebenfalls als Partstart qualifiziert ist, oder — falls es keinen nachfolgenden Takt gibt, der als Partstart qualifiziert ist — durch das Ende des Songs.

**Redundanzvermeidung:** Keine Information, die sich auch aus dieser Vorgabe ableiten ließe, darf redundant am Part gespeichert werden, um Inkonsistenzen zu vermeiden. Insbesondere werden folgende Werte **nicht** am Part gespeichert, sondern zur Laufzeit berechnet:

- Anzahl der Takte (ergibt sich aus den Takten zwischen diesem Partstart und dem nächsten)
- Dauer (ergibt sich aus den zugehörigen Takten)
- Position/Reihenfolge (ergibt sich aus der Position des Starttaktes)

**Exklusive Parteigenschaften**, die mit dem Part gespeichert oder assoziiert werden dürfen:

- Name (z.B. „Intro", „Verse 1", „Chorus")
- Light Template (zugeordnetes Lichtprogramm)

### 16th-Note Position System

Accents werden auf 16tel-Noten-Ebene pro Takt positioniert (1-16):

```
Position: 1   2   3   4   5   6   7   8   9   10  11  12  13  14  15  16
Zählweise: 1   e   +   e   2   e   +   e   3   e   +   e   4   e   +   e
```

### Light Templates (= QLC+ Szenen-Gruppen aus live/ui/config.html)

```
00 blackout, 01 statisch bunt, 02 slow blue, 03 walking,
04 up'n'down, 05 left'n'right, 06 blinking, 07 round'n'round,
08 swimming, 09 Alarm, 10 Alarm 🔔🔔, 10 Strobe, 11 Stop,
12 slow red, 16 Searchlight, 20 white Fan up, 21 white fan down,
22 blind
```

### Aufgaben Phase 1 (DB-Pflege-App)

#### Meilenstein 1: Grundgerüst + GitHub Pages

- [x] Repo-Struktur anlegen (index.html, css/, js/, ui/)
- [x] GitHub Pages aktivieren
- [x] GitHub API Wrapper (`js/db.js`): Lesen, Schreiben, SHA-Tracking
- [x] Settings-Modal: Token + Repo konfigurieren (localStorage)
- [x] DB laden und im Speicher halten, Sync-Status-Anzeige

#### Meilenstein 2: DB Editor UI

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

#### Meilenstein 3: Audio Split

- [x] Audio-Datei laden (Drag & Drop, File-Picker)
- [x] Waveform-Darstellung (Web Audio API + Canvas)
- [x] Transport: Play, Pause, Seek (Klick auf Waveform)
- [x] Part-Tap: Markiert Part-Grenzen (übernimmt Part-Namen aus Song)
- [x] Bar-Tap: Markiert Taktgrenzen innerhalb Parts
- [x] BPM-Schätzung aus Bar-Intervallen
- [x] Undo-Funktion für Taps
- [x] alle Parts identifiziert
- [x] Referenz-Audio automatisch aus DB laden (`audio_ref`)
- [x] Part-Tap setzt automatisch ersten Bar-Marker (Takt 1 = Part-Start)
- [x] Marker per Drag & Drop verschiebbar (Part + Bar, Maus + Touch/iPad)
- [x] Visuelles Feedback beim Drag: Marker-Hervorhebung + Zeitanzeige
- [x] Erster Bar-Marker folgt automatisch beim Verschieben des Part-Markers
- [x] Zoom-Stufen bis 10x für präzises Marker-Editing

#### Meilenstein 4: Setlist-Verwaltung

- [x] Setlist erstellen, bearbeiten, Songs per Drag ordnen
- [x] Pausen einfügen
- [x] Setlist-Export (druckbares HTML/PDF für die Band)

-----

## Live-App (nur für Live-App-Sessions relevant)

### Was ist die Live-App?

Die Live-Lichtsteuerung für Auftritte, die auf dem Linux Mint Steuer-Laptop läuft:

- FastAPI-Backend steuert QLC+ über OSC
- Web-UI für Timo auf dem iPad (Songauswahl, Part-Navigation)
- Liest Songdaten aus der gemeinsamen `db/lighting-ai-db.json`

### Dateien der Live-App

```
lighting.ai/live/
├── README.md
├── config.yaml                    # Konfiguration (QLC+ Host, Ports etc.)
├── requirements.txt               # Python Dependencies
├── start-live.sh                  # Startskript
├── server/
│   ├── main.py                    # FastAPI Backend
│   └── qlc_osc.py                # QLC+ OSC-Steuerung
├── ui/
│   ├── index.html                 # Live-UI für iPad
│   └── config.html                # Konfigurations-UI
└── data/                          # Lokale Daten
```

### Tech Stack (Live-App)

|Komponente       |Technologie              |Begründung                        |
|-----------------|-------------------------|----------------------------------|
|Backend          |Python 3.11+ / FastAPI   |Async, WebSocket, OSC             |
|Lichtsteuerung   |QLC+ 4 über OSC          |Phase 1: bewährte Software        |
|DMX (Phase 3)    |sacn (Python)            |sACN/E1.31 direkt                 |
|OSC (Phase 2)    |python-osc               |XR18 Meter-Daten                  |
|OS               |Linux Mint               |Vorhandener Steuer-Laptop         |

### Python-Richtlinien (Live-App)

- Python 3.11+
- Type Hints überall
- async/await für I/O-Operationen
- Pydantic v2 für Datenmodelle
- `ruff` für Linting + Formatting
- Tests mit `pytest` + `pytest-asyncio`

### Netzwerk

|Netz    |Interface|Zweck                            |
|--------|---------|---------------------------------|
|WLAN    |wlan0    |OSC-Kommunikation mit XR18 Mixer |
|Ethernet|eth0     |sACN/DMX-Output an Showtec/ENTTEC|
|LAN/WLAN|beide    |WebApp-Zugriff (iPad, Laptop)    |

-----

## Gemeinsam genutzte Ressourcen

### Daten-Storage

- **Songdatenbank:** `db/lighting-ai-db.json` — wird von beiden Apps gelesen/geschrieben
- **Audio-Schnipsel:** `audio/{song_name}/...` — von DB-Pflege-App erzeugt
- **Kein Excel** — alles JSON-basiert

### Hardware

#### Licht-Rig

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

#### DMX-Nodes

- Showtec NET-2/3 (sACN -> DMX)
- 2x ENTTEC OCTO (sACN -> WS2812 Pixel)

#### Mixer

- Behringer XR18 (OSC über WLAN, 18 Kanäle, ~25 Hz Meter-Rate)

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
