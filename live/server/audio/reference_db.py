"""Reference database — SQLite-backed store for songs, bars and feature vectors.

Schema
------
songs          — Stammdaten aus lighting-ai-db.json
bars           — Takte mit absolutem bar_num (relativ zum Song), Audio-Pfad, Part-Name
feature_vectors— Vorberechnete Feature-Vektoren pro Takt (numpy BLOBs)

Alle bar_num-Werte sind **absolut zum Song** (Takt 1 = allererster Takt, keine
Rücksetzung an Partgrenzen). Part-Zugehörigkeit ergibt sich aus part_name.
"""

from __future__ import annotations

import io
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator, Sequence

import numpy as np

log = logging.getLogger("live.audio.refdb")

# Default DB path (override in tests or config)
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "reference.db"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SongRecord:
    song_id: str
    name: str
    bpm: float
    total_bars: int


@dataclass
class BarRecord:
    bar_id: str        # e.g. "B0059"
    song_id: str
    bar_num: int       # absolute to song (1-based)
    part_name: str     # e.g. "01 Thema 1"
    audio_path: str    # relative repo path, e.g. "audio/All The Small Things/..."


@dataclass
class FeatureVector:
    bar_id: str
    chroma: np.ndarray   # shape (12,), float32  — chroma_cqt mean
    mfcc: np.ndarray     # shape (20,), float32  — MFCC mean
    onset: np.ndarray    # shape (16,), float32  — onset strength in 16th-note bins
    rms: float           # scalar — RMS energy of the bar

    @property
    def vector(self) -> np.ndarray:
        """Concatenated feature vector (48 floats)."""
        return np.concatenate([self.chroma, self.mfcc, self.onset]).astype(np.float32)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _blob(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, arr.astype(np.float32))
    return buf.getvalue()


def _from_blob(data: bytes) -> np.ndarray:
    return np.load(io.BytesIO(data))


# ---------------------------------------------------------------------------
# ReferenceDB
# ---------------------------------------------------------------------------

class ReferenceDB:
    """Thread-safe wrapper around the SQLite reference database."""

    def __init__(self, path: Path = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # --- Connection context manager -----------------------------------------

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        con = sqlite3.connect(self.path, check_same_thread=False)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    # --- Schema -----------------------------------------------------------------

    def _init_schema(self) -> None:
        with self._conn() as con:
            con.executescript("""
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS songs (
                    song_id     TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    bpm         REAL NOT NULL,
                    total_bars  INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS bars (
                    bar_id      TEXT PRIMARY KEY,
                    song_id     TEXT NOT NULL REFERENCES songs(song_id),
                    bar_num     INTEGER NOT NULL,   -- absolute to song, 1-based
                    part_name   TEXT NOT NULL DEFAULT '',
                    audio_path  TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_bars_song_num
                    ON bars(song_id, bar_num);

                CREATE TABLE IF NOT EXISTS feature_vectors (
                    bar_id      TEXT PRIMARY KEY REFERENCES bars(bar_id),
                    chroma      BLOB NOT NULL,   -- numpy float32 (12,)
                    mfcc        BLOB NOT NULL,   -- numpy float32 (20,)
                    onset       BLOB NOT NULL,   -- numpy float32 (16,)
                    rms         REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS probe_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT NOT NULL,      -- WAV-Dateiname ohne Extension
                    wav_offset  REAL NOT NULL,       -- Sekunden seit Aufnahmestart
                    song_id     TEXT NOT NULL DEFAULT '',
                    bar_num     INTEGER NOT NULL DEFAULT 0,
                    part_name   TEXT NOT NULL DEFAULT '',
                    confidence  REAL NOT NULL DEFAULT 0.0,
                    chroma      BLOB,               -- numpy float32 (12,)
                    mfcc        BLOB,               -- numpy float32 (20,)
                    onset       BLOB,               -- numpy float32 (16,)
                    rms         REAL NOT NULL DEFAULT 0.0,
                    bpm_live    REAL NOT NULL DEFAULT 0.0,
                    is_downbeat INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_probe_events_session
                    ON probe_events(session_id, wav_offset);
            """)
        log.debug("Reference DB initialised at %s", self.path)

    # --- Songs ------------------------------------------------------------------

    def upsert_song(self, song: SongRecord) -> None:
        with self._conn() as con:
            con.execute(
                """INSERT INTO songs(song_id, name, bpm, total_bars)
                   VALUES(?, ?, ?, ?)
                   ON CONFLICT(song_id) DO UPDATE SET
                       name=excluded.name,
                       bpm=excluded.bpm,
                       total_bars=excluded.total_bars""",
                (song.song_id, song.name, song.bpm, song.total_bars),
            )

    def get_song(self, song_id: str) -> SongRecord | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT song_id, name, bpm, total_bars FROM songs WHERE song_id=?",
                (song_id,),
            ).fetchone()
        if row is None:
            return None
        return SongRecord(**dict(row))

    def list_songs(self) -> list[SongRecord]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT song_id, name, bpm, total_bars FROM songs ORDER BY name"
            ).fetchall()
        return [SongRecord(**dict(r)) for r in rows]

    def delete_song(self, song_id: str) -> None:
        """Remove song and all associated bars + feature vectors."""
        with self._conn() as con:
            bar_ids = [
                r[0]
                for r in con.execute(
                    "SELECT bar_id FROM bars WHERE song_id=?", (song_id,)
                ).fetchall()
            ]
            if bar_ids:
                placeholders = ",".join("?" * len(bar_ids))
                con.execute(
                    f"DELETE FROM feature_vectors WHERE bar_id IN ({placeholders})",
                    bar_ids,
                )
                con.execute(
                    f"DELETE FROM bars WHERE bar_id IN ({placeholders})", bar_ids
                )
            con.execute("DELETE FROM songs WHERE song_id=?", (song_id,))

    # --- Bars -------------------------------------------------------------------

    def upsert_bar(self, bar: BarRecord) -> None:
        with self._conn() as con:
            con.execute(
                """INSERT INTO bars(bar_id, song_id, bar_num, part_name, audio_path)
                   VALUES(?, ?, ?, ?, ?)
                   ON CONFLICT(bar_id) DO UPDATE SET
                       song_id=excluded.song_id,
                       bar_num=excluded.bar_num,
                       part_name=excluded.part_name,
                       audio_path=excluded.audio_path""",
                (bar.bar_id, bar.song_id, bar.bar_num, bar.part_name, bar.audio_path),
            )

    def get_bars_for_song(self, song_id: str) -> list[BarRecord]:
        with self._conn() as con:
            rows = con.execute(
                """SELECT bar_id, song_id, bar_num, part_name, audio_path
                   FROM bars WHERE song_id=? ORDER BY bar_num""",
                (song_id,),
            ).fetchall()
        return [BarRecord(**dict(r)) for r in rows]

    def get_bar(self, bar_id: str) -> BarRecord | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT bar_id, song_id, bar_num, part_name, audio_path FROM bars WHERE bar_id=?",
                (bar_id,),
            ).fetchone()
        if row is None:
            return None
        return BarRecord(**dict(row))

    def get_bar_by_num(self, song_id: str, bar_num: int) -> BarRecord | None:
        """Gibt den BarRecord für (song_id, bar_num) zurück oder None."""
        with self._conn() as con:
            row = con.execute(
                "SELECT bar_id, song_id, bar_num, part_name, audio_path "
                "FROM bars WHERE song_id=? AND bar_num=?",
                (song_id, bar_num),
            ).fetchone()
        if row is None:
            return None
        return BarRecord(**dict(row))

    # --- Feature Vectors --------------------------------------------------------

    def upsert_feature(self, fv: FeatureVector) -> None:
        with self._conn() as con:
            con.execute(
                """INSERT INTO feature_vectors(bar_id, chroma, mfcc, onset, rms)
                   VALUES(?, ?, ?, ?, ?)
                   ON CONFLICT(bar_id) DO UPDATE SET
                       chroma=excluded.chroma,
                       mfcc=excluded.mfcc,
                       onset=excluded.onset,
                       rms=excluded.rms""",
                (
                    fv.bar_id,
                    _blob(fv.chroma),
                    _blob(fv.mfcc),
                    _blob(fv.onset),
                    float(fv.rms),
                ),
            )

    def get_feature(self, bar_id: str) -> FeatureVector | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT bar_id, chroma, mfcc, onset, rms FROM feature_vectors WHERE bar_id=?",
                (bar_id,),
            ).fetchone()
        if row is None:
            return None
        return FeatureVector(
            bar_id=row["bar_id"],
            chroma=_from_blob(row["chroma"]),
            mfcc=_from_blob(row["mfcc"]),
            onset=_from_blob(row["onset"]),
            rms=row["rms"],
        )

    def get_all_features(self) -> list[FeatureVector]:
        """Load all feature vectors into memory (used by HMM at startup)."""
        with self._conn() as con:
            rows = con.execute(
                "SELECT bar_id, chroma, mfcc, onset, rms FROM feature_vectors"
            ).fetchall()
        return [
            FeatureVector(
                bar_id=r["bar_id"],
                chroma=_from_blob(r["chroma"]),
                mfcc=_from_blob(r["mfcc"]),
                onset=_from_blob(r["onset"]),
                rms=r["rms"],
            )
            for r in rows
        ]

    def bars_without_features(self) -> list[BarRecord]:
        """Return bars that have an audio_path but no feature vector yet."""
        with self._conn() as con:
            rows = con.execute(
                """SELECT b.bar_id, b.song_id, b.bar_num, b.part_name, b.audio_path
                   FROM bars b
                   LEFT JOIN feature_vectors fv ON fv.bar_id = b.bar_id
                   WHERE b.audio_path != '' AND fv.bar_id IS NULL
                   ORDER BY b.song_id, b.bar_num"""
            ).fetchall()
        return [BarRecord(**dict(r)) for r in rows]

    # --- Probe Events -----------------------------------------------------------

    def log_probe_event(
        self,
        session_id: str,
        wav_offset: float,
        song_id: str,
        bar_num: int,
        part_name: str,
        confidence: float,
        chroma: "np.ndarray",
        mfcc: "np.ndarray",
        onset: "np.ndarray",
        rms: float,
        bpm_live: float,
        is_downbeat: bool,
    ) -> None:
        """Loggt eine HMM-Entscheidung mit allen Feature-Daten."""
        with self._conn() as con:
            con.execute(
                """INSERT INTO probe_events
                   (session_id, wav_offset, song_id, bar_num, part_name,
                    confidence, chroma, mfcc, onset, rms, bpm_live, is_downbeat)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    session_id,
                    wav_offset,
                    song_id,
                    bar_num,
                    part_name,
                    confidence,
                    _blob(chroma),
                    _blob(mfcc),
                    _blob(onset),
                    float(rms),
                    float(bpm_live),
                    int(is_downbeat),
                ),
            )

    def export_probe_session(self, session_id: str) -> dict:
        """Exportiert alle Events einer Session als JSON-serialisierbares dict."""
        with self._conn() as con:
            rows = con.execute(
                """SELECT wav_offset, song_id, bar_num, part_name, confidence,
                          chroma, mfcc, onset, rms, bpm_live, is_downbeat
                   FROM probe_events
                   WHERE session_id = ?
                   ORDER BY wav_offset""",
                (session_id,),
            ).fetchall()

        events = []
        for r in rows:
            events.append({
                "wav_offset": round(r["wav_offset"], 3),
                "song_id": r["song_id"],
                "bar_num": r["bar_num"],
                "part_name": r["part_name"],
                "confidence": round(r["confidence"], 4),
                "chroma": _from_blob(r["chroma"]).tolist(),
                "mfcc": _from_blob(r["mfcc"]).tolist(),
                "onset": _from_blob(r["onset"]).tolist(),
                "rms": round(r["rms"], 6),
                "bpm_live": round(r["bpm_live"], 2),
                "is_downbeat": bool(r["is_downbeat"]),
            })

        return {
            "session_id": session_id,
            "event_count": len(events),
            "events": events,
        }

    def list_probe_sessions(self) -> list[dict]:
        """Listet alle vorhandenen Probe-Sessions."""
        with self._conn() as con:
            rows = con.execute(
                """SELECT session_id,
                          COUNT(*) as event_count,
                          MIN(wav_offset) as start_offset,
                          MAX(wav_offset) as end_offset
                   FROM probe_events
                   GROUP BY session_id
                   ORDER BY session_id DESC"""
            ).fetchall()
        return [
            {
                "session_id": r["session_id"],
                "event_count": r["event_count"],
                "duration_sec": round(r["end_offset"] - r["start_offset"], 1),
            }
            for r in rows
        ]

    # --- Stats ------------------------------------------------------------------

    def stats(self) -> dict:
        with self._conn() as con:
            n_songs = con.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
            n_bars = con.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
            n_features = con.execute("SELECT COUNT(*) FROM feature_vectors").fetchone()[0]
        return {"songs": n_songs, "bars": n_bars, "feature_vectors": n_features}
