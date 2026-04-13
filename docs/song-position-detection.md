# Song-Positions-Erkennung — Implementierungsvorschläge

**Stand:** 2026-04-13  
**Kontext:** Live-App + DB-Pflege-App, Behringer XR18, 18 Kanäle @ 48 kHz

---

## Grundlagen & Korrekturen

### Signalqualität CH04–CH06

CH04–CH06 sind **Direktkanäle von Amp-Simulatoren** (Kemper/HX Stomp o.ä.):

- **Kein Bleed** von Schlagzeug, Gesang oder anderen Instrumenten
- **Keine Drum-Transients** im Signal
- Pegel konsistent, Latenz minimal
- Chroma-Qualität auf diesen Kanälen deutlich besser als ursprünglich angenommen

| Kanal (0-basiert) | Quelle | Signaltyp |
|---|---|---|
| CH01 (idx 0) | Lead Vocal Pete | Mikrofon (Bleed möglich) |
| CH04 (idx 3) | Gitarre 2 / Rhythm | Direktsignal, Amp-Sim |
| CH05 (idx 4) | Lead Guitar L | Direktsignal, Amp-Sim |
| CH06 (idx 5) | Bass | Direktsignal, Amp-Sim |

### Tonart ist bekannt

Die Tonart kommt aus `db.songs[id].key` — kein Key-Detection nötig.  
`apply_key_weight()` in `chroma_viz.py` ist bereits implementiert und gewichtet Töne der Tonart stärker. Das macht Chroma-Vektoren auf CH05/CH06 unmittelbar verwendbar.

### Verbleibendes Problem: Obertöne

Power-Chords und Distortion spreizen Energie über mehrere Pitch-Classes:  
Ein E5-Powerchord (E+H) mit Distortion erzeugt starke Peaks auf E, H, G#, D.  
Lösung: **Akkord-Erwartungswerte** in der DB (→ Abschnitt 3).

---

## Architektur: Drei Schichten

```
┌─────────────────────────────────────────────────────┐
│  Schicht 1: Beat-Counter (primär)                   │
│  Beat-Detection → BarTracker → Takt-Nummer          │
│  → weiß immer wo ich bin, solange kein Drift        │
├─────────────────────────────────────────────────────┤
│  Schicht 2: VAD-Muster-Abgleich (Drift-Korrektur)   │
│  CH01 VAD live vs. Lyrik-Muster aus DB              │
│  → periodischer Positions-Fix alle 4–8 Takte        │
├─────────────────────────────────────────────────────┤
│  Schicht 3: Chroma-Matching (Konfidenz)             │
│  CH05 Chroma live vs. Akkord-Erwartung aus DB       │
│  → bestätigt oder zweifelt an Schicht 1+2           │
└─────────────────────────────────────────────────────┘
```

Schicht 1 navigiert. Schicht 2 korrigiert. Schicht 3 zweifelt.

---

## Schicht 1: Beat-Counter

### Bereits vorhanden
- `BarTracker` zählt Takte aus Kick+Snare-Events
- `db.songs[id].parts` enthält Taktanzahl pro Part
- `bar_num` wird bereits in JSONL geloggt

### Was fehlt
- **Part-Offset-Tabelle** zur Laufzeit berechnen:

```python
def build_part_map(song: dict) -> list[dict]:
    """Gibt [{part_name, bar_start, bar_end}] zurück."""
    parts = sorted(song['parts'].values(), key=lambda p: p['pos'])
    cursor = 1
    result = []
    for p in parts:
        result.append({
            'name':      p['name'],
            'bar_start': cursor,
            'bar_end':   cursor + p['bars'] - 1,
        })
        cursor += p['bars']
    return result
```

- `bar_num → part_name` Lookup in `AudioProcess.set_song()` vorberechnen
- Part-Wechsel als WebSocket-Event emittieren:

```python
{"type": "part_change", "part_name": "Chorus", "bar_num": 25, "confidence": 1.0}
```

### Zuverlässigkeit
Sehr hoch — solange Beat-Detection läuft. Kritischer Punkt: der erste Anker (Takt 1).  
Takt-1-Anker-Quellen in Priorität:
1. Crash auf Beat 1 (bereits implementiert in `_crash_beat1_correct`)
2. Erstes VAD-Ereignis (Pete singt los = bekannter Takt)
3. Manuell über WebSocket (`action: set_bar`, `bar_num: 1`)

---

## Schicht 2: VAD-Muster-Abgleich

### Idee
Jeder Takt hat bekannte Vokal-Aktivität aus den Lyrics:

```python
vad_expected = [
    bool(db['bars'][bar_id]['lyrics'].strip())
    for bar_id in bars_for_song(song_id)
]
# → [False, True, True, False, True, True, True, False, ...]
```

Das Live-VAD-Signal (CH01) ergibt dasselbe Muster — mit zeitlichem Offset.  
**Sliding-Window-Korrelation** findet den Offset = aktuelle Takt-Position.

### Implementierung

```python
def vad_correlate(
    vad_live: list[bool],      # letzte N Takte, live gemessen
    vad_expected: list[bool],  # ganzer Song aus DB
    window: int = 8,           # Fensterbreite in Takten
) -> tuple[int, float]:
    """Gibt (bar_num, konfidenz) zurück."""
    best_pos, best_score = 0, -1.0
    n = len(vad_expected)
    for start in range(n - window + 1):
        segment = vad_expected[start:start + window]
        matches = sum(a == b for a, b in zip(vad_live[-window:], segment))
        score = matches / window
        if score > best_score:
            best_score, best_pos = score, start + window
    return best_pos, best_score
```

Schwellwert für Konfidenz: **≥ 0.75** (6 von 8 Takten stimmen überein).

### Einschränkungen
- Songs mit langen Instrumental-Parts haben wenig Unterscheidungskraft
- Kurze Songs (<16 Takte Lyrics) können mehrdeutig sein
- Lösung: Fenster vergrößern, Energie-Level als Tiebreaker

### Wo im Code
`live/server/audio/audio_process.py` — neues `_vad_matcher` Objekt, aktualisiert  
nach jedem vollständigen Takt (d.h. nach jedem Bar-Event aus BarTracker).

---

## Schicht 3: Chroma-Matching (neu bewertet)

### Warum jetzt realistischer
Da CH05 ein Direktsignal ohne Bleed ist, ist Chroma-Qualität ausreichend für:
- Bestätigung ob der erkannte Akkord plausibel ist
- Erkennung von Akkordwechseln (Delta-Signal)
- Konfidenz-Boost für Schicht 1+2 bei eindeutigen Akkordfolgen

### Akkord-Erwartungswerte in DB-Pflege-App erfassen

Neues optionales Feld `chord` pro Takt in `db.bars`:

```json
{
  "B042": {
    "part_id": "...",
    "bar_num": 5,
    "lyrics": "Here we go again",
    "chord": "Em",
    "has_accents": false
  }
}
```

Format: Standard-Akkord-Symbole — `"Em"`, `"G"`, `"D/F#"`, `"Bm7"`.  
Leer = unbekannt / nicht eingetragen.

**Chroma-Vektor aus Akkord-Symbol berechnen** (deterministisch):

```python
CHORD_TEMPLATES = {
    'maj':  [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0],  # 1-3-5
    'min':  [1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0],  # 1-b3-5
    'maj7': [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1],
    'min7': [1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 0],
    '5':    [1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0],  # Power-Chord
    # ...
}

def chord_to_chroma(chord_str: str) -> list[float]:
    """'Em' → 12-dim Chroma-Vektor (normiert)."""
    root, quality = parse_chord(chord_str)
    template = CHORD_TEMPLATES.get(quality, CHORD_TEMPLATES['maj'])
    rotated = template[12 - root:] + template[:12 - root]
    # Oberton-Gewichtung: Grundton + Quinte stärker als Terz
    arr = [v * (1.5 if i in (0, 7) else 1.0) for i, v in enumerate(rotated)]
    norm = sum(v**2 for v in arr) ** 0.5
    return [v / norm for v in arr] if norm > 0 else arr
```

Dies gibt einen **deterministischen Erwartungsvektor** — unabhängig von der Aufnahme.  
Vergleich live Chroma vs. Erwartung via Kosinus-Ähnlichkeit.

### Wo in reference.db speichern

Option A: Feld `chord` in `bars`-Tabelle (Text, nullable)  
Option B: Vorberechneten Chroma-Vektor in `feature_vectors.chroma` überschreiben  
→ **Option A** ist flexibler, B wäre eleganter für den Abruf

---

## Event-Katalog (ANKER-Tab)

Erweiterung des bestehenden ANKER-Tabs: statt freiem Typ-Dropdown einen  
strukturierten Ereignis-Katalog anbieten.

### Katalog (Stand 2026-04-13)

```javascript
const EVENT_CATALOG = [
  // ── Schlagzeug ──────────────────────────────────────
  { id: 'crash_beat1',    label: 'Crash auf Beat 1',       group: 'drum',     detection: 'crash_detector' },
  { id: 'drum_fill',      label: 'Drum Fill',              group: 'drum',     detection: 'snare_burst' },
  { id: 'snare_roll',     label: 'Snare-Roll',             group: 'drum',     detection: 'snare_density' },
  { id: 'kick_only',      label: 'Nur Kick (kein Snare)',  group: 'drum',     detection: 'kick_without_snare' },
  { id: 'double_kick',    label: 'Double-Kick',            group: 'drum',     detection: 'kick_burst' },
  { id: 'hihat_open',     label: 'Offene HiHat',           group: 'drum',     detection: 'oh_inter_beat_rms' },
  { id: 'cymbal_cascade', label: 'Becken-Kaskade',         group: 'drum',     detection: 'crash_burst' },

  // ── Gesang ──────────────────────────────────────────
  { id: 'vocal_start',    label: 'Gesang beginnt',         group: 'vocal',    detection: 'vad_rising' },
  { id: 'vocal_end',      label: 'Gesang endet',           group: 'vocal',    detection: 'vad_falling' },
  { id: 'vocal_scream',   label: 'Schrei / Hohe Lage',     group: 'vocal',    detection: 'pitch_high' },
  { id: 'vocal_long',     label: 'Lange Note gehalten',    group: 'vocal',    detection: 'vad_sustained' },
  { id: 'vocal_acap',     label: 'A cappella',             group: 'vocal',    detection: 'vad_band_silent' },
  { id: 'backing_vocals', label: 'Backing Vocals ein',     group: 'vocal',    detection: 'vad_ch02_04' },

  // ── Dynamik & Struktur ───────────────────────────────
  { id: 'band_silent',    label: 'Band setzt aus',         group: 'dynamics', detection: 'rms_all_silent' },
  { id: 'band_enters',    label: 'Band setzt ein',         group: 'dynamics', detection: 'rms_rising_after_silence' },
  { id: 'energy_high',    label: 'Energie-Anstieg (Chorus)', group: 'dynamics', detection: 'main_rms_high' },
  { id: 'energy_low',     label: 'Energie-Abfall (Verse)', group: 'dynamics', detection: 'main_rms_low' },
  { id: 'pickup',         label: 'Pickup / Auftakt',       group: 'dynamics', detection: 'onset_pre_beat1' },
  { id: 'ritardando',     label: 'Ritardando',             group: 'dynamics', detection: 'ioi_increasing' },
  { id: 'half_time',      label: 'Halbzeit-Feel',          group: 'dynamics', detection: 'snare_rate_halved' },

  // ── Gitarre & Bass ───────────────────────────────────
  { id: 'guitar_solo',    label: 'Gitarren-Solo',          group: 'guitar',   detection: 'ch05_dominant' },
  { id: 'guitar_silent',  label: 'Gitarre schweigt',       group: 'guitar',   detection: 'ch05_rms_silent' },
  { id: 'guitar_intro',   label: 'Gitarren-Intro (allein)', group: 'guitar',  detection: 'ch05_active_rest_silent' },
  { id: 'bass_enters',    label: 'Bass setzt ein',         group: 'bass',     detection: 'ch06_rms_rising' },
  { id: 'bass_silent',    label: 'Bass schweigt',          group: 'bass',     detection: 'ch06_rms_silent' },
];
```

### Erweiterung

Neuen Event hinzufügen = eine Zeile im Array ergänzen.  
`detection`-Wert ist der Schlüssel für die spätere Algorithmus-Implementierung in `detection/`.

---

## Offene Aufgaben

### DB-Pflege-App

- [ ] **ANKER-Tab**: `EVENT_CATALOG` statt freiem Typ+Beschreibung  
      Felder: `event_id` (Dropdown), `notes` (optional, Freitext)
- [ ] **Takte-Tab**: Optionales `chord`-Feld pro Takt (z.B. `"Em"`, leer = unbekannt)
- [ ] **VAD-Erwartungsmuster**: Automatisch aus `bars[].lyrics != ""` berechnen —  
      kein UI nötig, reine Berechnung beim Export/Save

### Live-App / Detection

- [ ] **`detection/reference_db.py`**: `chord`-Feld in `bars`-Tabelle (Schema-Migration)
- [ ] **`detection/chord_templates.py`** (neu): `chord_to_chroma(str) → list[float]`  
      inkl. Oberton-Gewichtung und `parse_chord()` für gängige Symbole
- [ ] **`live/server/audio/audio_process.py`**: `_vad_matcher` — VAD-Muster-Abgleich  
      nach jedem Bar-Event, emittiert `PositionFix`-Event wenn Konfidenz ≥ 0.75
- [ ] **`live/server/audio/audio_process.py`**: Part-Offset-Tabelle aus DB laden,  
      `part_change`-Events über WebSocket emittieren
- [ ] **`live/server/audio/audio_process.py`**: `set_song()` erweitern:  
      `song_id` → Part-Map + VAD-Erwartungsmuster + Referenz-Chromas laden
- [ ] **Event-Katalog-Detektion**: Pro `detection`-Schlüssel eine Funktion in  
      `detection/event_detector.py` (neu) implementieren

### Priorisierung

1. **Part-Offset-Tabelle + `part_change`-Event** — sofortiger Nutzen, wenig Aufwand  
2. **VAD-Erwartungsmuster + Muster-Abgleich** — stärkster Konfidenz-Gewinn  
3. **ANKER-Tab: Event-Katalog** — bessere UX für Timo  
4. **Akkord-Feld in Takte-Tab** — optionale Qualitätsverbesserung für Chroma  
5. **`chord_to_chroma()`** — erst sinnvoll wenn Akkorde eingetragen sind
