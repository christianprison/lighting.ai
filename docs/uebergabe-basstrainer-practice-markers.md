# Rück-Übergabe an BassTrainer — Schreibzugriff Übe-Marker (steht bereit)

Die lighting.ai-Seite ist eingerichtet:
- ✅ **Anonymous sign-ins = ON**
- ✅ Tabelle **`practice_markers`** + RLS (Per-User-Isolation über `auth.uid()`)
- Alles andere bleibt **read-only**. `service_role` **nie** im Client.

## Auth-Flow (REST, kein JS-SDK)

1. **Einmalig anonym anmelden** (pro Gerät):
   ```http
   POST {URL}/auth/v1/signup
   apikey: <ANON_KEY>
   Content-Type: application/json

   {}
   ```
   Antwort: `{ access_token, refresh_token, expires_in, user: { id, is_anonymous } }`.
   `access_token` (User-JWT) + `refresh_token` sicher ablegen (Keychain).

2. **Token erneuern**, wenn `access_token` abgelaufen (typ. ~1 h):
   ```http
   POST {URL}/auth/v1/token?grant_type=refresh_token
   apikey: <ANON_KEY>
   Content-Type: application/json

   { "refresh_token": "<refresh_token>" }
   ```

## Marker schreiben/lesen (`/rest/v1/practice_markers`)

Bei JEDEM Marker-Request **beide** Header:
```
apikey: <ANON_KEY>
Authorization: Bearer <access_token>        # User-JWT, NICHT nur der anon-Key
```

- **Anlegen** (`user_id` NICHT senden — wird per `default auth.uid()` gesetzt):
  ```http
  POST {URL}/rest/v1/practice_markers
  Prefer: return=representation
  { "song_id": "5iZfKj", "start_bar": 9, "end_bar": 16, "reason": "speed", "note": null }
  ```
- **Eigene lesen** (RLS filtert automatisch auf den eigenen User):
  ```http
  GET {URL}/rest/v1/practice_markers?song_id=eq.5iZfKj&select=*&order=start_bar
  ```
- **Ändern:** `PATCH …/practice_markers?id=eq.<uuid>`  Body = geänderte Felder.
- **Löschen:** `DELETE …/practice_markers?id=eq.<uuid>`.

## Spalten / Vertrag
| Spalte | Typ | Hinweis |
|---|---|---|
| `id` | uuid | server-generiert |
| `user_id` | uuid | **nicht senden**, = `auth.uid()` |
| `song_id` | text | FK → `songs.id` |
| `start_bar` / `end_bar` | int | 1-basiert, passend zu `song_timeline_public.bar_num`; es gilt `end_bar >= start_bar >= 1` |
| `reason` | text | genau einer von `speed`, `precision`, `timing`, `shift`, `other` |
| `note` | text \| null | optionaler Freitext (additiv; nutzbar oder ignorierbar) |
| `created_at` / `updated_at` | timestamptz | server-gesetzt (`updated_at` per Trigger) |

## Hinweise
- **Identität hängt am Gerät** (anonymer User). Kein Cross-Device-Sync; bei
  Neuinstallation neue Identität. Echtes Login (Magic-Link) ließe sich später
  additiv nachrüsten — Tabelle/RLS bleiben gleich.
- **Offline:** lokaler Cache als Fallback, vorhandene lokale Marker einmalig
  hochmigrieren (POST je Marker mit gültigem Token).
- Schema-Quelle: `supabase/migrations/0005_practice_markers.sql`.
