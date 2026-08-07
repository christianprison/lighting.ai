-- Anon write access to Storage + audio_assets (Option B follow-up, 2026-08-02).
--
-- The DB-Pflege-App now uploads audio directly to Supabase Storage instead of
-- GitHub, to avoid the two-different-delivery-paths class of bug that broke
-- BassTrainer playback for one song (a typographic apostrophe in the object
-- key: GitHub Pages served it fine, Supabase Storage rejected it with
-- InvalidKey). One single path for reads AND writes going forward.
--
-- Same "kein Login" trade-off as 0010, extended from the 5 catalog tables to
-- file storage and its audio_assets metadata: anyone with the (public,
-- client-embedded) anon key can upload/overwrite/delete objects in the
-- `snippets` bucket and rows in audio_assets. Accepted trade-off, matches the
-- project decision already made for the tables.
--
-- Idempotent: drop-then-create so it can be re-applied safely.
--
-- NOTE: no "alter table storage.objects enable row level security" here —
-- Supabase has RLS on storage.objects enabled by default from project
-- creation, and that specific ALTER TABLE subcommand requires table
-- ownership (which even the SQL-editor role doesn't have on storage.objects,
-- unlike CREATE POLICY, which Supabase's SQL editor role IS permitted to run).

drop policy if exists "anon write snippets objects" on storage.objects;
create policy "anon write snippets objects" on storage.objects
  for all to anon
  using (bucket_id = 'snippets')
  with check (bucket_id = 'snippets');

drop policy if exists "anon write audio_assets" on public.audio_assets;
create policy "anon write audio_assets" on public.audio_assets
  for all to anon using (true) with check (true);

grant insert, update, delete on public.audio_assets to anon;
