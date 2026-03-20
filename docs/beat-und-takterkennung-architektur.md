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
### Struktur
```
SQLite (reference.db)     ← Metadaten, BPM, Takt-Positionen, Setlisten
audio/
  song_001/
    full.wav              ← Original-Aufnahme (Stereo-Mix)
    takt_001.wav          ← extrahiertes Takt-Snippet
    takt_002.wav
    ...
```
### Takt-Snippets
- Format: WAV, Mono oder Stereo (Summensignal)
- Länge: exakt ein Takt (aus BPM berechnet)
- Bereits vorhandene Takt-Positionen (Sekunden + Taktnummer relativ zum Songstart) werden übernommen
- Für jedes Snippet wird beim Import ein **Fingerprint-Vektor** vorberechnet und in der DB gespeichert
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
- [ ] Wie werden Fingerprint-Vektoren in SQLite gespeichert? (BLOB mit numpy, oder separate Tabelle)
- [ ] Schwellwerte für Gauß-Breiten der Übergänge (empirisch tunen nach ersten Tests)
- [ ] Wie wird der aktive Song der Setliste manuell gesetzt? (UI-Element im Browser)
- [ ] Fallback wenn Fingerprint-Match unter Konfidenz-Schwelle liegt (z.B. bei sehr lauten Fills)
