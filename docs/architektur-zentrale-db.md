# Architekturentwurf v3: Zentrale Songs-/Audio-/Feature-DB für mehrere Projekte

> **Status:** Entwurf v3 — eingearbeitete Rückmeldung der BassTrainer-Session (v2 → v3).
> **Kontext:** Zentrale DB für mehrere Projekte mit eigenem Repo — u.a. **lighting.ai**
> (Lichtsteuerung Coverband THE PACT, Python/FastAPI + Vanilla-JS-WebApp) und **BassTrainer**
> (Next.js/Vercel, Audio-Play-along + RAG).
> **Owner-Entscheidungen:** (1) Geteilt werden alle vier Datenarten: Song-Stammdaten, Audio-Snippets,
> Probenmitschnitte, Detection-Features. (2) Supabase wird **Master**; lighting.ai zieht lokalen Export
> für Offline-Live-Betrieb. (3) Audio wird **nicht** in Git committet — Browser liest per signierter URL.

---

## 0. Änderungen v2 → v3 (Begründungen)

Eingearbeitete Rückmeldung der BassTrainer-Session, nach Wichtigkeit:

1. **🔴 Genau ein Schreibpfad pro Datenart + harter Cutover** (statt bidirektionalem Sync). Bidirektionaler
   Reverse-Import hätte „wer-zuletzt-gewinnt"-Überschreibungen riskiert. → Single-Writer-Invariante, Abschnitt 12.
2. **🟠 Multi-GB-RF64-Mitschnitte auf Cloudflare R2 / Backblaze B2** statt Supabase-Bucket — Egress-frei (R2),
   selten gelesen, groß. Metadaten + signierte URLs bleiben in Supabase. Das `bucket`-Feld trägt es bereits.
3. **🟠 Idempotente Importe** über `unique (bucket, storage_path)` — Re-Importe werden zu Upserts statt Duplikaten.
4. **🟡 `feature_vectors`-PK `(song_id, bar_num)` verifiziert** (siehe unten) + **kein Vektor-Index** bei dieser
   Datenmenge (linearer Scan exakt + schneller; HNSW erst bei Bedarf).
5. **🟡 `updated_at` per `moddatetime`-Trigger** automatisch pflegen (Export-Job baut auf Änderungszeit auf).
6. **🟢 Snapshot-Versionierung** (`_generated_at`, `_source`) im generierten JSON — ergänzt die Offline-Fallback-Kette.
7. **🟢 Audio raus aus Git (Lösung b):** Snippets liegen ab Phase 2 in Supabase Storage, die Pflege-App liest per
   signierter URL. Kein Git-LFS nötig, Repo bleibt schlank.

> **Verifikation zu Punkt 4:** `detection/reference_db.py` dokumentiert ausdrücklich: *„Alle bar_num-Werte sind
> absolut zum Song (Takt 1 = allererster Takt, keine Rücksetzung an Partgrenzen). Part-Zugehörigkeit ergibt sich
> aus part_name."* Die bestehende SQLite hat sogar `UNIQUE(song_id, bar_num)`. → `(song_id, bar_num)` ist der
> korrekte PK; `part_name` ist abgeleitetes Label, kein PK-Bestandteil.

---

## 0a. Implementierungs-Refinements v3.1 (Phase 1 umgesetzt)

Bei der Umsetzung von Phase 1 (Import-Transform + Round-Trip-Test) ergaben sich
aus der echten Datenanalyse drei Präzisierungen gegenüber dem §5-Schema:

1. **`bars` und `accents` werden normalisiert** (eigene Tabellen mit FK statt im
   JSONB). Grund: die realen Daten sind perfekt regulär (alle Kernfelder in allen
   2562 Bars / 280 Accents präsent), und die Live-Pipeline braucht
   `UNIQUE(song_id, bar_num)` als echte Constraint. `instrumental` ist „emit-if-true"
   (198 Bars, immer `True`).
2. **`song_detail_lighting.detail`** ist ein **sparses JSONB** mit ausschließlich
   den lighting-spezifischen Song-Feldern (split_markers, tms, qlc_parts, qlc_id,
   audio_ref(_name), lyrics_raw, total_bars, anchors, grundrhythmus, _lrclib_synced).
   Alle 10 Core-Felder sind in allen 51 Songs präsent → saubere Spalten-Trennung
   ohne Null/Absent-Ambiguität.
3. **`app_state`** (Singleton-Zeile) hält die globalen Teile, die §5 keinen Platz
   gab: `version`, `band`, `setlist`, `meta`.

**Verlustfreiheit bewiesen** (`tests/python/test_roundtrip.py`): JSON → Rows → JSON
ist semantisch identisch. *Byte*-Identität zur Quelle ist nicht möglich, weil die
bestehende Datei vier historische Bar-Key-Reihenfolgen enthält (kosmetisch); der
Export emittiert eine kanonische Reihenfolge (Mehrheit: `song_id` zuerst). Folge:
der **erste** Export reordnet einmalig einige Bar-Keys, danach ist der Export ein
stabiler Fixpunkt (keine Diff-Churn). Schema: `supabase/migrations/0001_initial_schema.sql`;
Transform: `scripts/central_db/transform.py`.

## 1. Zielbild in einem Satz

Strukturierte Metadaten in **Postgres (Supabase)**, kleine Audio-Snippets in **Supabase Storage**, große
RF64-Mitschnitte in **R2/B2** (Egress-frei), Detection-Features als **pgvector**-Vektoren — und lighting.ai
bekommt aus dem Postgres-Master einen **regenerierten lokalen JSON-Snapshot**, damit die Live-Lichtsteuerung
vollständig **offline** bleibt. **Genau ein Schreibpfad pro Datenart.**

---

## 2. Leitprinzipien

1. **Audio nie als BLOB in die SQL-DB.** Storage hält die Datei, Postgres nur Key + Metadaten.
2. **Gemeinsamer Kern, projektspezifische Ränder.** Ein schlankes `songs` für alle; projektspezifische
   Strukturen (lighting.ai-Lichtdaten) als JSONB-Erweiterung.
3. **Master in der Cloud, aber Live läuft lokal.** Supabase ist Source of Truth. Echtzeit-/Offline-kritische
   Systeme (lighting.ai-Live-App) halten lokalen Snapshot und lesen **nie** synchron aus der Cloud.
4. **Genau ein Schreibpfad pro Datenart.** Kein bidirektionaler Sync; Übergänge nur per hartem Cutover (Abschnitt 12).
5. **RAG-ready, aber projektabhängig aktiv.** Embedding-Felder für BassTrainer; lighting.ai nutzt native
   Audio-Feature-Vektoren (Chroma/MFCC) — beide in pgvector, unterschiedliche Dimension.
6. **Secrets nur serverseitig** (Service-Role-/LLM-Keys nie im Browser-Bundle).
7. **Stabile fachliche IDs** — bestehende Song-IDs bleiben Primary Key, keine UUID-Migration.

---

## 3. Technologie-Empfehlung

**Supabase (EU/Frankfurt)** als Plattform (Postgres, pgvector, Storage für Snippets, Auth, RLS) +
**Cloudflare R2** (oder Backblaze B2) für die großen RF64-Mitschnitte (S3-kompatibel, Egress-frei). Beide
S3-Buckets werden über dasselbe `audio_assets`-Schema referenziert; signierte URLs erzeugt jeweils der
Server-Code.

---

## 4. Systemüberblick

```
   ┌─────────────────── Supabase (EU/Frankfurt) ─── METADATEN-MASTER ──────────────┐
   │  Postgres:  songs (Kern)  +  song_detail_lighting (JSONB)                     │
   │             audio_assets  (Snippets + Mitschnitte, ein Modell, bucket-Feld)   │
   │             feature_vectors (pgvector: chroma(12)/mfcc(20))                   │
   │             transcripts   (pgvector 1536 — NUR BassTrainer/RAG)               │
   │  Storage:   bucket "snippets" (klein, MP3, signierte URLs)                    │
   │  Auth + RLS                                                                   │
   └──────┬──────────────────────┬──────────────────────────┬─────────────────────┘
          │ Export-Job            │ direkter Zugriff          │ signierte URL
          ▼ (unidirektional)      ▼ (Browser/Projekte)        ▼
   ┌──────────────────────┐  ┌──────────────────┐   ┌──────────────────────────────┐
   │ Git-Repo lighting.ai │  │ DB-Pflege-App     │   │ Cloudflare R2 / B2            │
   │ db/lighting-ai-db.json│ │ (GitHub Pages)    │   │ bucket "recordings" (GB,RF64) │
   │   = GENERATED snapshot│ │ Supabase JS-Client│   │ privat, Egress-frei           │
   │   (KEIN Audio in Git) │ │ liest Snippet-URLs│   └──────────────────────────────┘
   └──────────┬───────────┘  └──────────────────┘
              │ git pull (db_cache.py UNVERÄNDERT)
              ▼
   ┌──────────────────────────────────────────┐
   │ Live-Laptop (offline-fähig)               │
   │  reference.db LOKAL (Audio-Thread @25Hz)  │
   │  liest JSON-Snapshot, nie synchron Cloud  │
   └──────────────────────────────────────────┘
```

**Begründung Export-Pfad:** lighting.ai hat eine 4-stufige Offline-Fallback-Kette in `db_cache.py`
(git pull → GitHub-API → Repo-Kopie → stale Cache). Der Export-Job schreibt weiterhin nur `lighting-ai-db.json`
ins Repo → die Kette läuft **unverändert**. Die Live-App braucht zur Show **kein** Snippet-Audio (sie steuert
Licht via OSC; Audio-Features liegen lokal in `reference.db`) — deshalb ist „Audio raus aus Git" für den
Offline-Betrieb unkritisch.

---

## 5. Datenmodell

```sql
create extension if not exists vector;
create extension if not exists moddatetime;   -- für updated_at-Trigger

-- (1) Gemeinsamer Song-Kern — das lesen ALLE Projekte
--     text-PK: bestehende lighting.ai-IDs ("dgSleW") bleiben (Pfade/Anker hängen daran)
create table songs (
  id            text primary key,
  name          text not null,
  artist        text,
  bpm           int,
  music_key     text,                      -- Tonart, z.B. "D dur" / "Am"
  year          text,
  duration_sec  int,
  notes         text,
  updated_at    timestamptz not null default now()
);
create trigger songs_set_updated_at
  before update on songs
  for each row execute function moddatetime(updated_at);

-- (2) lighting.ai-spezifisch: komplette Nested-Struktur als JSONB.
--     BassTrainer ignoriert diese Tabelle vollständig.
--     Optionaler CHECK fängt grob kaputte Strukturen früh ab.
create table song_detail_lighting (
  song_id       text primary key references songs(id) on delete cascade,
  parts         jsonb,    -- Parts inkl. Bars/Accents/Light-Templates
  anchors       jsonb,    -- geordnete Anker-Liste
  grundrhythmus jsonb,    -- {"kick":[0.0,2.0],"snare":[1.0,3.0]}
  setlist       jsonb,
  updated_at    timestamptz not null default now(),
  constraint anchors_is_array check (anchors is null or jsonb_typeof(anchors) = 'array')
);
create trigger song_detail_set_updated_at
  before update on song_detail_lighting
  for each row execute function moddatetime(updated_at);

-- (3) EIN Audio-Modell für Snippets UND Mitschnitte. bucket-Feld trennt Storage-Backends.
--     unique(bucket, storage_path): natürlicher Idempotenz-Schlüssel → Re-Importe = Upserts.
create table audio_assets (
  id            uuid primary key default gen_random_uuid(),
  song_id       text references songs(id) on delete set null,   -- Snippet→Song; Mitschnitt evtl. NULL
  kind          text not null check (kind in ('snippet','playalong','rehearsal')),
  bucket        text not null,             -- 'snippets' (Supabase) | 'recordings-r2' (R2/B2)
  storage_path  text not null,             -- Key im jeweiligen Bucket
  bar_num       int,                       -- nur Snippets (absolut, 1-based)
  part_id       text,                      -- nur Snippets
  channels      int,                       -- 18 bei Mitschnitten, 2/1 bei Play-along
  duration_sec  int,
  recorded_at   timestamptz,
  created_at    timestamptz not null default now(),
  unique (bucket, storage_path),
  unique (song_id, kind, part_id, bar_num)  -- zweiter Idempotenz-Schlüssel für Snippets
);

-- (4) Detection-Features als echte Vektoren — pgvector für lighting.ai (NICHT RAG).
--     PK (song_id, bar_num) verifiziert: bar_num absolut zum Song, keine Part-Rücksetzung.
--     KEIN Vektor-Index: bei Repertoire-Größe (paar tausend Takte) ist linearer Scan exakt + schneller.
--     Falls je nötig: HNSW statt ivfflat, und erst NACH dem Daten-Load bauen.
create table feature_vectors (
  song_id       text not null references songs(id) on delete cascade,
  bar_num       int not null,
  part_name     text,                      -- abgeleitetes Label
  chroma        vector(12),
  mfcc          vector(20),
  rms           real,
  sample_count  int default 1,             -- inkrementelles Averaging
  primary key (song_id, bar_num)
);

-- (5) RAG-Transkripte — NUR BassTrainer. lighting.ai befüllt diese Tabelle nicht.
--     Ebenfalls (vorerst) ohne Vektor-Index, solange die Sammlung klein ist.
create table transcripts (
  id             uuid primary key default gen_random_uuid(),
  audio_asset_id uuid not null references audio_assets(id) on delete cascade,
  chunk_text     text not null,
  ts_start       numeric,
  ts_end         numeric,
  embedding      vector(1536),
  created_at     timestamptz not null default now()
);
```

**Abbildung der Anforderungen:**
- *Gemeinsame Songliste (beide Projekte)* → `select * from songs`
- *lighting.ai-Lichtstruktur* → Join `song_detail_lighting` (JSONB) — projektlokal
- *Snippets / Play-along / Mitschnitte* → `audio_assets` nach `kind`/`bucket`, Datei aus passendem Storage-Backend
- *lighting.ai Takt-Matching* → Cosine-Suche in `feature_vectors.chroma` (linearer Scan)
- *BassTrainer-RAG* → Embedding-Suche in `transcripts`, Join auf `audio_assets`

---

## 6. Integration je Projekt

### 6a. lighting.ai (Python/FastAPI + Vanilla-JS, offline-kritisch)

- **DB-Pflege-App (Browser, GitHub Pages):** bekommt den **Supabase-JS-Client** (Anon-Key + RLS).
  - Snippet-Audio wird **per signierter URL** geladen (nicht mehr aus Repo-Pfaden) → **kein Audio in Git**.
  - Neue Snippets werden direkt in den Supabase-`snippets`-Bucket hochgeladen.
  - Metadaten-Schreiben: siehe Cutover (Abschnitt 12).
- **Export-Job** `scripts/export_from_supabase.py` (unidirektional Supabase → Git):
  1. liest `songs` + `song_detail_lighting`
  2. rekonstruiert die `lighting-ai-db.json`-Struktur, ergänzt `"_generated": true`, `"_generated_at"`, `"_source"`
  3. committet **nur die JSON** ins Repo (kein Audio) → `db_cache.py` zieht sie wie gewohnt
- **Live-App:** **keine** Codeänderung an `db_cache.py`; liest den committeten Snapshot. Braucht zur Show kein Snippet-Audio.
- **reference.db** bleibt **lokal**; optional aus `feature_vectors` vorab generiert, aber zur Laufzeit nie
  synchron aus der Cloud (Echtzeit + Prime Directive: Simulation und Live fahren denselben deterministischen,
  offline-fähigen Code).

### 6b. BassTrainer (Next.js/Vercel) — wie v1/v2

- `lib/supabase/{client,server}.ts`, `lib/songs/{types,queries}.ts`, gekapselt (v0-sync-schonend).
- Streaming via kurzlebiger signierter URL aus privatem Bucket (R2 für große Dateien).
- RAG-Ingestion asynchron (Edge Function / Cron / lightning.AI-Job), nicht im Request-Pfad.

### Env-Variablen
```
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...        # nur Server
R2_ACCOUNT_ID=... / R2_ACCESS_KEY_ID=... / R2_SECRET_ACCESS_KEY=...   # nur Server, große Mitschnitte
OPENAI_API_KEY=...                   # nur BassTrainer-RAG
```

---

## 7. RAG-Pipeline (Phase 2, **nur BassTrainer**)

Unverändert: Upload → Whisper-Transkription → Chunking → Embedding → Cosine-Query → LLM-Antwort mit Zeitmarke.
**lighting.ai nimmt nicht teil** — dessen „Suche" ist Anker-/Feature-Matching über `feature_vectors`, kein Text-RAG.

---

## 8. Sicherheit & Datenschutz

- **RLS auf allen Tabellen.** `songs` + Snippets öffentlich lesbar (Pflege-App läuft offen auf GitHub Pages).
  **Bucket `recordings-r2` privat** — Probenmitschnitte enthalten Bandmitglieder = personenbezogene Daten.
- **Service-Role- / R2-Keys** nur serverseitig.
- **EU-Region** (Supabase Frankfurt; R2 EU-Jurisdiktion wählen).
- **Kurzlebige signierte URLs** für privaten Zugriff.

---

## 9. Migration der Bestände

| Quelle | Ziel | Hinweis |
|---|---|---|
| `db/lighting-ai-db.json` (~800 KB) | `songs` + `song_detail_lighting` | IDs 1:1 übernehmen |
| `audio/{song}/.../bar_NNN.mp3` | Supabase Bucket `snippets` + `audio_assets` | danach aus Git entfernen (Lösung b) |
| `live/data/recordings/**/*.wav` (GB, RF64) | R2 Bucket `recordings-r2` + `audio_assets` | nicht transcoden, mehrkanalig, privat |
| `reference.db` feature_vectors | `feature_vectors` | chroma vector(12), mfcc vector(20) |
| BassTrainer-Bestände | `songs` / `audio_assets` | wie v1 |

---

## 10. Umsetzungsphasen

| Phase | Inhalt | Ergebnis |
|---|---|---|
| 0 | Supabase-Projekt (EU) + R2-Bucket, Schema (Abschnitt 5), Env-Vars | Infrastruktur |
| 1 | Import `lighting-ai-db.json` → `songs` + `song_detail_lighting` | Stammdaten zentral |
| 2 | Snippets → `snippets`-Bucket + `audio_assets`; Pflege-App auf **signierte URLs** umstellen; Audio aus Git entfernen | Audio geteilt, Git schlank |
| 3 | **Export-Job** Supabase → `lighting-ai-db.json` + Git (unidirektional) | Offline-Live gesichert |
| 4 | Mitschnitte (RF64) → R2 `recordings-r2` + `audio_assets` (privat) | Mitschnitte geteilt |
| 5 | `reference.db` → `feature_vectors` (pgvector, ohne Index) | zentrale Feature-Pflege |
| 6 | BassTrainer-Anbindung + RAG-Ingestion + Such-UI | semantische Suche (BassTrainer) |
| 7 | **Cutover:** Pflege-App schreibt Metadaten direkt nach Supabase | Supabase final Master |

---

## 11. Offene Punkte / Entscheidungen

- [ ] **Export-Trigger:** manuell nach Pflege-Session, Cron, oder DB-Webhook auf `updated_at`-Delta?
- [ ] **Feature-Spiegelung:** `reference.db` aus `feature_vectors` als Setup-/Build-Schritt generieren
      (Echtzeit-Lesen bleibt lokal).
- [ ] **Auth-Tiefe:** öffentliche Songs/Snippets genügen — oder Bandmitglieder-Rollen für Mitschnitte?
- [ ] **R2 vs. B2** final wählen (R2: Zero-Egress + Cloudflare-Ökosystem; B2: günstigerer Speicher).
- [ ] **Embedding-Modell/-Dimension** für BassTrainer-`transcripts` festlegen (1536 ist Platzhalter).
- [ ] **JSONB-Validierung:** reicht der einfache `anchors_is_array`-CHECK, oder volles JSON-Schema (z.B. via `pg_jsonschema`)?

---

## 12. Harte Invarianten (für alle anschließenden Projekte)

> **(A) Genau ein Schreibpfad pro Datenart — Übergänge nur per hartem Cutover.**
> Kein bidirektionaler Sync. Konkret lighting.ai-Metadaten:
> - **Vor Cutover (Phase 1–6):** Git ist Master; Pflege-App schreibt JSON→Git; Supabase wird nur importiert;
>   **Export-Job ist AUS.**
> - **Cutover (Phase 7):** einmaliger letzter Import, dann Pflege-App auf Supabase-Direktschreiben umstellen.
> - **Nach Cutover:** Supabase ist Master; Export-Job läuft **strikt unidirektional** Supabase → `lighting-ai-db.json`;
>   die generierte Datei trägt `"_generated": true` + Header „GENERATED — do not edit by hand" und wird **nie**
>   von Hand editiert.
> - **Nie beide Richtungen gleichzeitig aktiv.**
>
> *Audio (Snippets) ist eine eigene Datenart mit eigenem Single-Writer:* ab Phase 2 schreibt die Pflege-App
> Snippets direkt in den Supabase-Bucket; Git enthält **kein** Audio mehr.
>
> **(B) Echtzeit-/Offline-kritische Systeme lesen niemals synchron aus Supabase.**
> Sie halten einen lokalen Snapshot (lighting.ai: regenerierte `lighting-ai-db.json` + lokale `reference.db`)
> und funktionieren vollständig ohne Internet. Der `"_generated_at"`-Marker erlaubt der Live-App, veraltete
> Snapshots zu erkennen (ergänzt die Fallback-Kette in `db_cache.py`). Supabase ist Master für Pflege und
> projektübergreifendes Teilen — **nicht** der Laufzeitpfad einer Live-Bühnenshow.
