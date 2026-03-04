# Übergabedokument: lighting.ai WebApp

## Stand: 2026-03-04

Dieses Dokument dient als Einstiegspunkt für einen neuen Chat, der die WebApp weiterentwickelt. Es beschreibt den aktuellen Zustand, die bekannten Bugs und die nächsten Schritte.

---

## 1. Aktueller Stand

Phase 1 (DB-Pflege-App) ist **funktional komplett**. Alle Meilensteine 1–4 aus CLAUDE.md sind abgehakt. Die App läuft als reine Client-App im Browser und kommuniziert direkt mit der GitHub API.

### Architektur-Überblick

```
index.html              → Single Entry Point, Tab-Router, Modals
css/style.css           → Dark Theme, CSS Grid Layout (2420 Zeilen)
js/app.js               → Gesamte App-Logik (4673 Zeilen, monolithisch)
js/db.js                → GitHub API Wrapper (255 Zeilen)
js/audio-engine.js      → Web Audio API Wrapper (384 Zeilen)
db/lighting-ai-db.json  → Songdatenbank (65+ Songs)
audio/                  → Audio-Schnipsel (MP3, per GitHub API)
```

### Tabs & Features

| Tab | Funktion | Status |
|-----|----------|--------|
| SETLIST | Setlist verwalten, Drag-Reorder, Export | ✅ fertig |
| SONGS (Editor) | Song-Metadaten, Parts-Tabelle, Bar-Editor | ✅ fertig |
| PARTS | Parts & Bars aller Songs, Accent-Grid (16tel) | ✅ fertig |
| LYRICS | Lyrics verteilen (1 Zeile = 1 Takt), Collapse | ✅ fertig |
| TAKTE | Flat-View aller Takte, Lyrics inline editierbar | ✅ fertig |
| AUDIO SPLIT | Tap-to-Split, Waveform, Marker-Drag, MP3-Export | ✅ fertig (mit Bugs) |

---

## 2. Bekannte Bugs & Probleme

### 2.1 🔴 iPad Chrome: Menüzeile verschwindet

**Problem:** Auf dem iPad unter Chrome gerät die Menüzeile (`#header`, 52px) manchmal außer Sicht. Der Header ist nur noch durch kompletten Neuaufbau des Browserfensters wiederherstellbar.

**Technischer Kontext:**
- Header ist kein `position: fixed/sticky`, sondern eine CSS-Grid-Area (`grid-area: header`)
- Layout: `#app` nutzt `grid-template-rows: var(--header-h) 1fr` mit `--header-h: 52px`
- `#app` hat `height: 100vh` — auf iOS/iPadOS ist `100vh` bekanntermaßen problematisch wegen der dynamischen Adressleiste (Safari/Chrome)
- Content-Area (`#content`) hat `overflow-y: auto` — wenn der Viewport sich durch die iOS-Adressleiste verschiebt, kann das Grid-Layout aus dem sichtbaren Bereich rutschen
- Kein `@media`-Query für Touch-Geräte vorhanden
- Kein `resize`-Event-Handler der das Layout korrigiert

**Vermutete Ursache:** Die Kombination aus `100vh` und der dynamischen Adressleiste von iOS Chrome führt dazu, dass das Grid größer wird als der sichtbare Viewport. Scrollt der Content-Bereich, kann der Header aus dem Viewport rutschen, weil das Grid selbst nicht scrollbar ist.

**Lösungsansätze:**
1. `100vh` durch `100dvh` (dynamic viewport height) ersetzen — wird seit iOS 15.4 unterstützt
2. Fallback: `height: calc(100vh - env(safe-area-inset-top) - env(safe-area-inset-bottom))`
3. Alternativ: Header auf `position: sticky; top: 0` umstellen statt Grid-Area
4. `<meta name="viewport">` um `viewport-fit=cover` ergänzen und `env(safe-area-inset-*)` nutzen
5. Event-Handler für `resize` und `visualViewport` API als Absicherung

**Relevante Stellen:**
- `css/style.css:27-31` — `#app` Grid-Definition mit `height: 100vh`
- `css/style.css:71-82` — `#header` Styling (keine position-Eigenschaft)
- `index.html:5` — `<meta name="viewport">`

### 2.2 🔴 Marker-Drag auf Waveform buggy

**Problem:** Das Verschieben von Part- und Bar-Markern im Audio-Split-Tab funktioniert nicht zuverlässig.

**Identifizierte Teilprobleme:**

1. **Tolerance-Bug beim Mitziehen des ersten Bar-Markers (app.js:~1821):**
   ```javascript
   if (Math.abs(barsInPart[0].time - oldTime) < 0.01) {
     barsInPart[0].time = newTime;
   }
   ```
   Die 10ms-Toleranz ist zu knapp. Wenn ein Bar-Marker durch Import oder manuelle Anpassung leicht verschoben ist, wird er beim Drag des Part-Markers nicht mitgezogen → Part und erster Bar laufen auseinander.

2. **Keine Begrenzung beim Drag:**
   - Part-Marker können über andere Part-Marker hinweg gezogen werden
   - Bar-Marker können vor den Start ihres Parts gezogen werden
   - Erst nach dem Loslassen wird per `reassignBarMarkerParts()` neu zugeordnet — während des Drags sieht der User inkonsistente Zustände

3. **Touch-Handling unvollständig:**
   - Kein Multi-Touch-Schutz (zwei Finger können Drag durcheinanderbringen)
   - Auf dem iPad können versehentliche Gesten (z.B. Wischen zum Zurücknavigieren) den Drag-State korrumpieren
   - `_isDragging` wird bei abgebrochenen Touch-Events ggf. nicht zurückgesetzt

4. **Part-Reorder bricht Marker-Zuordnung:**
   - Wenn Parts im Editor per Move-Up/Down umsortiert werden (`app.js:~923-947`), werden nur die `pos`-Werte getauscht
   - `song.split_markers` wird NICHT aktualisiert
   - Ergebnis: Nach dem Umsortieren zeigen die Marker auf die falschen Parts, Audio-Export schreibt Bars in falsche Part-IDs

**Relevante Stellen:**
- `js/app.js:~1713-1924` — Gesamtes Drag-System
- `js/app.js:~1767-1787` — `onWaveformPointerDown()`
- `js/app.js:~1789-1836` — `onWaveformPointerMove()`
- `js/app.js:~1838-1869` — `onWaveformPointerUp()`
- `js/app.js:~1874-1896` — `reassignBarMarkerParts()`, `snapFirstBarsToPartMarkers()`

---

## 3. Nächste Schritte: Daten-Konsistenz

### 3.1 Problem: Abhängigkeiten zwischen Songs, Parts, Bars, Accents

Die aktuelle Datenstruktur hat **implizite Referenzen** die bei CRUD-Operationen manuell konsistent gehalten werden müssen:

```
Song (db.songs[songId])
  └─ Parts (song.parts[partId])        — nested im Song-Objekt
       └─ Bars (db.bars[barId])         — flat, referenziert Part via bar.part_id
            └─ Accents (db.accents[accId]) — flat, referenziert Bar via accent.bar_id
  └─ Split-Markers (song.split_markers)  — referenziert Parts via partIndex (Position!)
```

**Aktuelle Cascade-Delete-Implementierung:**
- Part löschen → Bars löschen → Accents löschen ✅ (implementiert, `app.js:~896-920`)
- "Alle Takte löschen" → Accents löschen → Bars löschen ✅ (implementiert, `app.js:~4175-4205`)
- Song löschen → ❌ **nicht implementiert** (kein UI dafür)

**Probleme:**

1. **Keine Integritätsprüfung beim Laden:** Orphaned Bars/Accents (z.B. nach manuellem JSON-Edit) werden nicht erkannt
2. **Part-Reorder invalidiert Split-Markers:** `partIndex` in Markern ist positionsbasiert, nicht ID-basiert
3. **Part-Duplicate kopiert keine Bars/Accents:** Beim Duplizieren eines Parts werden nur Part-Metadaten kopiert, nicht die zugehörigen Bars und Accents
4. **Kein Song-Delete:** Kann zu verwaisten Daten führen
5. **Bar-Count-Änderung ohne Cleanup:** Wenn `part.bars` von 8 auf 4 reduziert wird, bleiben Bars 5-8 als Waisen in `db.bars`

### 3.2 Vorgeschlagene Neustrukturierung

**Ziel:** Zu jedem Zeitpunkt konsistente Daten — kein manuelles Aufräumen nötig.

**Ansatz 1: Referentielle Integrität als Modul**

Ein neues Modul `js/integrity.js` das:
- **Validierung:** `validateDB(db)` prüft alle Referenzen und meldet Inkonsistenzen
- **Cleanup:** `cleanupOrphans(db)` entfernt verwaiste Records
- **Cascade-Delete:** Zentrale Funktionen `deleteSong(db, songId)`, `deletePart(db, songId, partId)`, `deleteBar(db, barId)` die alle abhängigen Daten aufräumen
- **Cascade-Duplicate:** `duplicatePart(db, songId, partId)` kopiert auch Bars + Accents
- **Part-Reorder:** Aktualisiert auch `split_markers.partIndex` Werte
- **Bar-Count-Sync:** Wenn `part.bars` geändert wird, werden überzählige Bars entfernt

**Ansatz 2: Split-Markers von partIndex auf partId umstellen**

Statt `{time: 5.2, partIndex: 0}` → `{time: 5.2, partId: "5Ij0Ns_P001"}` — macht die Marker unabhängig von der Part-Reihenfolge.

**Empfehlung:** Beide Ansätze kombinieren.

---

## 4. Globaler State & Rendering-Flow

### State-Variablen (js/app.js, Zeile 1-55)

```javascript
// Kern-Daten
let db = null;                    // Gesamte DB im Speicher
let dbSha = null;                 // GitHub SHA für Optimistic Locking
let dirty = false;                // Ungespeicherte Änderungen?
let readOnly = true;              // Ohne Token = read-only

// UI-Navigation
let activeTab = 'editor';        // Aktiver Tab
let selectedSongId = null;       // Ausgewählter Song
let selectedPartId = null;       // Ausgewählter Part
let selectedBarNum = null;       // Ausgewählter Takt

// Audio-Split State
let partMarkers = [];             // [{time, partIndex}]
let barMarkers = [];              // [{time, partIndex}]
let _dragMarker = null;           // Aktiver Drag: {type, index, originalTime}
let _isDragging = false;          // Drag aktiv (nach 3px Threshold)
```

### Rendering

- Kein Virtual DOM — direktes `innerHTML` + Event-Delegation
- `switchTab(tab)` → `renderContent()` → tab-spezifische Render-Funktion
- Jeder Tab hat eigene `render*()` und `handle*Click(e)` / `handle*Change(e)` Funktionen
- Waveform: Canvas-basiert (`drawWaveform()`)

### Dirty-State-Management

- `markDirty()` → setzt `dirty = true`, zeigt "UNSAVED" Badge
- `handleSave()` → `saveDB()` via GitHub API, setzt `dirty = false`
- Auto-Save: **nicht implementiert** — nur manuell per Ctrl+S oder Save-Button

---

## 5. Wichtige Code-Stellen (Referenz)

| Bereich | Datei | Zeilen (ca.) |
|---------|-------|-------------|
| Global State | `js/app.js` | 1-55 |
| ID-Generierung | `js/app.js` | 359-376 |
| Part CRUD (Add/Del/Move/Dup) | `js/app.js` | 870-960 |
| Bar CRUD | `js/app.js` | 960-1050 |
| Accent Grid | `js/app.js` | 1050-1150 |
| Waveform Drawing | `js/app.js` | 1550-1710 |
| Marker Drag System | `js/app.js` | 1713-1924 |
| Audio Export | `js/app.js` | 2050-2250 |
| Part-Duration Berechnung | `js/app.js` | 330-355 |
| Lyrics Tab | `js/app.js` | 3500-3800 |
| Setlist Tab | `js/app.js` | 3900-4170 |
| Takte Tab (Alle Takte löschen) | `js/app.js` | 4175-4205 |
| Save/Load | `js/app.js` | 4430-4520 |
| GitHub API | `js/db.js` | komplett |
| Audio Playback/Export | `js/audio-engine.js` | komplett |
| Grid Layout & Header | `css/style.css` | 27-82 |
| Sidebar | `css/style.css` | 216-275 |
| Content Area | `css/style.css` | 276-312 |

---

## 6. Priorisierte Aufgaben für den neuen Chat

### Prio 1: iPad Header-Bug fixen
1. `100vh` → `100dvh` mit Fallback
2. `viewport-fit=cover` + `safe-area-inset` testen
3. Ggf. Header auf `position: sticky` umstellen
4. Testen: Chrome iPad, Safari iPad, Desktop

### Prio 2: Marker-Drag stabilisieren
1. Tolerance von 0.01s auf 0.05s erhöhen (oder dynamisch: prozentual zur Bar-Dauer)
2. Drag-Begrenzung: Marker dürfen nicht über Nachbar-Marker hinaus
3. Touch-Events absichern: `touchcancel` Handler, Multi-Touch ignorieren
4. Part-Reorder → Split-Markers mit-aktualisieren

### Prio 3: Daten-Konsistenz Refactoring
1. `js/integrity.js` Modul erstellen
2. Split-Markers auf `partId` statt `partIndex` umstellen (Migration!)
3. Zentrale Delete/Duplicate-Funktionen mit Cascade
4. `validateDB()` beim Laden ausführen, Orphans loggen/bereinigen
5. Bar-Count-Änderungen mit Cleanup

---

## 7. Technische Rahmenbedingungen

- **Kein Framework, kein Build-Step** — Vanilla ES6+ JS, ES Modules
- **Keine externen Dependencies** außer Google Fonts (Sora, DM Mono) und lamejs (CDN, MP3-Encoding)
- **GitHub API** für Persistenz (Token im localStorage)
- **Web Audio API** für alles Audio-bezogene
- **Touch-optimiert:** Tap-Targets ≥ 36px
- **Dark Theme:** Farben siehe CSS-Variablen in CLAUDE.md
- Hauptdatei `js/app.js` ist **4673 Zeilen** — monolithisch, aber funktioniert. Modularisierung ist wünschenswert, aber kein Blocker.
