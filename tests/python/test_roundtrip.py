"""THE centerpiece port test: lighting-ai-db.json -> rows -> json is lossless.

Proves the central-DB schema (v3.1) represents the existing database without
losing or mangling a single field. If this is green, the Supabase import/export
cannot silently drop data.

Pure stdlib — runs offline, no database needed.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.central_db.transform import db_json_to_rows, rows_to_db_json  # noqa: E402

DB_PATH = REPO_ROOT / "db" / "lighting-ai-db.json"


class RoundTripTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = DB_PATH.read_text(encoding="utf-8")
        cls.db = json.loads(cls.raw)

    # ── The core guarantee ─────────────────────────────────────────────
    def test_roundtrip_is_semantically_identical(self) -> None:
        rebuilt = rows_to_db_json(db_json_to_rows(self.db))
        self.assertEqual(rebuilt, self.db)

    def test_export_is_canonical_and_stable(self) -> None:
        # Byte-identity to the SOURCE is impossible: the existing file has four
        # historical bar key orderings (cosmetic). The transform emits one
        # canonical order, so the FIRST Supabase->json export reorders some bar
        # keys once. What matters is that every export thereafter is stable —
        # the canonical form is a fixed point, so git diffs don't churn.
        once = json.dumps(rows_to_db_json(db_json_to_rows(self.db)), indent=2, ensure_ascii=False)
        twice = json.dumps(
            rows_to_db_json(db_json_to_rows(json.loads(once))), indent=2, ensure_ascii=False
        )
        self.assertEqual(once, twice, "export is not a stable fixed point")

    def test_canonicalisation_changes_only_key_order_not_data(self) -> None:
        # Re-affirms the one-time export diff is purely cosmetic: the canonical
        # form is semantically identical to the source.
        rebuilt = rows_to_db_json(db_json_to_rows(self.db))
        self.assertEqual(json.loads(json.dumps(rebuilt)), self.db)

    # ── Row-shape sanity (mirrors the SQL schema constraints) ──────────
    def test_every_song_yields_a_core_and_a_detail_row(self) -> None:
        rows = db_json_to_rows(self.db)
        n = len(self.db["songs"])
        self.assertEqual(len(rows["songs"]), n)
        self.assertEqual(len(rows["song_detail_lighting"]), n)

    def test_core_rows_carry_every_core_column_non_null(self) -> None:
        rows = db_json_to_rows(self.db)
        from scripts.central_db.transform import CORE_FIELDS
        cols = {c for _, c in CORE_FIELDS} | {"id"}
        for r in rows["songs"]:
            self.assertEqual(set(r.keys()), cols)
            self.assertIsNotNone(r["id"])

    def test_detail_rows_never_contain_a_core_field(self) -> None:
        rows = db_json_to_rows(self.db)
        from scripts.central_db.transform import _CORE_JSON_FIELDS
        for r in rows["song_detail_lighting"]:
            leaked = _CORE_JSON_FIELDS & set(r["detail"].keys())
            self.assertEqual(leaked, set(), f"core field leaked into detail: {leaked}")

    def test_bar_rows_satisfy_unique_song_bar(self) -> None:
        rows = db_json_to_rows(self.db)
        keys = [(b["song_id"], b["bar_num"]) for b in rows["bars"]]
        self.assertEqual(len(keys), len(set(keys)), "UNIQUE(song_id, bar_num) violated")

    def test_bar_rows_have_fixed_columns(self) -> None:
        rows = db_json_to_rows(self.db)
        expected = {"bar_id", "bar_num", "lyrics", "audio", "has_accents", "song_id", "instrumental"}
        for b in rows["bars"]:
            self.assertEqual(set(b.keys()), expected)

    def test_accent_rows_reference_bars_that_exist_in_rows(self) -> None:
        rows = db_json_to_rows(self.db)
        bar_ids = {b["bar_id"] for b in rows["bars"]}
        dangling = [a["accent_id"] for a in rows["accents"] if a["bar_id"] not in bar_ids]
        self.assertEqual(dangling, [], f"accents referencing missing bars: {dangling[:5]}")

    def test_app_state_singleton_holds_globals(self) -> None:
        rows = db_json_to_rows(self.db)
        app = rows["app_state"]
        self.assertEqual(app["id"], 1)
        self.assertEqual(app["version"], self.db["version"])
        self.assertEqual(app["band"], self.db["band"])
        self.assertEqual(app["setlist"], self.db["setlist"])
        self.assertEqual(app["meta"], self.db["meta"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
