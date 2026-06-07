"""Contract tests for detection/reference_db.py (the SQLite feature store).

After the port, ``reference.db`` may be regenerated from the central
``feature_vectors`` table — but its public read/write contract (used by the
live audio thread) must stay identical. These tests run against a throwaway
SQLite file in a temp dir.

Requires numpy (live/rehearsal venv). Skipped automatically where it or the
detection package is unavailable (e.g. this CI sandbox).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import numpy as np
    from detection.reference_db import (
        ReferenceDB,
        SongRecord,
        BarRecord,
        FeatureVector,
    )
    _IMPORT_ERR = None
except Exception as exc:  # pragma: no cover - environment-dependent
    _IMPORT_ERR = exc


@unittest.skipIf(_IMPORT_ERR is not None, f"detection/numpy unavailable: {_IMPORT_ERR}")
class ReferenceDBContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ReferenceDB(Path(self._tmp.name) / "reference.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_song_roundtrip(self) -> None:
        self.db.upsert_song(SongRecord(song_id="abc123", name="Animal", bpm=164.0, total_bars=80))
        got = self.db.get_song("abc123")
        self.assertIsNotNone(got)
        self.assertEqual(got.name, "Animal")
        self.assertEqual(got.total_bars, 80)
        self.assertEqual([s.song_id for s in self.db.list_songs()], ["abc123"])

    def test_upsert_song_is_idempotent(self) -> None:
        self.db.upsert_song(SongRecord(song_id="abc123", name="Animal", bpm=164.0, total_bars=80))
        self.db.upsert_song(SongRecord(song_id="abc123", name="Animal (v2)", bpm=165.0, total_bars=82))
        self.assertEqual(len(self.db.list_songs()), 1)
        self.assertEqual(self.db.get_song("abc123").name, "Animal (v2)")

    def test_bars_and_parts(self) -> None:
        self.db.upsert_song(SongRecord(song_id="s", name="S", bpm=120.0, total_bars=4))
        bars = [
            BarRecord(bar_id="B1", song_id="s", bar_num=1, part_name="Intro", audio_path="audio/s/1.mp3"),
            BarRecord(bar_id="B2", song_id="s", bar_num=2, part_name="Intro", audio_path="audio/s/2.mp3"),
            BarRecord(bar_id="B3", song_id="s", bar_num=3, part_name="Verse", audio_path="audio/s/3.mp3"),
        ]
        for b in bars:
            self.db.upsert_bar(b)

        # bar_num is absolute to song, no reset at part boundary (verified contract)
        self.assertEqual([b.bar_num for b in self.db.get_bars_for_song("s")], [1, 2, 3])
        self.assertEqual(self.db.get_bar_by_num("s", 2).part_name, "Intro")

        parts = self.db.get_parts_for_song("s")
        by_name = {p["part_name"]: p for p in parts}
        self.assertEqual(by_name["Intro"]["first_bar"], 1)
        self.assertEqual(by_name["Intro"]["last_bar"], 2)
        self.assertEqual(by_name["Verse"]["first_bar"], 3)

    def test_feature_vector_roundtrip(self) -> None:
        self.db.upsert_song(SongRecord(song_id="s", name="S", bpm=120.0, total_bars=1))
        self.db.upsert_bar(BarRecord(bar_id="B1", song_id="s", bar_num=1, part_name="", audio_path=""))
        fv = FeatureVector(
            bar_id="B1",
            chroma=np.arange(12, dtype=np.float32),
            mfcc=np.arange(20, dtype=np.float32),
            onset=np.arange(16, dtype=np.float32),
            rms=0.5,
        )
        self.db.upsert_feature(fv)
        got = self.db.get_feature("B1")
        self.assertIsNotNone(got)
        np.testing.assert_array_almost_equal(got.chroma, np.arange(12))
        self.assertAlmostEqual(got.rms, 0.5, places=5)

    def test_delete_song_cascades(self) -> None:
        self.db.upsert_song(SongRecord(song_id="s", name="S", bpm=120.0, total_bars=1))
        self.db.upsert_bar(BarRecord(bar_id="B1", song_id="s", bar_num=1, part_name="", audio_path=""))
        self.db.delete_song("s")
        self.assertIsNone(self.db.get_song("s"))
        self.assertEqual(self.db.get_bars_for_song("s"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
