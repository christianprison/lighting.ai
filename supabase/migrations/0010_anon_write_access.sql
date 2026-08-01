-- Anon write access for the DB-Pflege-App (Supabase cutover, Option B).
--
-- Hobby project, single trusted user (Timo), no login UI wanted. The anon/
-- publishable key is public by design (ships in the browser bundle); RLS is
-- what scopes what it may do. These policies grant the `anon` role full
-- insert/update/delete on exactly the 5 tables the WebApp owns — nothing
-- else in the project is affected, and the anon key still cannot touch
-- practice_markers, song_intros writes, curators, or any service_role-only
-- RPC (prune_catalog etc.).
--
-- Anyone who has the URL + anon key can write/delete on these 5 tables.
-- Accepted trade-off per project decision (2026-08-01) in favour of no login.
--
-- Idempotent: drop-then-create so it can be re-applied safely.

drop policy if exists "anon write songs"        on public.songs;
drop policy if exists "anon write song_detail"  on public.song_detail_lighting;
drop policy if exists "anon write bars"         on public.bars;
drop policy if exists "anon write accents"      on public.accents;
drop policy if exists "anon write app_state"    on public.app_state;

create policy "anon write songs" on public.songs
  for all to anon using (true) with check (true);

create policy "anon write song_detail" on public.song_detail_lighting
  for all to anon using (true) with check (true);

create policy "anon write bars" on public.bars
  for all to anon using (true) with check (true);

create policy "anon write accents" on public.accents
  for all to anon using (true) with check (true);

create policy "anon write app_state" on public.app_state
  for all to anon using (true) with check (true);

grant insert, update, delete on public.songs                to anon;
grant insert, update, delete on public.song_detail_lighting  to anon;
grant insert, update, delete on public.bars                  to anon;
grant insert, update, delete on public.accents                to anon;
grant insert, update, delete on public.app_state              to anon;
