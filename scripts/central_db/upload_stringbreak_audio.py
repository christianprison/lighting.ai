#!/usr/bin/env python3
"""Stringbreak: BandHelper-Aufnahmen nach Supabase Storage hochladen.

Läuft LOKAL auf dem Rechner, auf dem die exportierten Audiodateien liegen
(anders als ``upload_audio.py``, das in GitHub Actions läuft und die im Repo
eingecheckten Dateien nimmt — Stringbreaks 294 MB sollen nicht ins Repo).

Die Song-Zuordnung muss nicht von Hand gepflegt werden: ``db/Stringbreak.json``
(BandHelper-Export) enthält bereits eine ``recording``-Sammlung und pro Song
ein ``recordings``-Feld mit den zugehörigen Aufnahme-IDs. Das Skript verbindet
also drei Ebenen:

    Datei im Ordner  →  BandHelper-Aufnahme  →  BandHelper-Song  →  Supabase-Song
    (per Name)          (recordings-Feld)       (per Name)

Der Dateiname-Abgleich ist tolerant (Groß-/Kleinschreibung, Apostrophe,
Sonderzeichen, Mehrfach-Leerzeichen), weil BandHelbers Export beim Schreiben
auf die Platte Zeichen ersetzt: aus "(1 Strophe + Refrain)" wird
"(1 Strophe   Refrain)".

Übersprungen werden (jeweils mit Begründung im Report):
- Aufnahmen ohne Datei im Ordner
- Dateien, deren Song in BandHelper ``active='0'`` ist (ausrangiert, deshalb
  gar nicht erst nach Supabase importiert)

Storage-Layout (analog zu The Pact, Bucket ``snippets``):

    audio/stringbreak/{song_id}/{slug}.mp3

Zugangsdaten aus der Umgebung::

    export SUPABASE_URL=https://ivkcvvjtwwfommsnxerv.supabase.co
    export SUPABASE_SERVICE_ROLE_KEY=sb_secret_...

Aufruf::

    python3 scripts/central_db/upload_stringbreak_audio.py ~/Downloads          # Vorschau
    python3 scripts/central_db/upload_stringbreak_audio.py ~/Downloads --write  # echt

Idempotent: erneutes Ausführen überschreibt dieselben Objekte (upsert) und
trifft beim Registrieren auf ``(bucket, storage_path)``.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

BAND_ID = "stringbreak"
BUCKET = "snippets"
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".flac", ".ogg"}

# Welche Variante wird Referenz-Audio, wenn ein Song mehrere Aufnahmen hat?
# Erster Treffer gewinnt; alles Unbekannte landet hinten.
_REF_PREFERENCE = ("original", "studio", "playback", "live", "probe", "nur axel")


# ── Namens-Normalisierung ──────────────────────────────────────────────────


def _norm(s: str) -> str:
    """Vergleichsform: nur Kleinbuchstaben/Ziffern, Rest wird zu Leerzeichen."""
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"\.(mp3|m4a|wav|flac|ogg)$", "", s, flags=re.I).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def _label_of(recording_name: str) -> str:
    """Varianten-Bezeichnung aus dem Klammer-Zusatz, z.B. "nur Axel"."""
    m = re.search(r"\(([^)]*)\)\s*$", recording_name.strip())
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def _slug(name: str) -> str:
    """Storage-sicherer Dateiname (nur ASCII, keine Apostrophe — siehe 0011)."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"\.(mp3|m4a|wav|flac|ogg)$", "", s, flags=re.I)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return s or "audio"


def _ref_rank(label: str) -> int:
    low = label.lower()
    for i, want in enumerate(_REF_PREFERENCE):
        if want in low:
            return i
    return len(_REF_PREFERENCE)


# ── Supabase REST ──────────────────────────────────────────────────────────


DEFAULT_URL = "https://ivkcvvjtwwfommsnxerv.supabase.co"
# Öffentlicher Key (steckt ohnehin im Browser-Frontend) — reicht zum Lesen der
# Songliste, also für die komplette Vorschau. Hochladen erfordert den secret Key.
PUBLIC_KEY = "sb_publishable_bS0KjYSEGa_CVEplXPC_ZA_gloEimqh"


def _env(*, need_write: bool) -> tuple[str, str]:
    """URL + Key. Ohne --write genügt der öffentliche Lese-Key."""
    url = (os.environ.get("SUPABASE_URL") or DEFAULT_URL).rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    if not need_write:
        return url, key or PUBLIC_KEY

    if not key:
        raise SystemExit(
            "FEHLER: Zum Hochladen den service_role (secret) Key setzen:\n"
            "  export SUPABASE_SERVICE_ROLE_KEY=sb_secret_...\n"
            "(Supabase → Project Settings → API Keys. Ohne --write läuft die "
            "Vorschau auch ohne diesen Key.)"
        )
    if key.startswith("sb_publishable_"):
        raise SystemExit(
            "FEHLER: Das ist der anon/publishable Key. Zum Hochladen wird der "
            "service_role (secret) Key gebraucht — Supabase → Project Settings "
            "→ API Keys."
        )
    return url, key


def _request(method: str, url: str, key: str, *, body: bytes | None = None,
             headers: dict[str, str] | None = None) -> bytes:
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"FEHLER {e.code} bei {method} {url}\n{e.read().decode()[:500]}")


def _rest_get(url: str, key: str, path: str) -> Any:
    return json.loads(_request("GET", f"{url}/rest/v1/{path}", key) or b"[]")


# ── Planung ────────────────────────────────────────────────────────────────


def _build_plan(src_dir: Path, bandhelper: dict, sb_songs: list[dict]) -> tuple[list[dict], list[str]]:
    """Ordnet jede Audiodatei einem Supabase-Song zu. Gibt (Plan, Hinweise)."""
    songs, recs = bandhelper["song"], bandhelper["recording"]

    files: dict[str, Path] = {}
    for p in sorted(src_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            files.setdefault(_norm(p.name), p)

    sb_by_name = {_norm(s["name"]): s for s in sb_songs}

    plan: list[dict] = []
    notes: list[str] = []
    used: set[str] = set()

    for song in sorted(songs.values(), key=lambda s: s.get("name", "")):
        rec_ids = [r for r in (song.get("recordings") or "").split(",") if r]
        if not rec_ids:
            continue
        target = sb_by_name.get(_norm(song.get("name", "")))

        for rid in rec_ids:
            rec = recs.get(rid)
            if not rec:
                continue
            key = _norm(rec.get("name", ""))
            path = files.get(key)
            if not path:
                notes.append(f"keine Datei   : {rec.get('name')!r}  (Song {song.get('name')!r})")
                continue
            used.add(key)
            if not target:
                why = "in BandHelper ausrangiert" if song.get("active") == "0" else "nicht in Supabase"
                notes.append(f"Song fehlt    : {path.name}  → {song.get('name')!r} ({why})")
                continue

            label = _label_of(rec.get("name", ""))
            plan.append({
                "path": path,
                "song_id": target["id"],
                "song_name": target["name"],
                "label": label,
                "storage_path": f"audio/{BAND_ID}/{target['id']}/{_slug(rec['name'])}{path.suffix.lower()}",
                "rank": _ref_rank(label),
                "size": path.stat().st_size,
            })

    for key, path in sorted(files.items()):
        if key not in used:
            notes.append(f"unbekannt     : {path.name}  (kein Eintrag in Stringbreak.json)")

    return plan, notes


def _reference_picks(plan: list[dict]) -> dict[str, dict]:
    """Pro Song die Aufnahme, die Referenz-Audio wird (beste Variante)."""
    best: dict[str, dict] = {}
    for item in plan:
        cur = best.get(item["song_id"])
        if cur is None or item["rank"] < cur["rank"]:
            best[item["song_id"]] = item
    return best


# ── Hauptlauf ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path, help="Ordner mit den exportierten Audiodateien")
    ap.add_argument("--json", type=Path, default=REPO_ROOT / "db" / "Stringbreak.json",
                    help="BandHelper-Export (Default: db/Stringbreak.json)")
    ap.add_argument("--write", action="store_true",
                    help="Tatsächlich hochladen (ohne dieses Flag nur Vorschau)")
    ap.add_argument("--set-reference", action="store_true",
                    help="Zusätzlich pro Song ein audio_ref setzen (beste Variante), "
                         "sofern der Song noch keins hat")
    args = ap.parse_args(argv)

    src: Path = args.src.expanduser().resolve()
    if not src.is_dir():
        raise SystemExit(f"FEHLER: {src} ist kein Verzeichnis.")

    bandhelper = json.loads(args.json.read_text(encoding="utf-8"))
    url, key = _env(need_write=args.write)

    print(f"Quelle : {src}")
    print(f"Ziel   : {url}  Bucket '{BUCKET}'\n")

    sb_songs = _rest_get(url, key, f"songs?select=id,name&band_id=eq.{BAND_ID}")
    print(f"{len(sb_songs)} Songs der Band '{BAND_ID}' in Supabase.\n")

    plan, notes = _build_plan(src, bandhelper, sb_songs)
    if not plan:
        raise SystemExit("Nichts zuzuordnen — stimmt der Quellordner?")

    total_mb = sum(i["size"] for i in plan) / 1048576
    n_songs = len({i["song_id"] for i in plan})
    print(f"✅ {len(plan)} Dateien → {n_songs} Songs  ({total_mb:.0f} MB)\n")

    by_song: dict[str, list[dict]] = {}
    for i in plan:
        by_song.setdefault(i["song_name"], []).append(i)
    for name in sorted(by_song):
        items = by_song[name]
        print(f"  {name}")
        for i in sorted(items, key=lambda x: x["rank"]):
            print(f"      • {i['label'] or '—':<22} {i['path'].name}")

    if notes:
        print(f"\n⚠️  {len(notes)} übersprungen:")
        for n in sorted(notes):
            print(f"  {n}")

    picks = _reference_picks(plan)
    if args.set_reference:
        print(f"\nReferenz-Audio würde für {len(picks)} Songs gesetzt (beste Variante).")

    if not args.write:
        print("\n[Vorschau] Keine Schreibzugriffe. Mit --write tatsächlich hochladen.")
        return 0

    # ── Upload ─────────────────────────────────────────────────────────────
    print(f"\nLade {len(plan)} Dateien hoch…")
    for n, item in enumerate(plan, 1):
        data = item["path"].read_bytes()
        ctype = mimetypes.guess_type(item["path"].name)[0] or "application/octet-stream"
        _request(
            "POST",
            f"{url}/storage/v1/object/{BUCKET}/{urllib.parse.quote(item['storage_path'])}",
            key,
            body=data,
            headers={"content-type": ctype, "x-upsert": "true"},
        )
        print(f"  [{n:>2}/{len(plan)}] {item['path'].name}")

    # ── audio_assets registrieren ──────────────────────────────────────────
    rows = [{
        "song_id": i["song_id"],
        "kind": "playalong",
        "bucket": BUCKET,
        "storage_path": i["storage_path"],
        "label": i["label"],
    } for i in plan]

    _request(
        "POST",
        f"{url}/rest/v1/audio_assets?on_conflict=bucket,storage_path",
        key,
        body=json.dumps(rows).encode(),
        headers={"content-type": "application/json",
                 "prefer": "resolution=merge-duplicates,return=minimal"},
    )
    print(f"\n{len(rows)} audio_assets-Zeilen registriert.")

    # ── Referenz-Audio (optional) ──────────────────────────────────────────
    if args.set_reference:
        existing = {
            r["song_id"]: (r.get("detail") or {})
            for r in _rest_get(url, key, "song_detail_lighting?select=song_id,detail")
        }
        updates = []
        for song_id, item in picks.items():
            detail = dict(existing.get(song_id, {}))
            if detail.get("audio_ref"):
                continue  # bestehendes Referenz-Audio nie überschreiben
            detail["audio_ref"] = item["storage_path"]
            detail["audio_ref_name"] = item["path"].name
            updates.append({"song_id": song_id, "detail": detail})

        if updates:
            _request(
                "POST",
                f"{url}/rest/v1/song_detail_lighting?on_conflict=song_id",
                key,
                body=json.dumps(updates).encode(),
                headers={"content-type": "application/json",
                         "prefer": "resolution=merge-duplicates,return=minimal"},
            )
        print(f"{len(updates)} Songs haben jetzt ein Referenz-Audio "
              f"({len(picks) - len(updates)} hatten schon eins).")

    print("\nFertig. Prüfen:  select kind, count(*) from audio_assets group by kind;")
    return 0


if __name__ == "__main__":
    sys.exit(main())
