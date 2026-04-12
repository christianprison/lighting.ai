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

### ⚠️ PRIME DIRECTIVE: Simulation = Live — ein Algorithmus, keine Ausnahmen

> **Diese Regel hat höchste Priorität und darf NIEMALS gebrochen werden.**  
> Jede neue Session muss diese Regel verstehen und einhalten, bevor sie irgendetwas implementiert.

**Die Simulation ist kein separater Modus. Sie ist das Testbett für den Live-Algorithmus.**

Der Sinn der Rehearsal-App-Simulation ist es, Fehler im Live-Algorithmus zu erkennen
und ihn robuster zu machen. Das funktioniert nur, wenn Simulation und Live-Betrieb
**exakt denselben Code** ausführen — Block für Block, Event für Event, ohne jede
Fallunterscheidung.

**Konkret bedeutet das:**
- Alle Erkennungsalgorithmen gehören in `detection/` und werden von beiden Apps importiert
- Es darf **keine** "Batch-Variante für die Simulation" und "Online-Variante für Live" geben
- Auch Komfort-Funktionen wie Bar-Tracking müssen als Streaming-Algorithmus gebaut sein,
  der sowohl auf aufgezeichnetem Audio (Simulation) als auch auf Live-Eingang (Echtzeit)
  funktioniert — **derselbe Code, dieselbe Reihenfolge der Operationen**
- Wer versucht ist, "in der Simulation können wir ja alle Events auf einmal sehen":
  **Nein.** Der Algorithmus sieht nur was er bisher gehört hat, genau wie im Live-Betrieb
- Jede Verbesserung an `detection/` ist automatisch eine Verbesserung an beiden Apps

```
detection/
├── beat_detector.py   # OnsetDetector: Kick/Snare/Crash-Erkennung (streaming)
├── bar_tracker.py     # BarTracker: Takt-Tracking (streaming, kein Batch)
├── fingerprint.py     # Feature-Extraktion
├── hmm.py             # HMM-basierte Positionsschätzung
└── reference_db.py    # SQLite-Backend
```

**Importpfad (identisch in beiden Apps):**
- Live-App (`live/server/`): `from detection.beat_detector import OnsetDetector`
- Rehearsal-App (`rehearsal_review/`): identischer Import (Repo-Root in `sys.path`)
- Simulator (`rehearsal_review/simulator.py`): identischer Import

**Implementiert in Session 2026-04:**  
`detection/bar_tracker.py` enthält den `BarTracker` — einen echten Streaming-Algorithmus,
der mit jedem eingehenden Kick-/Snare-Event inkrementell arbeitet und in Simulation wie
Live identisch läuft. Die Batch-Funktionen `_compute_bar_times()` und
`_find_anchor_by_phase()` wurden aus `rehearsal_review/mainwindow.py` entfernt.
`rehearsal_review/simulator.py` nutzt `BarTracker` direkt während der Simulation und
liefert `bar_times` + `bpm` im `finished`-Signal.

### ⚠️ MCP-Tool-Limitation: Dateigröße

**`mcp__github__push_files` und `mcp__github__create_or_update_file` haben ein stilles Content-Limit von ca. 48 KB.**  
Bei Dateien über dieser Grenze wird der `content`-Parameter einfach verworfen — die Tools geben "missing required parameter: content" zurück oder senden Leerinhalt.

**Konsequenz:** Niemals `push_files` / `create_or_update_file` für große Dateien (>~800 Zeilen Python) nutzen. Wenn `git push` geblockt ist und die MCP-Tools für große Dateien nicht funktionieren → Nutzer muss den Push von seinem lokalen Laptop aus durchführen.


### Versionierung

- **Bei jeder Änderung an der DB-Pflege-App die Version in `js/app.js` hochsetzen** (Konstante `APP_VERSION` am Anfang der Datei)
- **Bei jeder Änderung an der Live-App die Version in `live/ui/index.html` hochsetzen**
- **Bei jeder Änderung an der Rehearsal-App die Version in `rehearsal_review/mainwindow.py` hochsetzen** (Konstante `APP_VERSION` direkt unterhalb von `_ZOOM_PRESETS`)
- Patch-Version hochzählen (z.B. v1.0.0 → v1.0.1) bei normalen Änderungen
- Minor-Version bei größeren Features (z.B. v1.0.x → v1.1.0)

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
      "grundrhythmus": {"kick": [0.0, 2.0], "snare": [1.0, 3.0]},
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
│   ├── qlc_osc.py                # QLC+ OSC-Steuerung
│   └── audio/
│       ├── reference_db.py        # SQLite-Wrapper für Takt-Feature-Daten
│       ├── fingerprint.py         # Feature-Extraktion (chroma, MFCC, onset, RMS)
│       ├── recording_importer.py  # WAV → Features → reference.db (inkrementell)
│       └── snippet_importer.py    # Audio-Snippet → reference.db
├── ui/
│   ├── index.html                 # Live-UI für iPad
│   └── config.html                # Konfigurations-UI
└── data/
    ├── reference.db               # SQLite: songs, bars, feature_vectors
    └── recordings/                # 18-Kanal WAV + JSONL Event-Logs
        └── YYYY-MM-DD_HHmmss_*.{wav,jsonl}
```

### Dateien der Rehearsal-Review-App

```
lighting.ai/rehearsal_review/
├── start.sh                   # Startskript (venv /opt/lighting-venv)
├── main.py                    # Entry Point
├── mainwindow.py              # Hauptfenster
├── timeline.py                # Timeline-Widget
├── player.py                  # Audio-Playback (sounddevice)
├── session.py                 # Session-Datenmodell (JSONL → SongSegments)
├── peaks.py                   # Waveform-Peak-Extraktion (QThread)
├── overview.py                # Minimap-Widget (volle Session)
├── annotation.py              # Annotation-Datenmodell + JSON-I/O
├── fragment_detector.py       # Stille-basierte Fragment-Erkennung (chunked RMS)
├── sim_monitor.py             # Simulations-Monitor-Dialog
└── simulator.py               # Offline-Simulation der Live-Erkennungspipeline
```

-----

## Rehearsal Post-Preparation App (Live-App-Sessions)

### Was ist die Rehearsal App?

Eine PyQt6 Desktop-App für den Linux Mint Steuer-Laptop, die:

- Probenaufnahmen (18-Kanal WAV, 48 kHz) abhörbar macht (Solo, Mute, Zoom)
- Takt- und Part-Grenzen manuell annotieren lässt (B / P / F / U Shortcuts)
- Bar-Marker beim Verlassen des Annotationsmodus auf den nächsten Beat/Snare-Event snapped (Auto-Quantisierung, ±0,25 s)
- Part-Namen beim P-Dialog aus `reference.db` vorschlägt (Klappliste, Vorauswahl nach Takt-Nähe)
- Songs automatisch in Fragmente unterteilt (Stille-Erkennung auf 16 Kanälen) mit Geplänkel-Filter (Drum-Aktivität)
- Per-Fragment `restart_bar_num` erlaubt unterschiedliche Takt-Offsets pro Spielanlauf
- Annotierte Takte als Audio-Features in die `reference.db` importiert
- Die Kick/Snare-Erkennungspipeline offline auf Probenaufnahmen simuliert (`OnsetDetector`: Band-gefilterter ODF) zum Algorithmus-Tuning

### Starten

```bash
cd /home/thepact/git/lighting.ai_neu/rehearsal_review
./start.sh [optionaler/pfad/zur/session.jsonl]
```

venv: `/opt/lighting-venv` (PyQt6, sounddevice, soundfile, numpy, librosa)

### Wichtige Implementierungsdetails

#### Audio-Playback

- **sounddevice MUSS `device="pulse"` nutzen** — direktes ALSA ohne PulseAudio verursacht zufällige Knackser ("Furz"-Geräusche)
- Aktuell: `sd.play(data, sr, device="pulse", blocksize=4096)` in `player.py`
- WAV-Dateien: 18 Kanäle, float32, 48 kHz — Kanal 16+17 (0-basiert) = Main L/R

#### Session-Format

- **JSONL-Event-Log**: `{timestamp}_*.jsonl` — Events mit `t` (Sekunden seit Aufnahmestart), `type`, `data`
- **WAV-Referenz** im `session_start`-Event unter `"wav"`-Key; Fallback: gleicher Name mit `.wav`
- `session.py:load_session()` parst JSONL → `Session` mit `SongSegment`-Liste

#### Annotations-System

- **Datei**: `{session_stem}_annotations.json` neben dem JSONL
- **`SongAnnotation`**: `song_id`, `song_name`, `segment_start_t` (WAV-Offset), `start_bar_num` (Offset wenn Aufnahme nicht bei Takt 1 beginnt), `markers: list[BarMarker]`
- **`BarMarker`**: `t` (Sekunden relativ zum Segment-Start), `bar_num` (auto), `part_name` (nicht leer = Part-Start), `restart_bar_num` (nicht None = Fragment-Start, setzt Zähler zurück), `quantize_failed` (transient, nicht serialisiert — True wenn kein Beat in ±0,25 s gefunden)
- `_renumber()` nummeriert Marker ab `start_bar_num`; bei `restart_bar_num != None` wird der Zähler auf diesen Wert gesetzt
- `add_marker()` hält Liste sortiert nach `t`; akzeptiert optionales `restart_bar_num`
- **Auto-Quantisierung** (`mainwindow._quantize_bar_markers()`): beim Verlassen des Annotationsmodus werden alle Marker auf den nächsten `beat`- oder `snare`-Event aus dem Session-JSONL gesnapped (Fenster ±0,25 s). Marker ohne Treffer bekommen `quantize_failed=True` und erhalten ein rotes `?` in der Timeline.
- **Part-Dialog** (`_add_part_marker()`): lädt Parts aus `reference.db`, wählt den Part mit dem nächstgelegenen `first_bar` als Default in einer nicht-editierbaren Klappliste vor.
- **Fragment-Erkennung** (`fragment_detector.py`): chunked RMS-Analyse, Stille ≥ 1,5 s → Split. Geplänkel-Filter: Fragmente mit <10% Drum-Aktivität (CH 8+9) UND <8 s absoluter Drum-Zeit werden verworfen. Parameter: `min_drum_activity=0.10`, `min_drum_active_sec=8.0`. `Fragment.drum_ratio` enthält den gemessenen Anteil.

#### Timeline-Layout (Konstanten in `timeline.py`)

```
RULER_H  = 28    # Zeitlineal oben
EVENTS_H = 26    # Beat/Position-Events-Streifen
ANNOT_H  = 0     # Takt-Annotations-Streifen (deaktiviert — war immer leer)
LABEL_W  = 196   # Sticky-Label-Spalte links
```

ANNOT-Strip ist deaktiviert (ANNOT_H = 0). Der Code für Marker-Darstellung existiert noch,
wird aber durch den frühen `return`-Guard in `_paint_annotation_strip()` nie ausgeführt.
Wenn der ANNOT-Strip reaktiviert werden soll, ANNOT_H = 32 setzen.

ANNOT-Strip Marker-Farben (für Reaktivierung):
- **amber** (#f0a030): normaler Takt-Marker
- **grün** (#00dc82): Part-Start-Marker
- **weiß** (#ffffff, 2px): Fragment-Start-Marker (`restart_bar_num` gesetzt), Label `→T{n}`
- **rot `?`** (#ff3b5c): `quantize_failed=True` — kein Beat in Reichweite gefunden
- **violett** (#a78bfa): auto-erkannte Fragmentgrenze aus `fragment_detector.py` (nur visuell, kein BarMarker)
- **grün/grau Balken** (unten, während Fragmenterkennung): Aktivitätskarte der 50ms-RMS-Fenster; cyan Scan-Kopf-Linie

Events-Strip — Normal-Modus (JSONL-Events aus Probenaufnahme):
- Solide Linie = Downbeat | transparente Linie = Beat | cyan = Snare

Events-Strip — Sim-Overlay-Modus (`_sim_overlay=True`):
- JSONL-Events **komplett ausgeblendet** (wenn Sim-Events vorhanden)
- Sim-Diamonds im Events-Strip: amber = Sim-Kick (r=4, unten), cyan = Sim-Snare (r=4, oben), rot = Sim-Crash (r=7, Mitte)

Kanal-Rows mit Event-Markern (`_paint_event_markers()`):
- **OH L+R** (`BEAT_MARKER_CHS = {13,14}`): alle Beats — amber = Beat, rot = Downbeat
- **Snare** (`SNARE_MARKER_CHS = {9}`): snare-Events — cyan Diamond
- **Kick** (`KICK_MARKER_CHS = {8}`): nur `trigger="kick"` Beats — amber = Kick, rot = Kick+Downbeat
- Im Sim-Overlay: Original-Marker komplett ausgeblendet (wenn Sim-Events vorhanden), Sim-Events alpha=220

Taktgitter im Sim-Overlay (`_paint_sim_bars()`):
- Halbdurchsichtige weiße vertikale Linien (`rgba(255,255,255,55)`) über alle Drum-Tracks (Kick..OH L+R)
- Taktnummer alle 5 Takte in amber (FONT_BTN) in der Tom-Zeile
- Tom-Label-Zelle zeigt bei aktiver Sim `"{sim_bpm} BPM"` in amber unter dem Spurnahmen
- BPM wird aus dem medianen IOI der **letzten 8** Kick+Snare-Events berechnet (Filter: 60–220 BPM) — schnelle Reaktion auf Tempo-Änderungen

Annotation-Strip zeigt amber Oberkante + lila Hintergrund wenn Modus aktiv.
"Annotieren"-Button ist grün/invertiert wenn aktiv (`:checked` CSS).

#### reference.db Schema

```sql
songs          (song_id PK, name, bpm, total_bars)
bars           (bar_id PK, song_id FK, bar_num, part_name, audio_path)
feature_vectors(bar_id PK FK, chroma BLOB, mfcc BLOB, onset BLOB, rms REAL, sample_count INT)
probe_events   (id, session_id, wav_offset, song_id, bar_num, part_name, confidence, ...)
```

- `get_parts_for_song(song_id)` → Liste von `{part_name, first_bar, last_bar, bar_count}` — nützlich um `start_bar_num` zu setzen
- Inkrementelles Averaging: `new_mean = (old × n + new) / (n+1)` via `sample_count`
- Schema-Migration: `recording_importer.py` UND `ReferenceDB._ensure_sample_count_column()` legen `sample_count`-Spalte automatisch an falls fehlend
- `upsert_bar_chroma(song_id, bar_num, chroma)`: speichert Lead-Guitar-Chroma per Takt; legt Stub-Feature-Vector an falls noch keiner vorhanden (mfcc/onset = 0); bei vorhandenem Vektor: inkrementelles Averaging nur für chroma

#### Keyboard Shortcuts (Rehearsal App)

| Taste | Funktion |
|-------|----------|
| Space | Play / Pause |
| B | Takt-Marker an Cursor-Position (nur im Annotations-Modus) |
| P | Part-Start-Marker — Klappliste mit DB-Vorschlag (nur im Annotations-Modus) |
| F | Fragment-Start-Marker — fragt nach Start-Takt-Nummer (nur im Annotations-Modus) |
| U | Letzten Marker rückgängig (nur im Annotations-Modus) |
| + / - | Zoom in/out |
| 0 | Zoom Anpassen |
| Rechtsklick im ANNOT-Strip | Nächsten Marker löschen |

#### Simulation (simulator.py)

Zwei Worker — **Prime Directive bleibt**: SimulatorWorker = Live-Algorithmus, PostProcessWorker = reine Visualisierung.

`SimulatorWorker(QThread)` repliziert die Erkennungspipeline **offline**:
- Liest WAV **immer ab Segment-Anfang** in BLOCK_SIZE=2048-Blöcken
- Schickt jeden Block durch `OnsetDetector.process_block()` (Kick CH08, Snare CH09, Crash CH13+14)
- Schreibt alle Events in eine **JSONL-Datei** (`{stem}_sim_{song_id}_{HHmmss}.jsonl`)
- Puffert Chroma-Kanal (CH4) und Bass-Kanal (CH5) als Rohsignal-Arrays
- Ruft `tracker.finalize()` am Ende des Onset-Loops auf (flusht letzte <8 Events)
- Progress-Modal: 0–100 % für Onset-Loop
- `finished`-Dict: `jsonl_path`, `n_kicks`, `n_snares`, `n_crashes`, `kicks`, `snares`, `crashes`, `bar_times`, `bpm`, **`chroma_buf`** (np.ndarray), **`bass_buf`** (np.ndarray), `sample_rate`, `seg_start_t`, `seg_end_t`, `song_key`
- Sim-JSONL-Dateien werden im Dateiauswahldialog automatisch ausgeblendet (`_HideSimFiles` Proxy)
- Nach Simulation: Status-Bar zeigt `★ N Crashes` wenn Crashes erkannt wurden
- Diagnose stderr: `[SIM] Crashes: N erkannt (threshold RMS >0.0040, max OH-RMS im Segment: X.XXXX)`

`PostProcessWorker(QThread)` — nur Visualisierung, nicht Live:
- Empfängt `chroma_buf` + `bass_buf` von `SimulatorWorker.finished`
- Eigenes Progress-Modal (cyan Fortschrittsbalken): 0–50 % Chroma, 50–100 % Bass
- `finished`-Dict: `{"chroma_data": list[dict], "bass_data": list[dict]}`
- `chroma_data`: `[{"t": float, "chroma": list[float]}, ...]` pro Beat
- `bass_data`: `[{"t": float, "chroma": list[float], "rhythm": float}, ...]` pro Takt

**Bass-Analyse (`chroma_viz.py`):**
- `CH_BASS = 5` (CH06 = Bass); `CH_LEAD_GUITAR = 4`
- `bass_rhythm_score(audio_clip, sample_rate, bpm) -> float`: librosa `onset_strength` + `onset_detect` → IOIs (gefiltert: 0.05 s bis 4 Takte) → `max(0, 1 - 2 * |ioi - nächstes_8tel_vielfaches| / eighth_sec)` → Mittelwert. Wert 1.0 = perfekte 8tel, 0.0 = Rhythmus weicht um halbe 8tel-Periode ab
- `extract_bass_at_bars_from_array(...)`: Bandpass **30–300 Hz** (scipy Butterworth, einmalig berechnet) isoliert Bass-Grundtöne; HPSS **margin=8**; `chroma_cqt` mit `fmin=C1`; **Power-Normalisierung** (chroma² dann L2-norm) für scharfe Pitch-Klassen-Peaks; stille Takte (RMS < 2×10⁻⁴) werden übersprungen; `hop_length=256`
- `chroma_shape_type(chroma) -> str`: `"line"` (1–2 Klassen), `"triangle"` (3), `"diamond"` (4), `"pentagon"` (5), `"circle"` (6+)

**Bass-Visualisierung (Timeline):**
- `set_bass_data(data)`: setzt `_bass_data` und triggert `update()`
- `_paint_bass_shapes(p, vl, vr)`: Shapes im Bass-Track — Farbe = Chroma → RGB (Pitch), Form = Pitch-Klassen-Anzahl, Alpha = Rhythmus-Score × 180 + 40 (40 = unregelmäßig … 220 = perfekte 8tel)
- Tooltip `_bass_tip_at(pos)`: zeigt Chroma-Noten + `8tel-Rhythmus: XX %  (präzise/mäßig/unregelmäßig)`

**Sim-Overlay-Modus** (Toggle `⊙ Simulation` in Toolbar, wird nach Sim-Ende automatisch aktiviert):
- `_sim_overlay=True` → JSONL-Probe-Events komplett ausgeblendet (wenn Sim-Events vorhanden)
- Sim-Diamonds: amber = Kick, cyan = Snare (Events-Strip + Kanal-Rows)
- Taktgitter + BPM-Anzeige automatisch berechnet und eingeblendet
- Zoom wird nach Sim auf 80 px/s gesetzt
- `✕ Sim`-Button: löscht alle Sim-Events, BPM, Taktgitter; deaktiviert Overlay

#### OnsetDetector (`detection/beat_detector.py`)

Band-gefilterter ODF auf Sub-Window-Ebene (kein PLL, kein HMM, kein BPM-Tracking):

1. **Frequenzfilter** (Butterworth IIR, scipy, graceful fallback):
   - Kick CH08: Tiefpass 150 Hz — isoliert Kick-Body
   - Snare CH09: Bandpass 800–9000 Hz — verwirft Kick-Bleed
   - Crash CH13+14: Hochpass 8000 Hz — Crashes haben dort deutlich mehr Energie als HiHats

2. **Sub-Window ODF** für Kick/Snare (5.3 ms-Auflösung statt 42.7 ms-Block):
   - Block 2048 Samples → 8 × 256-Sample-Sub-Fenster
   - `peak_odf = max(max(0, rms[n] − rms[n−1]))` — halbrektifizierte erste Ableitung des RMS
   - `_prev_sub_rms` über Blockgrenzen mitgeführt

3. **Dual-Gate** für Kick/Snare: Onset nur wenn BEIDE Bedingungen:
   - `peak_odf > max(median(odf_hist) × factor, ONSET_MIN_ODF)` (adaptiver Median über 50 Blöcke)
   - `mean_rms > abs_rms_min` (absoluter RMS-Boden)

4. **Silence-Aware Warmup** für Kick/Snare:
   - Nach ≥ 12 stillen Blöcken (~0,5 s): erster Spike nach Stille wird unterdrückt
   - Verhindert False Positives beim Neueinsatz des Songs

5. **`_CrashDetector`** (RMS-basiert, kein adaptiver Median):
   - Crash CH13+14: signed L+R Mix `0.5*(OH_L + OH_R)` → Hochpass 8 kHz → RMS
   - `CRASH_RMS_MIN = 0.004` — nach 8kHz-HPF bleiben vom Rohsignal nur ~0.004–0.009 übrig; kein `abs()` vor dem Filter (würde Hochfrequenzanteil zerstören)
   - Cooldown: 0.8 s (erlaubt Crash auf jedem Takt bei 90+ BPM)
   - Erkennte Crashes gehen an `BarTracker.process_crash()` zur Beat-1-Phasen-Korrektur

Parameter:
- Kick: `threshold_factor=3.0`, `abs_rms_min=5e-3`, `cooldown=220 ms`
- Snare: `threshold_factor=2.2`, `abs_rms_min=3e-3`, `cooldown=280 ms`
- Crash: `CRASH_RMS_MIN=0.004`, `cooldown=800 ms`
- `ONSET_MIN_ODF=4e-3`, `SILENCE_BLOCKS=12`, `SUB_WIN=256`

#### BarTracker (`detection/bar_tracker.py`)

Streaming Takt-Tracker — verarbeitet Kick/Snare/Crash-Events inkrementell, kein Lookahead:

**Update-Throttling + Finalisierung**:
- `_UPDATE_EVERY = 8` — `_update()` wird nur alle 8 Kick+Snare-Events aufgerufen (Performance)
- `finalize()` — muss nach dem Onset-Loop aufgerufen werden (z.B. in `SimulatorWorker`), löst ein letztes `_update()` aus und füllt `bar_times` bis zum Segment-Ende auf

**BPM-Schätzung** (`_compute_bpm_from_events`):
- Nur die **letzten 8** kombinierten Kick+Snare-Events (medianer IOI, 60–220 BPM)
- Reagiert schnell auf Tempo-Änderungen; frühe Events beeinflussen BPM nicht mehr

**Anker-Berechnung** — zwei Modi, abhängig von `grundrhythmus`:
- **Mit Grundrhythmus** (`_find_anchor_by_pattern`): Pattern-Matching gegen song-spezifisches Kick/Snare-Muster
- **Ohne Grundrhythmus**: ODF-energie-gewichtetes Phasen-Histogramm über alle Kicks → erste Taktposition (`_find_anchor_by_phase`)
- **Fallback** (kein Grundrhythmus + keine Kicks): Crashes als einziger Anker (Crashes landen fast immer auf Beat 1)

**Dreistufige Phase-Korrektur** (in dieser Reihenfolge, jede Stufe überschreibt die vorherige):
1. **`_snare_phase_correct`** — kombiniertes Kick+Snare-Scoring über 4 Viertel-Offsets.  
   Korrigiert ±1/2/3-Beat-Fehler wenn Snare-Pattern (Beat 2+4) klar erkennbar.
2. **`_energy_beat1_correct`** — vergleicht mittlere Kick-ODF-Energie auf Beat-1-Phase vs. Beat-3-Phase.  
   Beat 1 (Downbeat) wird typischerweise stärker angeschlagen → höhere ODF.  
   Korrigiert +2-Beat-Fehler wenn alternative Phase >5% energiereicher (`avg_alt > avg_curr * 1.05`).
3. **`_crash_beat1_correct`** — Crashes landen fast immer auf Beat 1 (selten Beat 3, nie Beat 2/4).  
   Zählt Crashes bei `phase ≈ 0` für Kandidat A vs. Kandidat B → bevorzugt Kandidat mit mehr Beat-1-Crashes.  
   Überschreibt `_energy_beat1_correct`. Sehr zuverlässig bei Songs mit Crash-Cymbals.

**Grundrhythmus-Metadaten** (in `db/lighting-ai-db.json` pro Song):
```json
"grundrhythmus": {"kick": [0.0, 2.0], "snare": [1.0, 3.0]}
```
Positionen in Viertelschlägen (0.0 = Beat 1, 1.0 = Beat 2 … 3.99 = kurz vor Beat 4).  
Wenn ein Song kein `grundrhythmus` hat, wird Phasen-Histogramm + Crash-Fallback verwendet.

**Diagnostik auf stderr** (bei ≥20 Events / ≥10 Kicks):
- `[BAR] energy_beat1: phase_curr_avg=X phase_alt_avg=Y ratio=Z` — Z>1.05 = Korrektur ausgelöst
- `[BAR] _snare_phase_correct: T → T' (+N Beats, scores=[...])` — welche Korrektur angewendet
- `[BAR] Snare-Positionen in Takten (Beat 2≈1.0, Beat 4≈3.0): [...]` — Qualitätsprüfung
- `[SIM] Crashes: N erkannt (threshold RMS >0.0040)` — Crash-Detektion-Diagnose

#### Overview-Waveform (`mainwindow.py` + `overview.py`)

- Zeigt **mittleren RMS aller `DISPLAY_CHANNELS` (0–13)** als volle Session-Hüllkurve — alle Instrumentenspuren, nicht nur Main L/R Bus
- `PeakWorker` läuft mit `use_rms=True`: speichert ±RMS statt min/max-Peaksamples pro Punkt
- Normalisierung auf 95. Perzentile (`np.percentile(pk_max, 95)`) damit kleine RMS-Werte (0.01–0.1) sichtbar werden
- **Playhead-Synchronisation**: Wird aktualisiert von:
  - `_on_seek()` (Klick in Timeline) — neu hinzugefügt, war vorher fehlend
  - `_on_position()` (Playback-Tick)
  - `_on_overview_seek()` (Klick in Overview selbst)
  - `_on_song_combo_changed()` — reset auf `seg.start_t`

#### AudioProcess (`live/server/audio/audio_process.py`)

- `OnsetDetector` + `BarTracker` laufen im sounddevice-Callback (selber Thread, Lock-geschützt)
- `set_song(bpm, grundrhythmus=None, seg_start_t=None)`: konfiguriert BarTracker bei Songwechsel,
  muss aus dem FastAPI-Event-Loop via `await asyncio.to_thread(audio_process.set_song, ...)` aufgerufen werden
- Kick/Snare/Crash-Events werden per `process_kick/snare/crash(t_ev, energy)` in BarTracker eingespeist
- `_bar_tracker_lock` (threading.Lock) schützt alle BarTracker-Zugriffe
- **Bar-Events in JSONL**: nach jedem Onset-Event werden neue Takte (bt ≤ aktueller Zeitstempel)
  als `{"t": bt, "type": "bar", "bar_num": N, "bpm": B}` in die JSONL geschrieben
  — `_logged_bar_count` verhindert Duplikate; wird beim `set_song()` zurückgesetzt

#### ⚠️ Offene Punkte für nächste Session

1. **Grundrhythmus pflegen**: In der DB-Pflege-App `grundrhythmus`-Feld pro Song einpflegen:
   - Format: `{"kick": [0.0, 2.0], "snare": [1.0, 3.0]}` (Beat-Positionen 0.0–3.99)
   - Ohne grundrhythmus wird Crash-Fallback → Phasen-Histogramm verwendet

2. **select_song in main.py**: Bei Songwechsel über WebSocket (`action=select_song`) muss
   `audio_process.set_song(bpm, grundrhythmus)` aufgerufen werden (noch nicht implementiert).

3. **Chroma für Live-Vergleich nutzen**: `upsert_bar_chroma` speichert Lead-Guitar-Chroma
   aus der Simulation in reference.db. Für den Live-Part/Takt-Abgleich muss noch ein
   Vergleichs-Algorithmus (z.B. Kosinus-Ähnlichkeit) in audio_process.py implementiert werden.

4. **Feldtest Beat-1-Korrektur**: Simulation auf verschiedenen Songs laufen lassen und prüfen:
   - Crash-Detektion: Status-Bar zeigt `★ N Crashes`? Wenn 0 → `CRASH_RMS_MIN` (aktuell 0.004) weiter senken
   - Energy-Korrektur: `[BAR] energy_beat1: ratio=Z` auf stderr — Z > 1.05 = Korrektur greift
   - Taktgitter landet auf Beat 1 (Snare-Positionen ≈ 1.0 und 3.0 beats in Diagnostik)

5. **Koordinatensystem Sim-Events**: Sim-Events verwenden `t_k * pps` ohne Subtraktion von
   `seg.start_t`, JSONL-Events verwenden `(ev.t - seg.start_t) * pps` — potentieller Offset-Bug
   für Segmente die nicht bei WAV-Zeit 0 beginnen. Bisher nicht reproduziert.

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
placeholder
