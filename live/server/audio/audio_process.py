"""Permanenter Audio-Processing-Prozess.

Läuft als dauerhafter Background-Thread neben dem FastAPI/Uvicorn-Prozess.
Liest USB-Audio vom XR18 (sounddevice), führt Kick/Snare-Onset-Detection durch
und schickt Ergebnisse per asyncio.Queue an den FastAPI-Event-Loop.

Prozessmodell
-------------
    AudioProcess (Thread)           FastAPI (asyncio Event Loop)
      ├── sounddevice callback  →   asyncio.Queue
      └── OnsetDetector         →   WebSocket broadcast → Browser

Phase 1 (aktuell): sounddevice-Callback ist vollständig implementiert,
aber per Default deaktiviert (AUDIO_ENABLED=False im Server). Stattdessen
kann der Pfad über den Recorder allein genutzt werden.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from detection.beat_detector import OnsetDetector, OnsetEvent as _OnsetEvent
from .recorder import MultitrackRecorder

log = logging.getLogger("live.audio.process")

# ---------------------------------------------------------------------------
# Audio-Konfiguration
# ---------------------------------------------------------------------------

# Sample-Rate des XR18 per USB
SAMPLE_RATE = 48_000
# Blockgröße des sounddevice-Callbacks in Frames
BLOCK_SIZE = 2048
# Anzahl der Kanäle die vom XR18 gelesen werden (alle 18)
CHANNELS_TOTAL = 18


# ---------------------------------------------------------------------------
# Nachrichten vom Audio-Thread an FastAPI
# ---------------------------------------------------------------------------

@dataclass
class OnsetUpdate:
    """Kick/Snare-Onset-Ereignis."""
    onset_type: str   # "kick" | "snare"
    energy: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "type": "onset_update",
            "onset_type": self.onset_type,
            "energy": round(self.energy, 6),
            "timestamp": self.timestamp,
        }


@dataclass
class AudioStatus:
    """Status-Update des Audio-Prozesses."""
    running: bool
    device_name: str
    sample_rate: int
    channels: int
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "type": "audio_status",
            "running": self.running,
            "device": self.device_name,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Haupt-Klasse
# ---------------------------------------------------------------------------

class AudioProcess:
    """Verwaltet den dauerhaften Audio-Processing-Thread.

    Parameters
    ----------
    event_queue:
        asyncio.Queue, in die Ereignisse für den FastAPI-Loop geschrieben werden.
        Wird mit loop.call_soon_threadsafe befüllt (thread-safe).
    loop:
        Der asyncio-Event-Loop des FastAPI-Prozesses.
    device:
        sounddevice-Gerätename oder -Index. None = Standardgerät.
    """

    def __init__(
        self,
        event_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
        device: str | int | None = None,
    ) -> None:
        self.event_queue = event_queue
        self.loop = loop
        self.device = device

        self.onset_detector = OnsetDetector(sample_rate=SAMPLE_RATE)
        self.recorder = MultitrackRecorder(sample_rate=SAMPLE_RATE, channels=CHANNELS_TOTAL)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running = False
        self._device_name = ""
        self._error = ""

        # Pegel-Monitoring: RMS pro Kanal (für /api/audio/levels)
        self._channel_rms: np.ndarray = np.zeros(CHANNELS_TOTAL, dtype=np.float32)
        self._rms_lock = threading.Lock()

        # ADC-Zeitstempel des ersten Audio-Callbacks nach Aufnahme-Start.
        self._adc_start: float | None = None

    # --- Lifecycle ------------------------------------------------------------

    def start(self) -> None:
        """Startet den Audio-Processing-Thread."""
        if self._running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="audio-process",
            daemon=True,
        )
        self._thread.start()
        log.info("AudioProcess gestartet")

    def stop(self) -> None:
        """Stoppt den Audio-Processing-Thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        self._running = False
        log.info("AudioProcess gestoppt")

    def is_running(self) -> bool:
        return self._running

    def channel_levels(self) -> list[float]:
        """Aktuelle RMS-Pegel pro Kanal (0.0–1.0, float32)."""
        with self._rms_lock:
            return [round(float(v), 6) for v in self._channel_rms]

    @staticmethod
    def list_devices() -> list[dict]:
        """Listet alle verfügbaren Audio-Input-Geräte."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            return [
                {
                    "index": i,
                    "name": d["name"],
                    "channels_in": d["max_input_channels"],
                    "sample_rate": int(d["default_samplerate"]),
                }
                for i, d in enumerate(devices)
                if d["max_input_channels"] > 0
            ]
        except Exception as exc:
            return [{"error": str(exc)}]

    def status(self) -> dict:
        return AudioStatus(
            running=self._running,
            device_name=self._device_name,
            sample_rate=SAMPLE_RATE,
            channels=CHANNELS_TOTAL,
            error=self._error,
        ).to_dict()

    # --- Main Thread ----------------------------------------------------------

    def _run(self) -> None:
        """Haupt-Schleife des Audio-Threads."""
        try:
            import sounddevice as sd  # type: ignore
        except ImportError:
            log.warning(
                "sounddevice nicht installiert — AudioProcess läuft im Stub-Modus. "
                "Bitte 'pip install sounddevice' ausführen."
            )
            self._run_stub()
            return

        self._running = True
        try:
            devices = sd.query_devices()
            log.info("Verfügbare Audio-Geräte:")
            for i, d in enumerate(devices):
                log.info("  [%d] %s (in=%d)", i, d["name"], d["max_input_channels"])

            stream_kwargs: dict[str, Any] = {
                "samplerate": SAMPLE_RATE,
                "blocksize": BLOCK_SIZE,
                "dtype": "float32",
                "channels": CHANNELS_TOTAL,
                "callback": self._audio_callback,
            }
            if self.device is not None:
                stream_kwargs["device"] = self.device

            with sd.InputStream(**stream_kwargs) as stream:
                self._device_name = stream.device if isinstance(stream.device, str) else str(stream.device)
                log.info("Audio-Stream geöffnet: %s @ %d Hz, %d ch", self._device_name, SAMPLE_RATE, CHANNELS_TOTAL)
                self._send_status()

                # Aufnahme automatisch starten
                from datetime import datetime
                label = datetime.now().strftime("probe_%Y-%m-%d")
                try:
                    self.recorder.start(label=label)
                except RuntimeError as exc:
                    log.warning("Aufnahme konnte nicht gestartet werden: %s", exc)

                while not self._stop_event.is_set():
                    time.sleep(0.01)

                self.recorder.stop()

        except Exception as exc:
            self._error = str(exc)
            log.error("AudioProcess Fehler: %s", exc)
            self._send_status()
        finally:
            self._running = False

    def _run_stub(self) -> None:
        """Stub-Modus wenn sounddevice nicht verfügbar."""
        self._running = True
        self._device_name = "stub (kein sounddevice)"
        self._send_status()
        while not self._stop_event.is_set():
            time.sleep(1.0)
        self._running = False

    # --- sounddevice Callback (läuft im Audio-Thread) -------------------------

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: Any,
        status: Any,
    ) -> None:
        """Wird von sounddevice bei jedem neuen Audio-Block aufgerufen.

        indata: shape (frames, CHANNELS_TOTAL), float32
        """
        if status:
            log.warning("sounddevice Status: %s", status)

        # --- Aufnahme: alle 18 Kanäle direkt in Datei schreiben ---
        self.recorder.write_block(indata)

        # --- ADC-Zeitstempel: präziser WAV-Offset für diesen Block ---
        el = self.recorder.event_logger
        if el is not None and self._adc_start is None:
            self._adc_start = time_info.inputBufferAdcTime
        elif el is None:
            self._adc_start = None

        wav_offset: float | None = (
            time_info.inputBufferAdcTime - self._adc_start
            if self._adc_start is not None else None
        )

        # --- Pegel-Monitoring: RMS pro Kanal aktualisieren ---
        rms_per_ch = np.sqrt(np.mean(indata ** 2, axis=0))
        with self._rms_lock:
            self._channel_rms = rms_per_ch

        # --- Onset-Detection: Kick (CH09) + Snare (CH10) ---
        onsets = self.onset_detector.process_block(indata)
        for ev in onsets:
            self._emit(OnsetUpdate(onset_type=ev.type, energy=ev.energy))
            if el is not None:
                el.log(ev.type, wav_offset=wav_offset, energy=round(ev.energy, 6))

    # --- Emit (thread-safe → asyncio) ----------------------------------------

    def _emit(self, event: OnsetUpdate | AudioStatus) -> None:
        """Sendet ein Ereignis thread-safe in die asyncio-Queue."""
        self.loop.call_soon_threadsafe(self.event_queue.put_nowait, event)

    def _send_status(self) -> None:
        status = AudioStatus(
            running=self._running,
            device_name=self._device_name,
            sample_rate=SAMPLE_RATE,
            channels=CHANNELS_TOTAL,
            error=self._error,
        )
        self._emit(status)
