# Proben-Aufnahme

Der Live Controller kann die komplette Probe als Mehrspuraufnahme mitschneiden. Die Aufnahme dient ausschließlich der **Nachbereitung** (System-Tuning, Fingerprint-Kalibrierung) und läuft vollständig im Hintergrund — sie erfordert während der Probe keine weitere Aufmerksamkeit.

---

## Ablauf während der Probe

### 1. Aufnahme starten

Vor dem ersten Song den **REC**-Button in der Timeline (unten rechts, neben SYNC) kurz antippen.

- Der Button leuchtet rot
- Neben dem Button läuft eine Stoppuhr (MM:SS)
- Die Aufnahme läuft jetzt komplett im Hintergrund

Der aktuelle Song kann wie gewohnt ausgewählt werden — das hat keinen Einfluss auf die Aufnahme.

### 2. Aufnahme stoppen

Nach der letzten Nummer **REC** antippen:

1. Button wechselt auf **STOPP?** (amber, 3 Sekunden)
2. Nochmal **REC** antippen → Aufnahme wird gespeichert

Der zweistufige Stopp verhindert versehentliches Beenden der Aufnahme.

> Passiert gar nichts nach dem ersten Tap auf STOPP? → einfach 3 Sekunden warten, der Button kehrt zu REC (rot) zurück.

---

## Nachbereitung

### Aufnahmeliste öffnen

**REC**-Button ca. 0,6 Sekunden gedrückt halten (Langdruck) → öffnet das Nachbereitung-Modal.

Dort sind alle gespeicherten WAV-Dateien aufgelistet mit Dateiname und Größe.

### Stereo-Mixdown erstellen

Neben jeder Mehrspurdatei gibt es einen **MIXDOWN**-Button. Ein Tap erzeugt daraus eine abgemischte Stereo-WAV auf dem Server:

- Alle 18 Kanäle werden gleichgewichtet summiert (L = ungerade Kanäle, R = gerade Kanäle)
- Das Ergebnis wird auf −1 dBFS peak-normalisiert
- Die neue Datei heißt `<original>_mixdown.wav` und liegt im selben Verzeichnis
- Die Quelldatei bleibt unverändert

Mixdown-Dateien sind in der Liste durch ein grünes ✓ gekennzeichnet — sie haben keinen MIXDOWN-Button.

---

## Technische Details

| Eigenschaft     | Wert                                      |
|-----------------|-------------------------------------------|
| Format          | WAV, float32                              |
| Sample-Rate     | 48 kHz                                    |
| Kanäle          | 18 (alle XR18 USB-Kanäle)                 |
| Größe           | ca. 12,5 MB/min (Mehrspurdatei)           |
| Ablageort       | `live/data/recordings/`                   |
| Dateiname       | `YYYY-MM-DD_HHMMSS_Probe YYYY-MM-DD.wav`  |

### Speicherbedarf (Richtwerte)

| Probendauer | Mehrspurdatei | + Mixdown |
|-------------|---------------|-----------|
| 1 Stunde    | ca. 750 MB    | + 85 MB   |
| 2 Stunden   | ca. 1,5 GB    | + 170 MB  |
| 3 Stunden   | ca. 2,2 GB    | + 255 MB  |

---

## API-Endpunkte (Referenz)

| Method | Pfad                        | Beschreibung                        |
|--------|-----------------------------|-------------------------------------|
| POST   | `/api/recording/start`      | Aufnahme starten (`label`, `song_id`) |
| POST   | `/api/recording/stop`       | Aufnahme stoppen                    |
| GET    | `/api/recording/status`     | Status der laufenden Aufnahme       |
| GET    | `/api/recording/list`       | Alle WAV-Dateien im Recordings-Ordner |
| POST   | `/api/recording/mixdown`    | Stereo-Mixdown erstellen (`filename`) |
