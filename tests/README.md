# Test-Harness — Absicherung der Datennaht für die zentrale-DB-Portierung

Dieser Harness deckt **gezielt die Persistenz-/Datennaht** ab, die die
Portierung auf die zentrale Supabase-DB (`docs/architektur-zentrale-db.md`)
durchschneidet — nicht den UI-Code (`js/app.js`) oder den hardwaregebundenen
Audio-/OSC-Pfad, die die Portierung gar nicht berührt.

**Vorgehen:** erst diese Tests gegen den **heutigen** Code grün bekommen
(Baseline), dann portieren. Jede Implementierung hinter der Naht (GitHub-JSON →
Supabase) muss anschließend dieselben Outputs liefern.

## Ausführen

```bash
tests/run.sh
```

Suiten, deren Abhängigkeiten fehlen, **überspringen sauber** (kein Fehler).

## Inhalt

| Datei | Deckt ab | Läuft wo |
|---|---|---|
| `js/integrity.test.mjs` | `js/integrity.js` — validate/cleanup/cascade-delete/bar-count/marker-migration | überall mit Node ≥18 (`node --test`, kein npm install) |
| `python/test_db_schema.py` | Schema von `db/lighting-ai-db.json`: eingefrorene Feld-Union (Import-Spec), referenzielle Integrität, `UNIQUE(song_id, bar_num)` | überall (nur stdlib) |
| `python/test_reference_db.py` | `detection/reference_db.py` — Song/Bar/Part/Feature-Contract gegen temp-SQLite | Laptop (braucht `numpy`) |
| `python/test_live_api.py` | Read-API-Shapes `/api/songs`, `/api/songs/{id}/bars`, `/api/setlist` | Laptop (braucht `live/requirements.txt`) |
| `python/test_roundtrip.py` | **Port-Herzstück:** `lighting-ai-db.json` → central-DB-Rows → JSON verlustfrei (`scripts/central_db/transform.py`) | überall (nur stdlib) |

## Das Herzstück: die eingefrorene Feld-Union

`test_db_schema.py` friert die **exakten** Felder ein, die heute auf
Songs/Bars/Accents existieren, und teilt die Song-Felder in den geteilten Kern
(`CORE_SONG_FIELDS` → Postgres-Tabelle `songs`) und die lighting.ai-Details
(`DETAIL_SONG_FIELDS` → `song_detail_lighting` JSONB). Taucht ein neues Feld auf
oder verschwindet eines, schlägt der Test bewusst fehl — so kann die Portierung
**kein Feld still verlieren** (z.B. `split_markers`, `tms`, `qlc_parts`).

Diese CORE/DETAIL-Aufteilung ist zugleich die **Import-Spezifikation** für
Phase 1 der Portierung.

## Nach der Portierung (Round-Trip)

Sobald Import-/Export-Code existiert, kommt der zentrale Round-Trip-Test dazu:

```
lighting-ai-db.json → import (songs + song_detail_lighting) → export → identisch
```

Er beweist die Verlustfreiheit des Schemas. Bis dahin ist `test_db_schema.py`
die Pre-Port-Hälfte dieser Garantie.

## Laptop-Setup (volle Suite)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r tests/requirements-dev.txt -r live/requirements.txt
tests/run.sh
```
