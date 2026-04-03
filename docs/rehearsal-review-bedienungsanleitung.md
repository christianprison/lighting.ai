# Rehearsal Post-Preparation App — Bedienungsanleitung

**Version:** 2026-04 (rev 3)
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
│ Events-Strip: amber = Beat | cyan = Snare | grün ◆ = Downbeat               │
│   Im Sim-Overlay: orig. abgedunkelt + Sim ◆ (grün/amber/cyan) überlagert   │
│ ANNOT-Strip (oben):   amber = Takt | grün = Part-Start | weiß = Frag.-Start │
│            (unten):   cyan gestrichelt = HMM-Positionsschätzung ~T{n}       │
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

Mit dem **`▶ Simulation`**-Button wird die gesamte Live-Erkennungspipeline **offline** auf der Aufnahme ausgeführt — genauso wie sie im Live-Betrieb laufen würde, aber so schnell wie möglich (kein Echtzeit-Throttling).

### Was wird simuliert?

Dieselben Algorithmen wie `AudioProcess` im Live-Betrieb:

1. **BeatDetector (PLL-basiert):** Erkennt Beats, Downbeats und Snares aus Kick (CH09) / Snare (CH10) / Overheads (CH14/15). Seit April 2026 mit **Sub-Block-RMS**: Kick/Snare-Transienten (5–15 ms) werden auch bei Block-Grenzen zuverlässig erkannt.
2. **AudioHMM** *(optional, HMM-Toggle)*: Schätzt auf jedem Downbeat die Takt-Position per Fingerprint-Matching gegen `reference.db`. Läuft im **Rehearsal Mode** — Suchraum nur auf den aktuellen Song eingeschränkt. Nutzt **Zeit-Prior**: aus verstrichener Zeit + BPM wird der erwartete Takt berechnet (hilft bei harmonisch monotonen Songs wie „Dancing with myself").

### Ablauf

1. Song im Dropdown auswählen
2. **`▶ Simulation`** klicken → Fortschrittsbalken läuft
3. Simulation schreibt eine JSONL-Datei (`{session}_sim_{song}_{Zeit}.jsonl`) neben die Aufnahme
4. Nach Abschluss erscheinen die Ergebnisse **direkt in der Timeline**
5. Der **`⊙ Simulation`**-Button wird automatisch aktiviert (Overlay-Modus)

### Sim-Overlay-Modus

Im Overlay-Modus (`⊙ Simulation` = grün/aktiv) zeigt die Timeline:

**Events-Strip** (schmaler Streifen oben):
- Originale Probe-Events: stark abgedunkelt (25% Opacity)
- Sim-Diamonds: **grün** = Downbeat ◆, **amber** = Kick-Beat ◆, **cyan** = Snare ◆ (oben)

**Kanal-Rows** — im Overlay überlagert:
| Kanal | Original (abgedunkelt) | Simulation (voll sichtbar) |
|-------|------------------------|----------------------------|
| **OH L+R** | alle Beats (amber/rot) | alle Sim-Beats (amber = Beat, grün = Downbeat) |
| **Snare** | erkannte Snares (cyan) | Sim-Snares (cyan ◆) |
| **Kick** | kick-getriggerte Beats (amber/rot) | Sim-Kicks: amber = Kick, grün = Kick+Downbeat |

> **Lesehinweis Kick-Reihe:** Amber = Kick erkannt (beliebiger Beat), Rot/Grün = dieser Kick war gleichzeitig ein Downbeat (Takt 1). Die Dichte der Diamonds zeigt direkt wie zuverlässig der Kick erkannt wird.

**ANNOT-Strip** (Takt-Annotations-Streifen):
- Manuelle Annotationen (amber/grün/weiß) bleiben sichtbar
- HMM-Schätzungen (nur wenn HMM aktiv): `~T{n} Part` als cyan Linie, sehr transparent = eingefroren

### Overlay ein-/ausschalten

- **`⊙ Simulation`**-Button klicken → wechselt zwischen Sim-Overlay und Normal-Ansicht
- Normal-Ansicht zeigt nur die originalen Probe-Events (volle Sättigung)
- Overlay bleibt bis **`✕ Sim`** aktiv, auch beim Wechsel des Songs

### Ergebnis interpretieren

**Kick-Erkennung beurteilen:**
- Dichtes Muster in der Kick-Reihe = Kick wird gut erkannt
- Lücken = Transient lag an Block-Grenze oder unter Schwelle → ggf. `threshold_factor` in `beat_detector.py` senken

**BPM-Drift beurteilen:**
- Downbeats (grün) sollten gleichmäßig verteilt sein
- Driftet der Abstand → PLL hat Probleme → BPM aus DB prüfen

**HMM-Taktposition beurteilen** *(nur wenn HMM aktiv)*:
- `~T{n}` Labels im ANNOT-Strip mit manuellen Markern vergleichen
- Statuszeile zeigt Match-Quote: `Simulation: 48 Downbeats — Takt-Match: 32/48 (67%)`
- Bei schlechten Ergebnissen: zuerst mehr Probenaufnahmen importieren (`→ reference.db`)

### Wann ist die Simulation sinnvoll?

- **Nach dem ersten Import:** Prüfen ob die reference.db schon gut genug ist
- **Nach Parameteränderungen:** z.B. Sigma-Werte in `hmm.py`, Threshold in `beat_detector.py`
- **Zur Fehlersuche:** Herausfinden warum bestimmte Songs schlechter erkannt werden
- **Kick/Snare-Diagnose:** Sehen wo Transienten übersehen werden

**`✕ Sim`** entfernt alle Simulations-Ergebnisse aus der Timeline und deaktiviert den Overlay.

### Sim-JSONL-Datei

Die erzeugte Datei kann auch direkt analysiert werden:
```bash
# Alle Downbeats ausgeben
grep '"is_downbeat": true' *_sim_*.jsonl | head -20

# Vox-RMS-Verlauf (Gesangsenergie auf CH01 Pete Vox)
grep '"type": "beat"' *_sim_*.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    d = json.loads(line)
    print(f\"{d['t']:6.2f}s  vox_rms={d['data'].get('vox_rms', 0):.4f}\")
"
```

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

### Toolbar-Buttons Übersicht

| Button | Funktion |
|--------|----------|
| **Play / Stop** | Transport |
| **Song-Dropdown** | Song-Segment wechseln |
| **Fragmente** | Fragment-Erkennung für aktuellen Song starten |
| **Annotieren** | Annotations-Modus ein/aus (leuchtet grün wenn aktiv) |
| **ab Takt [n]** | Starttakt des ersten Fragments (Spinbox) |
| **Takt [B]** | Takt-Marker setzen (Shortcut: B) |
| **Part-Start [P]** | Part-Marker setzen mit Namens-Dialog (Shortcut: P) |
| **Fragment [F]** | Fragment-Start setzen mit Takt-Eingabe (Shortcut: F) |
| **Undo [U]** | Letzten Marker rückgängig (Shortcut: U) |
| **Speichern** | Annotationen in JSON speichern |
| **→ reference.db** | Annotierte Takte als Audio-Features importieren |
| **DB-Parts** | Parts-Panel aus reference.db ein/ausblenden |
| **▶ Simulation** | Offline-Simulation starten |
| **⊙ Simulation** | Sim-Overlay ein/ausschalten (erscheint nach Simulation) |
| **✕ Sim** | Simulations-Ergebnisse löschen |

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
