-- Convenience view: the setlist, flattened and joined to song details.
--
-- The setlist lives in app_state.setlist (JSONB). This view unrolls the items,
-- keeps only songs (drops 'pause' markers), joins the song core, and orders by
-- position — so a consumer (BassTrainer) needs just:  select * from setlist_public;
--
-- security_invoker = on -> the view respects the caller's RLS on the base
-- tables (app_state, songs), both of which already allow public SELECT.

create or replace view setlist_public
  with (security_invoker = on) as
select
  (item->>'pos')::int as pos,
  item->>'song_id'    as song_id,
  s.name,
  s.artist,
  s.bpm,
  s.music_key,
  s.duration_sec
from app_state a
cross join lateral jsonb_array_elements(a.setlist->'items') as item
join songs s on s.id = item->>'song_id'
where a.id = 1
  and item->>'type' = 'song'
order by pos;

grant select on setlist_public to anon, authenticated;
