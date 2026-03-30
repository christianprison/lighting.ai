# Rehearsal Post-Preparation App — Bedienungsanleitung

**Version:** 2026-03
**Zielgruppe:** Timo (Lichttechniker)
**Plattform:** Linux Mint Steuer-Laptop

---

## Was macht die App?

Die Rehearsal Post-Preparation App dient der **Nachbereitung von Probenaufnahmen**. Sie ermöglicht:

1. **Abhören** der 18-Kanal Probenaufnahmen (Behringer XR18 USB-Recording)
2. **Manuelles Annotieren** von Takt- und Part-Grenzen per Tastendruck
3. **Importieren** der annotierten Takte als Audio-Features in die `reference.db`

Die in die `reference.db` importierten Daten verbessern die automatische Takt- und Part-Erkennung im Live-Betrieb.

---

## Starten

```bash
cd /home/thepact/git/lighting.ai_neu/live/rehearsal_review
./start.sh
```

Optional: Session direkt übergeben:
```bash
./start.sh /home/thepact/git/lighting.ai_neu/live/data/recordings/2026-03-26_185333_Probe.jsonl
```

---

## Oberfläche

```
┌─────────────────────────────────────────────────────────────────────┐
│ [Play] [Stop]  [Song-Auswahl ▾]  [Fragmente]  Zoom: [80px/s ▾]   │
│ [Annotieren] ab Takt [1] [Takt B] [Part-Start P] [Fragment F]      │
│ [Undo U] [Speichern] [→ reference.db] [DB-Parts]                   │
├─────────────────────────────────────────────────────────────────────┤
│ Minimap (gesamte Session)                                           │
├─────────────────────────────────────────────────────────────────────┤
│ Zeitlineal                                                          │
│ Events (Beats, Positionen, Song-Wechsel)                            │
│ ANNOT-Strip: amber = Takt | grün = Part-Start | weiß = Fragment-Start│
│              violett = auto-erkannte Fragmentgrenze (F2, F3 …)      │
│ Mix (Main L+R)                                                      │
│ CH 1  ··· CH 16  (einzelne Kanäle)                                 │
│ ─────────────────────────────────── Scrollbar                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Session laden

1. **Datei → Öffnen** (Ctrl+O) → JSONL-Datei aus `live/data/recordings/` wählen
2. Die App lädt automatisch die passende WAV-Datei (gleicher Name, `.wav`)
3. Song-Auswahl-Dropdown füllt sich mit allen Songs der Session
4. Bestehende Annotationen werden automatisch geladen (falls `*_annotations.json` vorhanden)

**Welche Datei ist die richtige?**
Der Dateiname enthält Datum + Uhrzeit: `2026-03-26_185333_Probe.jsonl` = 26.03.2026 um 18:53:33.
Der erste Event in der JSONL gibt unter `"wav"` den zugehörigen WAV-Namen an:
```bash
head -1 /pfad/zur/session.jsonl
```

---

## Aufnahme abhören

### Transport
| Taste / Klick | Funktion |
|---------------|----------|
| **Space** | Play / Pause |
| **Stop**-Button | Zurück zum Anfang |
| Klick auf Timeline | Zu dieser Position springen |
| Klick auf Minimap | Grob zu einem Song-Abschnitt springen |

### Song wählen
- Dropdown oben: Song auswählen → Timeline zeigt nur den Abschnitt dieses Songs
- Die Wiedergabe startet am Song-Anfang

### Zoom
| Taste | Funktion |
|-------|----------|
| **+** | Zoom in (mehr Details) |
| **-** | Zoom out (mehr Überblick) |
| **0** | Zoom anpassen (Song passt ins Fenster) |
| Zoom-Dropdown | Direkt auf px/s-Wert springen |

Zoom-Bereich: 10 px/s (Überblick) bis 40960 px/s (Sample-genaue Ansicht).

### Solo / Mute (einzelne Kanäle)
- Im Label-Bereich links neben jeder Spur: **M** (Mute) und **S** (Solo)
- **S** klicken → nur dieser Kanal hörbar
- **M** klicken → dieser Kanal stumm
- Erneut klicken → zurücksetzen

**XR18 Kanalbelegung:**
- CH 1–16: Instrumenten-Eingänge (je nach Aufnahme-Setup)
- CH 17+18 (Mix): Main L/R — Standard-Hörkanal

---

## Takt- und Part-Annotationen setzen

### Vorbereitung
1. Song im Dropdown auswählen
2. **"Annotieren"**-Button klicken → Button leuchtet **grün** (aktiv)
3. Der ANNOT-Strip (zwischen Events und Waveform) erhält eine **amber Oberkante**

### Arbeitsablauf

**Empfohlene Methode:**
1. Song einmal komplett anhören, um die Struktur zu verstehen
2. Nochmal von vorne — jetzt bei jeder Taktgrenze **B** drücken

**B — Takt-Marker:**
- Drückt man **B** während der Wiedergabe → amber Linie erscheint an der aktuellen Cursor-Position
- Marker werden automatisch nummeriert: 1, 2, 3 …
- In der Timeline sichtbar als amber Linien mit Taktnummer

**P — Part-Start:**
- Drückt man **P** → Dialog fragt nach dem Part-Namen (z.B. "Intro", "Verse 1", "Chorus")
- Part-Start erscheint als **grüne** Linie (mit Name)
- Setzt gleichzeitig einen Takt-Marker (P = B + Part-Name)

**F — Fragment-Start:**
- Drückt man **F** → Dialog fragt nach der Takt-Nummer, ab der gezählt werden soll
- Fragment-Start erscheint als **weiße, breitere** Linie mit Label `→T25` (= "ab jetzt Takt 25")
- Alle nachfolgenden B-Marker zählen ab dieser Nummer weiter
- Verwenden wenn der Song innerhalb der Aufnahme mehrfach gespielt wurde (jedes Mal von einer anderen Stelle)

**U — Undo:**
- Entfernt den zuletzt gesetzten Marker (rückwärts durch die Liste)

**Rechtsklick im ANNOT-Strip:**
- Löscht den Marker, der der Klickposition am nächsten liegt (max. 1 Sekunde Abstand)

### Songs, die mehrfach (ab unterschiedlichen Stellen) gespielt wurden

Typischer Probenablauf: Ein Song wird 3× gespielt — einmal komplett, dann ab dem Bridge, dann nochmal der Chorus. Das ergibt **3 Fragmente** innerhalb desselben Song-Segments.

**Schritt 1: Fragmente automatisch erkennen**

1. Song im Dropdown auswählen
2. **"Fragmente"**-Button klicken → App analysiert alle 16 Instrumenten-Kanäle auf Stille-Lücken (≥ 1,5 Sekunden)
3. Ergebnis in der Statuszeile: `3 Fragmente erkannt — F1: 0:00–1:45 | F2: 1:52–3:10 | F3: 3:18–4:30`
4. Im ANNOT-Strip erscheinen **violette** vertikale Linien mit `F2`, `F3` … als Orientierungshilfe

**Schritt 2: Fragment-Start-Marker setzen**

An jeder Fragmentgrenze (wo der Song von vorne/von einer anderen Stelle startet):

1. Cursor an die Stelle fahren, wo das neue Fragment beginnt (Klick auf Timeline oder Wiedergabe)
2. **F** drücken → Dialog: "Takt-Nummer ab der gezählt wird:" → z.B. `25` eingeben
3. Weißer `→T25`-Marker erscheint
4. Danach mit **B** normal weiter-annotieren — Zählung beginnt bei 25, 26, 27 …

**Schritt 3: Erstes Fragment**

Das erste Fragment nutzt das globale "ab Takt"-Feld (wie gewohnt). Für alle weiteren Fragmente die **F**-Taste verwenden.

### Aufnahme beginnt nicht bei Takt 1 (ganzer Song)

Wenn die gesamte Aufnahme beim Chorus (Takt 25) gestartet wurde (= nur ein Fragment):

1. **"DB-Parts"**-Button klicken → Liste aller Parts aus `reference.db`
   Zeigt z.B.: `T 25–32  (8 Takte)   Chorus`
2. **Doppelklick** auf den entsprechenden Part → "ab Takt"-Feld springt auf 25
3. Jetzt werden die Marker als Takt 25, 26, 27 … nummeriert (statt 1, 2, 3)

Alternativ: "ab Takt"-Feld manuell auf den ersten DB-Takt der Aufnahme setzen.

### Marker nachträglich korrigieren

Marker können **nicht** per Drag verschoben werden — das ist bewusst, um Versehen zu vermeiden. Vorgehen bei falschem Marker:
1. Wiedergabe bis kurz vor den falschen Marker
2. **Rechtsklick** auf den Marker im ANNOT-Strip → löschen
3. An der richtigen Stelle **B** drücken

---

## Annotationen speichern

**"Speichern"**-Button → schreibt `{session_name}_annotations.json` neben die JSONL-Datei.

Wird automatisch auch beim Import (→ reference.db) gespeichert.

Die Annotationen bleiben beim nächsten Öffnen der Session erhalten.

---

## In reference.db importieren

Sind alle Takte annotiert und der "ab Takt"-Offset korrekt gesetzt:

1. **"→ reference.db"**-Button klicken
2. Die App:
   - Speichert Annotationen
   - Liest für jeden annotierten Takt das Audio-Segment aus der WAV (Main L/R)
   - Extrahiert Features (Chroma, MFCC, Onset-Stärke, RMS)
   - Trägt sie in `reference.db` ein (neuer Eintrag oder inkrementelles Averaging)
3. Fortschritt erscheint in der Statuszeile unten
4. Abschlussmeldung: "X neu, Y gemittelt, Z übersprungen"

**Inkrementelles Averaging:** Wenn derselbe Takt bereits aus einem früheren Import vorhanden ist, wird der Mittelwert gebildet — die reference.db verbessert sich mit jeder annotierten Probe.

**Übersprungene Takte:** Takte, für die kein Eintrag in `reference.db.bars` existiert, werden übersprungen. Das passiert wenn ein Song noch nicht in der DB angelegt ist oder die Taktnummer außerhalb des bekannten Bereichs liegt.

---

## DB-Parts-Panel

**"DB-Parts"**-Button öffnet einen Dialog mit allen Parts des aktuellen Songs aus `reference.db`:

```
T  1– 8    (8 Takte)   Intro
T  9–16    (8 Takte)   Verse 1
T 17–20    (4 Takte)   Pre-Chorus
T 21–28    (8 Takte)   Chorus
...
```

**Doppelklick** auf einen Eintrag → setzt "ab Takt" auf den ersten Takt dieses Parts.

---

## Fehlerbehebung

### Verzerrte Wiedergabe / Knackser
Die App nutzt sounddevice mit `device="pulse"`. Falls trotzdem Knackser auftreten:
- Sicherstellen dass PulseAudio läuft: `pulseaudio --check`
- App neu starten

### "WAV-Datei nicht gefunden"
Der JSONL-Header verweist auf eine WAV-Datei, die nicht im selben Verzeichnis liegt.
Lösung: WAV-Datei in dasselbe Verzeichnis wie die JSONL kopieren.

### "reference.db nicht gefunden" beim DB-Parts / Import
Die App sucht `reference.db` unter `live/data/reference.db` (zwei Verzeichnisse über der WAV-Datei).
Sicherstellen dass der Pfad `…/live/data/reference.db` existiert.

### Import: "0 neu, 0 gemittelt, N übersprungen"
Alle Takte wurden übersprungen, weil die Song-ID oder Taktnummern nicht in der `reference.db` vorhanden sind. Lösung:
1. Prüfen ob der Song in der reference.db angelegt ist (mit `sqlite3 reference.db "SELECT * FROM songs"`)
2. "ab Takt"-Offset korrekt setzen

### sounddevice nicht gefunden beim manuellen Python-Aufruf
Die App muss über `./start.sh` gestartet werden (aktiviert venv `/opt/lighting-venv`).
Für direkte Python-Befehle: `/opt/lighting-venv/bin/python3 ...`

---

## Technische Referenz

### Dateistruktur
```
live/data/recordings/
├── 2026-03-26_185333_Probe.jsonl        # Event-Log
├── 2026-03-26_185333_Probe.wav          # 18-Kanal-Aufnahme (48kHz, float32)
└── 2026-03-26_185333_Probe_annotations.json  # Takt-Annotationen (auto-erstellt)
```

### Annotation JSON-Format

**Einfaches Beispiel (ein Fragment, komplett ab Takt 1):**
```json
{
  "song_id_XYZ": {
    "song_id": "song_id_XYZ",
    "song_name": "Animal",
    "segment_start_t": 387.4,
    "start_bar_num": 1,
    "markers": [
      {"t": 0.0,   "bar_num": 1, "part_name": "Intro"},
      {"t": 1.832, "bar_num": 2, "part_name": ""},
      {"t": 3.664, "bar_num": 3, "part_name": ""}
    ]
  }
}
```

**Beispiel mit mehreren Fragmenten (F1 ab T1, F2 ab T25, F3 ab T17):**
```json
{
  "song_id_XYZ": {
    "song_id": "song_id_XYZ",
    "song_name": "Animal",
    "segment_start_t": 387.4,
    "start_bar_num": 1,
    "markers": [
      {"t": 0.0,   "bar_num":  1, "part_name": "Intro"},
      {"t": 1.832, "bar_num":  2, "part_name": ""},
      {"t": 110.4, "bar_num": 25, "part_name": "Chorus", "restart_bar_num": 25},
      {"t": 112.2, "bar_num": 26, "part_name": ""},
      {"t": 200.0, "bar_num": 17, "part_name": "Bridge", "restart_bar_num": 17},
      {"t": 201.8, "bar_num": 18, "part_name": ""}
    ]
  }
}
```

- `segment_start_t`: WAV-Offset in Sekunden (wann fängt dieser Song in der Aufnahme an)
- `start_bar_num`: Erster Takt des **ersten Fragments** = welche DB-Taktnummer
- `t`: Sekunden **relativ zum Segment-Start** (nicht zum WAV-Anfang)
- `restart_bar_num` *(optional)*: Fragment-Start-Marker — setzt die Takt-Zählung hier zurück

### WAV direkt abhören (ohne App, für Diagnose)
```bash
ffmpeg -ss 387 -i recording.wav -map_channel 0.0.16 -map_channel 0.0.17 -f wav - | aplay
```
(387 Sekunden = Zeitpunkt im WAV; Kanal 16+17 = Main L/R, 0-basiert)
