"""Permanenter Audio-Processing-Prozess.

Läuft als dauerhafter Background-Thread neben dem FastAPI/Uvicorn-Prozess.
Liest USB-Audio vom XR18 (sounddevice), führt Kick/Snare-Onset-Detection durch
und schickt Ergebnisse per asyncio.Queue an den FastAPI-Event-Loop.

Prozessmodell
-------------
    AudioProcess (Thread)            FastAPI (asyncio Event Loop)
      ├── sounddevice callback   →    asyncio.Queue
      ├── OnsetDetector          →    WebSocket broadcast → Browser
      ├── BarTracker             →    bar-Events in JSONL
      └── StreamingChromaExtractor    (Guitar + Bass)
            └── _chroma_worker  →    ChromaUpdate → WebSocket

Chroma-Pipeline (Prime Directive: identisch mit SimulatorWorker)
-----------------------------------------------------------------
- push_block() läuft im Audio-Callback (schnell: nur Buffer-Update, kein librosa)
- snapshot()   wird im Callback bei Beat/Bar-Events aufgerufen (schnell: nur copy())
- Chroma-Berechnung (STFT/CQT) läuft im _chroma_worker-Thread (10–100 ms, kein
  Blocking des Callbacks)
- Kosinus-Ähnlichkeit gegen Referenz-Chromas aus reference.db → bar_num + confidence
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

from detection.beat_detector import OnsetDetector, OnsetEvent as _OnsetEvent
from detection.bar_tracker import BarTracker
from detection.chroma_extractor import StreamingChromaExtractor, CH_GUITAR, CH_BASS
from .recorder import MultitrackRecorder

log = logging.getLogger("live.audio.process")

# ---------------------------------------------------------------------------
# Audio-Konfiguration
# ---------------------------------------------------------------------------

SAMPLE_RATE    = 48_000
BLOCK_SIZE     = 2048
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
class ChromaUpdate:
    """Chroma-Erkennungsergebnis aus dem Background-Worker."""
    kind: str           # "guitar" | "bass"
    t: float            # WAV-Zeitstempel (Sekunden)
    chroma: list[float] # 12-dim Chroma-Vektor
    bar_num: int        # bester Treffer in reference.db (-1 = keine Referenz)
    confidence: float   # Kosinus-Ähnlichkeit (0.0–1.0)

    def to_dict(self) -> dict:
        return {
            "type":       "chroma_update",
            "kind":       self.kind,
            "t":          round(self.t, 3),
            "chroma":     [round(v, 4) for v in self.chroma],
            "bar_num":    self.bar_num,
            "confidence": round(self.confidence, 4),
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
    loop:
        Der asyncio-Event-Loop des FastAPI-Prozesses.
    device:
        sounddevice-Gerätename oder -Index. None = Standardgerät.
    ref_db:
        Optional. ReferenceDB-Instanz für Chroma-Vergleich (Takt-Erkennung).
        Wenn None, wird Chroma gesendet aber kein Takt-Matching gemacht.
    """

    def __init__(
        self,
        event_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
        device: str | int | None = None,
        ref_db: "Any | None" = None,
    ) -> None:
        self.event_queue = event_queue
        self.loop = loop
        self.device = device
        self._ref_db = ref_db

        self.onset_detector = OnsetDetector(sample_rate=SAMPLE_RATE)
        self.recorder = MultitrackRecorder(sample_rate=SAMPLE_RATE, channels=CHANNELS_TOTAL)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running = False
        self._device_name = ""
        self._error = ""

        # Pegel-Monitoring
        self._channel_rms: np.ndarray = np.zeros(CHANNELS_TOTAL, dtype=np.float32)
        self._rms_lock = threading.Lock()

        # ADC-Zeitstempel des ersten Audio-Callbacks nach Aufnahme-Start
        self._adc_start: float | None = None

        # BarTracker
        self._bar_tracker: BarTracker = BarTracker(
            bpm=120.0,
            seg_start_t=0.0,
            seg_end_t=86400.0,
        )
        self._bar_tracker_lock = threading.Lock()
        self._logged_bar_count: int = 0

        # Streaming Chroma-Extraktoren (Prime Directive: identisch mit SimulatorWorker)
        self._guitar_extractor = StreamingChromaExtractor(
            sample_rate=SAMPLE_RATE,
            window_sec=0.5,
            use_cqt=False,
        )
        self._bass_extractor = StreamingChromaExtractor(
            sample_rate=SAMPLE_RATE,
            window_sec=2.0,
            target_sr=8_000,
            bp_low=30.0,
            bp_high=300.0,
            use_cqt=True,
            fmin_hz=32.703,
        )

        # Referenz-Chromas für Takt-Erkennung: {bar_num: chroma_array}
        self._ref_chromas: dict[int, np.ndarray] = {}
        self._current_song_id: str = ""
        self._current_bpm: float = 120.0

        # Chroma-Worker: Background-Thread für librosa-Berechnung
        self._chroma_queue: queue.Queue = queue.Queue(maxsize=64)
        self._latest_chroma: dict | None = None
        self._latest_chroma_lock = threading.Lock()
        self._chroma_thread = threading.Thread(
            target=self._chroma_worker,
            name="chroma-worker",
            daemon=True,
        )
        self._chroma_thread.start()

    # --- Lifecycle ------------------------------------------------------------

    def start(self) -> None:
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
        self._stop_event.set()
        # Chroma-Worker beenden
        try:
            self._chroma_queue.put_nowait({"kind": "stop"})
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout=5.0)
        self._running = False
        log.info("AudioProcess gestoppt")

    def is_running(self) -> bool:
        return self._running

    def channel_levels(self) -> list[float]:
        with self._rms_lock:
            return [round(float(v), 6) for v in self._channel_rms]

    def latest_chroma(self) -> dict | None:
        """Letzter Chroma-Update (guitar oder bass) mit Takt-Erkennungsergebnis."""
        with self._latest_chroma_lock:
            return dict(self._latest_chroma) if self._latest_chroma else None

    @staticmethod
    def list_devices() -> list[dict]:
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

    def set_song(
        self,
        bpm: float,
        grundrhythmus: dict | None = None,
        seg_start_t: float | None = None,
        song_id: str = "",
    ) -> None:
        """Konfiguriert BarTracker und Chroma-Extraktoren für einen neuen Song.

        Thread-safe — aus dem FastAPI-Event-Loop über asyncio.to_thread() aufrufen.

        Parameters
        ----------
        bpm:
            BPM aus der Songdatenbank.
        grundrhythmus:
            Optional. {"kick": [0.0, 2.0], "snare": [1.0, 3.0]}
        seg_start_t:
            Segment-Startzeit. None = aktuelle ADC-Zeit oder 0.
        song_id:
            Song-ID für Chroma-Referenz-Lookup in reference.db.
        """
        t0 = seg_start_t if seg_start_t is not None else (self._adc_start or 0.0)
        with self._bar_tracker_lock:
            self._bar_tracker = BarTracker(
                bpm=bpm,
                seg_start_t=t0,
                seg_end_t=t0 + 86400.0,
                grundrhythmus=grundrhythmus,
            )
            self._logged_bar_count = 0

        # Chroma-Extraktoren zurücksetzen
        # Bass-Fenster: 1,2 × Taktdauer (BPM-abhängig), max 3 s
        bar_sec = max(2.0, 4.0 * 60.0 / bpm) if bpm > 0 else 2.0
        self._guitar_extractor.reset()
        self._bass_extractor = StreamingChromaExtractor(
            sample_rate=SAMPLE_RATE,
            window_sec=min(bar_sec * 1.2, 3.0),
            target_sr=8_000,
            bp_low=30.0,
            bp_high=300.0,
            use_cqt=True,
            fmin_hz=32.703,
        )

        # Referenz-Chromas laden (für Takt-Erkennung via Kosinus-Ähnlichkeit)
        self._current_song_id = song_id
        self._current_bpm = bpm
        if self._ref_db is not None and song_id:
            try:
                self._ref_chromas = self._ref_db.get_all_bar_chromas(song_id)
                log.info(
                    "Referenz-Chromas geladen: %d Takte für Song %s",
                    len(self._ref_chromas), song_id,
                )
            except Exception as exc:
                log.warning("Referenz-Chromas konnten nicht geladen werden: %s", exc)
                self._ref_chromas = {}
        else:
            self._ref_chromas = {}

        log.info(
            "BarTracker + Chroma konfiguriert: bpm=%.1f  song=%s  ref_bars=%d",
            bpm, song_id or "(kein)", len(self._ref_chromas),
        )

    # --- Main Thread ----------------------------------------------------------

    def _run(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            log.warning(
                "sounddevice nicht installiert — AudioProcess läuft im Stub-Modus."
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
                "blocksize":  BLOCK_SIZE,
                "dtype":      "float32",
                "channels":   CHANNELS_TOTAL,
                "callback":   self._audio_callback,
            }
            if self.device is not None:
                stream_kwargs["device"] = self.device

            with sd.InputStream(**stream_kwargs) as stream:
                self._device_name = (
                    stream.device if isinstance(stream.device, str) else str(stream.device)
                )
                log.info(
                    "Audio-Stream geöffnet: %s @ %d Hz, %d ch",
                    self._device_name, SAMPLE_RATE, CHANNELS_TOTAL,
                )
                self._send_status()

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

        Zeitbudget: BLOCK_SIZE/SAMPLE_RATE = 42 ms @ 48 kHz.
        Alle Operationen hier MÜSSEN in <5 ms abgeschlossen sein.
        push_block() und snapshot() sind safe (nur Buffer-Operationen).
        Chroma-Berechnung (librosa) läuft im _chroma_worker-Thread.
        """
        if status:
            log.warning("sounddevice Status: %s", status)

        # --- Aufnahme: alle 18 Kanäle in Datei ---
        self.recorder.write_block(indata)

        # --- ADC-Zeitstempel ---
        el = self.recorder.event_logger
        if el is not None and self._adc_start is None:
            self._adc_start = time_info.inputBufferAdcTime
        elif el is None:
            self._adc_start = None

        wav_offset: float | None = (
            time_info.inputBufferAdcTime - self._adc_start
            if self._adc_start is not None else None
        )

        # --- Pegel-Monitoring ---
        rms_per_ch = np.sqrt(np.mean(indata ** 2, axis=0))
        with self._rms_lock:
            self._channel_rms = rms_per_ch

        # --- Streaming Chroma-Extraktoren befüllen (schnell: kein librosa) ---
        # Identisch mit SimulatorWorker: erst befüllen, dann Onset-Detection.
        if indata.shape[1] > CH_GUITAR:
            self._guitar_extractor.push_block(indata[:, CH_GUITAR])
        if indata.shape[1] > CH_BASS:
            self._bass_extractor.push_block(indata[:, CH_BASS])

        # --- Onset-Detection: Kick + Snare + Crash ---
        onsets = self.onset_detector.process_block(indata)
        for ev in onsets:
            self._emit(OnsetUpdate(onset_type=ev.type, energy=ev.energy))
            if el is not None:
                el.log(ev.type, wav_offset=wav_offset, energy=round(ev.energy, 6))

            t_ev = wav_offset if wav_offset is not None else 0.0

            # Guitar-Chroma-Snapshot bei Beat-Events → Background-Worker
            if ev.type in ("kick", "snare"):
                try:
                    snap = self._guitar_extractor.snapshot()
                    self._chroma_queue.put_nowait(
                        {"kind": "guitar", "snap": snap, "t": t_ev}
                    )
                except queue.Full:
                    pass  # Queue voll → überspringen, kein Blocking

            # BarTracker + Bar-Logging
            with self._bar_tracker_lock:
                if ev.type == "kick":
                    self._bar_tracker.process_kick(t_ev, energy=ev.energy)
                elif ev.type == "snare":
                    self._bar_tracker.process_snare(t_ev, energy=ev.energy)
                elif ev.type == "crash":
                    self._bar_tracker.process_crash(t_ev, energy=ev.energy)

                bar_times = sorted(self._bar_tracker.get_latest_bars())
                bpm_val   = self._bar_tracker.get_bpm()
                for bar_idx, bt in enumerate(bar_times):
                    if bar_idx < self._logged_bar_count:
                        continue
                    if bt > t_ev:
                        break
                    if el is not None:
                        el.log("bar", wav_offset=bt, bar_num=bar_idx + 1, bpm=bpm_val)
                    self._logged_bar_count = bar_idx + 1
                    # Bass-Chroma-Snapshot für neuen Takt → Background-Worker
                    try:
                        snap = self._bass_extractor.snapshot()
                        self._chroma_queue.put_nowait(
                            {"kind": "bass", "snap": snap, "t": bt}
                        )
                    except queue.Full:
                        pass

    # --- Chroma-Worker (Background-Thread) ------------------------------------

    def _chroma_worker(self) -> None:
        """Hintergrund-Thread: Chroma-Berechnung + Takt-Erkennung.

        Empfängt Buffer-Snapshots aus der Queue, berechnet STFT/CQT-Chroma
        (identisch mit StreamingChromaExtractor.get_chroma()),
        vergleicht per Kosinus-Ähnlichkeit gegen Referenz-Chromas und
        emittiert ChromaUpdate-Events.
        """
        try:
            import librosa
        except ImportError:
            log.warning("librosa nicht installiert — Chroma-Worker inaktiv.")
            # Queue leeren und Thread beenden
            while True:
                try:
                    task = self._chroma_queue.get(timeout=1.0)
                    if task.get("kind") == "stop":
                        break
                except queue.Empty:
                    pass
            return

        while True:
            try:
                task = self._chroma_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if task.get("kind") == "stop":
                break

            try:
                snap = task["snap"]
                buf  = snap["buf"]

                # Stille → überspringen
                if float(np.max(np.abs(buf))) < 1e-5:
                    continue

                # Chroma berechnen — identisch mit StreamingChromaExtractor.get_chroma()
                if snap["use_cqt"]:
                    chroma_mat = librosa.feature.chroma_cqt(
                        y=buf, sr=snap["out_sr"], hop_length=128,
                        fmin=snap["fmin"], n_chroma=12,
                    )
                else:
                    chroma_mat = librosa.feature.chroma_stft(
                        y=buf, sr=snap["out_sr"], hop_length=256,
                        n_fft=2048, n_chroma=12,
                    )

                c = chroma_mat.mean(axis=1).astype(np.float64)
                c = c ** 2  # Power-Normalisierung: schärfere Peaks
                norm = float(np.linalg.norm(c))
                if norm < 1e-8:
                    continue
                chroma = (c / norm).tolist()

                # Kosinus-Ähnlichkeit gegen Referenz-Chromas
                bar_num, confidence = -1, 0.0
                ref = self._ref_chromas  # atomare Referenz (GIL-sicher)
                if ref:
                    live_vec = np.array(chroma, dtype=np.float32)
                    live_norm = float(np.linalg.norm(live_vec))
                    best_sim = -1.0
                    if live_norm > 1e-8:
                        for bnum, ref_vec in ref.items():
                            rn = float(np.linalg.norm(ref_vec))
                            if rn < 1e-8:
                                continue
                            sim = float(np.dot(live_vec, ref_vec) / (live_norm * rn))
                            if sim > best_sim:
                                best_sim, bar_num = sim, bnum
                    confidence = max(0.0, best_sim)

                update = ChromaUpdate(
                    kind=task["kind"],
                    t=task["t"],
                    chroma=chroma,
                    bar_num=bar_num,
                    confidence=confidence,
                )
                self._emit(update)
                with self._latest_chroma_lock:
                    self._latest_chroma = update.to_dict()

            except Exception as exc:
                log.debug("Chroma-Worker Task-Fehler: %s", exc)

    # --- Emit (thread-safe → asyncio) ----------------------------------------

    def _emit(self, event: OnsetUpdate | AudioStatus | ChromaUpdate) -> None:
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
