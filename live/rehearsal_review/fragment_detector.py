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
from typing import Callable, Optional

import numpy as np
import soundfile as sf


@dataclass
class Fragment:
    """A contiguous played section within a song segment."""

    start_t: float   # seconds relative to segment start
    end_t: float     # seconds relative to segment start
    drum_ratio: float = 0.0  # Anteil Fenster mit Schlagzeug-Aktivität (0–1)

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
        return f"Fragment({self.fmt()}, {self.duration:.1f}s, drums={self.drum_ratio:.0%})"


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
    drum_ch_indices: Optional[list[int]] = None,
    min_drum_activity: float = 0.80,
    progress_callback: Optional[Callable[[float, list[float]], None]] = None,
) -> list[Fragment]:
    """``progress_callback(scan_t, rms_values)`` is called after each read chunk.

    *scan_t* is the end-time of the processed audio (seconds relative to
    segment start). *rms_values* is the list of per-window max-RMS values
    computed in this chunk, in order.  Use this to show live progress in the UI.
    """
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
        drum_ch_indices:  WAV channel indices for Kick + Snare (default: [8, 9]
                          = XR18 Kick/Snare). Fragments where the drum channels
                          are active in fewer than *min_drum_activity* of all
                          windows are discarded as "Geplänkel".
        min_drum_activity: Minimum fraction of windows with drum activity for a
                          fragment to be kept (default: 0.80 = 80 %).
                          Set to 0.0 to disable the drum-activity filter.

    Returns:
        List of Fragment objects sorted by start_t.  If no silence gaps are
        found the list contains a single fragment spanning the whole segment.
    """
    if seg_end_t <= seg_start_t:
        return []

    if drum_ch_indices is None:
        drum_ch_indices = [8, 9]   # XR18: ch8 = Kick, ch9 = Snare
    drum_set = set(drum_ch_indices)

    start_sample = int(seg_start_t * sample_rate)
    end_sample   = int(seg_end_t   * sample_rate)

    win_samples   = max(1, int(rms_window_sec * sample_rate))
    chunk_samples = max(win_samples, int(read_chunk_sec * sample_rate))

    rms_values:      list[float] = []
    drum_rms_values: list[float] = []   # per-window max-RMS of drum channels
    has_drum_chs = False                # set True once drum channels confirmed present
    leftover: Optional[np.ndarray] = None
    drum_leftover: Optional[np.ndarray] = None

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

            # Select valid instrument channels
            valid_chs = [c for c in ch_indices if c < chunk.shape[1]]
            if not valid_chs:
                data = chunk
            else:
                data = chunk[:, valid_chs]

            # Drum channels (subset of full WAV, not of valid_chs subset)
            valid_drum = [c for c in drum_ch_indices if c < chunk.shape[1]]
            if valid_drum:
                has_drum_chs = True
                drum_data = chunk[:, valid_drum]
            else:
                drum_data = None

            # Prepend leftover samples from previous chunk
            if leftover is not None:
                data = np.concatenate([leftover, data], axis=0)
            if drum_leftover is not None and drum_data is not None:
                drum_data = np.concatenate([drum_leftover, drum_data], axis=0)

            # Compute RMS for each full window
            n_full = data.shape[0] // win_samples
            chunk_rms: list[float] = []
            chunk_drum_rms: list[float] = []
            for i in range(n_full):
                win_slice = data[i * win_samples:(i + 1) * win_samples]
                per_ch_rms = np.sqrt(np.mean(win_slice ** 2, axis=0))
                chunk_rms.append(float(per_ch_rms.max()))
                if drum_data is not None:
                    d_slice = drum_data[i * win_samples:(i + 1) * win_samples]
                    d_rms = np.sqrt(np.mean(d_slice ** 2, axis=0))
                    chunk_drum_rms.append(float(d_rms.max()))
                else:
                    chunk_drum_rms.append(0.0)
            rms_values.extend(chunk_rms)
            drum_rms_values.extend(chunk_drum_rms)

            # Keep incomplete trailing samples for next iteration
            tail_start = n_full * win_samples
            leftover = data[tail_start:] if tail_start < data.shape[0] else None
            if drum_data is not None:
                drum_tail = drum_data[tail_start:]
                drum_leftover = drum_tail if drum_tail.shape[0] > 0 else None
            else:
                drum_leftover = None

            # Report progress to caller
            if progress_callback is not None and chunk_rms:
                scan_t = len(rms_values) * rms_window_sec
                progress_callback(scan_t, chunk_rms)

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

    # ── Build Fragment list ─────────────────────────────────────────────────
    drum_arr = np.array(drum_rms_values, dtype=np.float32)
    seg_dur   = seg_end_t - seg_start_t
    boundaries = [0.0] + split_ts + [seg_dur]

    fragments: list[Fragment] = []
    geplänkel: list[Fragment] = []

    for k in range(len(boundaries) - 1):
        frag_start = boundaries[k]
        frag_end   = boundaries[k + 1]
        if frag_end - frag_start < min_fragment_sec:
            continue

        # Drum-Aktivitäts-Ratio für dieses Fragment berechnen
        win_start = int(frag_start / rms_window_sec)
        win_end   = int(frag_end   / rms_window_sec)
        n_wins    = win_end - win_start
        if has_drum_chs and n_wins > 0 and min_drum_activity > 0.0:
            drum_active = int(np.sum(drum_arr[win_start:win_end] >= silence_thresh))
            ratio = drum_active / n_wins
        else:
            ratio = 1.0   # keine Drum-Kanäle → Filter deaktiviert

        frag = Fragment(start_t=frag_start, end_t=frag_end, drum_ratio=ratio)
        if ratio >= min_drum_activity:
            fragments.append(frag)
        else:
            geplänkel.append(frag)

    # If all fragments were filtered out as Geplänkel, return the whole segment
    # (or the longest Geplänkel fragment as fallback so the user isn't left empty)
    if not fragments:
        if geplänkel:
            best = max(geplänkel, key=lambda f: f.duration)
            return [Fragment(start_t=best.start_t, end_t=best.end_t, drum_ratio=best.drum_ratio)]
        return [Fragment(start_t=0.0, end_t=seg_dur)]

    return fragments
