-- Song intros for the BassTrainer „Anfänge lernen" exercise.
--
-- Note-level data (sounding pitch + timing) for the first notes of a song. This
-- domain does NOT exist elsewhere in lighting.ai — it is authored by hand in
-- db/song-intros.json and synced here (Git stays master). Source of truth = the
-- band's ears/tabs; nothing is derived/guessed.
--
-- `midi` = SOUNDING pitch (bass is written an octave higher than it sounds; the
-- mic hears the sounding pitch). Open strings: E1=28, A1=33, D2=38, G2=43.
-- `beat` = quarter-beats from the bar-1 downbeat (0.0 = downbeat; pickup may be
-- negative). Tempo comes from songs.bpm.

create table if not exists public.song_intros (
  song_id        text    not null references public.songs(id) on delete cascade,
  idx            int     not null,                 -- 1..N, gap-free, order of notes
  midi           int     not null check (midi between 0 and 127),
  beat           numeric not null,
  duration_beats numeric,
  string         int     check (string is null or string between 1 and 4),  -- E=1..G=4
  fret           int     check (fret is null or fret >= 0),
  note_name      text,                              -- optional convenience, e.g. "D2"
  primary key (song_id, idx)
);

alter table public.song_intros enable row level security;
create policy "public read song_intros" on public.song_intros
  for select using (true);
grant select on public.song_intros to anon, authenticated;
grant select, insert, update, delete on public.song_intros to service_role;

-- Stable public read contract (column order fixed; RLS of base table applies).
create or replace view public.song_intro_public
  with (security_invoker = on) as
select song_id, idx, midi, beat, duration_beats, string, fret, note_name
from public.song_intros;
grant select on public.song_intro_public to anon, authenticated;

-- Prune helper for the auto-sync (service_role only). Keys are "song_id|idx".
create or replace function public.prune_song_intros(p_keys text[])
returns void language sql security definer set search_path = public as $$
  delete from song_intros
   where array_length(p_keys, 1) is not null
     and (song_id || '|' || idx::text) <> all(p_keys);
$$;
revoke execute on function public.prune_song_intros(text[]) from public;
grant  execute on function public.prune_song_intros(text[]) to service_role;
