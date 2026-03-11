# Refactoring: Parts-Konzept entfernen (v1.6.0)

**Datum:** 2026-03-11
**Branch:** `claude/remove-parts-concept-k6oDg`

## Motivation

Das Parts-Konzept (Song → Parts → Bars → Accents) hat sich in der Praxis als unnötige Komplexitätsschicht erwiesen. Die Songstruktur wird jetzt direkt über Takte abgebildet:

**Vorher:** Song → Parts → Bars → Accents
**Nachher:** Song → Bars → Accents

## Zusammenfassung

- ~2.600 Zeilen Code entfernt (app.js: 9.130 → 6.531 Zeilen)
- Datenmodell vereinfacht: Bars referenzieren Songs direkt (`song_id` statt `part_id`)
- Parts-Backup in `db/parts_backup.json` für spätere Rekonstruktion gesichert
- APP_VERSION: v1.5.0 → v1.6.0

## Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `js/app.js` | Hauptrefactoring: Parts-Tab, Part Waveform Editor, Part-Tap etc. entfernt |
| `js/integrity.js` | Komplett neu geschrieben (Song-basierte Validierung statt Part-basiert) |
| `index.html` | Parts-Tab-Button, Part-Waveform-Editor-Modal entfernt, Hilfe aktualisiert |
| `db/lighting-ai-db.json` | Datenbank migriert (parts entfernt, total_bars hinzugefügt, bars auf song_id) |
| `db/parts_backup.json` | **Neu** — Backup aller Parts-Daten |

## Datenmodell-Änderungen

### Songs

```diff
  "5Ij0Ns": {
    "name": "Animal",
    "artist": "Neon Trees",
    "bpm": 164,
-   "parts": {
-     "5Ij0Ns_P001": { "pos": 1, "name": "Intro", "bars": 8, ... },
-     "5Ij0Ns_P002": { "pos": 2, "name": "Verse 1", "bars": 16, ... }
-   }
+   "total_bars": 24
  }
```

### Bars

```diff
  "B001": {
-   "part_id": "5Ij0Ns_P003",
+   "song_id": "5Ij0Ns",
    "bar_num": 1,
    "lyrics": "Here we go again..."
  }
```

### Split-Marker

```diff
  "split_markers": {
    "markers": [
-     { "time": 0.5, "partId": "5Ij0Ns_P001", "partStart": true },
-     { "time": 2.1, "partId": "5Ij0Ns_P001", "partStart": false }
+     { "time": 0.5 },
+     { "time": 2.1 }
    ]
  }
```

## UI-Änderungen

### Entfernte Elemente

1. **Parts-Tab** — komplett aus der Tab-Leiste entfernt
2. **Part Waveform Editor Modal** — HTML + JS (~600 Zeilen) entfernt
3. **PART TAP Button** im Audio-Split-Tab
4. **Part-Marker** (amber) in der Waveform-Darstellung
5. **Part-Spalte** im Takte-Tab
6. **Part-Gruppierung** im Accents-Tab (jetzt flache Bar-Liste)
7. **Part-Labels** (orange) im Lyrics-Tab
8. **Part-Abspielfunktion** im Lyrics-Tab
9. **Part hoch-/runterschieben Buttons** in der Toolbar

### Vereinfachte Elemente

| Bereich | Vorher | Nachher |
|---------|--------|---------|
| Audio Split | PART TAP + BAR TAP + UNDO + PARTS verteilen + DEL PARTS + DEL BARS | BAR TAP + UNDO + SNAP + DEL BARS |
| Lyrics | Part-Schritt → Bar-Schritt (2 Phasen) | Direkte Bar-Marker-Verteilung (1 Phase) |
| Accents | Parts aufklappen → Bar auswählen | Direkt Bar auswählen |
| Takte-Tab | Part-Spalte + Taktnummer innerhalb Part | Taktnummer im Song |
| Waveform | Amber Part-Marker + Cyan Bar-Marker | Nur Cyan Bar-Marker |

## Entfernte Funktionen (js/app.js)

### Komplett gelöscht

- `handlePartSelect`, `handlePartAction`, `handlePartPlay`
- `handlePartTap`, `handleDistributeParts`, `handleDeleteAllParts`
- `getPartIdForTime`, `getPartIndexForTime`, `getPartMarkers`, `getBarOnlyMarkers`
- `getPartStartTime`, `getPartEndTime`, `getBarMarkersForPart`
- `removeSplitMarkersForPart`, `getAllPartsFlat`
- `leHandlePartTap`, `_leStartHighlightLoop`, `_leHighlightTick`, `_leStopHighlight`
- `leRefreshPartPlayState`, `stopLyricsPartPlay`
- `buildAccentsPartsList`, `countPartAccents`
- `renderPartsTab`, `buildPartsTabTable`, `renderPartsTabBarSection`
- `buildPartsTabBarEditor`, `handlePartsTabClick`, `handlePartsTabChange`
- `handlePartsTabAction`, `handlePartsTabAccentToggle`
- `drawMiniWaveformMarkers`
- Gesamter Part Waveform Editor (`openPartWaveEditor`, `closePartWaveEditor`, `_pwDrawWaveform`, `_pwUpdateUI`, `_pwTogglePlay`, `_pwStopPlay`, `_pwNudge`, `_pwTapBar`, `_pwWaveformClick`, `_pwWaveformPointerDown`, `_pwWaveformHover`, `initPartWaveEditor` etc.)

### Umgeschrieben (ohne Parts-Referenzen)

- `handleBarTap` — setzt nur noch `{ time }` Marker
- `saveMarkersToSong` — speichert `song.total_bars` statt Part-bezogener Bars
- `restoreMarkersFromSong` — liest vereinfachte Marker
- `drawWaveform` — nur noch Cyan Bar-Marker
- `buildTapButtons` — nur BAR TAP, UNDO, SNAP, DEL BARS
- `renderAccentsTab` — flache Bar-Liste
- `buildAccentsBarList` — ersetzt `buildAccentsPartsList`
- `getAllBarsFlat` — nutzt `song.total_bars` und `getBarsForSong()`
- `buildTakteTabTable` — ohne Part-Spalte
- `handleAudioExport` — iteriert Marker direkt
- `handleDeleteAllBarMarkers` — löscht alle Marker, setzt `total_bars = 0`
- `leBuildBlocks` — nur Bar- und Word-Blöcke (keine Part-Blöcke)
- `leDistributeText` — verteilt auf `song.total_bars` Bars direkt
- `leSaveLyrics` — speichert per `selectedSongId`
- `leIsValidDrop` — Bar-Constraint ohne Part-Grenzen
- `leClearWords` — löscht Lyrics per `song_id`
- `getBarTimeRange` — einfacher Index-Lookup in Markern
- `handleDeleteAllBars` — setzt `total_bars = 0`, leert Marker
- Debug-Output — vereinfachter Bars-Vergleich

## integrity.js — Komplett neu

```javascript
// Vorher: validateDB prüfte bars → parts Referenzen
// Nachher: validateDB prüft bars → songs Referenzen

export function validateDB(db) {
  // Prüft: bar.song_id existiert in db.songs
  // Prüft: accent.bar_id existiert in db.bars
  // Prüft: setlist song_ids existieren
}

export function deleteSong(db, songId) {
  // Löscht Bars per song_id, deren Accents, Setlist-Referenzen
}

export function syncBarCount(db, songId, declaredCount) {
  // Synchronisiert Bars per song_id
}
```

## Parts-Backup

Die Datei `db/parts_backup.json` enthält:

- **songs**: Alle Songs mit ihren originalen `parts`-Objekten
- **bar_to_part_mapping**: Zuordnung jedes Bars zu seinem Part (`bar_id → part_id`)
- **split_markers_with_parts**: Original-Marker mit `partId` und `partStart` Feldern
- **accent_to_bar_to_part**: Accent → Bar → Part Zuordnungskette

Damit können die Parts-Daten bei Bedarf rekonstruiert werden.

## Bekannte Einschränkungen

- **QLC+ Chaser Import**: Die Chaser-Zuordnung war an Parts gekoppelt und ist jetzt funktional deaktiviert (zeigt "Keine Parts vorhanden"). Kann in einer zukünftigen Session auf Bar-Ebene reimplementiert werden.
- **QLC Parts Import (Drag & Drop)**: Ebenfalls deaktiviert, da es Parts als Ziel benötigte.

## Migration

Die Migration der bestehenden Datenbank wurde automatisch durchgeführt:

1. 52 Songs: `parts`-Objekte entfernt, `total_bars` aus Summe der Part-Bars berechnet
2. 674 Bars: `part_id` → `song_id` konvertiert (Song-ID aus Part-ID-Präfix extrahiert)
3. Split-Marker: `partId` und `partStart` Felder entfernt, nur `{ time }` behalten
