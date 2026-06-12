"""Phase 2 — derive audio_assets rows from the song DB.

Two kinds of audio (see docs/architektur-zentrale-db.md):
- ``playalong``  — full-song reference per song (songs.audio_ref), what the
                   BassTrainer app plays along to.
- ``snippet``    — one mp3 per bar (bars.audio), lighting.ai's bar-level audio.

Only files that actually EXIST on disk are emitted — the source DB has some
stale audio paths (broken references), and we must not register storage objects
that were never uploaded.

The storage key inside the bucket mirrors the repo-relative path (e.g.
``audio/All The Small Things/All The Small Things - Full Song.mp3``), so dragging
the local ``audio/`` folder into the bucket lines up 1:1 with ``storage_path``.

Pure / offline; ``repo_root`` is only used to check file existence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

BUCKET = "snippets"


def _exists(repo_root: Path, rel: str) -> bool:
    return bool(rel) and (repo_root / rel).is_file()


def audio_assets_rows(db: dict[str, Any], repo_root: Path) -> list[dict]:
    """Return audio_assets rows for every referenced audio file that exists."""
    rows: list[dict] = []
    seen_paths: set[str] = set()

    # (1) Full-song play-along tracks from songs.audio_ref
    for sid, s in db.get("songs", {}).items():
        ref = s.get("audio_ref")
        if _exists(repo_root, ref) and ref not in seen_paths:
            seen_paths.add(ref)
            rows.append({
                "song_id": sid,
                "kind": "playalong",
                "bucket": BUCKET,
                "storage_path": ref,
                "bar_num": None,
                "part_id": None,
            })

    # (2) Per-bar snippets from bars.audio
    for b in db.get("bars", {}).values():
        p = b.get("audio")
        if _exists(repo_root, p) and p not in seen_paths:
            seen_paths.add(p)
            rows.append({
                "song_id": b["song_id"],
                "kind": "snippet",
                "bucket": BUCKET,
                "storage_path": p,
                "bar_num": b["bar_num"],
                "part_id": None,
            })

    return rows
