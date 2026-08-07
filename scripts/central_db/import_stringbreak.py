#!/usr/bin/env python3
"""Import Stringbreak's song catalog from db/Stringbreak.json into Supabase.

db/Stringbreak.json is a raw BandHelper export (68 Songs, ~49 `active`) that
so far was only mined for lyrics text cross-referenced into The Pact's songs
(scripts/import_pact_html.py). This script imports it as ITS OWN catalog,
band_id='stringbreak' (Multi-Band-Migration 0012, 2026-08-07).

Field mapping:
- name/artist/tempo->bpm/key/duration->duration_sec+duration(mm:ss) direct.
- Custom fields resolved dynamically by NAME via db["custom_field"] (their
  IDs differ per BandHelper account context from what's documented for The
  Pact in CLAUDE.md) — PLUS a fallback for custom field IDs empirically
  confirmed shared account-wide (present verbatim on Stringbreak records but
  absent from Stringbreak.json's own custom_field listing): HJV7Of->year,
  ufURoQ->gema_nr, zXQ5Fy->pick, B8s0D8/prtQDP->Notiz. "Gema-Werke-Nr." (the
  Stringbreak-specific field) also maps to gema_nr. Any other non-empty
  custom field is appended to `notes`, labelled, rather than dropped.

No bars/accents import — BandHelper has no bar/cue-level data; that gets
filled in via Audio Split in the app, same as The Pact originally.

Usage:
    python -m scripts.central_db.import_stringbreak                    # dry-run (default)
    python -m scripts.central_db.import_stringbreak --write             # actually writes
    python -m scripts.central_db.import_stringbreak --exclude "Stimmpause"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SRC = REPO_ROOT / "db" / "Stringbreak.json"
BAND_ID = "stringbreak"

SUPABASE_URL = "https://ivkcvvjtwwfommsnxerv.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_bS0KjYSEGa_CVEplXPC_ZA_gloEimqh"

# Custom-field IDs empirically confirmed shared across the whole BandHelper
# account (identical IDs documented for The Pact in CLAUDE.md, found verbatim
# on Stringbreak song records too, even though Stringbreak.json's own
# custom_field listing doesn't enumerate them).
_SHARED_FIELD_ROLES = {
    "HJV7Of": "year",
    "ufURoQ": "gema_nr",
    "zXQ5Fy": "pick",
    "B8s0D8": "note:Axel Notiz",
    "prtQDP": "note:Axel Notiz 2",
}

_ID_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def _fmt_duration(sec: int) -> str:
    m, s = divmod(sec, 60)
    return f"{m}:{s:02d}"


def _build_field_roles(custom_field: dict[str, Any]) -> dict[str, str]:
    roles = dict(_SHARED_FIELD_ROLES)
    for cf_id, cf in custom_field.items():
        if cf_id in roles:
            continue
        name = (cf.get("name") or "").strip()
        if name == "Gema-Werke-Nr.":
            roles[cf_id] = "gema_nr"
        elif name:
            roles[cf_id] = f"note:{name}"
    return roles


def _map_song(raw: dict[str, Any], field_roles: dict[str, str]) -> dict[str, Any]:
    name = (raw.get("name") or "").strip()
    artist = (raw.get("artist") or "").strip()
    tempo = int(raw.get("tempo") or 0)
    duration_sec = int(raw.get("duration") or 0)
    key = (raw.get("key") or "").strip()

    year = ""
    pick = ""
    gema_nr = ""
    note_parts: list[str] = []
    for k, v in raw.items():
        if not k.startswith("custom_"):
            continue
        val = (v or "").strip()
        if not val:
            continue
        cf_id = k[len("custom_") :]
        role = field_roles.get(cf_id, f"note:custom_{cf_id}")
        if role == "year":
            if not year:
                year = val
        elif role == "pick":
            if not pick:
                pick = val
        elif role == "gema_nr":
            if not gema_nr:
                gema_nr = val
        elif role.startswith("note:"):
            note_parts.append(f"{role[5:]}: {val}")

    return {
        "name": name,
        "artist": artist,
        "bpm": tempo or None,
        "key": key,
        "year": year,
        "pick": pick,
        "gema_nr": gema_nr,
        "duration": _fmt_duration(duration_sec) if duration_sec else "",
        "duration_sec": duration_sec,
        "notes": "; ".join(note_parts),
        "band_id": BAND_ID,
    }


def _validate(songs: list[dict], existing_names: set[str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    seen_lower: dict[str, str] = {}
    for s in songs:
        label = f"{s['name']} ({s['artist']})" if s["artist"] else s["name"]
        if not s["name"]:
            errors.append(f"[{label}] name fehlt")
        if not s["artist"]:
            errors.append(f"[{label}] artist fehlt")
        key_lower = s["name"].strip().lower()
        if key_lower in seen_lower:
            errors.append(f"[{label}] doppelter Songname im Import (auch: {seen_lower[key_lower]})")
        else:
            seen_lower[key_lower] = label
        if key_lower in existing_names:
            errors.append(f"[{label}] Songname existiert schon bei Stringbreak in Supabase")

        bpm = s["bpm"]
        if not bpm:
            warnings.append(f"[{label}] BPM fehlt/0")
        elif bpm < 40 or bpm > 300:
            warnings.append(f"[{label}] BPM unplausibel: {bpm}")
        if not s["duration_sec"]:
            warnings.append(f"[{label}] Dauer fehlt/0")
        if not s["key"]:
            warnings.append(f"[{label}] Key leer")
        if "keine" in s["gema_nr"].lower():
            warnings.append(f"[{label}] GEMA-Feld sieht nach Platzhaltertext aus: \"{s['gema_nr']}\"")
        if not bpm and not s["duration_sec"]:
            warnings.append(f"[{label}] BPM UND Dauer beide 0 — evtl. kein echter Song (Platzhalter)?")
    return errors, warnings


# ── Supabase REST (anon key, gleicher Weg wie die WebApp) ─────────────────

def _sb_get(path: str) -> Any:
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {SUPABASE_ANON_KEY}"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _sb_post(path: str, body: Any, prefer: str = "return=minimal") -> Any:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{path}",
        data=data,
        method="POST",
        headers={
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        raise SystemExit(f"ERROR: POST {path} -> {e.code}: {e.read().decode('utf-8', 'replace')}")


def _existing_song_ids() -> set[str]:
    return {r["id"] for r in _sb_get("songs?select=id")}


def _existing_stringbreak_names() -> set[str]:
    rows = _sb_get(f"songs?select=name&band_id=eq.{BAND_ID}")
    return {r["name"].strip().lower() for r in rows}


def _generate_ids(n: int, taken: set[str]) -> list[str]:
    import random

    ids: list[str] = []
    for _ in range(n):
        for _attempt in range(50):
            candidate = "".join(random.choice(_ID_CHARS) for _ in range(6))
            if candidate not in taken:
                taken.add(candidate)
                ids.append(candidate)
                break
        else:
            raise SystemExit("ERROR: konnte keine kollisionsfreie ID generieren (50 Versuche) — sehr unwahrscheinlich, ID-Raum evtl. erschöpft?")
    return ids


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--write", action="store_true", help="tatsächlich nach Supabase schreiben (sonst nur Vorschau)")
    ap.add_argument("--exclude", default="", help="Komma-getrennte Songnamen, die übersprungen werden sollen")
    args = ap.parse_args(argv)

    exclude = {n.strip().lower() for n in args.exclude.split(",") if n.strip()}

    raw = json.loads(args.src.read_text(encoding="utf-8"))
    field_roles = _build_field_roles(raw.get("custom_field", {}))

    candidates = [
        s for s in raw["song"].values()
        if s.get("active") == "1" and (s.get("name") or "").strip().lower() not in exclude
    ]
    songs = [_map_song(s, field_roles) for s in candidates]

    print(f"Quelle: {args.src} — {len(raw['song'])} Songs total, {len(candidates)} aktiv nach --exclude.\n")

    print("Fetching existing Supabase state (Kollisionsprüfung)...")
    existing_ids = _existing_song_ids()
    existing_names = _existing_stringbreak_names()

    errors, warnings = _validate(songs, existing_names)

    if errors:
        print(f"\n❌ {len(errors)} ERROR(S) — Import abgebrochen:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"\n✅ Keine Errors. {len(warnings)} Warning(s):")
    for w in warnings:
        print(f"  - {w}")

    print(f"\nVorschau ({len(songs)} Songs):")
    for s in songs:
        print(f"  {s['name']:<40} {s['artist']:<25} bpm={s['bpm'] or '—':<5} key={s['key'] or '—'}")

    ids = _generate_ids(len(songs), set(existing_ids))
    for s, sid in zip(songs, ids):
        s["id"] = sid

    if not args.write:
        print(f"\n[dry-run] {len(songs)} Songs würden importiert (keine Netzwerk-Schreibzugriffe). Mit --write tatsächlich schreiben.")
        return 0

    # songs-Tabelle: core fields + id + band_id (song_detail_lighting bleibt
    # leer — kein FK-Zwang, wird erst durch spätere Lighting-Pflege befüllt)
    core_cols = ["name", "artist", "bpm", "key", "year", "pick", "gema_nr", "duration", "duration_sec", "notes", "band_id"]
    songs_rows = [{"id": s["id"], **{("music_key" if c == "key" else c): s[c] for c in core_cols}} for s in songs]
    _sb_post("songs", songs_rows)
    print(f"\n✅ {len(songs_rows)} Songs nach Supabase geschrieben (band_id={BAND_ID}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
