"""fragment_detector.py — Silence-based fragment detection for rehearsal recordings.

Splits a song segment into played fragments by finding silence gaps across all
instrument channels. A gap counts when ALL specified channels are simultaneously
below the RMS threshold for at least min_silence_sec seconds.

Typical usage::

    from fragment_detector import detect_fragments
    fragments = detect_fragments(
        wav_path=Path("recording.wav"),
        seg_start_t=387.4,
        seg_end_t=620.0,
        sample_rate=48000,
        ch_indices=list(range(16)),   # instrument channels only (not Main L/R)
    )
    for i, f in enumerate(fragments):
        print(f"Fragment {i+1}: {f.start_t:.2f}s \u2013 {f.end_t:.2f}s ({f.duration:.1f}s)")
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf


@dataclass
class Fragment:
    """A contiguous played section within a song segment."""

    start_t: float   # seconds relative to segment start
    end_t: float     # seconds relative to segment start

    @property
    def duration(self) -> float:
        return self.end_t - self.start_t

    def fmt(self) -> str:
        """Human-readable time range string."""
        def _fmt(t: float) -> str:
            m, s = divmod(t, 60)
            return f"{int(m)}:{s:04.1f}"
        return f"{_fmt(self.start_t)}\u2013{_fmt(self.end_t)}"

    def __repr__(self) -> str:
        return f"Fragment({self.fmt()}, {self.duration:.1f}s)"


def detect_fragments(
    wav_path: Path,
    seg_start_t: float,
    seg_end_t: float,
    sample_rate: int,
    ch_indices: list[int],
    *,
    rms_window_sec: float = 0.05,
    silence_thresh: float = 0.005,
    min_silence_sec: float = 1.5,
    min_fragment_sec: float = 3.0,
    read_chunk_sec: float = 10.0,
) -> list[Fragment]:
    """Detect song fragments by finding silence gaps across all given channels.

    The algorithm:
    1. Reads audio in chunks (memory-efficient, streams through the file).
    2. Computes windowed RMS per channel every *rms_window_sec* seconds.
    3. A window is "silent" when the maximum RMS across all channels is below
       *silence_thresh*.
    4. Consecutive silent windows forming a run \u2265 *min_silence_sec* mark a
       fragment boundary (split at the run's midpoint).
    5. Fragments shorter than *min_fragment_sec* are discarded.

    Args:
        wav_path:         Path to the multi-channel WAV file.
        seg_start_t:      Segment start within the WAV file (seconds).
        seg_end_t:        Segment end within the WAV file (seconds).
        sample_rate:      WAV sample rate (Hz).
        ch_indices:       0-based channel indices to analyse.
                          Use list(range(16)) for the 16 instrument channels of
                          an XR18 recording (leaves out Main L/R on ch 16/17).
        rms_window_sec:   Length of each RMS analysis window (seconds).
        silence_thresh:   RMS threshold below which a window is silent.
                          0.005 \u2248 \u221246 dBFS; adjust for noisy rehearsal rooms.
        min_silence_sec:  Minimum silence duration to split fragments.
        min_fragment_sec: Minimum fragment duration; shorter ones are dropped.
        read_chunk_sec:   Audio read chunk size (seconds). Controls RAM usage.
                          10 s \u00d7 16 ch \u00d7 float32 \u00d7 48 kHz \u2248 30 MB.

    Returns:
        List of Fragment objects sorted by start_t.  If no silence gaps are
        found the list contains a single fragment spanning the whole segment.
    """
    if seg_end_t <= seg_start_t:
        return []

    start_sample = int(seg_start_t * sample_rate)
    end_sample   = int(seg_end_t   * sample_rate)

    win_samples   = max(1, int(rms_window_sec * sample_rate))
    chunk_samples = max(win_samples, int(read_chunk_sec * sample_rate))

    rms_values: list[float] = []
    leftover: Optional[np.ndarray] = None

    with sf.SoundFile(wav_path) as f:
        total_frames = f.frames
        start_sample = min(start_sample, total_frames)
        end_sample   = min(end_sample,   total_frames)
        f.seek(start_sample)
        remaining = end_sample - start_sample

        while remaining > 0:
            to_read = min(chunk_samples, remaining)
            chunk = f.read(to_read, dtype="float32", always_2d=True)
            if chunk.shape[0] == 0:
                break
            remaining -= chunk.shape[0]

            # Select valid channels
            valid_chs = [c for c in ch_indices if c < chunk.shape[1]]
            if not valid_chs:
                # Fallback: use all channels
                data = chunk
            else:
                data = chunk[:, valid_chs]

            # Prepend leftover samples from previous chunk
            if leftover is not None:
                data = np.concatenate([leftover, data], axis=0)

            # Compute RMS for each full window
            n_full = data.shape[0] // win_samples
            for i in range(n_full):
                win = data[i * win_samples:(i + 1) * win_samples]
                per_ch_rms = np.sqrt(np.mean(win ** 2, axis=0))
                rms_values.append(float(per_ch_rms.max()))

            # Keep incomplete trailing samples for next iteration
            tail_start = n_full * win_samples
            leftover = data[tail_start:] if tail_start < data.shape[0] else None

    if not rms_values:
        seg_dur = seg_end_t - seg_start_t
        return [Fragment(start_t=0.0, end_t=seg_dur)]

    rms_arr   = np.array(rms_values, dtype=np.float32)
    is_silent = rms_arr < silence_thresh

    # \u2500\u2500 Find silence runs \u2265 min_silence_sec \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n    min_sil_wins = max(1, int(min_silence_sec / rms_window_sec))
    split_ts: list[float] = []  # split times relative to segment start

    i = 0
    n = len(is_silent)
    while i < n:
        if is_silent[i]:
            j = i + 1
            while j < n and is_silent[j]:
                j += 1
            run_len = j - i
            if run_len >= min_sil_wins:
                mid_win = i + run_len // 2
                split_ts.append(mid_win * rms_window_sec)
            i = j
        else:
            i += 1

    # \u2500\u2500 Build Fragment list \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n    seg_dur   = seg_end_t - seg_start_t
    boundaries = [0.0] + split_ts + [seg_dur]

    fragments: list[Fragment] = []
    for k in range(len(boundaries) - 1):
        frag_start = boundaries[k]
        frag_end   = boundaries[k + 1]
        if frag_end - frag_start >= min_fragment_sec:
            fragments.append(Fragment(start_t=frag_start, end_t=frag_end))

    # If all fragments were filtered out, return the whole segment as one
    if not fragments:
        return [Fragment(start_t=0.0, end_t=seg_dur)]

    return fragments
