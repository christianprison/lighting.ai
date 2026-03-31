# Rehearsal Post-Preparation App — Bedienungsanleitung

**Version:** 2026-03 (rev 2)
**Zielgruppe:** Timo (Lichttechniker)
**Plattform:** Linux Mint Steuer-Laptop

---

## Was macht die App?

Die Rehearsal Post-Preparation App dient der **Nachbereitung von Probenaufnahmen**. Sie ermöglicht:

1. **Abhören** der 18-Kanal Probenaufnahmen (Behringer XR18 USB-Recording)
2. **Manuelles Annotieren** von Takt- und Part-Grenzen per Tastendruck
3. **Importieren** der annotierten Takte als Audio-Features in die `reference.db`
4. **Offline-Simulation** der Live-Erkennung zum Optimieren des Algorithmus

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
┌──────────────────────────────────────────────────────────────────────────────┐
│ [Play] [Stop]  [Song-Auswahl ▾]  [Fragmente]  Zoom: [80px/s ▾]             │
│ [Annotieren] ab Takt [1] [Takt B] [Part-Start P] [Fragment F] [Undo U]      │
│ [Speichern] [→ reference.db] [DB-Parts] [▶ Simulation] [✕ Sim]              │
├──────────────────────────────────────────────────────────────────────────────┤
│ Minimap (gesamte Session)                                                    │
├──────────────────────────────────────────────────────────────────────────────┤
│ Zeitlineal                                                                   │
│ Events: amber/grau = Beat | cyan = Snare | violett = sim. Beat/Downbeat     │
│ ANNOT-Strip (oben):   amber = Takt | grün = Part-Start | weiß = Frag.-Start │
│            (unten):   gestrichelt violett = Sim.-Positionsschätzung ~T{n}   │
│            (Rand):    violett = auto-erk. Fragmentgrenze (F2, F3 …)         │
│            (unten):   grün/grau Aktivitätsbalken während Fragment-Erkennung │
│ Mix (Main L+R)                                                               │
│ CH 1  ··· CH 16  (einzelne Kanäle)                                          │
│ ──────────────────────────────────────── Scrollbar                          │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Session laden

1. **Datei → Öffnen** (Ctrl+O) → JSONL-Datei aus `live/data/recordings/` wählen
2. Die App lädt automatisch die passende WAV-Datei (gleicher Name, `.wav`)
3. Song-Auswahl-Dropdown füllt sich mit allen Songs der Session
4. Bestehende Annotationen werden automatisch geladen (falls `*_annotations.json` vorhanden)

**Welche Datei ist die richtige?**
Der Dateiname enthält Datum + Uhrzeit: `2026-03-26_185333_Probe.jsonl` = 26.03.2026 um 18:53:33.

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

### Zoom
| Taste | Funktion |
|-------|----------|
| **+** | Zoom in |
| **-** | Zoom out |
| **0** | Zoom anpassen (Song passt ins Fenster) |
| Zoom-Dropdown | Direkt auf px/s-Wert springen |

### Solo / Mute
- Im Label-Bereich links neben jeder Spur: **M** (Mute) und **S** (Solo)

**XR18 Kanalbelegung:**
- CH 1–16: Instrumenten-Eingänge (CH 9 = Kick, CH 10 = Snare)
- CH 17+18 (Mix): Main L/R

---

## Takt- und Part-Annotationen setzen

### Grundprinzip

**Parts sind keine eigenständigen Objekte** — ein Part entsteht dadurch, dass ein Takt-Marker mit einem Part-Namen versehen wird. Der **P**-Button setzt also immer einen Takt-Marker *und* qualifiziert ihn gleichzeitig als Part-Start.

### Vorbereitung
1. Song im Dropdown auswählen
2. **"Annotieren"**-Button klicken → Button leuchtet **grün** (aktiv)
3. Der ANNOT-Strip erhält eine **amber Oberkante**

### Tastenkürzel im Annotationsmodus

| Taste | Funktion |
|-------|----------|
| **B** | Takt-Marker an Cursor-Position (amber) |
| **P** | Part-Start-Marker — öffnet Klappliste mit Part-Namen aus reference.db (grün) |
| **F** | Fragment-Start-Marker — fragt nach Takt-Nummer (weiß, `→T{n}`) |
| **U** | Letzten Marker rückgängig |
| Rechtsklick im ANNOT-Strip | Nächsten Marker löschen |

### Part-Name Vorschlag (P-Dialog)

Beim Drücken von **P** wird automatisch:
1. Die reference.db nach Parts des aktuellen Songs durchsucht
2. Der Part gesucht, dessen erster Takt der aktuellen Cursor-Position am nächsten liegt
3. Dieser Part in der Klappliste **vorselektiert**

Die Liste ist nicht editierbar — alle möglichen Part-Namen kommen aus der Datenbank.

### Verlassen des Annotationsmodus → Auto-Quantisierung

Wenn der **"Annotieren"**-Button deaktiviert wird, werden alle gesetzten Takt-Marker automatisch auf den nächsten **Beat- oder Snare-Event** in der Aufnahme gesnapped (±0,25 Sekunden Suchfenster).

- **Statusleiste:** `Quantisiert: 47 OK, 2 nicht gefunden (? markiert)`
- Marker, für die kein Beat in Reichweite war, erhalten ein rotes **`?`** oben an der Markerlinie → diese manuell kontrollieren und ggf. per Rechtsklick löschen und neu setzen

### Songs, die mehrfach gespielt wurden

Typisch: ein Song wird 3× gespielt — komplett, dann ab dem Bridge, dann nur der Chorus.

**Schritt 1: Fragmente erkennen**

1. Song auswählen → **"Fragmente"**-Button klicken
2. Die App analysiert alle 16 Instrumenten-Kanäle auf Stille-Lücken (≥ 1,5 s)
3. **Geplänkel-Filter:** Fragmente mit weniger als 10% Schlagzeug-Aktivität *und* weniger als 8 Sekunden Schlagzeug werden verworfen — das verhindert, dass kurze Gitarren-Licks zwischen den Takes als echte Fragmente gezählt werden
4. Ergebnis: `3 Fragmente erkannt — F1: 0:00–1:45 [62%🥁] | F2: 1:52–3:10 [71%🥁] | F3: 3:18–4:30 [58%🥁]`
5. Im ANNOT-Strip erscheinen **violette** Linien `F2`, `F3` … als Orientierung
6. Während der Analyse: grüne/graue Aktivitätsbalken im ANNOT-Strip zeigen live welche Bereiche Instrumente enthalten

**Schritt 2: Fragment-Start-Marker setzen**

1. Cursor an die Stelle, wo das Fragment beginnt
2. **F** drücken → `"Takt-Nummer ab der gezählt wird:"` → z.B. `25`
3. Weißer `→T25`-Marker erscheint
4. Weiter mit **B** annotieren — Zählung läuft ab 25

**Schritt 3: Erstes Fragment**

Das erste Fragment verwendet "ab Takt" im Spinbox-Feld. Für alle weiteren: **F**.

### Aufnahme beginnt nicht bei Takt 1

1. **"DB-Parts"**-Button → Liste aller Parts aus `reference.db`
2. **Doppelklick** auf den entsprechenden Part → "ab Takt"-Feld springt auf den richtigen Wert

---

## Annotationen speichern

**"Speichern"**-Button → schreibt `{session_name}_annotations.json` neben die JSONL-Datei.

Wird automatisch auch beim Import (→ reference.db) gespeichert.

---

## In reference.db importieren

**Einstiegspunkt:** **`→ reference.db`**-Button in der Toolbar (erst aktiv wenn Session geladen).

1. Alle Takte annotieren und "ab Takt"-Offset korrekt setzen
2. **"→ reference.db"**-Button klicken
3. Die App:
   - Speichert Annotationen
   - Liest für jeden Takt das Audio-Segment aus der WAV (Main L/R)
   - Extrahiert Features (Chroma, MFCC, Onset-Stärke, RMS)
   - Schreibt in `reference.db` (neu oder inkrementelles Averaging)
4. Abschlussmeldung: `Import abgeschlossen: X neu, Y gemittelt, Z übersprungen`

**Inkrementelles Averaging:** Bereits bekannte Takte werden gemittelt — die DB verbessert sich mit jeder Probe.

**Übersprungene Takte:** Song-ID unbekannt oder Taktnummer außerhalb des DB-Bereichs.

---

## DB-Parts-Panel

**"DB-Parts"**-Button zeigt alle Parts des aktuellen Songs aus `reference.db`:

```
T  1– 8    (8 Takte)   Intro
T  9–16    (8 Takte)   Verse 1
T 21–28    (8 Takte)   Chorus
...
```

**Doppelklick** → setzt "ab Takt" auf den ersten Takt dieses Parts.

---

## Offline-Simulation der Live-Erkennung

Mit dem **`▶ Simulation`**-Button kann die gesamte Live-Erkennungspipeline offline auf der Aufnahme ausgeführt werden — genauso wie sie im Live-Betrieb laufen würde.

### Was wird simuliert?

Die Simulation führt denselben Code wie `AudioProcess` im Live-Betrieb aus:
1. **BeatDetector (PLL-basiert):** Erkennt Beats und Downbeats aus Kick/Snare/Overheads
2. **AudioHMM:** Schätzt auf jedem Downbeat die Takt-Position per Fingerprint-Matching gegen `reference.db`

Der HMM läuft im **Rehearsal Mode** — der Suchraum ist auf den aktuell gewählten Song eingeschränkt.

### Ergebnis in der Timeline (alles violett)

| Element | Darstellung |
|---------|-------------|
| Simulierter Downbeat | Solide violette Linie im Events-Strip |
| Simulierter Beat | Transparente violette Linie im Events-Strip |
| Positionsschätzung (sicher) | Gestrichelte violette Linie im ANNOT-Strip, `~T25 Chorus` |
| Positionsschätzung (eingefroren/unsicher) | Sehr transparente Linie, kein Label |

### Match-Auswertung

Nach Abschluss vergleicht die App die HMM-Schätzungen gegen die manuellen Annotationen:

`Simulation abgeschlossen: 48 Downbeats, 44 Positionsschätzungen — Takt-Match: 32/48 (67%)`

→ Hier erkennt man sofort, wo der Algorithmus driftet, und kann HMM-Parameter (Sigma-Werte, Konfidenz-Schwelle, Beam-Width) gezielt anpassen.

### Wann ist die Simulation sinnvoll?

- **Nach dem ersten Import:** Prüfen ob die reference.db schon gut genug ist
- **Nach Parameteränderungen:** z.B. nach Anpassen der Sigma-Werte in `hmm.py`
- **Zur Fehlersuche:** Herausfinden warum der Live-Betrieb an bestimmten Stellen driftet

**`✕ Sim`** entfernt alle Simulations-Ergebnisse aus der Timeline.

---

## Fehlerbehebung

### Verzerrte Wiedergabe / Knackser
Die App nutzt sounddevice mit `device="pulse"`. Falls Knackser auftreten:
- `pulseaudio --check` — sicherstellen dass PulseAudio läuft
- App neu starten

### "WAV-Datei nicht gefunden"
WAV-Datei muss im selben Verzeichnis wie die JSONL liegen.

### "reference.db nicht gefunden"
Die App sucht `reference.db` unter `…/live/data/reference.db` (zwei Verzeichnisebenen über der WAV-Datei).

### Import: "0 neu, 0 gemittelt, N übersprungen"
Song-ID oder Taktnummern nicht in `reference.db`. Prüfen:
```bash
sqlite3 reference.db "SELECT song_id, name FROM songs"
```

### Quantisierung: viele `?`-Marker
Keine Beat-Events in der JSONL vorhanden (XR18 war nicht verbunden oder Beat-Detection lief nicht). In diesem Fall die `?`-Marker manuell kontrollieren — sie liegen am gesetzten Tipp-Zeitpunkt, nicht am echten Beat.

### sounddevice nicht gefunden
App über `./start.sh` starten (aktiviert venv `/opt/lighting-venv`).

---

## Technische Referenz

### Tastenkürzel (komplett)

| Taste | Funktion |
|-------|----------|
| Space | Play / Pause |
| B | Takt-Marker (nur im Annotationsmodus) |
| P | Part-Start-Marker (nur im Annotationsmodus) |
| F | Fragment-Start-Marker (nur im Annotationsmodus) |
| U | Letzten Marker rückgängig (nur im Annotationsmodus) |
| + / - | Zoom in/out |
| 0 | Zoom anpassen |
| Rechtsklick ANNOT-Strip | Nächsten Marker löschen |

### Dateistruktur
```
live/data/recordings/
├── 2026-03-26_185333_Probe.jsonl              # Event-Log
├── 2026-03-26_185333_Probe.wav                # 18-Kanal-Aufnahme (48kHz, float32)
└── 2026-03-26_185333_Probe_annotations.json   # Takt-Annotationen (auto-erstellt)
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

- `t`: Sekunden **relativ zum Segment-Start**
- `restart_bar_num`: Fragment-Start — setzt Takt-Zählung zurück

### WAV direkt abhören (Diagnose)
```bash
ffmpeg -ss 387 -i recording.wav -map_channel 0.0.16 -map_channel 0.0.17 -f wav - | aplay
```
