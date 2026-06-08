# Runbook — Phase 1: lighting-ai-db.json → Supabase (real)

Schritt-für-Schritt für den ersten echten Import. Läuft auf **deinem Rechner**
(nicht in der Cloud-Session), weil der Service-Role-Key niemals in einen Chat
oder eine fremde Umgebung gehört.

> **Single-Writer-Invariante (docs §12):** In dieser Phase ist **Git noch Master**.
> Wir importieren nur JSON → Supabase. Der Export-Job (`export_from_supabase.py`)
> bleibt **aus**, bis zum Cutover (Phase 7). Nie beide Richtungen gleichzeitig.

---

## 0. Supabase-Projekt anlegen (EU/Frankfurt)

1. https://supabase.com → einloggen → **New project**.
2. **Region: `Central EU (Frankfurt)`** (DSGVO — Mitschnitte enthalten
   Bandmitglieder).
3. Name z.B. `thepact-central`, DB-Passwort vergeben (notieren).
4. Warten bis das Projekt „Active" ist (~2 Min).

## 1. Schema einspielen

Einfachster Weg ohne CLI — **SQL Editor**:

1. Im Projekt links **SQL Editor → New query**.
2. Inhalt von `supabase/migrations/0001_initial_schema.sql` komplett
   reinkopieren → **Run**.
3. Erwartung: „Success. No rows returned." Unter **Table Editor** erscheinen
   `songs`, `song_detail_lighting`, `bars`, `accents`, `app_state` (+
   `audio_assets`, `feature_vectors`, `transcripts` für später).

*(Alternativ mit Supabase CLI: `supabase link` + `supabase db push` —
die Migration liegt schon im erwarteten Pfad `supabase/migrations/`.)*

## 2. Zugangsdaten holen

Im Projekt **Settings → API**:
- **Project URL** → `SUPABASE_URL`
- **`service_role` secret** (NICHT `anon`!) → `SUPABASE_SERVICE_ROLE_KEY`

> ⚠️ Der `service_role`-Key umgeht RLS. Nur lokal/serverseitig verwenden,
> nie committen, nie in einen Chat einfügen.

## 3. Lokal vorbereiten

```bash
cd <dein-lighting.ai-checkout>
git pull origin main                       # Schema + Skripte holen
python3 -m venv .venv && source .venv/bin/activate
pip install -r scripts/central_db/requirements.txt

export SUPABASE_URL="https://xxxx.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="eyJ...."   # service_role
```

## 4. Trockenlauf (kein DB-Zugriff)

```bash
python -m scripts.central_db.import_to_supabase --dry-run
```
Erwartung:
```
  songs                   51
  song_detail_lighting    51
  bars                  2562
  accents                280
  app_state                1
```

## 5. Import

```bash
python -m scripts.central_db.import_to_supabase
```
Gibt pro Tabelle `upserted … (n)` aus. Idempotent — bei Fehler einfach erneut
ausführbar (upsert überschreibt, keine Duplikate).

## 6. Verifizieren (der Beweis)

```bash
python -m scripts.central_db.verify_supabase
```
Zieht jede Zeile zurück, rekonstruiert die DB über den inversen Transform und
vergleicht sie semantisch mit der lokalen JSON:
```
✅ OK — Supabase reproduces lighting-ai-db.json losslessly.
```
Bei `MISMATCH` nennt es die abweichende Tabelle.

---

## Danach (optional, noch in Phase 1)

- **RLS:** Tabellen sind anlegt-frei lesbar nur über `service_role`. Für den
  öffentlichen Lesezugriff (BassTrainer/DB-Pflege-App mit `anon`-Key) später
  RLS-Policies setzen — kommt in Phase 6/7, jetzt nicht nötig.
- **Export-Job NICHT laufen lassen** (s. Invariante oben).

## Troubleshooting

| Symptom | Ursache / Fix |
|---|---|
| `ERROR: set SUPABASE_URL …` | Env-Vars nicht exportiert (Schritt 3). |
| `pip install supabase` Hinweis | venv nicht aktiv oder Deps fehlen. |
| `foreign key violation` bei `bars` | Schema nicht eingespielt oder `songs` leer — Schritt 1 prüfen. |
| `MISMATCH` bei `bars` | Lokale JSON neuer als Import — Import erneut laufen lassen. |
| Verify zeigt weniger Bars | Paginierung: Skript holt in 1000er-Seiten; bei sehr großer DB Netzwerk prüfen. |
