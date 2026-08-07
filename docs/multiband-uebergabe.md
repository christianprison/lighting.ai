# Übergabe: Multi-Band-Fähigkeit (The Pact + Stringbreak)

> **Für Folge-Sessions** (Live-App-Session für Stringbreaks Rig, BassTrainer-
> Session für die Band-Auswahl-UI). Stand: 2026-08-07.

## TL;DR

lighting.ai verwaltet jetzt **zwei Bands** in derselben Supabase-Instanz —
**The Pact** und **Stringbreak** — mit komplett getrennten Song-Katalogen
und einem Band-Umschalter in der DB-Pflege-App. Das Datenmodell + die
DB-Pflege-App sind fertig. **Zwei Folgearbeiten sind bewusst nicht Teil
dieser Session** (anderes Repo bzw. andere Hardware/Kontext nötig) — siehe
unten.

## Was fertig ist

1. **Supabase-Schema** (`supabase/migrations/0012_multiband.sql`):
   - `bands`-Tabelle (`the_pact`, `stringbreak`), public read, kein anon-Write.
   - `songs.band_id` (FK, not null) — alle 51 Pact-Songs auf `the_pact`
     zurückdatiert.
   - `app_state`: Singleton (`id=1`) → eine Zeile PRO Band (`band_id` als PK).
   - `setlist_public`-View liefert `band_id` mit statt fix `id=1` zu joinen.
2. **DB-Pflege-App** (`js/db.js`, `js/app.js`):
   - `loadDB(bandId)`/`saveDB(data, sha, bandId, force)` — `songs`
     server-seitig per `band_id` gefiltert, `bars` server-seitig über die
     Song-ID-Liste, `accents`/`song_detail_lighting` client-seitig gefiltert
     (klein genug, vermeidet einen zweiten `bar_id in (...)`-Hop mit
     potenziell riesiger Liste).
   - Band-Umschalter im Header (`#band-switcher`), `localStorage`-persistiert.
   - **„+ Song"-Button**: legt einen neuen Song für die aktive Band an
     (Name/Artist/BPM/Key/Jahr/GEMA-Nr.) — vorher ging Song-Anlage nur per
     BandHelper-Bulk-Import.
3. **Python** (`scripts/central_db/`): `transform.py`, `export_from_supabase.py`,
   `verify_supabase.py`, `sync_to_supabase.py` sind band-aware (`--band`
   Pflichtparameter). `sync_to_supabase.py` (ohnehin nur manueller Not-Aus,
   siehe `docs/cutover-uebergabe.md`) überspringt den globalen Prune-Schritt
   automatisch, sobald mehr als eine Band existiert — `prune_catalog` (RPC,
   `0006_sync_rpc.sql`) kennt kein Band-Scoping und würde sonst beim
   Restore-aus-Git-Weg die jeweils andere Band leerräumen. **Falls dieser Weg
   je wieder gebraucht wird: `prune_catalog` müsste vorher um ein
   `p_band_id`-Argument erweitert werden — bislang nicht gebaut.**
4. **Export**: `.github/workflows/export-db.yml` exportiert jetzt beide Bands.
   The Pact bleibt `db/lighting-ai-db.json` (keine Config-Änderung für die
   laufende Live-App), Stringbreak ist neu `db/lighting-ai-db.stringbreak.json`.
5. **Stringbreak-Katalog-Import**: `scripts/central_db/import_stringbreak.py`
   liest `db/Stringbreak.json` (BandHelper-Export, lag schon im Repo, wurde
   bisher nur als Lyrics-Quelle für Pact-Songs missbraucht). Offline gegen
   die echten Daten getestet: 49 aktive Songs, 0 Errors, 34 Warnings (fehlende
   BPM/Key/Dauer bei echten Songs, GEMA-Platzhaltertext, „Stimmpause" als
   Nicht-Song erkannt). `--dry-run` ist Default, `--exclude "Name"` zum
   Überspringen einzelner Einträge, erst `--write` schreibt tatsächlich.

## Was NICHT Teil dieser Session ist (bewusst)

### 1. Live-App-Code für Stringbreaks Rig

Die Live-App ist architektonisch bereits **ein Band pro Deployment** (eigene
`config.yaml`, eigener `live/data/`-Cache) — für Stringbreak reicht rein
strukturell eine zweite Config mit
`db_path: db/lighting-ai-db.stringbreak.json`. **Aber**: die QLC+-
Funktions-Mappings sind aktuell hart im Python-Quellcode für Pacts Rig
verdrahtet, nicht datengetrieben:

- `live/server/qlc_osc.py`: `FUNCTION_TO_COLLECTION`, `DEFAULT_ACCENT_MAP`
  — "Extracted from Virtual Console buttons in lightingAI.qxw" (Kommentar
  im Code).
- `live/server/qlc_parser.py`: `ACCENT_FUNCTIONS`, `BASE_COLLECTIONS`.
- `live/server/audio/db_cache.py`: `_CACHE_FILES` sind hardcodierte
  Dateinamen (`lighting-ai-db.json`, `ThePact.qxw`) unabhängig vom
  konfigurierten Pfad — bei zwei Configs im selben `live/data/`-Verzeichnis
  würden sich die Caches überschreiben. Kein Problem, solange jede Band ihr
  eigenes Repo-Checkout/`live/data/` hat (wie ohnehin sinnvoll bei zwei
  physisch getrennten Rigs) — sonst müsste das parametriert werden.

→ Braucht eine eigene Live-App-Session, sobald Stringbreaks QLC+-Show-Datei
und Hardware-Mapping bekannt sind. `meta.qlc_scenes` (im DB-Schema schon
vorhanden, aktuell nur von der DB-Pflege-App geschrieben, von der Live-App
nie gelesen) wäre ein natürlicher Ort, die Mapping-Daten künftig
datengetrieben statt hartcodiert zu halten — aber das ist ein größerer
Umbau, kein Teil dieser Migration.

### 2. BassTrainer Band-Auswahl-UI

BassTrainer ist ein eigenes Repo, nicht Teil dieser Session. Die
Schnittstelle steht bereit:

- **`bands`** (public read): `select id, name from bands` — für einen
  Band-Umschalter.
- **`songs.band_id`**: jeder Song ist jetzt eindeutig einer Band zugeordnet.
- **`setlist_public.band_id`**: `select * from setlist_public where
  band_id = eq.<band>` statt der bisherigen ungefilterten Abfrage (die vor
  0012 automatisch nur eine Band kannte — seit 0012 liefert sie **beide**
  Bands gemischt, wenn nicht gefiltert wird!). **Das ist ein Breaking
  Change für BassTrainer, falls es `setlist_public` bisher ohne Filter
  abfragt** — muss dort nachgezogen werden.
- `song_timeline_public`/`song_parts_public`/`song_lyrics_public`/
  `song_intro_public` sind unverändert `song_id`-scoped — Band ergibt sich
  implizit darüber, welche `song_id`s BassTrainer nach der
  `setlist_public`-Abfrage kennt.

## Offene Kleinigkeiten

- `js/app.js`s lokaler Fallback-Pfad (`loadLocal()`, wenn Supabase nicht
  erreichbar ist) nutzt weiterhin den in den Settings konfigurierten
  einzelnen `path` — bandet sich nicht automatisch auf
  `lighting-ai-db.stringbreak.json` um, wenn Stringbreak aktiv ist. Seltener
  Fallback-der-Fallback-Fall, nicht kritisch; der Pfad lässt sich in den
  Settings manuell umstellen, falls es je auftritt.
- Stringbreak-Katalog ist mit diesem Handoff **vorbereitet, aber noch nicht
  geschrieben** — Migration muss zuerst im SQL-Editor laufen, dann
  `import_stringbreak.py --write` (nach `--dry-run`-Review).

## Nächste Schritte für die aktuelle Session

1. Migration `0012_multiband.sql` im Supabase SQL Editor ausführen.
2. Verifikation (bands, songs.band_id, zwei app_state-Zeilen).
3. `import_stringbreak.py --dry-run` Review, dann `--write`.
4. `export-db.yml` einmal manuell auslösen, beide Dateien prüfen.
5. Kurzer Live-Test: Band-Umschalter + „+ Song" im Browser.
