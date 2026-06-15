# Übergabe BassTrainer — Feature „Intro einspielen" (Anfänge aufnehmen)

> Statt Töne von Hand zu tippen, spielt der Owner die ersten Töne eines Songs auf
> dem Bass ein; BassTrainer erkennt sie (Mikro, vorhandene Pitch-Engine), lässt
> korrigieren und **exportiert** sie im Format von `db/song-intros.json`. Der
> Owner committet den Export ins lighting.ai-Repo → Auto-Sync → `song_intro_public`.

## Warum hier (native) und nicht in der Web-App
Die zuverlässige Bass-Tonhöhen/Onset-Erkennung liegt in BassTrainer. Im Browser
wäre sie schlechter (tiefe Frequenzen, Latenz, Oktavfehler) und doppelt gebaut.
**Erkennung gehört hierher.**

## Architektur-Grenze (wichtig)
BassTrainer bleibt **read-only auf dem geteilten Katalog**. Dieses Feature
**schreibt NICHTS** in `song_intros`/die DB — es **erzeugt nur Text** (Export).
Den committet der Owner nach lighting.ai (Git bleibt Single-Writer). Ein direkter
Kurator-Schreibpfad ist später additiv möglich (Weg 2), ist aber jetzt nicht nötig.

## Ablauf

1. **Song wählen** — `song_id` + `bpm` sind bekannt (aus `songs`).
2. **Einzähler/Metronom** im Songtempo (`songs.bpm`). Der **Downbeat von Takt 1 = `t0`**.
3. **Einspielen** der ersten ~4–8 Töne. Pro erkanntem Onset:
   - `beat = (onset_t − t0) · bpm / 60` → Viertel ab Downbeat. Auftakt vor Takt 1 →
     **negativ**. Sinnvoll quantisieren (z. B. auf ½- oder ¼-Beat, einstellbar).
   - Tonhöhe → **klingende** MIDI. Bass-Erkennung ist oktav-wackelig → auf die
     plausibelste Basslage schnappen, **Oktave editierbar** lassen.
   - MIDI → **Saite/Bund** vorschlagen (z. B. tiefste sinnvolle Lage).
4. **Korrektur-UI**: pro Ton Saite (E/A/D/G) / Bund / Beat / Dauer editieren;
   hinzufügen / löschen / verschieben; **Notenname** (D2 …) zur Kontrolle;
   **Vorschau abspielbar** (Klick + Töne) zum Gegenchecken „klingt das wie der Anfang?".
5. **Export** im exakten `db/song-intros.json`-Format (siehe unten). Per
   Share-Sheet / Zwischenablage / Datei. Der Owner fügt den Block ins Repo ein.

## Export-Format (1:1 wie `db/song-intros.json`)

```json
{
  "5iZfKj": [
    {"string": 3, "fret": 0, "beat": 0.0, "duration_beats": 0.5},
    {"string": 3, "fret": 0, "beat": 0.5, "duration_beats": 0.5},
    {"string": 4, "fret": 2, "beat": 1.0, "duration_beats": 1.0}
  ]
}
```

- Top-Level-Key = `song_id`. Wert = Liste der Töne **in Spielreihenfolge**.
- **`idx` NICHT exportieren** — wird beim Sync aus der Reihenfolge abgeleitet.
- Pro Ton **eine** Tonhöhen-Form genügt:
  - `string` (E=1, A=2, D=3, G=4) + `fret`  ← bevorzugt
  - oder `note_name` (`"D2"`)
  - oder `midi` (klingend)
- `beat` ist **Pflicht**, `duration_beats` optional.
- **Tempo NICHT** exportieren (kommt aus `songs.bpm`).

## Referenz
- Offene Saiten klingend: `E1=28, A1=33, D2=38, G2=43`; `midi = open[string] + fret`.
- `beat`: `0.0` = erster Schlag (Downbeat), `1.0` = Zählzeit 2, `0.5` = „und" der 1,
  Pickup negativ.

## Grenzen / Hinweise
- **Kein** Schreibzugriff auf den Katalog — nur Export.
- **Monophon** (ein Ton pro Beat-Position).
- Nach Commit + Sync (~1–2 Min) kann die App via
  `GET /rest/v1/song_intro_public?song_id=eq.<ID>&order=idx` prüfen, ob der Anfang
  hinterlegt ist (und ihn dann für die Übung „Anfänge lernen" nutzen).
