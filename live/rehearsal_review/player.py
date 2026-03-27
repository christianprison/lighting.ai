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
        error(str):               non-fatal playback errors.
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

        # Stored for reload_mix()
        self._wav_path: Optional[Path] = None
        self._mixdown_path: Optional[Path] = None
        self._seg_start_raw: float = 0.0
        self._seg_end_raw: float = 0.0

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
        solo_channels: Optional[list[int]] = None,
    ) -> None:
        """Load audio for the given time range.

        When solo_channels is None, prefers the stereo mixdown file (avoids
        reading 18 ch) or falls back to channels 16+17 from the raw WAV.
        When solo_channels is given, always reads from the raw WAV and mixes
        only those channels to stereo.
        """
        self.stop()

        self._wav_path = wav_path
        self._mixdown_path = mixdown_path
        self._seg_start_raw = start_t
        self._seg_end_raw = end_t

        self._load_data(solo_channels)
        self._seg_start_t = start_t
        self._start_frame = 0
        self._is_playing = False

    def reload_mix(self, solo_channels: Optional[list[int]]) -> None:
        """Reload audio mix with new channel selection, preserving playback position.

        Call this when Solo/Mute state changes while a segment is loaded.
        solo_channels=None restores the normal mix (mixdown or Main L/R).
        """
        if self._wav_path is None:
            return
        pos = self.position_in_segment
        was_playing = self._is_playing

        if was_playing:
            sd.stop()
            self._poll.stop()
            self._is_playing = False

        self._load_data(solo_channels)

        self._start_frame = min(int(pos * self._sr), max(0, len(self._data) - 1))

        if was_playing:
            self.play()

    def _load_data(self, solo_channels: Optional[list[int]]) -> None:
        """Read WAV frames and build self._data (N, 2) float32."""
        # Use mixdown only when no specific channel selection is requested
        use_mixdown = (
            solo_channels is None
            and self._mixdown_path is not None
            and self._mixdown_path.exists()
        )
        src = self._mixdown_path if use_mixdown else self._wav_path

        with sf.SoundFile(str(src)) as f:
            sr = f.samplerate
            n_ch = f.channels
            start = int(self._seg_start_raw * sr)
            end = int(self._seg_end_raw * sr)
            f.seek(start)
            raw = f.read(end - start, dtype="float32", always_2d=True)

        self._sr = sr

        if solo_channels is None:
            if use_mixdown:
                self._data = (
                    raw[:, :2] if raw.shape[1] >= 2
                    else np.column_stack([raw[:, 0]] * 2)
                )
            else:
                ch_l = min(16, n_ch - 1)
                ch_r = min(17, n_ch - 1)
                self._data = raw[:, [ch_l, ch_r]]
        else:
            # Mix only the requested channels into a stereo output.
            # ch16 → L, ch17 → R, all others → center (both L+R).
            n = raw.shape[0]
            stereo = np.zeros((n, 2), dtype=np.float32)
            for ch in solo_channels:
                ch = min(ch, n_ch - 1)
                mono = raw[:, ch]
                if ch == 16:
                    stereo[:, 0] += mono
                elif ch == 17:
                    stereo[:, 1] += mono
                else:
                    stereo[:, 0] += mono
                    stereo[:, 1] += mono
            np.clip(stereo, -1.0, 1.0, out=stereo)
            self._data = stereo

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
