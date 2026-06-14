-- Sync helper RPCs for the Git -> Supabase auto-sync (service_role only).
--
-- The sync upserts the current catalog, then calls these to DELETE rows that no
-- longer exist in the source JSON. PK lists travel in the POST body (RPC args),
-- so there is no URL-length limit even for thousands of bars.
--
-- Safety: each delete is guarded by `array_length(...) is not null` so an empty
-- list can never wipe a whole table (a bug/empty import is a no-op, not a purge).
-- Not callable by anon/authenticated — only service_role (used by the Action).

create or replace function public.prune_catalog(
  p_song_ids   text[],
  p_bar_ids    text[],
  p_accent_ids text[]
) returns void
language sql
security definer
set search_path = public
as $$
  delete from accents
    where array_length(p_accent_ids, 1) is not null
      and accent_id <> all(p_accent_ids);
  delete from bars
    where array_length(p_bar_ids, 1) is not null
      and bar_id <> all(p_bar_ids);
  delete from songs
    where array_length(p_song_ids, 1) is not null
      and id <> all(p_song_ids);
$$;

create or replace function public.prune_audio_assets(p_paths text[])
returns void
language sql
security definer
set search_path = public
as $$
  delete from audio_assets
    where kind in ('snippet', 'playalong')        -- never touch private 'rehearsal'
      and array_length(p_paths, 1) is not null
      and storage_path <> all(p_paths);
$$;

revoke execute on function public.prune_catalog(text[], text[], text[]) from public;
revoke execute on function public.prune_audio_assets(text[]) from public;
grant  execute on function public.prune_catalog(text[], text[], text[]) to service_role;
grant  execute on function public.prune_audio_assets(text[]) to service_role;
