"""Permanenter Audio-Processing-Prozess.

Läuft als dauerhafter Background-Thread neben dem FastAPI/Uvicorn-Prozess.
Liest USB-Audio vom XR18 (sounddevice), führt Beat-Detection und
HMM-basierte Takt-Positionsschätzung durch und schickt Ergebnisse
per asyncio.Queue an den FastAPI-Event-Loop.

Prozessmodell (wie im Architektur-Dokument beschrieben)
-------------------------------------------------------
    AudioProcess (Thread)           FastAPI (asyncio Event Loop)
      ├── sounddevice callback  →   asyncio.Queue
      ├── Beat-Detection        →   WebSocket broadcast → Browser
      └── HMM / Takt-Position   →   OSC-Ausgang → QLC+

Phase 1 (aktuell): sounddevice-Callback ist vollständig implementiert,
aber per Default deaktiviert (AUDIO_ENABLED=False). Stattdessen kann
der Fingerprint-Matching-Pfad über den Importer befüllt und offline
getestet werden.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .beat_detector import BeatDetector, BeatEvent as _BeatEvent
from .hmm import AudioHMM, HMMState
from .reference_db import ReferenceDB

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
# Index des Summensignals (0-basiert) — wird für Fingerprinting genutzt
# Beim XR18 per USB liegt der Stereo-Mix auf den letzten beiden Kanälen.
# Tatsächliche Belegung ist geräteabhängig und muss kalibriert werden.
CHANNEL_MIX_L = 16  # CH17 (0-basiert)
CHANNEL_MIX_R = 17  # CH18 (0-basiert)

# Minimale Pufferlänge für einen Feature-Snapshot (in Sekunden)
SNAPSHOT_MIN_SEC = 0.5


# ---------------------------------------------------------------------------
# Nachrichten vom Audio-Thread an FastAPI
# ---------------------------------------------------------------------------

@dataclass
class PositionUpdate:
    """Neue Takt-Position vom HMM."""
    song_id: str
    bar_num: int
    part_name: str
    confidence: float
    is_frozen: bool
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "type": "position_update",
            "song_id": self.song_id,
            "bar_num": self.bar_num,
            "part_name": self.part_name,
            "confidence": round(self.confidence, 3),
            "is_frozen": self.is_frozen,
            "timestamp": self.timestamp,
        }


@dataclass
class BeatUpdate:
    """Beat/Downbeat-Ereignis."""
    beat_num: int        # 1–4
    bar_num_local: int   # Takt innerhalb des aktuellen Songs (absolut)
    bpm: float
    is_downbeat: bool    # True wenn Beat 1 (Taktanfang)
    is_fill: bool        # True wenn Tom-Fill erkannt
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "type": "beat_update",
            "beat_num": self.beat_num,
            "bpm": round(self.bpm, 1),
            "is_downbeat": self.is_downbeat,
            "is_fill": self.is_fill,
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
    db:
        ReferenceDB-Instanz (geladen beim Server-Start)
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
        db: ReferenceDB,
        event_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
        device: str | int | None = None,
    ) -> None:
        self.db = db
        self.event_queue = event_queue
        self.loop = loop
        self.device = device

        self.hmm = AudioHMM(db)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running = False
        self._device_name = ""
        self._error = ""

        # Ring-Buffer für Stereo-Mix-Samples (1 Sekunde, für HMM-Fingerprinting)
        self._ring_buffer: list[np.ndarray] = []
        self._ring_lock = threading.Lock()
        self._ring_max_blocks = SAMPLE_RATE // BLOCK_SIZE  # ~23 Blöcke/Sek

        # Snapshot-Timing: Feature-Extraktion auf Downbeat triggern
        self._snapshot_pending = False
        self._current_bpm: float = 120.0

        # Beat-Detektor (PLL-basiert, Multi-Channel)
        self.beat_detector = BeatDetector(sample_rate=SAMPLE_RATE, initial_bpm=self._current_bpm)

    # --- Lifecycle ------------------------------------------------------------

    def start(self) -> None:
        """Startet den Audio-Processing-Thread."""
        if self._running:
            return
        self.hmm.load_all_states()
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

    def set_active_song(self, song_id: str | None) -> None:
        """Rehearsal Mode: Suchraum auf einen Song einschränken."""
        self.hmm.set_active_song(song_id)

    def set_bpm(self, bpm: float) -> None:
        """Aktualisiert das Tempo (wird vom DB-Song-Wechsel getriggert)."""
        self._current_bpm = bpm
        self.beat_detector.set_bpm(bpm)
        log.debug("BPM auf %.1f gesetzt", bpm)

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
        """Haupt-Schleife des Audio-Threads.

        Versucht sounddevice zu öffnen. Falls nicht verfügbar (Phase 1,
        kein XR18 angeschlossen), läuft der Thread als Stub weiter und
        sendet nur Status-Updates.
        """
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

                while not self._stop_event.is_set():
                    self._process_ring_buffer()
                    time.sleep(0.01)  # 10ms polling interval

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

        Zwei parallele Pfade:
          1. Multi-Channel → BeatDetector (Kick/Snare/Overheads/Toms)
          2. Stereo-Mix → Ring-Buffer → HMM-Fingerprinting (beat-synchron)
        """
        if status:
            log.warning("sounddevice Status: %s", status)

        # --- Pfad 1: Beat-Detection (alle Kanäle, block-weise) ---
        beat_events = self.beat_detector.process_block(indata)
        for ev in beat_events:
            beat_update = BeatUpdate(
                beat_num=ev.beat_num,
                bar_num_local=ev.bar_num,
                bpm=ev.bpm,
                is_downbeat=ev.is_downbeat,
                is_fill=ev.is_fill,
            )
            self._emit(beat_update)
            # Downbeat (Beat 1) → HMM-Snapshot triggern
            if ev.is_downbeat:
                self._snapshot_pending = True

        # --- Pfad 2: Stereo-Mix in Ring-Buffer für Fingerprinting ---
        if indata.shape[1] > CHANNEL_MIX_R:
            stereo = indata[:, [CHANNEL_MIX_L, CHANNEL_MIX_R]]
        else:
            stereo = indata[:, :2]  # Fallback: erste zwei Kanäle

        with self._ring_lock:
            self._ring_buffer.append(stereo.copy())
            if len(self._ring_buffer) > self._ring_max_blocks:
                self._ring_buffer.pop(0)

    # --- Feature-Extraktion und HMM-Update ------------------------------------

    def _process_ring_buffer(self) -> None:
        """Verarbeitet den Ring-Buffer wenn ein Snapshot ausstehend ist."""
        if not self._snapshot_pending:
            return
        self._snapshot_pending = False

        with self._ring_lock:
            if not self._ring_buffer:
                return
            # Alle gepufferten Blöcke zusammenfügen
            audio = np.concatenate(self._ring_buffer, axis=0)

        # Mono-Summe für Fingerprinting
        mono = np.mean(audio, axis=1).astype(np.float32)

        if len(mono) < int(SAMPLE_RATE * SNAPSHOT_MIN_SEC):
            return  # zu wenig Audio

        try:
            from .fingerprint import extract_features_from_array
            # BPM aus BeatDetector (live gemessen) bevorzugen
            bpm_for_fingerprint = self.beat_detector.bpm or self._current_bpm
            chroma, mfcc, onset, rms = extract_features_from_array(
                mono, sr=SAMPLE_RATE, bpm=bpm_for_fingerprint
            )
        except Exception as exc:
            log.warning("Feature-Extraktion fehlgeschlagen: %s", exc)
            return

        # HMM-Update
        state: HMMState = self.hmm.update(chroma, mfcc, onset)

        # Ergebnis in asyncio-Queue schieben
        update = PositionUpdate(
            song_id=state.song_id,
            bar_num=state.bar_num,
            part_name=state.part_name,
            confidence=state.confidence,
            is_frozen=state.is_frozen,
        )
        self._emit(update)

    # --- Emit (thread-safe → asyncio) ----------------------------------------

    def _emit(self, event: PositionUpdate | BeatUpdate | AudioStatus) -> None:
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
