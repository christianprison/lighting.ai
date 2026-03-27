"""player.py — Audio segment playback via sounddevice.

Loads a segment from either a stereo mixdown WAV or channels 16+17
from the raw 18-channel WAV, then plays it via sounddevice.
Position is tracked by recording the wall-clock start time.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import sounddevice as sd
from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class AudioPlayer(QObject):
    """Play audio segments with play / pause / seek / stop.

    Signals:
        position_changed(float): current position in WAV seconds, ~50 ms.
        playback_stopped():       emitted when playback reaches end.
    """

    position_changed = pyqtSignal(float)
    playback_stopped = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._data: Optional[np.ndarray] = None   # (samples, 2) float32
        self._sr: int = 48_000
        self._start_frame: int = 0
        self._play_ts: float = 0.0
        self._is_playing: bool = False
        self._seg_start_t: float = 0.0

        self._poll = QTimer(self)
        self._poll.setInterval(40)
        self._poll.timeout.connect(self._tick)

    # ── Loading ──────────────────────────────────────────────────────────────

    def load_segment(
        self,
        wav_path: Path,
        start_t: float,
        end_t: float,
        mixdown_path: Optional[Path] = None,
    ) -> None:
        """Load audio for the given time range.

        Prefers the stereo mixdown file for speed (avoids reading 18 ch).
        Falls back to channels 16+17 from the raw WAV.
        """
        self.stop()

        src = mixdown_path if (mixdown_path and mixdown_path.exists()) else wav_path

        with sf.SoundFile(str(src)) as f:
            sr = f.samplerate
            n_ch = f.channels
            start = int(start_t * sr)
            end = int(end_t * sr)
            f.seek(start)
            raw = f.read(end - start, dtype="float32", always_2d=True)

        if src is mixdown_path:
            # Already stereo
            self._data = raw[:, :2] if raw.shape[1] >= 2 else np.column_stack([raw[:, 0]] * 2)
        else:
            # Extract Main L/R (channels 16+17, 0-indexed)
            ch_l = min(16, n_ch - 1)
            ch_r = min(17, n_ch - 1)
            self._data = raw[:, [ch_l, ch_r]]

        self._sr = sr
        self._seg_start_t = start_t
        self._start_frame = 0
        self._is_playing = False

    # ── Transport ────────────────────────────────────────────────────────────

    def play(self) -> None:
        if self._data is None:
            return
        try:
            sd.play(self._data[self._start_frame:], self._sr)
        except Exception as exc:
            self.error.emit(str(exc))
            self._is_playing = False
            return
        self._play_ts = time.monotonic()
        self._is_playing = True
        self._poll.start()

    def pause(self) -> None:
        if not self._is_playing:
            return
        sd.stop()
        elapsed_frames = int((time.monotonic() - self._play_ts) * self._sr)
        self._start_frame = min(
            len(self._data) - 1,
            self._start_frame + elapsed_frames,
        )
        self._is_playing = False
        self._poll.stop()

    def seek(self, t_in_segment: float) -> None:
        """Seek to seconds relative to segment start."""
        was = self._is_playing
        if was:
            sd.stop()
            self._poll.stop()
        self._start_frame = max(0, int(t_in_segment * self._sr))
        if self._data is not None:
            self._start_frame = min(self._start_frame, len(self._data) - 1)
        if was:
            self.play()

    def stop(self) -> None:
        sd.stop()
        self._is_playing = False
        self._start_frame = 0
        self._poll.stop()

    def toggle(self) -> None:
        if self._is_playing:
            self.pause()
        else:
            self.play()

    # ── Position ─────────────────────────────────────────────────────────────

    @property
    def position_in_segment(self) -> float:
        if not self._is_playing:
            return self._start_frame / self._sr
        return self._start_frame / self._sr + (time.monotonic() - self._play_ts)

    @property
    def position_in_wav(self) -> float:
        return self._seg_start_t + self.position_in_segment

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    # ── Internal ─────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        if self._data is None:
            return
        pos = self.position_in_segment
        if pos >= len(self._data) / self._sr:
            sd.stop()
            self._is_playing = False
            self._start_frame = 0
            self._poll.stop()
            self.playback_stopped.emit()
            return
        self.position_changed.emit(self.position_in_wav)
