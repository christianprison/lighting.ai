"""Multitrack-Recorder für die Probe.

Schreibt alle 18 XR18-Kanäle als 18-Kanal-WAV auf die lokale Festplatte.
Die Dateien können nach der Probe genutzt werden um:
  - Den Fingerprint-Algorithmus mit echten Aufnahmen zu verbessern
  - Die Referenz-DB mit realen Bar-Segmenten zu befüllen
  - Beat-Detection-Parameter zu kalibrieren

Aufnahme-Format:
  - 18 Kanäle, 48 kHz, float32
  - Eine WAV-Datei pro Recording-Session (= pro Song oder manuell gestartet)
  - Dateiname: YYYY-MM-DD_HHMMSS_{label}.wav
  - Ablage: live/data/recordings/

Thread-Sicherheit:
  Der Recorder wird aus dem sounddevice-Callback-Thread aufgerufen.
  start()/stop() kommen vom FastAPI-HTTP-Thread.
  Ein threading.Lock schützt den gemeinsamen Zustand.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("live.audio.recorder")

DEFAULT_RECORDINGS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "recordings"


@dataclass
class RecordingInfo:
    """Beschreibt eine laufende oder abgeschlossene Aufnahme."""
    label: str            # Frei wählbarer Name (z.B. Song-Name)
    song_id: str          # Song-ID aus der DB (leer wenn kein Song gewählt)
    path: str             # Absoluter Pfad zur WAV-Datei
    started_at: str       # ISO-8601 Zeitstempel
    started_at_ts: float  # time.time() beim Start — für wav_offset-Berechnung
    channels: int         # Anzahl der aufgezeichneten Kanäle
    sample_rate: int      # Sample-Rate
    blocks_written: int   # Anzahl der bisher geschriebenen Audio-Blöcke
    running: bool         # True solange Aufnahme aktiv

    @property
    def session_id(self) -> str:
        """Dateiname ohne Extension — eindeutiger Session-Bezeichner."""
        from pathlib import Path
        return Path(self.path).stem


class MultitrackRecorder:
    """Nimmt alle XR18-Kanäle block-weise in eine WAV-Datei auf.

    Parameters
    ----------
    recordings_dir:
        Verzeichnis, in dem WAV-Dateien abgelegt werden.
        Wird automatisch erstellt wenn es nicht existiert.
    sample_rate:
        Sample-Rate des Audio-Streams (muss mit AudioProcess übereinstimmen).
    channels:
        Anzahl der aufzuzeichnenden Kanäle (default: 18).
    """

    def __init__(
        self,
        recordings_dir: Path = DEFAULT_RECORDINGS_DIR,
        sample_rate: int = 48_000,
        channels: int = 18,
    ) -> None:
        self.recordings_dir = recordings_dir
        self.sample_rate = sample_rate
        self.channels = channels

        self._lock = threading.Lock()
        self._sf_file: Optional[object] = None   # soundfile.SoundFile
        self._info: Optional[RecordingInfo] = None

    # --- Public API (aufgerufen vom FastAPI-Thread) ----------------------------

    def start(self, label: str = "", song_id: str = "") -> RecordingInfo:
        """Startet eine neue Aufnahme.

        Falls bereits eine Aufnahme läuft, wird diese zuerst gestoppt.

        Parameters
        ----------
        label:
            Beschreibung der Aufnahme, z.B. Song-Name. Wird im Dateinamen verwendet.
        song_id:
            Song-ID aus der DB für spätere Zuordnung.

        Returns
        -------
        RecordingInfo mit dem Pfad der neu angelegten Datei.
        """
        try:
            import soundfile as sf  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "soundfile nicht installiert. Bitte 'pip install soundfile' ausführen."
            ) from exc

        with self._lock:
            # Laufende Aufnahme beenden
            if self._sf_file is not None:
                self._close_locked()

            # Dateiname aus Zeitstempel + Label
            now = datetime.now()
            safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
            filename = now.strftime("%Y-%m-%d_%H%M%S")
            if safe_label:
                filename += f"_{safe_label}"
            filename += ".wav"

            self.recordings_dir.mkdir(parents=True, exist_ok=True)
            path = self.recordings_dir / filename

            self._sf_file = sf.SoundFile(
                str(path),
                mode="w",
                samplerate=self.sample_rate,
                channels=self.channels,
                format="WAV",
                subtype="FLOAT",
            )

            self._info = RecordingInfo(
                label=label,
                song_id=song_id,
                path=str(path),
                started_at=now.isoformat(),
                started_at_ts=time.time(),
                channels=self.channels,
                sample_rate=self.sample_rate,
                blocks_written=0,
                running=True,
            )
            log.info("Recording gestartet: %s", path)
            return self._info

    def stop(self) -> Optional[RecordingInfo]:
        """Beendet die laufende Aufnahme und schließt die Datei.

        Returns
        -------
        RecordingInfo der abgeschlossenen Aufnahme, oder None wenn keine lief.
        """
        with self._lock:
            if self._sf_file is None:
                return None
            info = self._close_locked()
            return info

    def write_block(self, indata: np.ndarray) -> None:
        """Schreibt einen Audio-Block in die WAV-Datei.

        Wird direkt aus dem sounddevice-Callback aufgerufen (Audio-Thread).
        indata: shape (frames, channels), float32

        Kein Lock nötig hier: der Python GIL schützt den Pointer-Check,
        und SoundFile.write() ist reentrant für einen einzelnen Writer-Thread.
        """
        if self._sf_file is None:
            return
        try:
            self._sf_file.write(indata)
            if self._info is not None:
                self._info.blocks_written += 1
        except Exception as exc:
            log.error("Fehler beim Schreiben des Audio-Blocks: %s", exc)
            # Aufnahme bei Fehler beenden um Datenverlust zu begrenzen
            self.stop()

    def status(self) -> dict:
        """Gibt den aktuellen Status als dict zurück (für API-Response)."""
        with self._lock:
            if self._info is None:
                return {"running": False}
            return {
                "running": self._info.running,
                "label": self._info.label,
                "song_id": self._info.song_id,
                "path": self._info.path,
                "started_at": self._info.started_at,
                "channels": self._info.channels,
                "sample_rate": self._info.sample_rate,
                "blocks_written": self._info.blocks_written,
                "duration_sec": round(
                    self._info.blocks_written * 2048 / self._info.sample_rate, 1
                ),
            }

    def mixdown(self, source_filename: str) -> dict:
        """Erstellt einen Stereo-Mixdown einer 18-Kanal-WAV-Aufnahme.

        Alle 18 Kanäle werden gleichgewichtet summiert (L = ungerade Kanäle,
        R = gerade Kanäle, analog zur üblichen Stereo-Panning-Konvention beim
        XR18: L-Bus auf ungerade USB-Kanäle, R-Bus auf gerade).
        Das Ergebnis wird peak-normalisiert und als neue WAV-Datei gespeichert.

        Parameters
        ----------
        source_filename:
            Dateiname (ohne Pfad) der 18-Kanal-Quelldatei.

        Returns
        -------
        dict mit ``path``, ``filename``, ``duration_sec``, ``size_mb``.
        """
        try:
            import soundfile as sf  # type: ignore
        except ImportError as exc:
            raise RuntimeError("soundfile nicht installiert.") from exc

        src = self.recordings_dir / source_filename
        if not src.exists():
            raise FileNotFoundError(f"Quelldatei nicht gefunden: {src}")

        data, sr = sf.read(str(src), dtype="float32", always_2d=True)
        n_ch = data.shape[1]

        # Stereo-Summierung: L = Kanäle 0,2,4,…  R = Kanäle 1,3,5,…
        left  = data[:, 0:n_ch:2].mean(axis=1)
        right = data[:, 1:n_ch:2].mean(axis=1) if n_ch > 1 else left.copy()

        stereo = np.stack([left, right], axis=1)

        # Peak-Normalisierung auf -1 dBFS
        peak = np.abs(stereo).max()
        if peak > 0:
            stereo *= (10 ** (-1 / 20)) / peak

        dest_name = src.stem + "_mixdown.wav"
        dest = self.recordings_dir / dest_name
        sf.write(str(dest), stereo, sr, subtype="FLOAT")

        size_mb = round(dest.stat().st_size / 1_048_576, 1)
        duration_sec = round(len(stereo) / sr, 1)
        log.info("Mixdown erstellt: %s (%.1f s, %.1f MB)", dest, duration_sec, size_mb)
        return {
            "filename": dest_name,
            "path": str(dest),
            "duration_sec": duration_sec,
            "size_mb": size_mb,
        }

    def list_recordings(self) -> list[dict]:
        """Listet alle vorhandenen WAV-Dateien im Recordings-Verzeichnis."""
        if not self.recordings_dir.exists():
            return []
        files = sorted(self.recordings_dir.glob("*.wav"), reverse=True)
        result = []
        for f in files:
            size_mb = round(f.stat().st_size / 1_048_576, 1)
            result.append({
                "filename": f.name,
                "path": str(f),
                "size_mb": size_mb,
                "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
        return result

    # --- Interne Hilfsmethoden (nur unter _lock aufrufen) ----------------------

    def _close_locked(self) -> RecordingInfo:
        """Schließt die SoundFile-Datei. Muss unter _lock aufgerufen werden."""
        assert self._sf_file is not None
        try:
            self._sf_file.close()
        except Exception as exc:
            log.error("Fehler beim Schließen der Aufnahme-Datei: %s", exc)

        self._sf_file = None
        info = self._info
        if info is not None:
            info.running = False
            duration = round(info.blocks_written * 2048 / info.sample_rate, 1)
            log.info(
                "Recording beendet: %s (%.1f s, %d Blöcke)",
                info.path, duration, info.blocks_written,
            )
        self._info = None
        return info  # type: ignore[return-value]
