"""player.py — Audio segment playback via sounddevice.

Loads a segment from either a stereo mixdown WAV or channels 16+17
from the raw 18-channel WAV, then plays it via sounddevice.
Position is tracked by recording the wall-clock start time.

Pre-processing: after each load_segment() call a RawLoader QThread
pre-fetches all channels from the raw 18-ch WAV in the background.
Once available, reload_mix() (called on Solo/Mute changes) is instant
— just numpy slice/add on the cached array, no disk I/O.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import sounddevice as sd
from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal


# ── Background loader ─────────────────────────────────────────────────────────

class RawLoader(QThread):
    """Reads all channels from the raw 18-ch WAV in a background thread.

    Signals:
        finished(np.ndarray, int, int): (raw_data, n_channels, generation)
    """
    finished = pyqtSignal(object, int, int)

    def __init__(self, wav_path: Path, start_t: float, end_t: float,
                 generation: int) -> None:
        super().__init__()
        self._wav_path = wav_path
        self._start_t = start_t
        self._end_t = end_t
        self._generation = generation
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            with sf.SoundFile(str(self._wav_path)) as f:
                sr = f.samplerate
                n_ch = f.channels
                start = int(self._start_t * sr)
                end = int(self._end_t * sr)
                f.seek(start)
                raw = f.read(end - start, dtype="float32", always_2d=True)
            if not self._cancelled:
                self.finished.emit(raw, n_ch, self._generation)
        except Exception:
            pass


# ── Audio player ──────────────────────────────────────────────────────────────

class AudioPlayer(QObject):
    """Play audio segments with play / pause / seek / stop.

    Signals:
        position_changed(float): current position in WAV seconds, ~40 ms.
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

        # Stored for reload_mix() and RawLoader
        self._wav_path: Optional[Path] = None
        self._mixdown_path: Optional[Path] = None
        self._seg_start_raw: float = 0.0
        self._seg_end_raw: float = 0.0

        # Pre-loaded raw channels (N × n_ch), populated by RawLoader
        self._raw: Optional[np.ndarray] = None
        self._n_ch_raw: int = 0
        self._raw_loader: Optional[RawLoader] = None
        self._load_gen: int = 0   # incremented each load_segment() call

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
        """Load audio for the given time range and start background pre-fetch.

        Prefers the stereo mixdown file for immediate playback (avoids
        reading all 18 ch). Falls back to channels 16+17 from the raw WAV.
        Simultaneously launches a RawLoader thread to cache all channels
        so that subsequent reload_mix() calls are instant (RAM only).
        """
        self.stop()

        self._wav_path = wav_path
        self._mixdown_path = mixdown_path
        self._seg_start_raw = start_t
        self._seg_end_raw = end_t
        self._raw = None
        self._n_ch_raw = 0

        # Cancel any previous background loader
        if self._raw_loader and self._raw_loader.isRunning():
            self._raw_loader.cancel()

        self._load_gen += 1
        self._load_data(solo_channels)
        self._seg_start_t = start_t
        self._start_frame = 0
        self._is_playing = False

        # Start background pre-fetch of all channels for instant solo/mute
        loader = RawLoader(wav_path, start_t, end_t, self._load_gen)
        loader.finished.connect(self._on_raw_loaded)
        self._raw_loader = loader
        loader.start()

    def reload_mix(self, solo_channels: Optional[list[int]]) -> None:
        """Reload audio mix with new channel selection, preserving position.

        If the background RawLoader has finished, this is a pure in-memory
        numpy operation (instant). Otherwise falls back to reading from disk.
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

        if self._raw is not None:
            self._mix_from_raw(solo_channels)
        else:
            self._load_data(solo_channels)

        self._start_frame = min(int(pos * self._sr), max(0, len(self._data) - 1))

        if was_playing:
            self.play()

    def _load_data(self, solo_channels: Optional[list[int]]) -> None:
        """Read WAV frames and build self._data (N, 2) float32."""
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

    def _mix_from_raw(self, solo_channels: Optional[list[int]]) -> None:
        """Build self._data from the pre-cached _raw array (no disk I/O)."""
        if solo_channels is None:
            ch_l = min(16, self._n_ch_raw - 1)
            ch_r = min(17, self._n_ch_raw - 1)
            self._data = self._raw[:, [ch_l, ch_r]]
        else:
            n = self._raw.shape[0]
            stereo = np.zeros((n, 2), dtype=np.float32)
            for ch in solo_channels:
                ch_idx = min(ch, self._n_ch_raw - 1)
                mono = self._raw[:, ch_idx]
                if ch == 16:
                    stereo[:, 0] += mono
                elif ch == 17:
                    stereo[:, 1] += mono
                else:
                    stereo[:, 0] += mono
                    stereo[:, 1] += mono
            np.clip(stereo, -1.0, 1.0, out=stereo)
            self._data = stereo

    def _on_raw_loaded(self, raw: np.ndarray, n_ch: int, gen: int) -> None:
        """Receive pre-loaded raw channels from RawLoader thread."""
        if gen == self._load_gen:   # discard results from stale loaders
            self._raw = raw
            self._n_ch_raw = n_ch

    # ── Transport ────────────────────────────────────────────────────────────

    def play(self) -> None:
        if self._data is None:
            return
        try:
            sd.play(self._data[self._start_frame:], self._sr,
                    device="pulse", blocksize=4096)
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
