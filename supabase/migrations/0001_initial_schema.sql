-- Central-DB initial schema (v3.1) for lighting.ai + BassTrainer + future projects.
-- See docs/architektur-zentrale-db.md. Refinement vs. §5 of that doc:
--   * bars / accents are NORMALISED tables (the real data is perfectly regular
--     and the live pipeline relies on UNIQUE(song_id, bar_num)), not JSONB.
--   * song_detail_lighting holds only the sparse lighting-specific fields as a
--     JSONB `detail` blob.
--   * app_state is a singleton row for the global bits (version/band/setlist/meta).
-- The Python transform (scripts/central_db/transform.py) is the exact inverse
-- of this layout and is proven lossless by tests/python/test_roundtrip.py.

create extension if not exists vector;
create extension if not exists moddatetime;

-- ── (1) Shared song core — readable by ALL projects ────────────────────────
create table if not exists songs (
  id            text primary key,          -- existing 6-char ids ("dgSleW")
  name          text not null,
  artist        text,
  bpm           integer,
  music_key     text,                      -- JSON field "key"
  year          text,                      -- stored as text in source ("2009")
  pick          text,
  gema_nr       text,
  duration      text,                      -- "3:30"
  duration_sec  integer,
  notes         text,
  updated_at    timestamptz not null default now()
);
create trigger songs_set_updated_at
  before update on songs for each row execute function moddatetime(updated_at);

-- ── (2) lighting.ai-only song fields — sparse JSONB, opaque to other projects ─
-- detail = { split_markers, tms, qlc_parts, qlc_id, audio_ref, audio_ref_name,
--            lyrics_raw, total_bars, anchors, grundrhythmus, _lrclib_synced }
create table if not exists song_detail_lighting (
  song_id     text primary key references songs(id) on delete cascade,
  detail      jsonb not null default '{}'::jsonb,
  updated_at  timestamptz not null default now(),
  constraint anchors_is_array
    check (detail->'anchors' is null or jsonb_typeof(detail->'anchors') = 'array')
);
create trigger song_detail_set_updated_at
  before update on song_detail_lighting for each row execute function moddatetime(updated_at);

-- ── (3) Bars — normalised, FK to songs, UNIQUE(song_id, bar_num) ───────────
create table if not exists bars (
  bar_id        text primary key,          -- existing "B0001" ids
  song_id       text not null references songs(id) on delete cascade,
  bar_num       integer not null,          -- absolute to song, 1-based
  lyrics        text not null default '',
  audio         text not null default '',  -- snippet path (Phase 2 -> audio_assets)
  has_accents   boolean not null default false,
  instrumental  boolean not null default false,
  unique (song_id, bar_num)
);
create index if not exists bars_song_idx on bars(song_id);

-- ── (4) Accents — normalised, FK to bars ───────────────────────────────────
create table if not exists accents (
  accent_id   text primary key,            -- existing "A0001" ids
  bar_id      text not null references bars(bar_id) on delete cascade,
  pos_16th    integer not null,            -- 1..16
  type        text not null,               -- bl/bo/hl/st/fg ... (see app_state.meta)
  notes       text not null default ''
);
create index if not exists accents_bar_idx on accents(bar_id);

-- ── (5) Global app state — single row ──────────────────────────────────────
create table if not exists app_state (
  id          integer primary key default 1 check (id = 1),
  version     text,
  band        text,
  setlist     jsonb,
  meta        jsonb,
  updated_at  timestamptz not null default now()
);
create trigger app_state_set_updated_at
  before update on app_state for each row execute function moddatetime(updated_at);

-- ── (6) Audio assets — Phase 2 (snippets@Supabase) / Phase 4 (recordings@R2) ─
create table if not exists audio_assets (
  id            uuid primary key default gen_random_uuid(),
  song_id       text references songs(id) on delete set null,
  kind          text not null check (kind in ('snippet','playalong','rehearsal')),
  bucket        text not null,             -- 'snippets' | 'recordings-r2'
  storage_path  text not null,
  bar_num       integer,
  part_id       text,
  channels      integer,
  duration_sec  integer,
  recorded_at   timestamptz,
  created_at    timestamptz not null default now(),
  unique (bucket, storage_path),
  unique (song_id, kind, part_id, bar_num)
);

-- ── (7) Detection features — Phase 5 (pgvector, NO index at repertoire size) ─
create table if not exists feature_vectors (
  song_id       text not null references songs(id) on delete cascade,
  bar_num       integer not null,
  part_name     text,
  chroma        vector(12),
  mfcc          vector(20),
  rms           real,
  sample_count  integer default 1,
  primary key (song_id, bar_num)
);

-- ── (8) RAG transcripts — BassTrainer only ─────────────────────────────────
create table if not exists transcripts (
  id             uuid primary key default gen_random_uuid(),
  audio_asset_id uuid not null references audio_assets(id) on delete cascade,
  chunk_text     text not null,
  ts_start       numeric,
  ts_end         numeric,
  embedding      vector(1536),
  created_at     timestamptz not null default now()
);
