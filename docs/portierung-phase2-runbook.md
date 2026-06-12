# Runbook — Phase 2: Audio-Snippets + Songs für BassTrainer

Ziel: die Audio-Dateien in Supabase Storage bringen und als `audio_assets`
registrieren, damit die **BassTrainer-App** Songs + Snippets nutzen kann.
Die **Songs** selbst liegen schon in der `songs`-Tabelle (Phase 1).

> Es werden **527** Audio-Dateien (181 MB) hochgeladen + registriert:
> 43 Full-Song-Tracks (`kind='playalong'`) + 484 Per-Bar-Snippets
> (`kind='snippet'`). 73 alte/tote Bar-Pfade werden bewusst übersprungen.

---

## Empfohlener Weg: GitHub Action (kein Laptop, kein lokaler Ordner)

Die Audio-Dateien liegen schon im GitHub-Repo. Ein Workflow lädt sie direkt von
dort nach Supabase — du startest ihn per Knopfdruck im Browser (iPad reicht).

### 1. Zwei Secrets im GitHub-Repo hinterlegen

GitHub → Repo `christianprison/lighting.ai` → **Settings → Secrets and variables
→ Actions → New repository secret**. Zwei Stück anlegen:

| Name | Wert |
|---|---|
| `SUPABASE_URL` | `https://ivkcvvjtwwfommsnxerv.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | dein `service_role`-Key (Supabase → Settings → API Keys) |

> Secrets sind verschlüsselt und tauchen nie in Logs auf — der richtige Ort für
> den Service-Key (nicht in den Chat, nicht in den Code).

### 2. Workflow starten

GitHub → **Actions** → links **„Upload Snippets to Supabase"** → rechts
**„Run workflow"** → grünen Button **Run workflow** drücken.

Der Lauf (ein paar Minuten):
- legt den **öffentlichen** Bucket `snippets` an (falls noch nicht da),
- lädt die 527 Audio-Dateien hoch (Key = Repo-Pfad, z.B. `audio/…/…​.mp3`),
- upsertet die `audio_assets`-Zeilen (idempotent — Neustart unschädlich).

Grüner Haken = fertig.

### 3. Prüfen (Supabase SQL-Editor)

```sql
select kind, count(*) from audio_assets group by kind order by kind;
-- erwartet: playalong 43, snippet 484
```

---

## Alternative: manuell (am Laptop, ohne Action)

Wenn du lieber lokal arbeitest und das Repo ausgecheckt hast:

1. **Bucket** `snippets` (public) im Dashboard anlegen.
2. Lokalen Ordner **`audio/`** per Drag&Drop in den Bucket ziehen
   (Storage-UI übernimmt die Unterordner 1:1).
3. `supabase/seed/0002_audio_assets.sql` im SQL-Editor einfügen + **Run**
   (registriert die `audio_assets`-Zeilen).

Oder per Skript: `SUPABASE_URL=… SUPABASE_SERVICE_ROLE_KEY=… python -m
scripts.central_db.upload_audio` (lädt hoch **und** registriert in einem).

---

## So liest BassTrainer die Daten

- **Songs:** Tabelle `songs` (Kernfelder) — bereits seit Phase 1 da.
- **Audio:** Tabelle `audio_assets` → `kind`, `song_id`, `storage_path`.
  - Full-Song zum Mitspielen: `where kind='playalong'`.
  - Per-Takt-Snippet: `where kind='snippet'` (`bar_num`).
- **Datei-URL** (public bucket, Pfad URL-kodieren):
  ```
  {SUPABASE_URL}/storage/v1/object/public/snippets/{storage_path}
  ```

Beispiel-Query (Songs + Play-along-Track):
```sql
select s.id, s.name, s.artist, s.bpm, s.music_key, a.storage_path
from songs s
join audio_assets a on a.song_id = s.id and a.kind = 'playalong';
```

---

## Hinweise

- **Öffentlicher Bucket** = Lesen offen (gewollt für BassTrainer). Schreiben nur
  mit Service-Key (Action/Dashboard).
- Die großen RF64-Probenmitschnitte kommen später in einen **privaten** Bucket
  bzw. R2 (Phase 4) — hier nur die kleinen MP3s.
- Seed/Upload neu erzeugen bei DB-/Audio-Änderungen:
  `python -m scripts.central_db.generate_audio_assets_sql` bzw. Workflow erneut starten.
