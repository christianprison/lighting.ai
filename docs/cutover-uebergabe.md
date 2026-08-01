# Übergabe: Supabase-Cutover der DB-Pflege-App (Option B)

> **✅ CUTOVER ABGESCHLOSSEN (2026-08-01).** Alle 6 Schritte durchgeführt und
> verifiziert — siehe „Status nach Durchführung" ganz unten. Dieses Dokument
> bleibt als historischer Kontext/Referenz stehen (Architektur-Leitplanke,
> Auth-Entscheidung, Dateirollen).

## TL;DR

Die DB-Pflege-App speichert bisher direkt über die **GitHub-API** (JSON-Blob
`db/lighting-ai-db.json`). Ziel des Cutovers: Die WebApp schreibt stattdessen
nach **Supabase** (Postgres) — auf **unserem** Schema, mit sicherem Schreibzugriff
und Locking. Die Live-App liest weiter aus Git, wird also über einen
**Supabase→Git-Export** versorgt. BassTrainer (Read-only-Konsument) bleibt heil.

**Wichtig:** Der akute Datenverlust-Bug ist bereits behoben (Option A, s.u.).
Der Cutover ist ein *Architektur-Upgrade*, kein Notfall — sauber und in Ruhe machen.

## Was bereits erledigt ist (Option A — gemergt)

- **v2026.06.30-save1** (PR #418, in `main`): Konfliktsicheres Speichern in
  `js/db.js` + `js/app.js`.
  - `saveDB()` überschreibt bei GitHub-409 **nicht** mehr blind (das war der
    Lost-Update-Datenverlust). Wirft `err.isConflict`; Überschreiben nur mit
    explizitem `force=true`.
  - `handleSave()` → `handleSaveConflict()`: Dialog „fremde Version laden" vs.
    „eigene erzwingen"; sonst bleibt `dirty` (nichts geht verloren).
  - `initTabGuard()` (BroadcastChannel): warnt bei mehreren offenen Tabs.

## Supabase-Ist-Zustand (am 2026-08-01 per anon-Key verifiziert)

Projekt: `https://ivkcvvjtwwfommsnxerv.supabase.co` (EU/Frankfurt).

**✅ Unsere Daten sind vollständig intakt:**

| Objekt | Status |
|---|---|
| `songs` | da (~51) |
| `bars` | 3462 Zeilen |
| `accents` | 283 Zeilen |
| `app_state` | ok (speist die View) |
| `setlist_public` (View) | funktioniert |
| `practice_markers` | existiert (RLS-leer ohne Login = korrekt) |

**⚠️ Vier Fremd-Tabellen** hat eine frühere „normale" Chat-Session angelegt —
sie gehören **nicht** zu unserem Schema und sind leer/Stubs:
`parts` (leer), `setlists` (1 leere Stub-Zeile), `setlist_items` (leer),
`meta` (`{"k":"version","v":"1.0"}`). Sie haben **nichts überschrieben** —
reiner Ballast. Werden beim Cutover gedroppt (Schritt 2).

**❔ Offen (nicht kritisch):** Storage — ist neben Bucket `snippets` ein
neuer `audio`-Bucket dazugekommen? (Kurzer Blick im Supabase-Dashboard → Storage.)

## Architektur-Leitplanke (NICHT verletzen)

**Unser Schema ist der Master.** Es ist das, was BassTrainer bereits liest
(`setlist_public`, `songs`), was `scripts/central_db/sync_to_supabase.py` +
`verify_supabase.py` pflegen und was verlustfrei mit `db/lighting-ai-db.json`
abgleichbar ist. Tabellen (siehe `supabase/migrations/`):

- `songs`, `song_detail_lighting`, `bars`, `accents`, `app_state`
- View `setlist_public` (Migration 0003) — BassTrainer-Schnittstelle
- `practice_markers` (Migration 0005, per-User via Supabase Anonymous Auth)
- `curators` (Migration 0008) — für Owner-Schreibzugriff gedacht

→ **Die relationalen Fremd-Tabellen `parts`/`setlists`/`setlist_items`/`meta`
NICHT verwenden.** Sie zu benutzen würde BassTrainer brechen und unser Modell
zerreißen. Auf unserem Schema aufbauen.

## Cutover-Plan (6 Schritte)

1. **Schreib-/Auth-Modell festlegen** ← *offene Entscheidung, s.u.* — muss vor
   allem anderen geklärt sein, prägt Schritte 3+4.
2. **Aufräumen:** `drop table parts, setlists, setlist_items, meta;` (im
   Supabase SQL Editor; als Migration `supabase/migrations/00NN_drop_stubs.sql`
   ablegen).
3. **RLS-Schreibpolicies** für unser Schema: Schreiben (`insert/update/delete`
   auf `songs`/`bars`/`accents`/`song_detail_lighting`/`app_state`) nur für den
   autorisierten Nutzer — gemäß gewähltem Auth-Modell (Curator-uid).
4. **WebApp-Persistenz umstellen** (`js/db.js` + Aufrufer in `js/app.js`):
   statt `PUT` auf GitHub → Upsert der Zeilen nach Supabase. Die
   JSON→Zeilen-Abbildung existiert schon in `scripts/central_db/sync_to_supabase.py`
   — nach JS portieren. UX/In-Memory-Modell der App bleibt gleich; nur das
   Backend wechselt. Locking über `app_state.updated_at` (optimistic) statt des
   bisherigen SHA-Konflikts.
5. **Supabase→Git-Export** (GitHub Actions Workflow, Umkehrung von
   `.github/workflows/sync-db.yml`): regeneriert `db/lighting-ai-db.json` aus
   Supabase, damit die **Live-App** (liest aus Git) aktuell bleibt.
   Baustein: `scripts/central_db/export_from_supabase.py` ist vorhanden.
6. **Verifikation:** `scripts/central_db/verify_supabase.py` (verlustfreier
   Round-Trip Supabase ↔ JSON) grün. BassTrainer-View `setlist_public` unverändert.

## Offene Entscheidung: Wie schreibt die WebApp nach Supabase?

Lesen ist offen (anon). Schreiben muss geschützt sein (sonst kann jeder die DB
löschen). Optionen:

- **(A) Supabase-Login + curator-RLS** *(empfohlen)*: Timo meldet sich in der
  WebApp per Magic-Link/E-Mail an; seine Supabase-uid steht in `curators`
  (Migration 0008 ist dafür schon da); RLS erlaubt genau Curatoren das Schreiben.
  Sicher, sauber, passt exakt zur vorhandenen Struktur. Braucht eine kleine
  Login-UI in der WebApp.
- **(B) Edge-Function als Schreib-Proxy**: hält den service_role-Key
  serverseitig; WebApp ruft sie mit geteiltem Geheimnis. Sicher, aber mehr
  Infrastruktur. Overkill für einen Einzelnutzer.
- **(C) service_role-Key im Client**: **unsicher** — jeder, der die Seite
  öffnet, kann alles löschen. Nicht machen.

→ **Nutzer muss (A)/(B)/(C) entscheiden.** Default-Empfehlung: **(A)**.

## Relevante Dateien

| Datei | Rolle |
|---|---|
| `js/db.js` | GitHub-Persistenz (wird um/auf Supabase-Schreiben umgebaut) |
| `js/app.js` | `handleSave`/`handleSaveConflict`, `APP_VERSION` (hochzählen!) |
| `scripts/central_db/sync_to_supabase.py` | JSON→Zeilen-Mapping (nach JS portieren) |
| `scripts/central_db/export_from_supabase.py` | Supabase→JSON (für Schritt 5) |
| `scripts/central_db/verify_supabase.py` | Verlustfreier Round-Trip-Check |
| `supabase/migrations/*.sql` | Schema (0001–0008), Ausgangspunkt für neue Migrationen |
| `.github/workflows/sync-db.yml` | heutiger Git→Supabase-Sync (Vorlage/umkehren) |

## Verbindungsdaten

- URL: `https://ivkcvvjtwwfommsnxerv.supabase.co`
- REST: `…/rest/v1/<table>` mit Headern `apikey` + `Authorization: Bearer <key>`
  (PostgREST). Auth: `…/auth/v1`. Storage: `…/storage/v1`.
- **anon/Publishable-Key** (client-safe, öffentlich): vom Nutzer erfragen
  (`sb_publishable_…`). **service_role-Key** (geheim) nur serverseitig,
  niemals in den Client.
- Egress: `*.supabase.co` muss in der Umgebungs-Netzwerk-Policy (Custom +
  Default-Liste behalten) freigegeben sein, damit diese Session Supabase
  direkt erreichen kann.

## Konventionen (aus CLAUDE.md)

- Branch: `claude/DB-Pflege-App-…` (Teilprojekt-Kennung PFLICHT).
- Deploy: Merge nach `main` → GitHub Pages.
- Bei jeder Änderung `APP_VERSION` in `js/app.js` hochzählen + Cache-Bust
  (`?v=…` in `index.html`), nach dem Push die neue Version dem Nutzer nennen.
- **PRIME DIRECTIVE** (Live/Sim identisch) betrifft die Live-/Rehearsal-App —
  hier nicht direkt relevant, aber im Blick behalten.

## Nächster Schritt für die neue Session

1. Dieses Dokument + `CLAUDE.md` lesen.
2. Egress prüfen: `curl -s -o /dev/null -w '%{http_code}' -H "apikey: <anon>"
   "https://ivkcvvjtwwfommsnxerv.supabase.co/rest/v1/songs?select=song_id&limit=1"`
   → `200` = Supabase erreichbar.
3. Mit dem Nutzer das **Auth-Modell** (A/B/C) klären — das ist der Blocker für alles Weitere.
4. Dann Schritte 2–6 des Plans umsetzen, jeweils klein + verifiziert.

---

## Status nach Durchführung (2026-08-01)

**Auth-Modell-Entscheidung:** Nutzer hat sich explizit gegen Login entschieden
(„am liebsten gar keine Auth — ist nur ein Hobbyprojekt"). Umgesetzt als
**anon-Key + offene RLS-Schreibpolicies** (nicht A, nicht service_role-im-
Client wie C) — der öffentliche anon-Key darf `insert/update/delete` auf genau
`songs`/`song_detail_lighting`/`bars`/`accents`/`app_state`, sonst nichts.
Akzeptierter Trade-off: jeder mit Key+URL kann diese 5 Tabellen schreiben.

**Schritt 1–6 erledigt:**

1. ~~Auth-Modell~~ → anon + offene RLS (s.o.), kein Curator/Login-Flow gebaut.
2. **Aufräumen**: `supabase/migrations/0009_drop_stub_tables.sql` — `parts`,
   `setlists`, `setlist_items`, `meta` gedroppt (per SQL-Editor durch den
   Nutzer, verifiziert via REST: `PGRST205` auf allen vieren).
3. **RLS-Schreibpolicies**: `supabase/migrations/0010_anon_write_access.sql`
   — `anon` darf `insert/update/delete` auf den 5 Tabellen. Verifiziert per
   Insert+Delete-Roundtrip über den anon-Key.
4. **WebApp-Persistenz**: `js/db.js` spricht jetzt PostgREST statt GitHub
   Contents API (`loadDB()`/`saveDB()` ohne repo/token/path). JS-Port von
   `transform.py` (`dbJsonToRows`/`rowsToDbJson`). Optimistic Locking über
   `app_state.updated_at` statt GitHub-SHA — gleiche Konflikt-Dialog-UX in
   `js/app.js` bleibt unverändert. Löschungen werden gezielt anhand der beim
   Laden bekannten IDs geprunt (kein globales "delete all except"). Audio-
   Blobs bleiben unverändert auf GitHub. `APP_VERSION` → `v2026.08.01-supabase1`.
   Verifiziert: Load-Reconstruction matcht `db/lighting-ai-db.json`
   byte-für-byte; Save/Konflikterkennung/Prune-Diff getestet (Testzeilen
   sauber entfernt).
5. **Supabase→Git-Export**: `.github/workflows/export-db.yml` (Cron alle 15
   Min + manuell), Umkehrung von `sync-db.yml` (dessen Auto-Trigger deshalb
   entfernt wurde — nur noch manueller Not-Aus/Restore-Weg). Dabei Bug in
   `export_from_supabase.py` gefunden+gefixt: `_fetch_rows()` paginierte
   nicht (Supabase deckelt `select()` auf 1000 Zeilen, `bars` hat 3462 —
   ohne Fix wären ~2/3 der Takte beim Export verlorengegangen). Live
   getestet (Workflow-Run `30710571889`, erfolgreich, korrekt kein Commit
   da inhaltlich unverändert).
6. **Verifikation**: `scripts/central_db/verify_supabase.py` grün (51
   Songs/3462 Bars/283 Accents, verlustfrei). `setlist_public` +
   `song_lyrics_public` (BassTrainer-Views) unverändert funktionsfähig.

**Offene Kleinigkeiten (nicht blockierend):**
- Nutzer hat `service_role`-Key + DB-Passwort im Chat gepostet (für die
  Migrations-Ausführung, da direkte DB-Verbindung aus der Sandbox technisch
  blockiert war). Empfehlung an den Nutzer ausgesprochen, das DB-Passwort zu
  rotieren (Project Settings → Database → Reset database password).
- Storage-Bucket-Frage aus dem Übergabe-Dokument (`audio`-Bucket neben
  `snippets`?) weiterhin offen, unkritisch, nicht Teil dieses Cutovers.
- Alle Pushes liefen über den bestehenden `auto-merge-to-main.yml`-Workflow
  automatisch nach `main` (PRs #420–#422) — GitHub Pages hat den neuen Stand
  damit bereits live.
