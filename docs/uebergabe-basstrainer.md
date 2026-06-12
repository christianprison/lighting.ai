# Übergabe an die BassTrainer-App — zentrale Songs-/Audio-DB (Supabase)

> Für die **BassTrainer**-Session. lighting.ai hat eine zentrale Datenbank
> aufgebaut, aus der BassTrainer **Songs und Audio lesen** kann. Dieses Dokument
> ist alles, was du dafür brauchst.

## TL;DR

- Plattform: **Supabase** (Postgres + Storage), Region **EU/Frankfurt** (DSGVO).
- BassTrainer ist ein **Read-only-Konsument**: lesen ja, schreiben nein.
  lighting.ai ist alleiniger Schreiber (Single-Source-of-Truth).
- Verfügbar: **51 Songs**, **43 Full-Song-Play-along-Tracks**, **484 Per-Takt-Snippets**.

## Verbindung (im Browser)

```
SUPABASE_URL      = https://ivkcvvjtwwfommsnxerv.supabase.co
SUPABASE_ANON_KEY = <Publishable/anon-Key>
```

Den `anon`/Publishable-Key gibt dir der Projekt-Owner (Supabase → Settings →
API Keys → „Publishable" `sb_publishable_…` **oder** Legacy `anon`). Dieser Key
ist **browser-safe**. Der `service_role`/secret-Key darf **niemals** in den
BassTrainer-Client — er umgeht alle Sicherheit.

```ts
import { createClient } from "@supabase/supabase-js";
const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
);
```

## Datenmodell (nur was BassTrainer braucht)

### Tabelle `songs` — der gemeinsame Song-Kern
| Spalte | Typ | Beispiel |
|---|---|---|
| `id` | text (PK) | `"5iZfKj"` |
| `name` | text | `"Animal"` |
| `artist` | text | `"Neon Trees"` |
| `bpm` | int | `164` |
| `music_key` | text | `"D dur"` |
| `year` | text | `"2009"` |
| `duration` | text | `"3:30"` |
| `duration_sec` | int | `210` |
| `pick`, `gema_nr`, `notes` | text | (Band-Metadaten, optional) |

### Tabelle `audio_assets` — die Audio-Registry
| Spalte | Typ | Bedeutung |
|---|---|---|
| `song_id` | text (FK → songs) | zu welchem Song |
| `kind` | text | `'playalong'` (Full-Song) oder `'snippet'` (ein Takt) |
| `bucket` | text | immer `'snippets'` |
| `storage_path` | text | Key im Bucket, z.B. `audio/Animal/…​.mp3` |
| `bar_num` | int \| null | nur bei `snippet`: die Taktnummer |

> Weitere lesbare Tabellen (`song_detail_lighting`, `bars`, `accents`,
> `app_state`) sind **lighting-spezifisch** — BassTrainer kann sie ignorieren.

## Songs lesen

```ts
// Alle Songs mit ihrem Play-along-Track
const { data } = await supabase
  .from("songs")
  .select("id, name, artist, bpm, music_key, audio_assets(kind, storage_path)")
  .eq("audio_assets.kind", "playalong");
```

oder direkt per Join-Query (SQL):
```sql
select s.id, s.name, s.artist, s.bpm, s.music_key, a.storage_path
from songs s
join audio_assets a on a.song_id = s.id and a.kind = 'playalong';
```

Per-Takt-Snippets eines Songs:
```ts
const { data } = await supabase
  .from("audio_assets")
  .select("bar_num, storage_path")
  .eq("song_id", songId).eq("kind", "snippet")
  .order("bar_num");
```

## Audio abspielen (öffentlicher Bucket)

Der Bucket `snippets` ist **public** → direkte URL, keine signierten URLs nötig:

```ts
const { data } = supabase.storage.from("snippets").getPublicUrl(storage_path);
audioEl.src = data.publicUrl;
```

URL-Muster (manuell, Pfad URL-kodieren):
```
https://ivkcvvjtwwfommsnxerv.supabase.co/storage/v1/object/public/snippets/{storage_path}
```

## Wichtige Hinweise

- **Read-only:** RLS erlaubt `anon` nur `SELECT` auf den Katalog-Tabellen +
  `audio_assets` (nur `kind in ('snippet','playalong')`). INSERT/UPDATE/DELETE
  sind gesperrt. Bitte keine Schreibpfade gegen diese DB bauen.
- **Nicht jeder Song hat Audio:** 43 von 51 Songs haben einen `playalong`-Track,
  nur ein Teil hat Snippets. Fehlende Audios sauber abfangen (kein Eintrag in
  `audio_assets` = kein Audio).
- **`id` ist stabil** (6-stellig, z.B. `5iZfKj`) — als Fremdschlüssel/Cache-Key nutzbar.
- **Private Daten:** Probenmitschnitte (`kind='rehearsal'`) und Detection-Features
  sind **nicht** öffentlich und tauchen bei dir nicht auf. Korrekt so.
- **Schema-Quelle:** `supabase/migrations/0001_initial_schema.sql` +
  `0002_rls_public_read.sql` im lighting.ai-Repo. Architektur:
  `docs/architektur-zentrale-db.md`.

## Was BassTrainer NICHT tun sollte
- Keine Schreibzugriffe (lighting.ai pflegt die Daten).
- Den `service_role`-Key nicht verwenden/einbetten.
- Sich nicht auf die lighting-spezifischen JSONB-Felder verlassen — der stabile
  Vertrag ist `songs` (Kern) + `audio_assets`.
