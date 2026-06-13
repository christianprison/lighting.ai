-- Public read views for the lyrics/parts/timeline contract (BassTrainer).
--
-- The raw data lives in lighting-specific places: timing + part starts in
-- song_detail_lighting.detail.split_markers (JSONB), lyrics per bar in `bars`.
-- These views flatten that into a clean, testable contract so consumers never
-- touch the JSONB. security_invoker = on -> they respect the (public-read) RLS
-- of the underlying tables.
--
-- COVERAGE: only ~21/51 songs are split (have timing + parts). Songs without a
-- split produce NO rows in song_timeline_public / song_parts_public — fall back
-- to song_lyrics_public (static lyrics_raw, ~50 songs).

-- (1) Per-bar timeline: the spine for synced lyric highlighting in play mode.
create or replace view song_timeline_public
  with (security_invoker = on) as
with mk as (
  select sd.song_id,
         ord::int                           as bar_num,
         (val->>'time')::double precision    as t_start
  from song_detail_lighting sd
  cross join lateral
    jsonb_array_elements(sd.detail->'split_markers'->'markers')
    with ordinality as m(val, ord)
),
ps as (
  select sd.song_id,
         (val->>'bar_num')::int as start_bar,
         val->>'name'           as part_name
  from song_detail_lighting sd
  cross join lateral
    jsonb_array_elements(sd.detail->'split_markers'->'part_starts') as p(val)
)
select
  mk.song_id,
  mk.bar_num,
  mk.t_start,
  lead(mk.t_start) over (partition by mk.song_id order by mk.bar_num) as t_end,
  (select ps.part_name from ps
     where ps.song_id = mk.song_id and ps.start_bar <= mk.bar_num
     order by ps.start_bar desc limit 1) as part_name,
  b.lyrics,
  coalesce(b.instrumental, false) as instrumental
from mk
left join bars b on b.song_id = mk.song_id and b.bar_num = mk.bar_num;

-- (2) Part / section list per song (Intro, Verse 1, …) with its first bar.
create or replace view song_parts_public
  with (security_invoker = on) as
select sd.song_id,
       (val->>'bar_num')::int as start_bar,
       val->>'name'           as part_name,
       val->>'light_template' as light_template   -- lighting-only, BT may ignore
from song_detail_lighting sd
cross join lateral
  jsonb_array_elements(sd.detail->'split_markers'->'part_starts') as p(val);

-- (3) Static raw lyrics (fallback for songs without a timeline). The [Part]
--     tags inside lyrics_raw double as section headers.
create or replace view song_lyrics_public
  with (security_invoker = on) as
select song_id,
       detail->>'lyrics_raw'         as lyrics_raw,
       (detail->>'total_bars')::int  as total_bars
from song_detail_lighting
where detail ? 'lyrics_raw';

grant select on song_timeline_public, song_parts_public, song_lyrics_public
  to anon, authenticated;
