-- Mehrere play-along-Aufnahmen pro Song unterscheidbar machen (2026-08-08).
--
-- Ausgangslage: Stringbreaks BandHelper-Katalog bringt 54 Aufnahmen für 48
-- Songs mit — viele Songs haben mehrere Varianten derselben Nummer
-- ("(original)", "(nur Axel)", "(playback)", "(live)", "(Studio)"). Bisher
-- konnte `audio_assets` diese Varianten nur über `storage_path` auseinander
-- halten, was für eine Anzeige im Song-Editor unbrauchbar ist.
--
-- `label` trägt genau diesen Varianten-Namen (der Klammer-Zusatz aus dem
-- BandHelper-Aufnahmenamen, z.B. "nur Axel"). Leer = keine Variante benannt.
--
-- Warum keine Änderung an den UNIQUE-Constraints: `unique (song_id, kind,
-- part_id, bar_num)` greift bei play-along-Zeilen ohnehin nicht, weil
-- `part_id`/`bar_num` dort NULL sind und Postgres NULLs in UNIQUE-Constraints
-- nie als gleich behandelt. Mehrere play-along-Zeilen pro Song sind damit
-- schon heute erlaubt; `unique (bucket, storage_path)` bleibt die echte
-- Dedup-Grenze und ist weiterhin das ON-CONFLICT-Ziel der Upload-Skripte.
--
-- Idempotent: if not exists / drop-then-create, beliebig oft anwendbar.

alter table public.audio_assets
  add column if not exists label text not null default '';

comment on column public.audio_assets.label is
  'Varianten-Name einer Aufnahme, z.B. "nur Axel", "original", "playback". '
  'Leer = unbenannt. Nur zur Anzeige, nicht Teil eines Schlüssels.';

-- Die bestehende Read-Policy aus 0002 zählt Spalten nicht auf (`using (kind in
-- (...))`), `label` ist damit automatisch mitgelesen. Kein Policy-Update nötig.

-- Häufigste Abfrage der DB-Pflege-App: alle play-along-Aufnahmen eines Songs.
create index if not exists audio_assets_song_kind_idx
  on public.audio_assets (song_id, kind);
