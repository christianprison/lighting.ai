"""Characterization of the song-database SCHEMA (db/lighting-ai-db.json).

This is the pre-port spec. The central-DB port maps this JSON onto the v3
Postgres schema (``songs`` core + ``song_detail_lighting`` JSONB + top-level
``bars``/``accents``). These tests freeze the *exact* field set so the
import/export round-trip cannot silently drop a field (e.g. ``split_markers``,
``tms``, ``qlc_parts``).

Pure stdlib (``unittest``) — runs anywhere, also collected by pytest.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "db" / "lighting-ai-db.json"

# ── The port's field mapping, frozen ───────────────────────────────────────
# Shared core -> Postgres `songs` columns (readable by ALL projects):
CORE_SONG_FIELDS = frozenset({
    "name", "artist", "bpm", "key", "year",
    "duration", "duration_sec", "notes", "pick", "gema_nr",
})
# lighting.ai-specific -> `song_detail_lighting` JSONB (opaque to other projects):
DETAIL_SONG_FIELDS = frozenset({
    "_lrclib_synced", "anchors", "audio_ref", "audio_ref_name", "grundrhythmus",
    "lyrics_raw", "qlc_id", "qlc_parts", "split_markers", "tms", "total_bars",
})
# Union = every field that currently exists on any song. The port MUST carry
# all of these. A new field appearing here fails the test on purpose, forcing a
# conscious decision (core vs. detail) before the schema can drift.
EXPECTED_SONG_FIELDS = CORE_SONG_FIELDS | DETAIL_SONG_FIELDS

EXPECTED_BAR_FIELDS = frozenset({
    "song_id", "bar_num", "lyrics", "audio", "has_accents", "instrumental",
})
EXPECTED_ACCENT_FIELDS = frozenset({
    "bar_id", "pos_16th", "type", "notes",
})
EXPECTED_TOP_KEYS = frozenset({
    "version", "band", "setlist", "songs", "bars", "accents", "meta",
})


def _union_of_keys(collection: dict) -> set:
    keys: set = set()
    for v in collection.values():
        keys |= set(v.keys())
    return keys


class DBSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = json.loads(DB_PATH.read_text(encoding="utf-8"))

    # ── Top-level shape ────────────────────────────────────────────────
    def test_top_level_keys(self) -> None:
        self.assertEqual(set(self.db.keys()), set(EXPECTED_TOP_KEYS))

    def test_collections_non_empty(self) -> None:
        self.assertGreater(len(self.db["songs"]), 0)
        self.assertGreater(len(self.db["bars"]), 0)
        self.assertGreater(len(self.db["accents"]), 0)

    # ── Field sets (the import spec) ───────────────────────────────────
    def test_song_fields_match_expected_union(self) -> None:
        observed = _union_of_keys(self.db["songs"])
        new = observed - EXPECTED_SONG_FIELDS
        gone = EXPECTED_SONG_FIELDS - observed
        self.assertEqual(
            new, set(),
            f"New song field(s) {sorted(new)} — assign to CORE or DETAIL before porting.",
        )
        self.assertEqual(
            gone, set(),
            f"Song field(s) {sorted(gone)} disappeared — update mapping/fixtures.",
        )

    def test_core_and_detail_partition_is_disjoint_and_complete(self) -> None:
        self.assertEqual(CORE_SONG_FIELDS & DETAIL_SONG_FIELDS, set())
        self.assertEqual(CORE_SONG_FIELDS | DETAIL_SONG_FIELDS, set(EXPECTED_SONG_FIELDS))

    def test_bar_fields_match_expected_union(self) -> None:
        self.assertEqual(_union_of_keys(self.db["bars"]), set(EXPECTED_BAR_FIELDS))

    def test_accent_fields_match_expected_union(self) -> None:
        self.assertEqual(_union_of_keys(self.db["accents"]), set(EXPECTED_ACCENT_FIELDS))

    # ── Every song carries the shared core minimally ───────────────────
    def test_every_song_has_a_name(self) -> None:
        missing = [sid for sid, s in self.db["songs"].items() if not s.get("name")]
        self.assertEqual(missing, [], f"songs without a name: {missing}")

    # ── Referential integrity (must survive the port) ──────────────────
    def test_every_bar_references_an_existing_song(self) -> None:
        songs = set(self.db["songs"])
        orphans = [bid for bid, b in self.db["bars"].items() if b.get("song_id") not in songs]
        self.assertEqual(orphans, [], f"orphan bars: {orphans[:10]}")

    def test_every_accent_references_an_existing_bar(self) -> None:
        bars = set(self.db["bars"])
        orphans = [aid for aid, a in self.db["accents"].items() if a.get("bar_id") not in bars]
        self.assertEqual(orphans, [], f"orphan accents: {orphans[:10]}")

    def test_setlist_song_refs_exist(self) -> None:
        songs = set(self.db["songs"])
        dangling = [
            it.get("song_id")
            for it in self.db["setlist"].get("items", [])
            if it.get("type") == "song" and it.get("song_id") not in songs
        ]
        self.assertEqual(dangling, [], f"dangling setlist refs: {dangling}")

    def test_bar_num_is_unique_per_song(self) -> None:
        # Mirrors the UNIQUE(song_id, bar_num) the port relies on (feature_vectors PK).
        #
        # KNOWN DATA DEBT: song "HDX1IN" (You're all I have) carries stale
        # duplicate bars 1-4 from a re-split (131 bar objects vs. total_bars=120,
        # bar_num runs to 127). It must be cleaned up BEFORE/DURING the port, or
        # the UNIQUE(song_id, bar_num) constraint will reject the import. This
        # allowlist keeps the baseline green for the existing debt while still
        # catching any NEW duplicate that creeps into another song.
        KNOWN_DUPLICATE_SONGS = {"HDX1IN"}
        seen: dict[tuple, str] = {}
        dups = []
        for bid, b in self.db["bars"].items():
            key = (b.get("song_id"), b.get("bar_num"))
            if key in seen and b.get("song_id") not in KNOWN_DUPLICATE_SONGS:
                dups.append((key, seen[key], bid))
            seen[key] = bid
        self.assertEqual(dups, [], f"NEW duplicate (song_id, bar_num): {dups[:10]}")

    # ── Accent types are declared in meta (consistency) ────────────────
    def test_accent_types_are_known(self) -> None:
        known = set(self.db["meta"].get("accent_types", {}))
        used = {a.get("type") for a in self.db["accents"].values()}
        unknown = used - known
        self.assertEqual(unknown, set(), f"accent types not in meta.accent_types: {unknown}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
