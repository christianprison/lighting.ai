"""song_intros builder: idx derivation, _-skip, unknown-song-id skip."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.central_db.song_intros import song_intros_rows  # noqa: E402

INTROS_FILE = REPO_ROOT / "db" / "song-intros.json"


class SongIntrosBuilderTest(unittest.TestCase):
    def test_idx_is_derived_gapfree(self) -> None:
        intros = {"AAA": [{"midi": 38, "beat": 0.0}, {"midi": 40, "beat": 0.5}, {"midi": 43, "beat": 1.0}]}
        rows, skipped = song_intros_rows(intros, {"AAA"})
        self.assertEqual([r["idx"] for r in rows], [1, 2, 3])
        self.assertEqual(skipped, [])
        self.assertEqual(rows[0], {"song_id": "AAA", "idx": 1, "midi": 38, "beat": 0.0,
                                   "duration_beats": None, "string": None, "fret": None, "note_name": None})

    def test_optional_fields_passthrough(self) -> None:
        intros = {"AAA": [{"midi": 38, "beat": -1.0, "duration_beats": 0.5, "string": 3, "fret": 0, "note_name": "D2"}]}
        rows, _ = song_intros_rows(intros, {"AAA"})
        self.assertEqual(rows[0]["string"], 3)
        self.assertEqual(rows[0]["note_name"], "D2")
        self.assertEqual(rows[0]["beat"], -1.0)  # pickup allowed

    def test_underscore_keys_ignored(self) -> None:
        intros = {"_format": "doc", "_example": [{"midi": 1, "beat": 0}], "AAA": [{"midi": 38, "beat": 0}]}
        rows, skipped = song_intros_rows(intros, {"AAA"})
        self.assertEqual({r["song_id"] for r in rows}, {"AAA"})
        self.assertEqual(skipped, [])

    def test_unknown_song_id_is_skipped_not_fatal(self) -> None:
        intros = {"GHOST": [{"midi": 38, "beat": 0}], "AAA": [{"midi": 38, "beat": 0}]}
        rows, skipped = song_intros_rows(intros, {"AAA"})
        self.assertEqual(skipped, ["GHOST"])
        self.assertEqual({r["song_id"] for r in rows}, {"AAA"})

    def test_repo_intros_file_is_valid_and_safe(self) -> None:
        # The committed authoring file must parse and contain only _-keys for now
        # (no real song_ids invented). When the band adds real intros, this still
        # passes as long as they reference existing songs.
        data = json.loads(INTROS_FILE.read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict)
        # every non-_ key's value must be a list of note dicts with midi+beat
        for k, v in data.items():
            if k.startswith("_"):
                continue
            self.assertIsInstance(v, list, f"{k} must map to a list")
            for n in v:
                self.assertIn("midi", n)
                self.assertIn("beat", n)


if __name__ == "__main__":
    unittest.main(verbosity=2)
