# Beat- und Takterkennung – Architektur

## Ziel

Das System soll während eines Live-Auftritts in Echtzeit erkennen:

- **Welcher Song** gerade gespielt wird
- **Welcher Takt** innerhalb des Songs (absolut, z.B. Takt 42)
- **Welcher Beat** innerhalb des Takts (1–4)
- **Welche Zählzeit** (1–16, für spätere 16tel-genaue Lichtsteuerung)

Diese Informationen steuern das Grundprogramm der Lichtanlage automatisch. Der Licht-Mensch setzt darauf aufbauend manuelle Akzente.

-----

## Eingangssignale

### USB-Audio (Behringer XR18)

Der XR18 wird per USB an den PC angeschlossen und liefert alle 18 Kanäle als separate Audiospuren in Echtzeit (48 kHz).

**Kanalbelegung:**

|Kanal|Instrument    |
|-----|--------------|
|CH01 |Pete Vox      |
|CH02 |Axel Vox      |
|CH03 |Bibo Vox      |
|CH04 |Pete Guitar   |
|CH05 |Axel Guitar   |
|CH06 |Bibo Bass     |
|CH07 |Synth (selten)|
|CH09 |Kick          |
|CH10 |Snare         |
|CH11 |Tom Hi        |
|CH12 |Tom Mid       |
|CH13 |Tom Lo        |
|CH14 |Overhead 1    |
|CH15 |Overhead 2    |

### OSC (nur Ausgang)

OSC wird **ausschließlich zur Ausgabe** genutzt: Python-Server → QLC+ → DMX/ArtNet → Fixtures. OSC-Meter-Werte des XR18 werden **nicht** als Eingang verwendet.

-----

## Referenzdatenbank

### Dateistruktur (GitHub)

```
audio/
  songs/
    001_highway_to_hell/
      reference_stereo.mp3          ← Referenz-Mix (Original oder Probemitschnitt)
      snippets/
        stereo/
          001_intro_t001.wav        ← Takt 1, Intro
          001_intro_t002.wav
          002_vers1_t001.wav        ← Takt 1, Vers 1
          ...
        ch01_pete_vox/
          001_intro_t001.wav        ← gleiche Struktur pro Kanal
          ...
        ch09_kick/
          ...
```

Namensschema Snippets: `{part_index}_{part_name}_t{takt_nr_im_part}.wav`

- Alphabetisch sortiert = korrekte Reihenfolge
- Part-Name macht Dateien human-readable ohne DB-Abfrage

### Was auf GitHub liegt

- Code, DB-Schema, Metadaten
- Stereo-Referenzmixe (bereits vorhanden)
- Takt-Snippets (Stereo + Einzelkanäle, kurz genug für Git)
- Feature-Point-Vektoren pro Takt (JSON oder SQLite)
- Konfidenz-Logs aus Proben

### Was lokal bleibt (Licht-Laptop)

- 18-Spur-Vollaufnahmen der Proben (temporäres Analysematerial, zu groß für GitHub)

### Takt-Snippets

- Format: WAV, Stereo (Summensignal) + optional Einzelkanäle
- Länge: exakt ein Takt (aus BPM berechnet)
- Bereits vorhandene Takt-Positionen (Sekunden + Taktnummer relativ zum Songstart) werden übernommen
- Für jedes Snippet wird beim Import ein **Feature-Vektor** vorberechnet und in der DB gespeichert

### Feature Points pro Takt

Kompakter Vektor der stabilen, diskriminativen Merkmale – gespeichert in SQLite und versioniert auf GitHub:

```json
{
  "takt_id": "001_highway_intro_t001",
  "chroma_vector":      [12 Werte],
  "channel_activity":   [18 bool],
  "onset_pattern":      [16 Werte],
  "spectral_centroid":  [18 Werte],
  "energy_ratios":      [18 Werte],
  "confidence_history": [float, ...]
}
```

|Feature             |Bedeutung                              |Stabilität             |
|--------------------|---------------------------------------|-----------------------|
|`chroma_vector`     |Harmonischer Inhalt (Akkorde/Töne)     |hoch                   |
|`channel_activity`  |Welche Instrumente spielen             |hoch                   |
|`onset_pattern`     |Rhythmisches Muster im 16tel-Raster    |hoch                   |
|`spectral_centroid` |Grobe Klangfarbe pro Kanal             |mittel                 |
|`energy_ratios`     |Relative Energie pro Kanal             |mittel                 |
|`confidence_history`|Erkennungssicherheit über Proben hinweg|wächst mit Probenanzahl|

### Setliste

- Jeweils eine aktive Setliste mit geordneter Song-Reihenfolge
- Reicht für den Live-Einsatz aus

-----

## Systemarchitektur

```
USB-Audio (18 Kanäle, 48kHz)
        │
        ├── CH09 Kick  ──────────────────┐
        ├── CH10 Snare ──────────────────┤──► Beat-Detection-Modul
        ├── CH14/15 Overhead ────────────┘    (Tempo, Beat 1–4, Zählzeit)
        │
        └── Summensignal (Mix) ──────────────► Fingerprint-Matching
                                               (Song-ID, Takt-Position)
                                                        │
                                               HMM-Zustandsschätzung
                                                        │
                                          ┌─────────────┴──────────────┐
                                          ▼                            ▼
                                   Takt-Position               Beat/Zählzeit
                                          │                            │
                                          └──────────┬─────────────────┘
                                                     ▼
                                            Python-Server (FastAPI)
                                                     │
                                          ┌──────────┴──────────┐
                                          ▼                     ▼
                                    WebSocket               OSC-Ausgang
                                  (Browser-UI)            → QLC+ → DMX
```

-----

## Beat-Detection

### Tempo

- Overhead-Kanäle (CH14/15): dichteste Transienten → feinste BPM-Schätzung
- Kick (CH09): Bestätigung

### Downbeat (Beat 1)

- Snare (CH10) markiert zuverlässig **Beat 2 und 4** (genre-übergreifend stabil)
- Beat 1 wird daraus rückgerechnet
- Bass (CH06): Transienten auf Beat 1 als Korrektiv

### Fill-Erkennung (= Taktgrenze)

- Tom-Kanäle (CH11–13) aktiv → letzter Takt einer Phrase
- Nächster Takt = Phrasenanfang → Beat-1-Bestätigung

### Zählzeit (16tel)

- Nicht per Fingerprint, sondern per **Interpolation** aus bekanntem BPM und Taktstart
- Auflösung: bei 120 BPM = 125ms pro 16tel → mit USB-Audio präzise erreichbar

-----

## Takt-Positionserkennung (HMM)

### Grundprinzip

Das System kennt die gesamte Setliste mit allen Takten. Es kombiniert zwei Informationen:

1. **Wo war ich gerade?** – der aktuelle Zustand (Song X, Takt Y) macht den nächsten Zustand wahrscheinlich
1. **Was höre ich gerade?** – der Fingerprint-Vergleich gibt die Ähnlichkeit zum gespeicherten Takt an

### Hidden Markov Model

|Begriff               |Bedeutung                                            |
|----------------------|-----------------------------------------------------|
|Hidden State          |wahrer Zustand: (Song, Takt)                         |
|Transition Probability|Gauß-Verteilung um den "Normalfall" (nächster Takt)  |
|Emission Probability  |Fingerprint-Ähnlichkeit des aktuellen Audio-Snapshots|

### Übergangswahrscheinlichkeiten (Gauß-Breite)

- **Takt → Takt**: sehr schmal (live kaum Takte übersprungen)
- **Part → Part**: etwas breiter (Wiederholung, ausgelassener Chorus möglich)
- **Song → Song**: breit (Setliste kann sich spontan ändern)

### Selbst-Resyncing

Wenn die Band einen Takt wiederholt oder überspringt, sucht das System automatisch in der Umgebung (einige Takte vor/zurück) nach dem besten Fingerprint-Match – ohne manuellen Reset.

### Zustandsraum (Größenordnung)

```
~25 Songs × ~120 Takte = ~3000 Zustände
```

Für Viterbi-Algorithmus in Echtzeit problemlos handhabbar.

### Fingerprint

- Berechnet aus dem **Summensignal** (weil Referenz-DB ebenfalls Stereo-Mix)
- Feature-Vektor: Chroma-Features + MFCC kombiniert
- Snapshot wird **beat-synchron** getriggert (immer auf Beat 1) → kein Versatz-Problem

-----

## Rehearsal Mode

### Ziel

Mit möglichst wenig Interaktion während der Probe das Erkennungssystem aufbereiten und kontinuierlich verbessern.

### Ablauf

**Vorbereitung (vor der Probe)**

- Songs in der DB anlegen mit Referenz-Stereo-Mix
- Takt-Snippets aus Referenz-Audio extrahieren
- Feature-Vektoren vorberechnen

**Während der Probe**

- Licht-Laptop per USB am XR18
- Server im Rehearsal Mode: aktiver Song wird **manuell** aus der vorbereiteten Setliste gesetzt
- Erkennung läuft nur innerhalb des aktuellen Songs (reduzierter Suchraum)
- Gleichzeitige Aufzeichnung:
  - 18-Spur-Audio (lokal, temporär)
  - Konfidenz-Log: Erkennungssicherheit pro Takt über die gesamte Probendauer
  - Event-Log mit Timestamps: wann wurde welcher Song manuell gesetzt, wann erkannte das System welchen Takt
- **Keine** automatische Übernahme von Takt-Snippets in die DB (System könnte im falschen Takt sein)

**Nachanalyse (nach der Probe)**

- Offline Re-Run des HMM auf dem 18-Spur-Recording
- Ground Truth bekannt (Event-Log) → Algorithmus gegen reale Daten tunen
- Kritische Stellen (niedrige Konfidenz) identifizieren
- Feature-Gewichtungen im HMM anpassen
- Verfeinerte Feature-Vektoren in DB schreiben und auf GitHub pushen

### Lernzyklus

```
Vorbereitung → Probe (Rehearsal) → Nachanalyse → verfeinerte DB
                                                        ↓
                                                  nächste Probe
```

Mit jeder Probe wächst `confidence_history` pro Takt und das System lernt welche Features stabil und diskriminativ sind.

-----

## Integration in bestehenden Server

### Prozessmodell

Das Audio-Processing läuft als **dauerhafter separater Prozess** (nicht als einmaliger Job):

```
AudioProcess (permanent)          FastAPI-Prozess (Uvicorn)
  ├── sounddevice callback   →    asyncio.Queue
  ├── Beat-Detection         →    WebSocket broadcast → Browser
  └── HMM / Takt-Position    →    OSC-Ausgang → QLC+
```

### Bekannte Tech-Schulden (aus bestehender Codebasis)

- `qlc_osc.py:104` und `main.py:283`: `time.sleep(0.05)` → ersetzen durch `await asyncio.sleep(0.05)`

-----

## Bibliotheken (Vorschläge)

|Aufgabe        |Bibliothek                                                       |
|---------------|-----------------------------------------------------------------|
|USB-Audio-Input|`sounddevice`                                                    |
|Beat-Detection |`madmom` (RNN-basiert, robustester Beat-Tracker)                 |
|Fingerprinting |`librosa` (Chroma, MFCC)                                         |
|HMM            |`hmmlearn` oder eigene Implementierung (Zustandsraum klein genug)|
|OSC-Ausgang    |`python-osc` (bereits vorhanden)                                 |
|Datenbank      |`SQLite` (Python-nativ)                                          |

-----

## Offene Entscheidungen

- [ ] Wie werden Feature-Vektoren in SQLite gespeichert? (BLOB mit numpy, oder separate Tabelle)
- [ ] Schwellwerte für Gauß-Breiten der Übergänge (empirisch tunen nach ersten Tests)
- [ ] Wie wird der aktive Song im Rehearsal Mode manuell gesetzt? (UI-Element im Browser)
- [ ] Fallback wenn Fingerprint-Match unter Konfidenz-Schwelle liegt (z.B. bei sehr lauten Fills)
- [ ] Takt-Nummerierung: relativ zum Part oder absolut zum Song?
- [ ] Welche Kanäle bekommen Einzelkanal-Snippets in der DB? (Minimum: CH09 Kick, CH10 Snare, CH06 Bass)
