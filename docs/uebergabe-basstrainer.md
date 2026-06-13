# Übergabe an die BassTrainer-App — zentrale Songs-/Audio-DB (Supabase)

> Für die **BassTrainer**-Session. lighting.ai hat eine zentrale Datenbank
> aufgebaut, aus der BassTrainer **Songs und Audio lesen** kann. Dieses Dokument
> ist alles, was du dafür brauchst.

## TL;DR

- Plattform: **Supabase** (Postgres + Storage), Region **EU/Frankfurt** (DSGVO).
- BassTrainer ist ein **Read-only-Konsument**: lesen ja, schreiben nein.
  lighting.ai ist alleiniger Schreiber (Single-Source-of-Truth).
- Verfügbar: **51 Songs**, **43 Full-Song-Play-along-Tracks**, **484 Per-Takt-Snippets**.

## Verbindung

```
SUPABASE_URL      = https://ivkcvvjtwwfommsnxerv.supabase.co
SUPABASE_ANON_KEY = <Publishable/anon-Key>
```

Den `anon`/Publishable-Key gibt dir der Projekt-Owner (Supabase → Settings →
API Keys → „Publishable" `sb_publishable_…` **oder** Legacy `anon`). Dieser Key
ist **client-safe**. Der `service_role`/secret-Key darf **niemals** in den
BassTrainer-Client — er umgeht alle Sicherheit.

Supabase ist nichts weiter als **PostgREST + HTTP-Storage** — du brauchst **kein
SDK**. Native (iPad/URLSession) gehst du direkt per REST.

### REST (native App, ohne SDK — empfohlen für die iPad-App)

Jeder Daten-Request an `…/rest/v1/…` braucht zwei Header:
```
apikey:        <ANON_KEY>
Authorization: Bearer <ANON_KEY>
```
PostgREST-Query-Syntax: `select=spalten`, Filter `spalte=eq.wert`,
`spalte=in.(a,b)`, Sortierung `order=spalte.asc`.

```http
GET {URL}/rest/v1/setlist_public?select=*&order=pos
GET {URL}/rest/v1/songs?select=id,name,artist,bpm,music_key,duration_sec
GET {URL}/rest/v1/audio_assets?song_id=eq.5iZfKj&kind=eq.playalong&select=storage_path
```

Swift/URLSession-Skizze:
```swift
var req = URLRequest(url: URL(string: "\(base)/rest/v1/setlist_public?select=*&order=pos")!)
req.setValue(anonKey, forHTTPHeaderField: "apikey")
req.setValue("Bearer \(anonKey)", forHTTPHeaderField: "Authorization")
let (data, _) = try await URLSession.shared.data(for: req)
// data ist JSON-Array -> JSONDecoder
```

### JS-SDK (nur falls Web/Next.js)

```ts
import { createClient } from "@supabase/supabase-js";
const supabase = createClient(url, anonKey);
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

> Weitere lesbare Tabellen (`song_detail_lighting`, `bars`, `accents`) sind
> **lighting-spezifisch** — BassTrainer kann sie ignorieren. **Ausnahme:**
> `app_state` enthält die **Setlist** (siehe unten).

### Tabelle `app_state` — globale Daten inkl. Setlist
Eine einzige Zeile (`id = 1`). Relevant für BassTrainer ist die JSONB-Spalte
`setlist`:
```json
{
  "name": "Repertoire",
  "items": [
    { "type": "song", "pos": 1, "song_id": "dgSleW" },
    { "type": "song", "pos": 2, "song_id": "qVbU6L" }
    // optional auch { "type": "pause" }
  ]
}
```
`items` ist die **geordnete Reihenfolge** (nach `pos`). Item-Typen: `"song"`
(mit `song_id`) oder `"pause"`. Öffentlich lesbar.

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

## Setlist lesen

Die Setlist steckt in `app_state.setlist` (eine Zeile, `id = 1`):

```ts
const { data } = await supabase
  .from("app_state")
  .select("setlist")
  .eq("id", 1)
  .single();

const items = data.setlist.items;                    // geordnet nach pos
const songIds = items.filter(i => i.type === "song").map(i => i.song_id);

// Songdetails dazu holen:
const { data: songs } = await supabase
  .from("songs")
  .select("id, name, artist, bpm, music_key")
  .in("id", songIds);
```

**Einfacher (empfohlen):** Es gibt die fertige **View `setlist_public`** —
Setlist schon mit Songdetails verknüpft und nach `pos` sortiert:
```http
GET {URL}/rest/v1/setlist_public?select=*&order=pos
-> [{ pos, song_id, name, artist, bpm, music_key, duration_sec }, …]
```

## Audio abspielen (öffentlicher Bucket)

Der Bucket `snippets` ist **public** → **direkte URL, ohne Auth, ohne SDK**.
Setze einfach diese URL als Quelle deines Players (AVPlayer/`<audio>`):
```
{URL}/storage/v1/object/public/snippets/{storage_path}
```
**Pfad URL-kodieren** (Leerzeichen → `%20`, Apostroph etc.), Slashes erhalten.
Swift-Beispiel:
```swift
let key = storagePath.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed)!
let url = URL(string: "\(base)/storage/v1/object/public/snippets/\(key)")!
player = AVPlayer(url: url)
```
(Im Web-SDK äquivalent: `supabase.storage.from("snippets").getPublicUrl(path)`.)

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
