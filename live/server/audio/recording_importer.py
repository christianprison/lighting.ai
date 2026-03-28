"""recording_importer.py — Feature-Extraktion aus annotierten Probe-Aufnahmen.

Workflow
--------
1. Benutzer annotiert Takte/Parts manuell in der Rehearsal Post-Preparation App.
2. Dieser Importer liest die Annotationen + 18-Kanal-WAV.
3. Für jeden annotierten Takt: Audio-Segment → Features → reference.db.

Feature-Extraktion
------------------
- Kanal 16 + 17 (Main L/R) → Mono-Mix → Resample auf 22 050 Hz → librosa
- Identisches Verfahren wie snippet_importer.py (``extract_features_from_array``)

Inkrementelles Averaging
------------------------
Bei bestehenden Feature-Vektoren wird ein gewichteter Mittelwert gebildet:

    new_mean = (old_mean × n + new) / (n + 1)

Dazu wird eine optionale ``sample_count``-Spalte in ``feature_vectors``
genutzt (wird bei Bedarf per ALTER TABLE angelegt, Default = 1).

Schema-Migration
----------------
Falls die Spalte ``sample_count`` noch nicht existiert, wird sie per
``ALTER TABLE feature_vectors ADD COLUMN sample_count INTEGER DEFAULT 1``
automatisch hinzugefügt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import numpy as np

if TYPE_CHECKING:
    from .reference_db import ReferenceDB

log = logging.getLogger("live.audio.recording_importer")

# WAV-Kanäle für den Stereo-Mix (0-basiert, XR18 USB-Belegung)
_MIX_L = 16
_MIX_R = 17
# Ziel-Samplerate für Feature-Extraktion (librosa-Standard)
_TARGET_SR = 22_050


# ---------------------------------------------------------------------------
# Ergebnis-Statistik
# ---------------------------------------------------------------------------

@dataclass
class ImportStats:
    songs_processed: int = 0
    bars_updated: int = 0       # vorhandener Eintrag: gemittelt
    bars_inserted: int = 0      # neuer Eintrag
    bars_skipped: int = 0       # kein Bar-Record in DB oder zu kurz
    errors: int = 0


# ---------------------------------------------------------------------------
# Haupt-Funktion
# ---------------------------------------------------------------------------

def import_from_recording(
    wav_path: Path,
    annotations: dict,               # dict[song_id, SongAnnotation]
    ref_db_path: Path,
    db_json_path: Path,
    session_sample_rate: int = 48_000,
) -> ImportStats:
    """Importiert annotierte Takte aus einer Probe-Aufnahme in die reference.db.

    Parameters
    ----------
    wav_path:
        Pfad zur 18-Kanal-WAV-Datei (48 kHz, float32).
    annotations:
        Dict ``song_id → SongAnnotation`` (aus ``annotation.py`` geladen).
        ``SongAnnotation.segment_start_t`` gibt den WAV-Offset des
        Segment-Starts an; ``BarMarker.t`` ist relativ dazu.
    ref_db_path:
        Pfad zur SQLite reference.db.
    db_json_path:
        Pfad zur ``lighting-ai-db.json`` (für BPM-Lookup).
    session_sample_rate:
        Samplerate der WAV-Aufnahme (Standard: 48 000 Hz).
        Wird durch soundfile-Header überschrieben.
    """
    try:
        import librosa          # type: ignore
        import soundfile as sf  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "librosa und soundfile werden benötigt: pip install librosa soundfile"
        ) from exc

    import json as _json

    from .reference_db import ReferenceDB
    from .fingerprint import extract_features_from_array

    # BPM-Map aus lighting-ai-db.json laden
    bpm_map: dict[str, float] = {}
    if db_json_path.exists():
        with db_json_path.open(encoding="utf-8") as f:
            db_raw = _json.load(f)
        bpm_map = {
            sid: float(s.get("bpm", 120))
            for sid, s in db_raw.get("songs", {}).items()
        }

    ref_db = ReferenceDB(ref_db_path)
    _ensure_sample_count_column(ref_db)

    stats = ImportStats()

    # WAV lazy lesen – nur benötigte Frames per seek
    with sf.SoundFile(str(wav_path)) as wav_file:
        file_sr:   int = wav_file.samplerate
        n_channels: int = wav_file.channels
        total_frames: int = wav_file.frames

        log.info(
            "WAV: %s  (%d ch, %d Hz, %d Frames = %.1f min)",
            wav_path.name, n_channels, file_sr,
            total_frames, total_frames / file_sr / 60,
        )

        # Mix-Kanal-Auswahl
        if n_channels > max(_MIX_L, _MIX_R):
            mix_l, mix_r = _MIX_L, _MIX_R
        else:
            log.warning(
                "WAV hat nur %d Kanäle — nutze Kanal 0/1 als Mix-Fallback", n_channels
            )
            mix_l, mix_r = 0, min(1, n_channels - 1)

        for song_id, song_ann in annotations.items():
            if not song_ann.markers:
                log.info("Song %s: keine Marker — übersprungen", song_id)
                continue

            seg_offset = float(getattr(song_ann, "segment_start_t", 0.0))
            bpm        = bpm_map.get(song_id, 120.0)
            stats.songs_processed += 1

            log.info(
                "Song: %s (%s)  — %d Takte annotiert, Offset %.2f s",
                song_id, song_ann.song_name, len(song_ann.markers), seg_offset,
            )

            for i, marker in enumerate(song_ann.markers):
                bar_num = marker.bar_num

                # Zeitgrenzen (WAV-absolut)
                t_start = seg_offset + marker.t
                if i + 1 < len(song_ann.markers):
                    t_end = seg_offset + song_ann.markers[i + 1].t
                else:
                    # Letzter Takt: 4 Sekunden Fallback (1 Takt bei 60 BPM)
                    beat_dur = 60.0 / bpm * 4  # 1 Takt = 4 Beats
                    t_end = t_start + beat_dur

                frame_start = max(0, int(t_start * file_sr))
                frame_end   = min(total_frames, int(t_end * file_sr))
                n_frames    = frame_end - frame_start

                if n_frames < int(0.1 * file_sr):
                    log.debug(
                        "  T%03d: zu kurz (%d Frames) — übersprungen", bar_num, n_frames
                    )
                    stats.bars_skipped += 1
                    continue

                # Audio-Block lesen und zu Mono mixen
                wav_file.seek(frame_start)
                block = wav_file.read(n_frames, dtype="float32", always_2d=True)
                mono = (block[:, mix_l] + block[:, mix_r]) * 0.5

                # Auf Ziel-Samplerate resampling (falls nötig)
                if file_sr != _TARGET_SR:
                    mono = librosa.resample(mono, orig_sr=file_sr, target_sr=_TARGET_SR)

                # Feature-Extraktion
                try:
                    chroma, mfcc, onset, rms = extract_features_from_array(
                        mono, _TARGET_SR, bpm=bpm
                    )
                except Exception as exc:
                    log.warning("  T%03d Feature-Extraktion: %s", bar_num, exc)
                    stats.errors += 1
                    continue

                # Bar-Record in reference.db suchen
                bar_rec = ref_db.get_bar_by_num(song_id, bar_num)
                if bar_rec is None:
                    log.debug("  T%03d kein Bar-Record für %s — übersprungen",
                              bar_num, song_id)
                    stats.bars_skipped += 1
                    continue

                # Feature-Vektor inkrementell einarbeiten
                is_new = _upsert_averaged(
                    ref_db, bar_rec.bar_id, chroma, mfcc, onset, float(rms)
                )
                if is_new:
                    stats.bars_inserted += 1
                else:
                    stats.bars_updated += 1
                log.debug(
                    "  T%03d %s  %s",
                    bar_num,
                    "NEU" if is_new else "gemittelt",
                    bar_rec.bar_id,
                )

    log.info(
        "Import fertig: %d Songs | %d neu | %d gemittelt | "
        "%d übersprungen | %d Fehler",
        stats.songs_processed,
        stats.bars_inserted,
        stats.bars_updated,
        stats.bars_skipped,
        stats.errors,
    )
    return stats


# ---------------------------------------------------------------------------
# Interne Hilfsfunktionen
# ---------------------------------------------------------------------------

def _ensure_sample_count_column(ref_db: "ReferenceDB") -> None:
    """Fügt ``sample_count``-Spalte zu ``feature_vectors`` hinzu falls fehlend."""
    with ref_db._conn() as con:
        cols = [row[1] for row in
                con.execute("PRAGMA table_info(feature_vectors)").fetchall()]
        if "sample_count" not in cols:
            con.execute(
                "ALTER TABLE feature_vectors "
                "ADD COLUMN sample_count INTEGER DEFAULT 1"
            )
            log.info("feature_vectors.sample_count-Spalte angelegt (Migration)")


def _upsert_averaged(
    ref_db: "ReferenceDB",
    bar_id: str,
    chroma: np.ndarray,
    mfcc: np.ndarray,
    onset: np.ndarray,
    rms: float,
) -> bool:
    """Inkrementelles Averaging des Feature-Vektors in der DB.

    Returns True wenn ein neuer Eintrag angelegt wurde, False wenn gemittelt.
    """
    # Direktzugriff auf private Helpers (_blob, _from_blob) aus reference_db
    from .reference_db import _blob, _from_blob

    with ref_db._conn() as con:
        row = con.execute(
            "SELECT chroma, mfcc, onset, rms, COALESCE(sample_count, 1) AS n "
            "FROM feature_vectors WHERE bar_id = ?",
            (bar_id,),
        ).fetchone()

        if row is None:
            # Neuer Eintrag
            con.execute(
                "INSERT INTO feature_vectors "
                "(bar_id, chroma, mfcc, onset, rms, sample_count) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (bar_id, _blob(chroma), _blob(mfcc), _blob(onset), rms),
            )
            return True

        # Vorhandenen Eintrag mitteln
        n          = int(row["n"])
        old_chroma = _from_blob(row["chroma"])
        old_mfcc   = _from_blob(row["mfcc"])
        old_onset  = _from_blob(row["onset"])
        old_rms    = float(row["rms"])

        n1 = n + 1
        new_chroma = ((old_chroma * n + chroma) / n1).astype(np.float32)
        new_mfcc   = ((old_mfcc   * n + mfcc)   / n1).astype(np.float32)
        new_onset  = ((old_onset  * n + onset)   / n1).astype(np.float32)
        new_rms    = (old_rms * n + rms) / n1

        con.execute(
            "UPDATE feature_vectors "
            "SET chroma=?, mfcc=?, onset=?, rms=?, sample_count=? "
            "WHERE bar_id=?",
            (_blob(new_chroma), _blob(new_mfcc), _blob(new_onset),
             new_rms, n1, bar_id),
        )
        return False
