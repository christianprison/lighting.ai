# Übergabe DB-Pflege-App — 7. März 2026

## Aktueller Stand

- **Version:** v0.15.9
- **Branch:** `claude/review-project-docs-2XaRt` (2 Commits ahead of `main`, nicht gemergt)
- **Working Tree:** clean (keine uncommitted changes)
- **Haupt-Dateien:** `js/app.js` (7.921 Zeilen), `css/style.css` (3.338 Zeilen)

---

## Was in dieser Session passiert ist

### Hauptarbeit: Lyrics-Tab komplett neu gebaut (v0.13.6 → v0.15.9)

Der Lyrics-Tab wurde von einem einfachen Textfeld-basierten Editor zu einem **grafischen Marker-Editor** umgebaut. Die Entwicklung verlief über mehrere Iterationen:

#### Phase 1: Quick Insert & Basics (v0.13.6–v0.13.9)
- Quick-Insert-Chips für häufige Lyrics-Bausteine
- Chips als iOS-Keyboard-Toolbar statt Inline
- Wort-Shift-Buttons zum Verschieben von Lyrics zwischen Takten
- Zeilenbasiertes Verteilen statt wortbasiert

#### Phase 2: Lyrics-Tab Umbau (v0.14.0)
- Rohtext-Eingabe oben, Part-Cards unten
- Größere Touch-Targets für iPad
- Keine leeren Takte mehr anzeigen

#### Phase 3: Grafischer Marker-Editor (v0.15.0–v0.15.9)
Der Lyrics-Tab arbeitet jetzt in **drei Phasen:**

1. **Phase `empty`:** Rohtext eingeben/einfügen (Textarea)
2. **Phase `parts`:** Part-Marker auf den Text setzen (per Tap auf Wort-Grenzen)
3. **Phase `bars`:** Takt-Marker innerhalb der Parts setzen

**Kern-Features des Marker-Editors:**
- Wörter werden als einzelne Spans gerendert, Marker werden zwischen Wörtern platziert
- **Drag & Drop** für Part- und Bar-Marker (Touch + Maus)
- **Floating Balloon** zeigt beim Drag den Marker-Namen und die Position
- **Word-Snap:** Cursor springt immer zur linken Wortgrenze (links vom Finger bei Touch)
- **Marker-Prediction:** Bar-Marker werden automatisch gleichmäßig über die Wörter eines Parts verteilt ("Verteilen"-Button)
- **Marker-Rekonstruktion:** Bestehende Lyrics aus der DB werden in Marker zurückübersetzt
- Part-Marker werden amber (`#f0a030`) dargestellt, Bar-Marker cyan (`#38bdf8`)
- "Zurück"-Button in der Bars-Phase kehrt zur Parts-Phase zurück
- "Übernehmen"-Button schreibt die verteilten Lyrics in die DB-Bars

### Lyrics-Editor State-Variablen (app.js, Zeile 34–41)
```javascript
let _lePhase = 'empty';        // 'empty' | 'parts' | 'bars'
let _leWords = [];              // [{text, offset, newlineBefore, emptyLineBefore, isHeader}]
let _lePartMarkers = [];        // [{partId, charOffset, confirmed}]
let _leBarMarkers = [];         // [{partId, barNum, charOffset}]
let _leDrag = null;             // {type:'part'|'bar', idx, currentOffset, wordPositions}
let _leInitSongId = null;       // songId for which markers were initialized
```

### Weitere Änderungen in dieser Session
- **Bars-Phase Zurück-Button** (v0.15.7): Button-Label klarer ("← Parts-Marker")
- **Part-Marker Drag verbessert** (v0.15.8): Drag-Handling für Part-Marker optimiert
- **Word-Snap Cursor** (v0.15.9): Cursor-Position bei Touch-Drag links statt unter dem Finger

---

## Bekannte offene Punkte / Bugs

1. **Lyrics-Übernahme in DB:** Wenn man Marker setzt und "Übernehmen" drückt, werden die Lyrics in die `bars`-Records der DB geschrieben. Es gibt aber noch keinen visuellen Feedback-Mechanismus, der zeigt, welche Bars bereits Lyrics haben.

2. **Instrumental-Parts:** Parts, die als "Instrumental" markiert sind, sollten im Marker-Editor übersprungen oder speziell behandelt werden. Aktuell werden sie wie normale Parts behandelt.

3. **Undo für Marker:** Es gibt kein Undo für einzelne Marker-Platzierungen (nur "Zurück zur Parts-Phase" oder "Alle zurücksetzen").

4. **Part-Playback im Lyrics-Tab:** Audio-Playback funktioniert, aber nur wenn Split-Marker im Audio-Tab vorhanden sind. Die Funktion `stopLyricsPartPlay()` wird beim Tab-Wechsel aufgerufen (Zeile 1037).

5. **Performance bei vielen Wörtern:** Bei Songs mit sehr viel Text (>500 Wörter) kann das Rendering der Word-Spans spürbar langsam werden, weil bei jedem Re-Render der gesamte HTML-Block neu gebaut wird.

---

## Architektur-Übersicht der relevanten Funktionen

### Lyrics-Editor (app.js, ab Zeile ~3994)
| Funktion | Zeile (ca.) | Beschreibung |
|----------|-------------|-------------|
| `leParseRawText()` | 3997 | Rohtext → Word-Tokens parsen |
| `leHasAnyBarLyrics()` | 4055 | Prüft ob Parts schon Bar-Lyrics haben |
| `lePredictBarMarkers()` | 4067 | Automatische Takt-Marker-Verteilung |
| `leReconstructMarkers()` | 4233 | Marker aus bestehenden DB-Lyrics rekonstruieren |
| `renderLyricsTab()` | 4350 | Haupt-Render-Funktion |
| `leRenderMarker()` | 4516 | Einzelnen Marker rendern |
| `leStartPartPhase()` | 4569 | Wechsel in Parts-Phase |
| `leStartBarPhase()` | 4620 | Wechsel in Bars-Phase |
| `leBackToPartPhase()` | 4627 | Zurück zur Parts-Phase |
| `leResetAll()` | 4637 | Alles zurücksetzen |

### Audio-Tab / Waveform (app.js, ab Zeile ~2700)
- Marker-Drag mit Floating Balloon
- Part-Marker (amber) und Bar-Marker (cyan)
- `snapFirstBarsToPartMarkers()` — erster Bar folgt Part-Marker
- `saveMarkersToSong()` — Marker in DB persistieren

---

## Projekt-Konventionen (Kurzfassung)

- **Vanilla JS**, kein Framework, keine Dependencies
- **Version in `js/app.js`** hochsetzen bei jeder Änderung (`APP_VERSION`)
- **Branch-Name muss `DB-Pflege-App` enthalten** laut CLAUDE.md
- **Dark Theme** mit `--green` als Primärakzent
- **Touch-optimiert** (iPad ist primäres Gerät)
- **GitHub API** für Persistenz (Token in localStorage)
- Details im `CLAUDE.md` im Repo-Root

---

## Dateistruktur (relevante Dateien)

```
lighting.ai/
├── CLAUDE.md                      # Projekt-Dokumentation & Regeln
├── index.html                     # Entry Point
├── css/style.css                  # Dark Theme Styles (3.338 Zeilen)
├── js/
│   ├── app.js                     # Haupt-App (7.921 Zeilen, Version v0.15.9)
│   ├── db.js                      # GitHub API Wrapper
│   ├── integrity.js               # DB-Integritätsfunktionen
│   ├── audio-engine.js            # Web Audio API
│   └── utils.js                   # Hilfsfunktionen
├── db/
│   └── lighting-ai-db.json        # Songdatenbank (65+ Songs)
└── audio/                         # Audio-Schnipsel pro Song/Part
```

---

## Git-Status

- `main` ist der Deploy-Branch (GitHub Pages)
- Aktueller Branch `claude/review-project-docs-2XaRt` hat 2 ungemergte Commits:
  - `e60bcef` — Word-Snap Cursor immer links vom Finger
  - `27e37f1` — Part-Marker Drag verbessert (v0.15.8)
- PRs #57–#62 wurden in dieser Session erstellt und gemergt
