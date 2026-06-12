-- Public-read RLS policies for the shared song catalog.
--
-- The project was created with "automatic RLS", so every table has RLS enabled
-- but no policies -> the anon/publishable key (used by BassTrainer in the
-- browser) is denied. These policies open READ access to the non-sensitive
-- catalog. Writes get NO policy, so they stay service_role-only.
--
-- Idempotent: drop-then-create so it can be re-applied safely.

alter table songs                enable row level security;
alter table song_detail_lighting enable row level security;
alter table bars                 enable row level security;
alter table accents              enable row level security;
alter table app_state            enable row level security;
alter table audio_assets         enable row level security;

drop policy if exists "public read songs"        on songs;
drop policy if exists "public read song_detail"  on song_detail_lighting;
drop policy if exists "public read bars"         on bars;
drop policy if exists "public read accents"      on accents;
drop policy if exists "public read app_state"    on app_state;
drop policy if exists "public read public audio" on audio_assets;

create policy "public read songs"       on songs                for select using (true);
create policy "public read song_detail" on song_detail_lighting for select using (true);
create policy "public read bars"        on bars                 for select using (true);
create policy "public read accents"     on accents              for select using (true);
create policy "public read app_state"   on app_state            for select using (true);

-- audio_assets: expose only the public-audio kinds. Future private rehearsal
-- recordings (kind='rehearsal') stay hidden from the anon key.
create policy "public read public audio" on audio_assets
  for select using (kind in ('snippet', 'playalong'));

-- NOTE: feature_vectors and transcripts intentionally get NO public policy
-- (private / not needed by BassTrainer).
