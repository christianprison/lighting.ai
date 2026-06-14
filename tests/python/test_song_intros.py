"""song_intros builder: pitch resolution (string+fret/note_name/midi), idx, skips."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.central_db.song_intros import (  # noqa: E402
    song_intros_rows, _note_to_midi, _midi_to_name,
)

INTROS_FILE = REPO_ROOT / "db" / "song-intros.json"


class PitchHelpersTest(unittest.TestCase):
    def test_open_strings_note_names(self) -> None:
        # Sounding open strings: E1=28, A1=33, D2=38, G2=43
        self.assertEqual(_note_to_midi("E1"), 28)
        self.assertEqual(_note_to_midi("A1"), 33)
        self.assertEqual(_note_to_midi("D2"), 38)
        self.assertEqual(_note_to_midi("G2"), 43)

    def test_accidentals_and_roundtrip(self) -> None:
        self.assertEqual(_note_to_midi("F#2"), 42)
        self.assertEqual(_note_to_midi("Db2"), 37)
        self.assertEqual(_midi_to_name(38), "D2")
        self.assertEqual(_midi_to_name(28), "E1")


class SongIntrosBuilderTest(unittest.TestCase):
    def test_string_fret_resolves_to_sounding_midi(self) -> None:
        intros = {"AAA": [
            {"string": 3, "fret": 0, "beat": 0.0},   # open D -> 38
            {"string": 4, "fret": 2, "beat": 1.0},   # G string fret2 -> 45 (A2)
        ]}
        rows, skipped, problems = song_intros_rows(intros, {"AAA"})
        self.assertEqual(problems, [])
        self.assertEqual([r["idx"] for r in rows], [1, 2])
        self.assertEqual(rows[0]["midi"], 38)
        self.assertEqual(rows[0]["note_name"], "D2")   # auto-filled
        self.assertEqual(rows[1]["midi"], 45)

    def test_note_name_and_midi_forms(self) -> None:
        intros = {"AAA": [{"note_name": "D2", "beat": 0.0}, {"midi": 43, "beat": 1.0}]}
        rows, _, problems = song_intros_rows(intros, {"AAA"})
        self.assertEqual(problems, [])
        self.assertEqual(rows[0]["midi"], 38)
        self.assertEqual(rows[1]["midi"], 43)

    def test_underscore_and_unknown_skipped(self) -> None:
        intros = {"_x": [{"midi": 1, "beat": 0}], "GHOST": [{"midi": 38, "beat": 0}],
                  "AAA": [{"string": 1, "fret": 0, "beat": 0}]}
        rows, skipped, problems = song_intros_rows(intros, {"AAA"})
        self.assertEqual(skipped, ["GHOST"])
        self.assertEqual({r["song_id"] for r in rows}, {"AAA"})

    def test_bad_note_skips_whole_song_not_fatal(self) -> None:
        # missing pitch on note 2 -> whole song skipped + reported, idx stays clean
        intros = {"AAA": [{"string": 3, "fret": 0, "beat": 0}, {"beat": 1.0}]}
        rows, skipped, problems = song_intros_rows(intros, {"AAA"})
        self.assertEqual(rows, [])
        self.assertEqual(len(problems), 1)
        self.assertIn("AAA", problems[0])

    def test_repo_intros_file_parses(self) -> None:
        data = json.loads(INTROS_FILE.read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict)
        rows, skipped, problems = song_intros_rows(data, set())  # no real songs yet
        self.assertEqual(rows, [])      # only _-keys -> nothing
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
