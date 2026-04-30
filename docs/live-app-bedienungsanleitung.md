# lighting.ai Live-App — Bedienungsanleitung

**Version:** 2026-04-26 (v2026.04.24b)
**Zielgruppe:** Lichttechniker (Timo)
**Gerät:** iPad (Hauptbedienung) oder Laptop (alternativ)

---

## Inhaltsverzeichnis

1. [Systemübersicht](#1-systemübersicht)
2. [Vor dem Gig: System starten](#2-vor-dem-gig-system-starten)
3. [Die Oberfläche](#3-die-oberfläche)
4. [Song auswählen und spielen](#4-song-auswählen-und-spielen)
5. [Parts und Steps navigieren](#5-parts-und-steps-navigieren)
6. [Accents und Effekte](#6-accents-und-effekte)
7. [Tap Tempo](#7-tap-tempo)
8. [Proben-Aufnahme](#8-proben-aufnahme)
9. [QLC+ Konfiguration](#9-qlc-konfiguration)
10. [Offline-Betrieb](#10-offline-betrieb)
11. [Fehlersuche](#11-fehlersuche)
12. [Technische Referenz](#12-technische-referenz)

---

## 1. Systemübersicht

Die Live-App ist eine Web-Oberfläche, die auf dem iPad läuft und über WLAN mit dem Steuer-Laptop kommuniziert. Der Laptop steuert QLC+ per OSC (Open Sound Control), das wiederum die Lichtanlage schaltet.

```
iPad (Safari)
    │  WLAN
    ▼
Steuer-Laptop (Linux Mint)
  lighting.ai Server (FastAPI)
    │  OSC (UDP/7700)
    ▼
QLC+ 4
    │  sACN/DMX
    ▼
Lichtanlage (THE PACT)
```

**Was die App kann:**
- Aktuelle Setlist anzeigen und Songs auswählen
- Durch Song-Parts und Steps navigieren → QLC+ schaltet automatisch die richtigen Lichtszenen
- Accents manuell triggern (Blinder, Strobe, Fog, Blackout, Alarm)
- Tap Tempo für BPM-Anzeige
- Komplette Probe als 18-Spur-Aufnahme mitschneiden (für Nachbereitung)

---

## 2. Vor dem Gig: System starten

### Schritt 1 — Steuer-Laptop vorbereiten

QLC+ starten (falls nicht schon laufend):
```
QLC+ öffnen → lightingAI.qxw laden
```

### Schritt 2 — lighting.ai Server starten

Terminal öffnen und folgendes eingeben:
```bash
cd ~/lighting.ai/live
./start-live.sh
```

Das Skript:
1. Prüft alle Python-Abhängigkeiten
2. Synchronisiert die Songdatenbank von GitHub (braucht kurz Internet)
3. Startet den Web-Server auf Port 8080
4. Öffnet Chrome automatisch

**Ausgabe bei Erfolg:**
```
✓ Dependencies OK
✓ DB synced (db/lighting-ai-db.json)
✓ Server gestartet: http://0.0.0.0:8080
```

### Schritt 3 — iPad verbinden

1. Safari öffnen
2. Adresse eingeben: `http://192.168.x.x:8080`
   *(IP des Laptops — steht auf dem Aufkleber am Laptop)*
3. **Optional:** „Zum Home-Bildschirm" → Fullscreen-App-Modus

Beim Laden erscheint kurz ein Verbindungs-Screen mit 4 Statusanzeigen:

| Aufgabe | Bedeutung |
|---------|-----------|
| Songs laden | Songdatenbank aus DB |
| Setlist laden | Aktuelle Setlist |
| QLC+ Mapping | Lichtszenen zuordnen |
| WebSocket verbinden | Echtzeit-Verbindung zum Server |

Alle vier müssen **grün** sein, bevor der Auftritt beginnt.

---

## 3. Die Oberfläche

Das Interface ist in vier Bereiche aufgeteilt:

```
┌──────────────┬────────────────────┬──────────────┐
│  PARTS       │                    │              │
│  (oben       │  PLAYBACK-CENTER   │  SETLIST     │
│   links)     │  (mitte)           │  (rechts)    │
│──────────────│                    │              │
│  ANKER       │                    │              │
│  (unten      │                    │              │
│   links)     │                    │              │
├──────────────┴────────────────────┴──────────────┤
│  TIMELINE (unten)                                │
└──────────────────────────────────────────────────┘
```

### Parts-Panel (links oben)

Zeigt alle Parts (Songteile) des aktuell geladenen Songs:
- **Grün hervorgehoben** = aktuell aktiver Part
- **Ausgegraut** = schon gespielt
- Antippen springt zu diesem Part

Beispiel:
```
▶ Intro          [aktiv, grün]
  Verse 1
  Pre-Chorus
  Chorus 1
  ...
```

### Anker-Panel (links unten)

Zeigt die **akustischen Erkennungsmarken** (Anker) des aktuellen Songs in chronologischer Reihenfolge. Anker sind markante Momente im Song — etwa ein Schrei, ein Crash-Becken oder ein bestimmter Einsatz — die als Orientierungspunkte dienen.

| Zustand | Darstellung |
|---------|-------------|
| Vergangener Anker | Abgedunkelt (30% Opacity) |
| Nächster Anker | Amber hervorgehoben |
| Kommende Anker | Normal sichtbar |

Pro Anker wird angezeigt:
- **Farbiger Typ-Badge** (PETE = cyan, AXEL = amber, CHRIS = grün, DRUM = rot, GTR = violett, BASS = mint)
- **Ereignis** (z.B. „Crash (Beat 1)", „Setzt ein")
- **Part + Takt + Zählzeit** (z.B. „Intro · T1 · 1")

Das Panel scrollt automatisch so, dass der nächste Anker sichtbar ist.

Anker werden in der DB-Pflege-App im **ANKER**-Tab gepflegt.

### Playback-Center (mitte)

- **Song-Titel** und Artist oben
- **Step-Anzeige** (z.B. „2 / 8") — aktueller Step von Gesamt
- **Beat-Bereich** mit Tap-Button und BPM-Anzeige
- **Override-Buttons** für direkte Lichteffekte
- **PREV / NEXT** Buttons für Step-Navigation

### Setlist-Panel (rechts)

Zeigt alle Songs der aktuellen Setlist in Reihenfolge:
- **Grün** = gerade gespielt
- **Blass** = schon fertig
- Antippen wählt Song aus
- **`+`-Button** oben rechts im Panel-Header öffnet den Song-Picker (→ [Kapitel 4b](#4b-spontan-song-hinzufügen))
- **⚙️-Button** öffnet QLC+-Konfiguration

### Timeline (unten)

Zeigt die Takte des aktuellen Parts als Leiste:
- Einzelne Taktblöcke anklickbar
- Status-Dots zeigen QLC+- und DB-Verbindung
- **SYNC-Button** für manuellen DB-Abgleich
- **REC-Button** für Proben-Aufnahme (→ [Kapitel 8](#8-proben-aufnahme))

---

## 4. Song auswählen und spielen

1. **Song antippen** in der Setlist (rechts)
   → Parts werden geladen, erster Part wird aktiv
2. Ersten Step von QLC+ starten: **NEXT** antippen
3. App navigiert automatisch Steps entsprechend Song-Struktur

**Tipp:** Songs mit roter Markierung haben kein QLC+-Mapping hinterlegt — Lichtsteuerung funktioniert dann nicht automatisch.

---

## 4b. Spontan Song hinzufügen

Falls spontan ein Song gespielt wird, der nicht auf der geplanten Setlist steht:

1. **`+`-Button** oben rechts im Setlist-Panel antippen
2. Song-Picker öffnet sich mit dem kompletten Repertoire
3. **Suche**: oben im Picker nach Name oder Artist filtern
4. Song antippen → erscheint am Ende der Setlist (mit ⊕-Markierung)
5. **ESC** oder ✕-Button schließt den Picker ohne Aktion

Songs die bereits auf der Setlist stehen, sind mit ✓ markiert und können nicht nochmal hinzugefügt werden.

**Wichtig:** Spontan hinzugefügte Songs werden **nur in dieser Session gespeichert** — sie erscheinen nicht dauerhaft auf der Setlist. Nach einem Browser-Reload ist die Setlist wieder im Ursprungszustand.

---

## 5. Parts und Steps navigieren

### NEXT / PREV

Die zwei großen Buttons unten in der Mitte:

- **NEXT** → nächster Step (= nächste Lichtszene in QLC+)
- **PREV** → vorheriger Step

Bei jedem Tippen schickt die App einen OSC-Befehl an QLC+, das dann die Lichtszene wechselt.

### Direktsprung

- **Part antippen** (links) → springt zum ersten Step dieses Parts
- **Takt antippen** (Timeline unten) → springt zu diesem Takt

### Step-Anzeige

Die Anzeige `2 / 8` bedeutet: aktuell Step 2 von 8 Steps im Song.
Ein Step entspricht einer Lichtszene in QLC+.

---

## 6. Accents und Effekte

Die **Override-Buttons** in der Mitte sind für direkte Lichteffekte, unabhängig vom aktuellen Step:

| Button | Effekt |
|--------|--------|
| **BLINDER** | Blinder kurz aufblitzen |
| **STROBE** | Strobe-Blitz |
| **FOG 5s** | Nebelmaschine 5 Sekunden |
| **FOG 10s** | Nebelmaschine 10 Sekunden |
| **FOG AN** | Nebelmaschine dauerhaft an |
| **FOG AUS** | Nebelmaschine aus |
| **BLACK** | Blackout (alles aus) |
| **ALARM** | Alarm-Effekt |

**Wichtig:** Diese Buttons überschreiben den aktuellen Step **nicht** — QLC+ kehrt danach automatisch zur aktuellen Szene zurück.

---

## 7. Tap Tempo

Der große **Tap-Kreis** in der Mitte zeigt das aktuelle BPM.

**Bedienung:**
1. Im Takt tippen (mindestens 3-4 Mal)
2. BPM-Anzeige aktualisiert sich nach jedem Tap
3. Die vier Beat-Punkte visualisieren den 4/4-Takt

Das BPM-Display dient zur Orientierung — die App steuert die Lichter aktuell noch **nicht automatisch** nach Tempo (kommt in Phase 2).

---

## 8. Proben-Aufnahme

Der **REC-Button** (Timeline, unten rechts neben SYNC) schneidet die komplette Probe als 18-Spur-WAV mit. Die Aufnahme dient der Nachbereitung (System-Tuning, Fingerprint-Kalibrierung) und läuft unsichtbar im Hintergrund — während der Probe ist keine weitere Bedienung nötig.

### Aufnahme starten

**REC** antippen → Button wird **vollständig rot** (solides Rot), Stoppuhr läuft inline.

Die Aufnahme startet sofort — kein Label, kein Dialog. Der Dateiname wird automatisch beim Stoppen aus den gespielten Songs zusammengesetzt.

### Aufnahme stoppen

Am Ende der Probe **REC** nochmal antippen → Aufnahme wird sofort gespeichert, Toast zeigt den Dateinamen. Der Button kehrt in den Ruhezustand zurück (roter Rahmen, transparenter Hintergrund).

Zwei Zustände:
- **Ruhend**: roter Rand, transparenter Hintergrund = keine Aufnahme
- **Aktiv**: vollständig rotes Feld, dunkler Text = Aufnahme läuft

**Drei Dateien pro Aufnahme** (gleicher Stamm im selben Ordner):
- `*.wav` — 18 Kanäle Audio (RF64)
- `*.jsonl` — strukturierte Events: `kick`/`snare`/`crash`, `bar`,
  `band_event` (band_starts/stops), `anchor_matched` (Anker-Treffer mit
  id, type, event, bar_num, beat, part_hint, trigger), `user`-Aktionen
  (`select_song`, `next`, `goto_part`, `accent`, `tap`)
- `*.log` — Klartext-Diagnose vom AnchorMatcher und BarTracker
  (`[ANKER] warte auf #NN …`, `✓ ERKANNT`, `cooldown`, `RMS …`,
  `[BAR] energy_beat1 …`, `_snare_phase_correct …`); Format `[  s.ss] msg`,
  Sekunden-Timestamp seit Aufnahme-Start. In der Rehearsal-Review-App per
  Rechtsklick auf den Events-Strip zeitsynchron aufrufbar.

**Dateiname:** `recordings/YYYY-MM-DD/HHMM_Song1_Song2_Song3.{wav,jsonl,log}`
Beispiel: `recordings/2026-04-26/1853_Animal_Creep_Sweet_Home_Alabama.wav`
Die Songs werden automatisch aus der Songauswahl übernommen (max. 6 Songs im Dateinamen). Der bei Aufnahme-Start aktive Song wird seit v2026.04.30d ebenfalls als `select_song`-Event geloggt — vorher fehlte er, falls keine weitere Songauswahl folgte.

### Nachbereitung (nach der Probe)

**REC ca. 0,6 Sekunden gedrückt halten** (Langdruck) → öffnet das Nachbereitung-Modal mit der Liste aller gespeicherten Aufnahmen.

Dort gibt es pro Mehrspurdatei einen **MIXDOWN**-Button. Ein Tap darauf erzeugt eine abgemischte Stereo-WAV auf dem Laptop:
- Alle 18 Kanäle werden gleichgewichtet summiert (L = ungerade Kanäle, R = gerade Kanäle)
- Ergebnis wird auf −1 dBFS peak-normalisiert
- Neue Datei: `<original>_mixdown.wav` im selben Verzeichnis
- Quelldatei bleibt unverändert

Mixdown-Dateien sind in der Liste durch ein grünes ✓ gekennzeichnet.

### Dateiformat

Aufnahmen werden im **RF64**-Format gespeichert (Erweiterung des WAV-Standards mit 64-Bit-Größenfeldern). Kein 4-GB-Limit, kein ungültiger Size-Header bei langen Proben. Mixdowns sind normale WAV-Dateien.

### Speicherbedarf (Richtwerte)

| Probendauer | Mehrspurdatei (RF64) | + Mixdown |
|-------------|----------------------|-----------|
| 1 Stunde    | ca. 750 MB           | + 85 MB   |
| 2 Stunden   | ca. 1,5 GB           | + 170 MB  |
| 3 Stunden   | ca. 2,2 GB           | + 255 MB  |

---

## 9. QLC+ Konfiguration

Das **⚙️-Symbol** (oben rechts in der Setlist) öffnet das Konfigurations-Modal.

### Verbindungseinstellungen

| Feld | Standard | Bedeutung |
|------|----------|-----------|
| Host | 127.0.0.1 | IP-Adresse des QLC+-Rechners |
| Port | 7700 | OSC Input-Port in QLC+ |
| Universe | 1 | OSC Universe in QLC+ |

**Wenn QLC+ auf demselben Laptop läuft:** Host bleibt `127.0.0.1`.
**Wenn QLC+ auf einem separaten Rechner läuft:** Host = IP dieses Rechners.

### Verbindung testen

Im Config-Modal gibt es ein Grid mit allen QLC+-Funktionen. Einzelne Buttons antippen testet die OSC-Verbindung direkt — das entsprechende Licht sollte kurz aufgehen.

**Status-Indikator:**
- **Grüner Punkt** neben „QLC+" = Verbindung OK
- **Roter Punkt** = keine Verbindung (QLC+ läuft nicht oder falscher Port)

### QLC+ einmalig einrichten (nur bei Ersteinrichtung)

1. QLC+ öffnen → `Inputs/Outputs`
2. Ein freies Universe wählen (z.B. Universe 9)
3. OSC Input-Plugin aktivieren, Port auf 7700 setzen
4. Virtual Console → Buttons erstellen und External Inputs zuweisen
5. In lighting.ai Config-Modal: Host/Port/Universe anpassen und testen

---

## 10. Offline-Betrieb

Falls beim Start **kein Internet** verfügbar ist (z.B. auf einer Bühne ohne WLAN zum Router):

- Der Server nutzt automatisch die **lokale DB-Kopie** (`live/data/lighting-ai-db.json`)
- Die App läuft vollständig offline — alle Songs und Steps sind verfügbar
- Der Status-Dot „DB" zeigt **rot** (offline), App funktioniert trotzdem

**Empfehlung:** Einmal vor dem Gig mit Internet starten (synchronisiert automatisch), dann funktioniert der Auftritt auch ohne Verbindung.

---

## 11. Fehlersuche

### „QLC+ nicht verbunden" (roter Punkt)

1. Prüfen ob QLC+ läuft und die richtige `.qxw`-Datei geladen ist
2. In QLC+ prüfen: `Inputs/Outputs` → OSC Input auf Port 7700 aktiv?
3. Im Config-Modal: Host, Port, Universe prüfen
4. Einen Test-Button im Config-Modal antippen

### „Songs laden fehlgeschlagen" beim Start

1. WLAN-Verbindung des iPads prüfen (muss im selben Netz sein wie Laptop)
2. IP-Adresse des Laptops prüfen (könnte sich geändert haben)
3. Server-Logs auf dem Laptop prüfen:
   ```bash
   # Im Terminal des Laptops sichtbar wo start-live.sh läuft
   ```

### App reagiert nicht / hängt

1. Safari auf dem iPad: Seite neu laden (Pull-down oder Reload-Button)
2. WebSocket reconnectet automatisch nach 2 Sekunden
3. Falls gar nichts hilft: Server neustarten mit `./start-live.sh`

### Falsches Licht beim Step-Wechsel

1. Song-Mapping in QLC+ prüfen (ist der richtige Chaser dem Song zugeordnet?)
2. Im Config-Modal: QLC+-Funktionen testen
3. Manuell in QLC+ nachschauen, welche Collection dem Step entspricht

### DB ist veraltet (neue Songs fehlen)

1. Internet-Verbindung herstellen
2. **SYNC**-Button in der Timeline (unten) antippen
3. Seite neu laden

---

## 12. Technische Referenz

### OSC Channel-Belegung

| Funktion | OSC Channel |
|----------|-------------|
| CueList Play | 1 |
| CueList Stop | 2 |
| CueList Next (NEXT-Button) | 3 |
| CueList Prev (PREV-Button) | 4 |
| Blinder | 10 |
| Blackout | 11 |
| Strobe | 12 |
| Alarm | 13 |
| Fog An | 14 |
| Fog Aus | 15 |
| Fog 5s | 16 |
| Fog 10s | 17 |
| Tap Tempo | 20 |

### Netzwerk-Ports

| Port | Protokoll | Dienst |
|------|-----------|--------|
| 8080 | HTTP/WebSocket | lighting.ai Web-UI |
| 7700 | UDP (OSC) | QLC+ Steuerung |

### Dateipfade (Laptop)

| Datei | Zweck |
|-------|-------|
| `~/lighting.ai/live/config.yaml` | Server-Konfiguration |
| `~/lighting.ai/live/data/lighting-ai-db.json` | Lokale DB-Kopie |
| `~/lighting.ai/live/data/recordings/YYYY-MM-DD/` | Proben-Aufnahmen (WAV), ein Unterordner pro Tag |
| `~/lighting.ai/db/lightingAI.qxw` | QLC+ Workspace |
| `~/lighting.ai/live/start-live.sh` | Start-Skript |

### config.yaml anpassen

```yaml
qlc:
  osc_host: "127.0.0.1"   # IP von QLC+
  osc_port: 7700           # OSC Port
  osc_universe: 0          # Universe (0-basiert, also Universe 1 = 0)

server:
  port: 8080               # Web-UI Port
```

---

*Letzte Aktualisierung: 23. April 2026 — lighting.ai für THE PACT, Haan*
