-- Curator write access for song_intros (BassTrainer „Intro einspielen", Weg 2).
--
-- Only allow-listed users (curators) may write song_intros; everyone else keeps
-- read-only (public read policy from 0007 stays). No service_role in any client:
-- the owner's app authenticates as itself (its Supabase user uid), and that uid
-- is added to `curators`. song_intros is now Supabase-master (curator-authored),
-- so it is NO LONGER part of the Git→Supabase auto-sync.

create table if not exists public.curators (
  user_id  uuid primary key,
  note     text,
  added_at timestamptz not null default now()
);
-- Locked down: RLS on, no policies -> not reachable via the public API at all.
-- Managed only via SQL editor / service_role.
alter table public.curators enable row level security;

-- Allow-list check that bypasses RLS on `curators` (SECURITY DEFINER), so write
-- policies can consult it without exposing the table.
create or replace function public.is_curator() returns boolean
language sql security definer stable set search_path = public as $$
  select exists (select 1 from curators where user_id = auth.uid());
$$;
grant execute on function public.is_curator() to anon, authenticated;

-- song_intros: curators may insert/update/delete (public SELECT already exists).
drop policy if exists "curators insert song_intros" on public.song_intros;
drop policy if exists "curators update song_intros" on public.song_intros;
drop policy if exists "curators delete song_intros" on public.song_intros;

create policy "curators insert song_intros" on public.song_intros
  for insert with check (public.is_curator());
create policy "curators update song_intros" on public.song_intros
  for update using (public.is_curator()) with check (public.is_curator());
create policy "curators delete song_intros" on public.song_intros
  for delete using (public.is_curator());

grant insert, update, delete on public.song_intros to authenticated;

-- To make a device/user a curator (after BassTrainer shows its uid):
--   insert into curators (user_id, note) values ('<uid>', 'Christian iPad');
