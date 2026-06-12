# Runbook — Phase 2: Audio-Snippets + Songs für BassTrainer

Ziel: die Audio-Dateien in Supabase Storage bringen und als `audio_assets`
registrieren, damit die **BassTrainer-App** Songs + Snippets nutzen kann.
Die **Songs** selbst liegen schon in der `songs`-Tabelle (Phase 1).

Bewusst **ohne Service-Key/Terminal** — alles über das Supabase-Dashboard +
SQL-Editor, wie in Phase 1.

> Es werden **527** Audio-Verweise registriert: 43 Full-Song-Tracks
> (`kind='playalong'`) + 484 Per-Bar-Snippets (`kind='snippet'`). 73 alte/tote
> Bar-Pfade werden bewusst übersprungen.

---

## 1. Bucket `snippets` anlegen (öffentlich)

1. Im Projekt links **Storage → New bucket**.
2. Name: **`snippets`**.
3. **Public bucket: AN** (Songs/Snippets sind kein Geheimnis → BassTrainer kann
   ohne signierte URLs lesen; das ist die einfache Variante).
4. Create.

*(Die großen RF64-Probenmitschnitte kommen später in einen separaten,
**privaten** Bucket bzw. R2 — Phase 4. Hier nur die kleinen MP3s.)*

## 2. Audio hochladen (Ordner-Drag&Drop)

1. Bucket `snippets` öffnen → **Upload** (oder den Ordner direkt ins Fenster
   ziehen).
2. Den lokalen Ordner **`audio/`** aus deinem Repo-Checkout reinziehen.
   Die Storage-UI übernimmt die Unterordner-Struktur 1:1 → die Keys werden
   `audio/{Song}/{Part}/….mp3`, also genau die Pfade aus der DB.
3. Warten bis alle Dateien (~219 MB, ~900 MP3) durch sind.

> Free-Tier-Storage: 1 GB — 219 MB passen locker.

## 3. audio_assets registrieren (SQL-Editor)

1. `supabase/seed/0002_audio_assets.sql` öffnen (kommt gleich als Datei von mir,
   liegt auch im Repo).
2. Inhalt kopieren → **SQL Editor → New query** → einfügen → **Run**.
3. Idempotent (`on conflict (bucket, storage_path) do nothing`).

**Verifikation** (neue Query):
```sql
select kind, count(*) from audio_assets group by kind order by kind;
-- erwartet: playalong 43, snippet 484
```

## 4. So liest BassTrainer die Daten

- **Songs:** Tabelle `songs` (Kernfelder) — bereits da seit Phase 1.
- **Audio:** Tabelle `audio_assets` → `kind`, `song_id`, `storage_path`.
  - Full-Song zum Mitspielen: `where kind='playalong'`.
  - Per-Takt-Snippet: `where kind='snippet'` (`bar_num`).
- **Datei-URL** (public bucket):
  ```
  {SUPABASE_URL}/storage/v1/object/public/snippets/{storage_path}
  ```
  Beispiel:
  `https://ivkcvvjtwwfommsnxerv.supabase.co/storage/v1/object/public/snippets/audio/All%20The%20Small%20Things/All%20The%20Small%20Things%20-%20Full%20Song.mp3`
  (Pfad URL-kodieren — Leerzeichen → `%20` etc.)

Beispiel-Query für BassTrainer (Songs + Play-along-URL):
```sql
select s.id, s.name, s.artist, s.bpm, s.music_key, a.storage_path
from songs s
join audio_assets a on a.song_id = s.id and a.kind = 'playalong';
```

---

## Hinweise

- **RLS/Storage:** Bei „Public bucket" ist Lesen offen — gewollt für BassTrainer.
  Schreiben in den Bucket geht nur mit Service-Key (Dashboard/Upload).
- **DB-Pflege-App auf signierte URLs umstellen** (lighting.ai-intern) ist *nicht*
  Teil dieses Ziels und kann später kommen — BassTrainer braucht es nicht.
- Seed neu erzeugen bei DB-/Audio-Änderungen:
  `python -m scripts.central_db.generate_audio_assets_sql`.
