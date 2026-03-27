"""session.py — Rehearsal session data model.

Loads a JSONL event log and locates the matching WAV file.
Splits the recording into SongSegments based on select_song events.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SessionEvent:
    t: float           # seconds since recording start
    type: str
    data: dict = field(default_factory=dict)


@dataclass
class SongSegment:
    song_id: str
    song_name: str
    start_t: float     # seconds in WAV
    end_t: float
    events: list[SessionEvent] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end_t - self.start_t


@dataclass
class Session:
    wav_path: Path
    mixdown_path: Optional[Path]   # stereo mixdown if available
    jsonl_path: Path
    sample_rate: int
    n_channels: int
    total_duration: float
    songs: list[SongSegment]
    all_events: list[SessionEvent]


def load_session(jsonl_path: Path, db: Optional[dict] = None) -> Session:
    """Parse a JSONL event log and return a Session.

    Args:
        jsonl_path: Path to the .jsonl file.
        db: Optional loaded lighting-ai-db.json for song name enrichment.
    """
    events: list[SessionEvent] = []
    with open(jsonl_path, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            t = float(obj.pop("t", 0.0))
            etype = str(obj.pop("type", "unknown"))
            events.append(SessionEvent(t=t, type=etype, data=obj))

    wav_name: Optional[str] = None
    sample_rate = 48_000
    n_channels = 18
    total_duration = 0.0

    for ev in events:
        if ev.type == "session_start":
            wav_name = ev.data.get("wav")
            sample_rate = int(ev.data.get("sample_rate", 48_000))
            n_channels = int(ev.data.get("channels", 18))
        elif ev.type == "session_end":
            total_duration = float(ev.data.get("duration_sec", ev.t))

    if total_duration == 0.0 and events:
        total_duration = events[-1].t

    wav_path = (
        jsonl_path.parent / wav_name if wav_name
        else jsonl_path.with_suffix(".wav")
    )
    if not wav_path.exists():
        raise FileNotFoundError(f"WAV-Datei nicht gefunden: {wav_path}")

    # Check for pre-computed stereo mixdown
    mix_candidate = wav_path.parent / (wav_path.stem + "_mixdown.wav")
    mixdown_path = mix_candidate if mix_candidate.exists() else None

    # Build song segments from select_song events
    selects: list[tuple[float, str, str]] = []
    for ev in events:
        if ev.type == "user" and ev.data.get("action") == "select_song":
            d = ev.data.get("data", {})
            sid = str(d.get("song_id", ""))
            name = str(d.get("name", "Unbekannt"))
            if db and sid in db.get("songs", {}):
                name = db["songs"][sid].get("name", name)
            selects.append((ev.t, sid, name))

    songs: list[SongSegment] = []
    for i, (start_t, sid, name) in enumerate(selects):
        end_t = selects[i + 1][0] if i + 1 < len(selects) else total_duration
        seg_events = [e for e in events if start_t <= e.t < end_t]
        songs.append(SongSegment(
            song_id=sid,
            song_name=name,
            start_t=start_t,
            end_t=end_t,
            events=seg_events,
        ))

    # Fallback: no select_song events → show entire recording as one segment
    if not songs:
        songs.append(SongSegment(
            song_id="",
            song_name=jsonl_path.stem,
            start_t=0.0,
            end_t=total_duration,
            events=events,
        ))

    return Session(
        wav_path=wav_path,
        mixdown_path=mixdown_path,
        jsonl_path=jsonl_path,
        sample_rate=sample_rate,
        n_channels=n_channels,
        total_duration=total_duration,
        songs=songs,
        all_events=events,
    )
