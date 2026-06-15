# Übergabe BassTrainer — „Intro einspielen" (direkt in die DB, ohne Datei)

> Der Owner spielt die ersten Töne eines Songs auf dem Bass ein; BassTrainer
> erkennt sie (Mikro, vorhandene Pitch-Engine), lässt korrigieren und schreibt
> sie **direkt** in `song_intros` (Supabase). Kein File, kein Commit.
> **Nur der Owner** (Kurator) darf schreiben; alle anderen bleiben read-only.
> Der `service_role`-Key kommt **nicht** in die App.

## Identität: Kurator-Allowlist
- BassTrainer ist schon anonym angemeldet (von `practice_markers`) — **dieselbe
  Identität** (`auth.uid()`) wird zum Kurator.
- lighting.ai hat eine Tabelle `curators (user_id uuid)`. Nur uids darin dürfen
  `song_intros` schreiben (RLS via `is_curator()`); Lesen bleibt öffentlich.
- **Einmalige Einrichtung:** BassTrainer zeigt im „Kurator-Modus"/Settings die
  **eigene uid** an (aus dem JWT `sub` bzw. `GET /auth/v1/user`). Der Owner trägt
  diese uid einmal in `curators` ein (Supabase SQL-Editor):
  `insert into curators (user_id, note) values ('<uid>', 'Christian iPad');`
  Danach darf genau dieses Gerät schreiben. (Bei Neuinstallation ändert sich die
  anonyme uid → einmal neu eintragen. Optional später: echtes Login statt anonym.)

## Schreiben (nur Kurator) — `/rest/v1/song_intros`
Header bei JEDEM Schreib-Request:
```
apikey: <ANON_KEY>
Authorization: Bearer <access_token>     # User-JWT (das gleiche wie bei practice_markers)
```

**Speichern eines Song-Anfangs = pro Song ersetzen** (idempotent):
1. Alte Töne löschen:
   ```http
   DELETE /rest/v1/song_intros?song_id=eq.<ID>
   ```
2. Neue Töne einfügen (idx 1..N selbst vergeben, in Spielreihenfolge):
   ```http
   POST /rest/v1/song_intros
   Content-Type: application/json
   [
     {"song_id":"5iZfKj","idx":1,"midi":38,"beat":0.0,"duration_beats":0.5,"string":3,"fret":0,"note_name":"D2"},
     {"song_id":"5iZfKj","idx":2,"midi":45,"beat":1.0,"string":4,"fret":2,"note_name":"A2"}
   ]
   ```
- **`midi` ist Pflicht** (klingende Tonhöhe) — BassTrainer rechnet sie aus
  Saite+Bund: `midi = open[string] + fret` mit `open = {1:28(E1),2:33(A1),3:38(D2),4:43(G2)}`.
- `string`/`fret`/`note_name`/`duration_beats` optional (für Anzeige/Pflege).
- `beat` = Viertel ab Takt-1-Downbeat (`0.0` = erster Schlag; Auftakt negativ).
- Nicht-Kuratoren bekommen **403** → in der UI sauber abfangen (nur Owner kuratiert).

## Aufnahme-/Korrektur-Flow (wie gehabt)
1. Song wählen (`song_id`, `bpm` aus `songs`).
2. Einzähler im Songtempo; Downbeat Takt 1 = `t0`.
3. Einspielen → pro Onset: `beat = (onset_t − t0)·bpm/60` (quantisieren),
   klingende `midi` (oktav-wackelig → plausible Basslage, Oktave editierbar),
   `midi → Saite/Bund` vorschlagen.
4. Korrektur-UI (Saite/Bund/Beat/Dauer editieren, add/del/move, Notenname,
   Vorschau abspielbar).
5. **Speichern** → DELETE+POST wie oben.

## Lesen (unverändert, öffentlich)
```http
GET /rest/v1/song_intro_public?song_id=eq.<ID>&order=idx
```
→ `{song_id, idx, midi, beat, duration_beats, string, fret, note_name}`.
Leeres Ergebnis = noch kein Anfang → Song in der Übung überspringen/markieren.

## Grenzen
- Schreibrecht **nur** auf `song_intros` und **nur** für Kuratoren. Alles andere
  bleibt read-only. Kein `service_role` im Client.
- Monophon (ein Ton pro `idx`).
