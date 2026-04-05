"""peaks.py — Waveform peak extraction in a QThread.

Reads the WAV file block-by-block to keep memory usage low.
Emits progress (0-100) and finished(TrackPeaks) signals.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from PyQt6.QtCore import QThread, pyqtSignal


# Channels shown in the timeline (0-indexed).
# CH 7 (index 7) and CH 16 (index 15) are skipped — not connected.
DISPLAY_CHANNELS: list[int] = [16, 17, 0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14]

CHANNEL_LABELS: dict[int, str] = {
    0: "Pete Vox", 1: "Axel Vox", 2: "Bibo Vox", 3: "Rhythm Guitar",
    4: "Lead Guitar", 5: "Bass", 6: "Synth",
    8: "Kick",  9: "Snare", 10: "Tom H", 11: "Tom M",
    12: "Tom L", 13: "OH L", 14: "OH R",
    16: "Main L", 17: "Main R",
}

SUM_CHANNELS = {16, 17}   # shown larger / green


@dataclass
class ChannelPeaks:
    channel: int
    peaks_min: np.ndarray   # float32, shape (n,)
    peaks_max: np.ndarray   # float32, shape (n,)

    @property
    def n_points(self) -> int:
        return len(self.peaks_min)


@dataclass
class TrackPeaks:
    channel_peaks: dict[int, ChannelPeaks]   # ch_index → peaks
    duration: float


class PeakWorker(QThread):
    """Background thread that extracts waveform peaks from a WAV segment."""

    progress = pyqtSignal(int)        # 0-100
    finished = pyqtSignal(object)     # TrackPeaks
    error = pyqtSignal(str)

    N_POINTS = 3_000    # target peak points per channel
    READ_SIZE = 96_000  # samples per I/O read (2 s @ 48 kHz)

    def __init__(
        self,
        wav_path: Path,
        ch_indices: list[int],
        start_t: float,
        end_t: float,
        sample_rate: int = 48_000,
        n_points: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._cancelled = False
        self.wav_path = wav_path
        self.ch_indices = ch_indices
        self.start_t = start_t
        self.end_t = end_t
        self.sample_rate = sample_rate
        self._n_points = n_points if n_points > 0 else self.N_POINTS

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            peaks = self._extract()
            if not self._cancelled:
                self.finished.emit(TrackPeaks(peaks, self.end_t - self.start_t))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))

    def _extract(self) -> dict[int, ChannelPeaks]:
        sr = self.sample_rate
        start = int(self.start_t * sr)
        end = int(self.end_t * sr)
        total = max(1, end - start)

        spp = max(1, total // self._n_points)        # samples per peak point
        n = total // spp                             # actual number of points

        pmins = {ch: np.ones(n, dtype=np.float32) for ch in self.ch_indices}
        pmaxs = {ch: np.full(n, -1.0, dtype=np.float32) for ch in self.ch_indices}

        point = 0
        consumed = 0
        leftover: np.ndarray | None = None

        with sf.SoundFile(str(self.wav_path)) as f:
            f.seek(start)
            while consumed < total and point < n:
                to_read = min(self.READ_SIZE, total - consumed)
                chunk = f.read(to_read, dtype="float32", always_2d=True)
                if len(chunk) == 0:
                    break
                consumed += len(chunk)

                # Prepend any leftover samples from the previous read
                buf = (
                    np.concatenate([leftover, chunk], axis=0)
                    if leftover is not None else chunk
                )

                # Extract complete peak points
                n_pts = len(buf) // spp
                for pi in range(n_pts):
                    if point >= n:
                        break
                    seg = buf[pi * spp: (pi + 1) * spp]
                    for ch in self.ch_indices:
                        if ch < seg.shape[1]:
                            pmins[ch][point] = seg[:, ch].min()
                            pmaxs[ch][point] = seg[:, ch].max()
                    point += 1

                # Keep remainder for next iteration
                rem = len(buf) % spp
                leftover = buf[-rem:] if rem > 0 else None

                self.progress.emit(min(99, int(consumed / total * 100)))

        # Handle any leftover that fills a partial point
        if leftover is not None and len(leftover) > 0 and point < n:
            for ch in self.ch_indices:
                if ch < leftover.shape[1]:
                    pmins[ch][point] = leftover[:, ch].min()
                    pmaxs[ch][point] = leftover[:, ch].max()
            point += 1

        self.progress.emit(100)

        return {
            ch: ChannelPeaks(ch, pmins[ch][:point], pmaxs[ch][:point])
            for ch in self.ch_indices
        }
