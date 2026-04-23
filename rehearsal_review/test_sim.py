#!/usr/bin/env python3
"""test_sim.py — Standalone-Test der Anker-Erkennung ohne Qt/sounddevice.

Verwendung:
    python3 test_sim.py <session.jsonl> [song_index]
    python3 test_sim.py <wav_file> <seg_start_s> <seg_end_s> <song_id>

Beispiel:
    python3 test_sim.py /pfad/zur/2026-03-26_185333_Probe_2026-03-26.jsonl
    python3 test_sim.py /pfad/zur/2026-03-26_185333_Probe_2026-03-26.wav 184.81 509.90 pVmkRc
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import numpy as np
import soundfile as sf

from detection.beat_detector import OnsetDetector
from detection.anchor_matcher import AnchorMatcher

BLOCK_SIZE = 2048


def _log(msg: str) -> None:
    os.write(1, (msg + "\n").encode("utf-8", errors="replace"))


def load_db_song(song_id: str) -> dict:
    db_path = Path(_REPO_ROOT) / "db" / "lighting-ai-db.json"
    db = json.loads(db_path.read_text("utf-8"))
    return db.get("songs", {}).get(song_id, {})


def parse_session_jsonl(jsonl_path: Path) -> list[dict]:
    """Gibt Liste von Segmenten zurück: {song_id, song_name, start_t, end_t, wav_path}."""
    segments = []
    wav_path = None
    current: dict | None = None
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            t = ev.get("t", 0.0)
            etype = ev.get("type", "")
            data = ev.get("data", {})
            if etype == "session_start":
                wav_ref = data.get("wav", "")
                if wav_ref:
                    wav_path = Path(wav_ref) if Path(wav_ref).is_absolute() else jsonl_path.parent / wav_ref
                if not wav_path or not wav_path.exists():
                    alt = jsonl_path.with_suffix(".wav")
                    if alt.exists():
                        wav_path = alt
            elif etype == "song_start":
                current = {
                    "song_id":   data.get("song_id", ""),
                    "song_name": data.get("song_name", "?"),
                    "start_t":   t,
                    "end_t":     None,
                    "wav_path":  wav_path,
                }
            elif etype == "song_end" and current:
                current["end_t"] = t
                segments.append(current)
                current = None
    if current:
        current["end_t"] = current["start_t"] + 600.0
        segments.append(current)
    return segments


def run_test(wav_path: Path, seg_start_t: float, seg_end_t: float,
             song_id: str, song_name: str = "?") -> None:
    song = load_db_song(song_id)
    bpm = float(song.get("bpm", 120.0))
    anchors: list = song.get("anchors", []) or []

    _log("")
    _log(f"=== Anker-Erkennungstest ===")
    _log(f"Song:    {song_name} ({song_id})")
    _log(f"BPM:     {bpm}")
    _log(f"WAV:     {wav_path.name}")
    _log(f"Segment: {seg_start_t:.2f}s – {seg_end_t:.2f}s")
    _log(f"Anker:   {len(anchors)}")
    _log("")

    with sf.SoundFile(wav_path) as meta:
        sr = meta.samplerate
        total_frames = meta.frames

    start_sample = min(int(seg_start_t * sr), total_frames)
    end_sample   = min(int(seg_end_t   * sr), total_frames)
    total_seg    = end_sample - start_sample
    _log(f"sr={sr}  start_sample={start_sample}  end_sample={end_sample}")
    _log("")

    detector = OnsetDetector(sample_rate=sr, block_size=BLOCK_SIZE)
    matcher  = AnchorMatcher(
        anchors=anchors,
        bpm=bpm,
        seg_start_t=seg_start_t,
        sample_rate=sr,
        block_size=BLOCK_SIZE,
    )
    _log("")

    kicks: list[float] = []
    snares: list[float] = []
    crashes: list[float] = []
    blocks_done = 0
    t_wall_start = time.monotonic()

    with sf.SoundFile(wav_path) as wav_f:
        wav_f.seek(start_sample)
        remaining = end_sample - wav_f.tell()

        while remaining > 0:
            to_read = min(BLOCK_SIZE, remaining)
            block   = wav_f.read(to_read, dtype="float32", always_2d=True)
            if block.shape[0] == 0:
                break
            remaining -= block.shape[0]

            t_mid = blocks_done * BLOCK_SIZE / sr + (block.shape[0] / 2) / sr
            t_abs = seg_start_t + t_mid

            t_block_start = time.monotonic()

            for ev in detector.process_block(block):
                energy = float(ev.energy)
                if ev.type == "kick":
                    kicks.append(t_mid)
                    if len(kicks) <= 10:
                        _log(f"  KICK #{len(kicks):2d}  t={t_mid:.2f}s  e={energy:.4f}")
                    m = matcher.process_kick(t_abs, energy)
                    if m:
                        _log(f"  >>> ANKER MATCH (kick) cursor jetzt {matcher._cursor}/{len(matcher._anchors)}")
                elif ev.type == "snare":
                    snares.append(t_mid)
                    if len(snares) <= 5:
                        _log(f"  snare #{len(snares):2d}  t={t_mid:.2f}s  e={energy:.4f}")
                    m = matcher.process_snare(t_abs, energy)
                    if m:
                        _log(f"  >>> ANKER MATCH (snare) cursor jetzt {matcher._cursor}/{len(matcher._anchors)}")
                elif ev.type == "crash":
                    crashes.append(t_mid)
                    _log(f"  CRASH  t={t_mid:.2f}s  e={energy:.4f}")
                    m = matcher.process_crash(t_abs, energy)
                    if m:
                        _log(f"  >>> ANKER MATCH (crash) cursor jetzt {matcher._cursor}/{len(matcher._anchors)}")

            m = matcher.process_block(block, t_abs)
            if m:
                _log(f"  >>> ANKER MATCH (RMS) cursor jetzt {matcher._cursor}/{len(matcher._anchors)}")

            blocks_done += 1
            t_block_ms = (time.monotonic() - t_block_start) * 1000

            if blocks_done % 200 == 0:
                wall_elapsed = time.monotonic() - t_wall_start
                audio_done   = blocks_done * BLOCK_SIZE / sr
                _log(f"  [♥] block={blocks_done:5d}  audio={audio_done:.1f}s  "
                     f"wall={wall_elapsed:.1f}s  "
                     f"K={len(kicks)} S={len(snares)} C={len(crashes)}  "
                     f"block_ms={t_block_ms:.1f}")

    wall_total = time.monotonic() - t_wall_start
    audio_dur  = total_seg / sr
    _log("")
    _log(f"=== Ergebnis ===")
    _log(f"Verarbeitet: {blocks_done} Blöcke in {wall_total:.1f}s "
         f"(Audio: {audio_dur:.0f}s, Faktor: {audio_dur/max(wall_total,0.1):.1f}x Echtzeit)")
    _log(f"Kicks: {len(kicks)}  Snares: {len(snares)}  Crashes: {len(crashes)}")
    _log(f"Anker erkannt: {matcher._cursor}/{len(matcher._anchors)}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        _log(__doc__)
        sys.exit(1)

    first = Path(args[0])

    if first.suffix == ".jsonl":
        # Modus 1: Session-JSONL → Segment auswählen
        segments = parse_session_jsonl(first)
        if not segments:
            _log(f"Keine Song-Segmente in {first} gefunden.")
            sys.exit(1)
        _log("Gefundene Segmente:")
        for i, seg in enumerate(segments):
            dur = (seg["end_t"] or 0) - seg["start_t"]
            _log(f"  [{i}] {seg['song_name']} ({seg['song_id']})  "
                 f"{seg['start_t']:.1f}s–{seg['end_t']:.1f}s  {dur:.0f}s")
        idx = int(args[1]) if len(args) > 1 else 0
        seg = segments[idx]
        wav_path = seg["wav_path"]
        if not wav_path or not wav_path.exists():
            _log(f"WAV nicht gefunden: {wav_path}")
            sys.exit(1)
        run_test(wav_path, seg["start_t"], seg["end_t"], seg["song_id"], seg["song_name"])

    elif first.suffix.lower() in (".wav", ".flac", ".aiff", ".ogg"):
        # Modus 2: WAV + Parameter direkt
        if len(args) < 4:
            _log("Verwendung: test_sim.py <wav> <start_s> <end_s> <song_id>")
            sys.exit(1)
        wav_path   = first
        seg_start  = float(args[1])
        seg_end    = float(args[2])
        song_id    = args[3]
        song_name  = load_db_song(song_id).get("name", song_id)
        run_test(wav_path, seg_start, seg_end, song_id, song_name)

    else:
        _log(f"Unbekannter Dateityp: {first}")
        sys.exit(1)


if __name__ == "__main__":
    main()
