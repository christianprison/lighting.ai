-- Private practice markers for the BassTrainer app.
--
-- BassTrainer is read-only on the shared catalog; this is the ONE table it may
-- write. Per-user isolation via Supabase Anonymous Auth: each device signs in
-- anonymously and gets a JWT whose auth.uid() owns its rows. RLS guarantees a
-- user only ever sees/changes their own markers.
--
-- PREREQUISITE (Dashboard): Authentication → Providers → "Anonymous sign-ins" = ON.
--
-- Contract matches the BassTrainer handoff. Additive (non-breaking) extras vs.
-- that spec — the client may ignore them: `note` (optional free text),
-- `updated_at`, and a start/end sanity CHECK.

create table if not exists public.practice_markers (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid(),
  song_id     text not null references public.songs(id) on delete cascade,
  start_bar   int  not null,
  end_bar     int  not null,
  reason      text not null check (reason in ('speed','precision','timing','shift','other')),
  note        text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  constraint practice_markers_bar_range check (start_bar >= 1 and end_bar >= start_bar)
);

create index if not exists practice_markers_user_song_idx
  on public.practice_markers (user_id, song_id);

create trigger practice_markers_set_updated_at
  before update on public.practice_markers
  for each row execute function moddatetime(updated_at);

alter table public.practice_markers enable row level security;

-- Each user sees/changes ONLY their own markers.
create policy markers_select on public.practice_markers
  for select using (auth.uid() = user_id);
create policy markers_insert on public.practice_markers
  for insert with check (auth.uid() = user_id);
create policy markers_update on public.practice_markers
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy markers_delete on public.practice_markers
  for delete using (auth.uid() = user_id);

-- Anonymous sign-in users carry the `authenticated` role (with is_anonymous=true).
grant select, insert, update, delete on public.practice_markers to authenticated;
