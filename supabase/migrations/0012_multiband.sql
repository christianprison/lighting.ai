-- Multi-Band-Fähigkeit: The Pact + Stringbreak (2026-08-07).
--
-- lighting.ai war bisher hart auf eine einzige Band zugeschnitten: `songs`
-- hatte keine Band-Zuordnung, `app_state` war ein strikter Singleton
-- (`id integer primary key default 1 check (id = 1)`) für genau eine
-- Setlist/Meta/Version. Diese Migration führt eine `bands`-Tabelle ein,
-- gibt `songs` eine `band_id`-Spalte und macht `app_state` zu einer Zeile
-- PRO Band statt einer globalen Singleton-Zeile. `bars`/`accents`/
-- `song_detail_lighting`/`audio_assets` brauchen KEINE eigene band_id-Spalte
-- — sie sind über `song_id` schon transitiv band-gescoped.
--
-- RLS: bestehende Schreibpolicies auf songs/app_state (0010,
-- `using(true) with check(true)`) brauchen keine Änderung — sie decken die
-- neue Spalte automatisch ab. `bands` selbst ist absichtlich nur lesbar
-- (kein anon-Write) — Bands werden selten/bewusst per Migration angelegt,
-- wie `curators` (0008).

-- ── (1) bands ────────────────────────────────────────────────────────────
create table if not exists public.bands (
  id         text primary key,   -- Slug: 'the_pact', 'stringbreak'
  name       text not null,      -- Anzeigename: 'The Pact', 'Stringbreak'
  created_at timestamptz not null default now()
);

alter table public.bands enable row level security;
drop policy if exists "public read bands" on public.bands;
create policy "public read bands" on public.bands for select using (true);
grant select on public.bands to anon, authenticated;

insert into public.bands (id, name) values
  ('the_pact', 'The Pact'),
  ('stringbreak', 'Stringbreak')
on conflict (id) do nothing;

-- ── (2) songs.band_id ───────────────────────────────────────────────────
alter table public.songs add column if not exists band_id text references public.bands(id);
update public.songs set band_id = 'the_pact' where band_id is null;
alter table public.songs alter column band_id set not null;

-- ── (3) app_state: Singleton -> eine Zeile pro Band ────────────────────
alter table public.app_state add column if not exists band_id text references public.bands(id);
update public.app_state set band_id = 'the_pact' where band_id is null and id = 1;
alter table public.app_state alter column band_id set not null;

alter table public.app_state drop constraint if exists app_state_pkey;
alter table public.app_state drop constraint if exists app_state_id_check;
alter table public.app_state drop column if exists id;
alter table public.app_state add primary key (band_id);

insert into public.app_state (band_id, version, band, setlist, meta) values
  ('stringbreak', '1.0', 'Stringbreak', '{"name": "Setlist", "items": []}'::jsonb, '{}'::jsonb)
on conflict (band_id) do nothing;

-- ── (4) setlist_public: band_id statt fixem id=1 ───────────────────────
create or replace view setlist_public
  with (security_invoker = on) as
select
  a.band_id,
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
where item->>'type' = 'song'
order by a.band_id, pos;

grant select on setlist_public to anon, authenticated;
