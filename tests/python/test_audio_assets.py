"""Phase 2 — audio_assets row derivation is correct and points at real files.

Skips automatically where the audio/ folder is absent (shallow checkout / CI
without the binaries).
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.central_db.audio_assets import audio_assets_rows, BUCKET  # noqa: E402

DB_PATH = REPO_ROOT / "db" / "lighting-ai-db.json"
AUDIO_DIR = REPO_ROOT / "audio"


@unittest.skipUnless(AUDIO_DIR.is_dir(), "audio/ folder not present in this checkout")
class AudioAssetsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = json.loads(DB_PATH.read_text(encoding="utf-8"))
        cls.rows = audio_assets_rows(cls.db, REPO_ROOT)

    def test_rows_exist(self) -> None:
        self.assertGreater(len(self.rows), 0)

    def test_every_row_points_to_an_existing_file(self) -> None:
        missing = [r["storage_path"] for r in self.rows if not (REPO_ROOT / r["storage_path"]).is_file()]
        self.assertEqual(missing, [], f"rows pointing at missing files: {missing[:5]}")

    def test_columns_and_bucket(self) -> None:
        for r in self.rows:
            self.assertEqual(set(r.keys()),
                             {"song_id", "kind", "bucket", "storage_path", "bar_num", "part_id"})
            self.assertEqual(r["bucket"], BUCKET)
            self.assertIn(r["kind"], {"playalong", "snippet"})

    def test_storage_path_is_unique(self) -> None:
        paths = [r["storage_path"] for r in self.rows]
        self.assertEqual(len(paths), len(set(paths)), "duplicate storage_path (UNIQUE violation)")

    def test_playalong_rows_match_song_audio_ref(self) -> None:
        songs = self.db["songs"]
        for r in (x for x in self.rows if x["kind"] == "playalong"):
            self.assertIsNone(r["bar_num"])
            self.assertEqual(songs[r["song_id"]].get("audio_ref"), r["storage_path"])

    def test_snippet_rows_match_a_bar(self) -> None:
        bars_by_key = {(b["song_id"], b["bar_num"]): b for b in self.db["bars"].values()}
        for r in (x for x in self.rows if x["kind"] == "snippet"):
            self.assertIsNotNone(r["bar_num"])
            bar = bars_by_key.get((r["song_id"], r["bar_num"]))
            self.assertIsNotNone(bar, f"snippet has no matching bar: {r}")
            self.assertEqual(bar["audio"], r["storage_path"])

    def test_song_ids_exist(self) -> None:
        songs = set(self.db["songs"])
        bad = [r["song_id"] for r in self.rows if r["song_id"] not in songs]
        self.assertEqual(bad, [], f"audio_assets referencing unknown songs: {bad[:5]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
