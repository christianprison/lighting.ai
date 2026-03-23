"""Snippet-Importer — CLI-Skript zum Befüllen der SQLite-Referenz-DB.

Liest die vorhandene Songdatenbank (db/lighting-ai-db.json) und die
Audio-Schnipsel (audio/{Song}/{Part}/{NNN ...}.mp3) und:

1. Legt Songs und Bars in der SQLite-Referenz-DB an
2. Berechnet Feature-Vektoren für alle Bars mit Audio-Datei
3. Speichert Feature-Vektoren als numpy BLOBs in SQLite

Zwei Import-Pfade werden unterstützt:

A) split_markers (neu): Song hat split_markers.markers[] + audio_ref.
   Das Referenz-Audio wird einmal geladen und pro Takt anhand der
   Zeitstempel geschnitten. Feature-Extraktion direkt aus dem Array.

B) Einzelne MP3s (alt): Bar hat audio-Pfad zu einer fertigen MP3-Datei.
   Wird weiterhin unterstützt für ältere Songs.

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

import numpy as np

# Repo-Root bestimmen (lighting.ai/)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-24s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("importer")


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _load_audio_ref(audio_ref: str, repo_root: Path, sr: int = 22050):
    """Lädt das Referenz-Audio eines Songs als numpy-Array.

    Returns (y, sr) oder wirft FileNotFoundError.
    """
    try:
        import librosa  # type: ignore
    except ImportError as exc:
        raise ImportError("librosa ist nicht installiert.") from exc

    audio_abs = repo_root / audio_ref
    if not audio_abs.exists():
        raise FileNotFoundError(f"audio_ref nicht gefunden: {audio_abs}")

    y, _ = librosa.load(str(audio_abs), sr=sr, mono=True)
    return y, sr


def _slice_bar(
    y: np.ndarray,
    sr: int,
    markers: list[dict],
    bar_num: int,  # 1-basiert
) -> np.ndarray | None:
    """Schneidet einen Takt aus dem Referenz-Audio.

    Gibt None zurück wenn kein Marker für diesen Takt vorhanden.
    bar_num ist 1-basiert. markers[bar_num-1].time = Startzeit des Taktes.
    """
    idx = bar_num - 1
    if idx < 0 or idx >= len(markers):
        return None

    start_sec = markers[idx]["time"]
    end_sec = markers[idx + 1]["time"] if idx + 1 < len(markers) else None

    start_sample = int(start_sec * sr)
    end_sample = int(end_sec * sr) if end_sec is not None else len(y)

    # Mindestlänge: 0.1s (gegen leere Schnipsel an Songenden)
    if end_sample - start_sample < int(0.1 * sr):
        return None

    return y[start_sample:end_sample]


def _song_id_from_bar(bar: dict) -> str:
    """Leitet song_id aus einem Bar-Eintrag ab.

    Unterstützt beide Schema-Varianten:
    - Neu: bar hat 'song_id' direkt
    - Alt: bar hat 'part_id' im Format '{song_id}_P{NNN}'
    """
    if bar.get("song_id"):
        return bar["song_id"]
    part_id = bar.get("part_id", "")
    if "_" in part_id:
        return part_id.rsplit("_", 1)[0]
    return ""


# ---------------------------------------------------------------------------
# Haupt-Import
# ---------------------------------------------------------------------------

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
    from .fingerprint import extract_features, extract_features_from_array

    # DB laden
    if not db_json_path.exists():
        log.error("DB nicht gefunden: %s", db_json_path)
        sys.exit(1)

    with db_json_path.open(encoding="utf-8") as f:
        db = json.load(f)

    songs: dict = db.get("songs", {})
    bars: dict = db.get("bars", {})

    ref_db = ReferenceDB(ref_db_path)
    repo_root = audio_root.parent  # audio_root = repo_root/audio
    log.info("Referenz-DB: %s", ref_db_path)

    # Bars nach song_id gruppieren (beide Schema-Varianten)
    bars_by_song: dict[str, list[tuple[str, dict]]] = {}
    for bid, b in bars.items():
        sid = _song_id_from_bar(b)
        if not sid:
            continue
        bars_by_song.setdefault(sid, []).append((bid, b))

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
        song_bars_raw = bars_by_song.get(song_id, [])

        if not song_bars_raw:
            log.debug("Song %s (%s): keine Takte — übersprungen", song_id, song_name)
            continue

        # --- Importpfad bestimmen ---
        # Pfad A: split_markers mit Markern vorhanden
        sm = song.get("split_markers", {})
        markers = sm.get("markers", [])
        audio_ref = song.get("audio_ref", "")
        use_markers = bool(markers and audio_ref)

        # --- Part-Infos für Pfad B (alt: part_id-Schema) ---
        parts_of_song = song.get("parts", {})
        sorted_part_ids = sorted(
            parts_of_song.keys(),
            key=lambda pid: parts_of_song[pid].get("pos", 0),
        )
        part_offset: dict[str, int] = {}
        offset = 0
        for pid in sorted_part_ids:
            part_offset[pid] = offset
            n_bars_in_part = sum(
                1 for _, b in song_bars_raw if b.get("part_id") == pid
            )
            offset += n_bars_in_part

        # Part-Namen aus split_markers.part_starts (Pfad A) aufbauen
        part_starts: list[dict] = sm.get("part_starts", [])
        # Mapping bar_num → part_name (part_starts[i].bar_num = erster Takt des Parts)
        bar_to_part_name: dict[int, str] = {}
        if part_starts:
            # Für jeden Takt den zugehörigen Part-Namen bestimmen
            sorted_ps = sorted(part_starts, key=lambda x: x.get("bar_num", 1))
            for i, ps in enumerate(sorted_ps):
                start_bar = ps.get("bar_num", 1)
                end_bar = sorted_ps[i + 1].get("bar_num", 1) - 1 if i + 1 < len(sorted_ps) else 99999
                for bn in range(start_bar, end_bar + 1):
                    bar_to_part_name[bn] = ps.get("name", "")

        # Bars sortieren
        def _bar_sort_key(item: tuple[str, dict]) -> tuple[int, int]:
            _, b = item
            if use_markers:
                return (0, b.get("bar_num", 0))
            pid = b.get("part_id", "")
            part_pos = parts_of_song.get(pid, {}).get("pos", 0) if pid in parts_of_song else 0
            return (part_pos, b.get("bar_num", 0))

        song_bars = sorted(song_bars_raw, key=_bar_sort_key)
        total_bars = len(song_bars)

        # Song in Referenz-DB anlegen
        ref_db.upsert_song(SongRecord(
            song_id=song_id,
            name=song_name,
            bpm=bpm,
            total_bars=total_bars,
        ))

        # Referenz-Audio für Pfad A laden (einmalig pro Song)
        ref_audio: np.ndarray | None = None
        ref_sr: int = 22050
        if use_markers:
            try:
                ref_audio, ref_sr = _load_audio_ref(audio_ref, repo_root)
                log.info(
                    "Song: %s — %s (%d Takte, %.0f BPM) [split_markers]",
                    song_id, song_name, total_bars, bpm,
                )
            except FileNotFoundError as exc:
                log.warning("audio_ref nicht gefunden: %s — Pfad B versuchen", exc)
                use_markers = False

        if not use_markers:
            log.info(
                "Song: %s — %s (%d Takte, %.0f BPM) [einzelne MP3s]",
                song_id, song_name, total_bars, bpm,
            )

        for bar_id, bar_data in song_bars:
            bar_num_raw = bar_data.get("bar_num", 1)

            # Absoluten bar_num bestimmen
            if use_markers:
                bar_num = bar_num_raw  # bereits absolut im neuen Schema
            else:
                part_id = bar_data.get("part_id", "")
                bar_num = part_offset.get(part_id, 0) + bar_num_raw

            # Part-Namen bestimmen
            if use_markers and bar_to_part_name:
                part_name = bar_to_part_name.get(bar_num_raw, "")
            else:
                pid = bar_data.get("part_id", "")
                part_name = parts_of_song.get(pid, {}).get("name", "") or _part_name_from_path(bar_data.get("audio", ""))

            ref_db.upsert_bar(BarRecord(
                bar_id=bar_id,
                song_id=song_id,
                bar_num=bar_num,
                part_name=part_name,
                audio_path=bar_data.get("audio", ""),
            ))

            # Bereits vorhanden?
            if not force and ref_db.get_feature(bar_id) is not None:
                total_skipped += 1
                continue

            # --- Feature-Extraktion ---
            if use_markers and ref_audio is not None:
                # Pfad A: aus Referenz-Audio schneiden
                segment = _slice_bar(ref_audio, ref_sr, markers, bar_num_raw)
                if segment is None or len(segment) == 0:
                    log.debug("  T%03d kein Marker — übersprungen", bar_num)
                    total_missing += 1
                    continue
                try:
                    chroma, mfcc, onset, rms = extract_features_from_array(segment, ref_sr, bpm=bpm)
                    ref_db.upsert_feature(FeatureVector(
                        bar_id=bar_id,
                        chroma=chroma,
                        mfcc=mfcc,
                        onset=onset,
                        rms=rms,
                    ))
                    total_features += 1
                except Exception as exc:
                    log.warning("  T%03d Feature-Extraktion fehlgeschlagen: %s", bar_num, exc)
                    total_missing += 1

            else:
                # Pfad B: einzelne MP3-Datei
                audio_rel = bar_data.get("audio", "")
                if not audio_rel:
                    total_missing += 1
                    continue
                audio_abs = repo_root / audio_rel
                if not audio_abs.exists():
                    audio_abs = audio_root / Path(audio_rel).name
                if not audio_abs.exists():
                    log.warning("  T%03d Audio nicht gefunden: %s", bar_num, audio_rel)
                    total_missing += 1
                    continue
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
