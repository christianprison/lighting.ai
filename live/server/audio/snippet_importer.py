"""Snippet-Importer — CLI-Skript zum Befüllen der SQLite-Referenz-DB.

Liest die vorhandene Songdatenbank (db/lighting-ai-db.json) und die
Audio-Snippets (audio/{Song}/{Part}/{NNN ...}.mp3) und:

1. Legt Songs und Bars in der SQLite-Referenz-DB an
2. Berechnet Feature-Vektoren für alle Bars mit Audio-Datei
3. Speichert Feature-Vektoren als numpy BLOBs in SQLite

Usage (vom Repo-Root aus):
    python -m live.server.audio.snippet_importer [--db-path PATH] [--audio-root PATH] [--song SONG_ID]

Nach dem ersten Durchlauf können inkrementelle Updates ausgeführt werden
(nur Bars ohne Feature-Vektor werden neu berechnet).

Namensschema der Audio-Dateien (aus DB-Pflege-App)
---------------------------------------------------
  audio/{Song-Name}/{Part-Ordner}/{NNN Song-Name Part-Name}.mp3
  z.B. audio/All The Small Things/01 Thema 1/001 All The Small Things Thema 1.mp3

Part-Ordner: "{pos:02d} {Part-Name}" — alphabetisch = korrekte Reihenfolge.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Repo-Root bestimmen (lighting.ai/)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-24s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("importer")


def import_from_repo(
    db_json_path: Path,
    audio_root: Path,
    ref_db_path: Path,
    song_filter: str | None = None,
    force: bool = False,
) -> None:
    """Haupt-Import-Funktion.

    Parameters
    ----------
    db_json_path:  Pfad zu lighting-ai-db.json
    audio_root:    Pfad zum audio/-Verzeichnis (Repo-Root)
    ref_db_path:   Pfad zur SQLite-Referenz-DB (wird angelegt falls nicht vorhanden)
    song_filter:   Falls gesetzt, nur diesen Song importieren (song_id)
    force:         Feature-Vektoren auch für Bars neu berechnen, die bereits einen haben
    """
    from .reference_db import ReferenceDB, SongRecord, BarRecord, FeatureVector
    from .fingerprint import extract_features

    # DB laden
    if not db_json_path.exists():
        log.error("DB nicht gefunden: %s", db_json_path)
        sys.exit(1)

    with db_json_path.open(encoding="utf-8") as f:
        db = json.load(f)

    songs: dict = db.get("songs", {})
    bars: dict = db.get("bars", {})

    ref_db = ReferenceDB(ref_db_path)
    log.info("Referenz-DB: %s", ref_db_path)

    # Bars nach song_id gruppieren
    bars_by_song: dict[str, list[tuple[str, dict]]] = {}
    for bid, b in bars.items():
        sid = b.get("song_id", "")
        if sid not in bars_by_song:
            bars_by_song[sid] = []
        bars_by_song[sid].append((bid, b))

    # Songs verarbeiten
    song_ids = list(songs.keys())
    if song_filter:
        if song_filter not in songs:
            log.error("Song-ID nicht gefunden: %s", song_filter)
            sys.exit(1)
        song_ids = [song_filter]

    total_features = 0
    total_skipped = 0
    total_missing = 0

    for song_id in song_ids:
        song = songs[song_id]
        song_name = song.get("name", "")
        bpm = float(song.get("bpm", 120))
        song_bars = sorted(bars_by_song.get(song_id, []), key=lambda x: x[1].get("bar_num", 0))

        total_bars = len(song_bars)
        if total_bars == 0:
            log.debug("Song %s (%s): keine Takte — übersprungen", song_id, song_name)
            continue

        # Song in Referenz-DB anlegen
        ref_db.upsert_song(SongRecord(
            song_id=song_id,
            name=song_name,
            bpm=bpm,
            total_bars=total_bars,
        ))

        log.info("Song: %s — %s (%d Takte, %.0f BPM)", song_id, song_name, total_bars, bpm)

        for bar_id, bar_data in song_bars:
            bar_num = bar_data.get("bar_num", 0)
            audio_rel = bar_data.get("audio", "")

            # Part-Namen aus Audio-Pfad extrahieren
            part_name = _part_name_from_path(audio_rel)

            # Bar in Referenz-DB anlegen
            ref_db.upsert_bar(BarRecord(
                bar_id=bar_id,
                song_id=song_id,
                bar_num=bar_num,
                part_name=part_name,
                audio_path=audio_rel,
            ))

            if not audio_rel:
                total_missing += 1
                continue

            # Prüfen ob Feature-Vektor schon existiert
            if not force and ref_db.get_feature(bar_id) is not None:
                total_skipped += 1
                continue

            # Audio-Datei finden
            audio_abs = audio_root.parent / audio_rel  # audio_root = repo_root/audio
            if not audio_abs.exists():
                # Fallback: direkt im audio_root suchen
                audio_abs = audio_root / Path(audio_rel).name
            if not audio_abs.exists():
                log.warning("  T%03d Audio nicht gefunden: %s", bar_num, audio_rel)
                total_missing += 1
                continue

            # Feature-Vektor berechnen
            try:
                chroma, mfcc, onset, rms = extract_features(audio_abs, bpm=bpm)
                ref_db.upsert_feature(FeatureVector(
                    bar_id=bar_id,
                    chroma=chroma,
                    mfcc=mfcc,
                    onset=onset,
                    rms=rms,
                ))
                total_features += 1
                log.debug("  T%03d [%s] → Feature-Vektor OK", bar_num, part_name)
            except Exception as exc:
                log.warning("  T%03d Feature-Extraktion fehlgeschlagen: %s", bar_num, exc)
                total_missing += 1

    stats = ref_db.stats()
    log.info("")
    log.info("=== Import abgeschlossen ===")
    log.info("  Songs in DB:          %d", stats["songs"])
    log.info("  Bars in DB:           %d", stats["bars"])
    log.info("  Feature-Vektoren:     %d", stats["feature_vectors"])
    log.info("  Neu berechnet:        %d", total_features)
    log.info("  Übersprungen (exist): %d", total_skipped)
    log.info("  Fehlend/kein Audio:   %d", total_missing)


def _part_name_from_path(audio_path: str) -> str:
    """Extrahiert den Part-Ordner-Namen aus dem Audio-Pfad.

    Pfadformat: audio/{Song-Name}/{Part-Ordner}/{Datei}
    Gibt den Part-Ordner zurück oder "" wenn nicht bestimmbar.
    """
    if not audio_path:
        return ""
    parts = Path(audio_path).parts
    # parts: ('audio', 'All The Small Things', '01 Thema 1', '001 ....mp3')
    if len(parts) >= 3:
        return parts[2]  # Part-Ordner-Name
    return ""


# ---------------------------------------------------------------------------
# Incremental update (nur fehlende Features berechnen)
# ---------------------------------------------------------------------------

def compute_missing_features(
    ref_db_path: Path,
    audio_root: Path,
    db_json_path: Path,
) -> None:
    """Berechnet Feature-Vektoren nur für Bars ohne Feature-Vektor.

    Schneller Incremental-Update nach neuem Audio-Import über die DB-Pflege-App.
    """
    from .reference_db import ReferenceDB, FeatureVector
    from .fingerprint import extract_features
    import json

    ref_db = ReferenceDB(ref_db_path)

    # BPM pro Song aus JSON laden
    with db_json_path.open(encoding="utf-8") as f:
        db = json.load(f)
    bpm_map = {sid: float(s.get("bpm", 120)) for sid, s in db.get("songs", {}).items()}

    missing = ref_db.bars_without_features()
    log.info("%d Bars ohne Feature-Vektor", len(missing))

    ok = 0
    fail = 0
    for bar in missing:
        bpm = bpm_map.get(bar.song_id, 120.0)
        audio_abs = audio_root.parent / bar.audio_path
        if not audio_abs.exists():
            fail += 1
            continue
        try:
            chroma, mfcc, onset, rms = extract_features(audio_abs, bpm=bpm)
            ref_db.upsert_feature(FeatureVector(
                bar_id=bar.bar_id,
                chroma=chroma,
                mfcc=mfcc,
                onset=onset,
                rms=rms,
            ))
            ok += 1
        except Exception as exc:
            log.warning("T%03d %s: %s", bar.bar_num, bar.audio_path, exc)
            fail += 1

    log.info("Fertig: %d neu berechnet, %d fehlgeschlagen", ok, fail)


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Importiert Audio-Snippets in die SQLite-Referenz-DB und berechnet Feature-Vektoren."
    )
    parser.add_argument(
        "--db-json",
        default=str(_REPO_ROOT / "db" / "lighting-ai-db.json"),
        help="Pfad zur lighting-ai-db.json (default: db/lighting-ai-db.json)",
    )
    parser.add_argument(
        "--audio-root",
        default=str(_REPO_ROOT / "audio"),
        help="Pfad zum audio/-Verzeichnis (default: audio/)",
    )
    parser.add_argument(
        "--ref-db",
        default=str(_REPO_ROOT / "live" / "data" / "reference.db"),
        help="Pfad zur SQLite-Referenz-DB (default: live/data/reference.db)",
    )
    parser.add_argument(
        "--song",
        default=None,
        metavar="SONG_ID",
        help="Nur diesen Song importieren (z.B. 5iZfKj)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Feature-Vektoren auch für bereits verarbeitete Bars neu berechnen",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Nur fehlende Feature-Vektoren berechnen (schneller Update)",
    )
    args = parser.parse_args()

    db_json = Path(args.db_json)
    audio_root = Path(args.audio_root)
    ref_db = Path(args.ref_db)

    if args.incremental:
        compute_missing_features(ref_db, audio_root, db_json)
    else:
        import_from_repo(
            db_json_path=db_json,
            audio_root=audio_root,
            ref_db_path=ref_db,
            song_filter=args.song,
            force=args.force,
        )


if __name__ == "__main__":
    main()
