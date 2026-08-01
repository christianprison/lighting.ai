-- Drop stub tables left over from an earlier, unrelated chat session.
--
-- `parts`, `setlists`, `setlist_items`, `meta` are NOT part of our schema
-- (see docs/cutover-uebergabe.md). They were verified empty/stub-only on
-- 2026-08-01 and never overwrote our data. Our schema keeps parts implicit
-- (song_detail_lighting.detail.split_markers), setlist in app_state.setlist,
-- and meta in app_state.meta/version/band — these tables are pure ballast.

drop table if exists public.setlist_items;
drop table if exists public.setlists;
drop table if exists public.parts;
drop table if exists public.meta;
