"""Characterization of the Live-App READ API response shapes.

The endpoints ``/api/songs``, ``/api/songs/{id}/bars`` and ``/api/setlist`` are
thin shaping layers over the in-memory ``db``. After the port the *source* of
``db`` changes (Supabase-backed snapshot), but the JSON the iPad UI receives
must stay byte-shape-identical.

Strategy: import the module, swap the module-global ``db``/``qlc_data`` for a
fixture, and call the endpoint coroutines directly — no Uvicorn, no lifespan,
no audio/OSC hardware boot. Skipped where the live deps (fastapi, httpx,
sounddevice, …) are not installed (e.g. this CI sandbox).
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from live.server import main as live_main
    _IMPORT_ERR = None
except Exception as exc:  # pragma: no cover - environment-dependent
    live_main = None
    _IMPORT_ERR = exc


def _fixture_db() -> dict:
    return {
        "songs": {
            "S1": {
                "name": "Animal",
                "artist": "Neon Trees",
                "bpm": 164,
                "key": "D dur",
                "duration": "3:30",
                "duration_sec": 210,
                "anchors": [{"id": "anc_1", "pos": 1, "type": "drum", "event": "Crash"}],
            }
        },
        "bars": {
            "B0001": {"song_id": "S1", "bar_num": 1, "lyrics": "  here we go  "},
            "B0002": {"song_id": "S1", "bar_num": 2, "lyrics": "again"},
        },
        "setlist": {
            "name": "Repertoire",
            "items": [
                {"type": "song", "pos": 1, "song_id": "S1"},
                {"type": "pause"},
            ],
        },
    }


@unittest.skipIf(_IMPORT_ERR is not None, f"live deps unavailable: {_IMPORT_ERR}")
class LiveReadApiShapeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_db = getattr(live_main, "db", None)
        self._saved_qlc = getattr(live_main, "qlc_data", None)
        live_main.db = _fixture_db()
        live_main.qlc_data = None  # has_chaser -> False path

    def tearDown(self) -> None:
        live_main.db = self._saved_db
        live_main.qlc_data = self._saved_qlc

    def test_get_songs_shape(self) -> None:
        out = asyncio.run(live_main.get_songs())
        self.assertIn("S1", out)
        song = out["S1"]
        self.assertEqual(
            set(song.keys()),
            {"name", "artist", "bpm", "key", "duration", "duration_sec", "parts", "anchors"},
        )
        self.assertIsInstance(song["parts"], list)
        self.assertEqual(song["anchors"][0]["id"], "anc_1")

    def test_get_song_bars_shape(self) -> None:
        out = asyncio.run(live_main.get_song_bars("S1"))
        self.assertIsInstance(out, list)
        self.assertGreaterEqual(len(out), 1)
        part = out[0]
        self.assertEqual(set(part.keys()), {"part_id", "part_name", "bar_count", "bars"})
        bar = part["bars"][0]
        self.assertEqual(set(bar.keys()), {"bar_num", "lyrics"})
        self.assertEqual(bar["lyrics"], "here we go")  # endpoint strips whitespace

    def test_get_song_bars_404(self) -> None:
        out = asyncio.run(live_main.get_song_bars("NOPE"))
        # returns a JSONResponse with status 404
        self.assertEqual(getattr(out, "status_code", None), 404)

    def test_get_setlist_shape(self) -> None:
        out = asyncio.run(live_main.get_setlist())
        self.assertEqual(set(out.keys()), {"name", "items"})
        song_item = out["items"][0]
        self.assertEqual(
            set(song_item.keys()),
            {"type", "pos", "song_id", "name", "artist", "bpm", "has_chaser"},
        )
        self.assertEqual(song_item["has_chaser"], False)
        self.assertEqual(out["items"][1], {"type": "pause"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
