"""Multitrack-Recorder für die Probe.

Schreibt alle 18 XR18-Kanäle als 18-Kanal-WAV auf die lokale Festplatte.
Die Dateien können nach der Probe genutzt werden um:
  - Den Fingerprint-Algorithmus mit echten Aufnahmen zu verbessern
  - Die Referenz-DB mit realen Bar-Segmenten zu befüllen
  - Beat-Detection-Parameter zu kalibrieren

Aufnahme-Format:
  - 18 Kanäle, 48 kHz, float32
  - Eine WAV-Datei pro Recording-Session (= pro Song oder manuell gestartet)
  - Dateiname: HHMMSS_{Song1_Song2_...}.wav  (Uhrzeit 6-stellig — Sekundenauflösung
    schützt vor Filename-Kollisionen bei mehreren Starts in derselben Minute)
  - Ordner:    live/data/recordings/YYYY-MM-DD/

Thread-Sicherheit:
  Der Recorder wird aus dem sounddevice-Callback-Thread aufgerufen.
  start()/stop() kommen vom FastAPI-HTTP-Thread.
  Ein threading.Lock schützt den gemeinsamen Zustand.

Robustes Schließen:
  Bei Server-Abriss (geschlossenes Terminal, Laptop-Suspend, SIGHUP) lief
  früher der FastAPI-Shutdown-Hook nicht durch — die RF64-Header wurden nie
  finalisiert und die Dateien waren unleserlich ("psf_fseek() failed").
  Jetzt: atexit-Hook + SIGHUP-/SIGTERM-Handler in __init__ stellen sicher,
  dass close() auch bei abruptem Beenden noch läuft.
  Zusätzlich: alle FLUSH_EVERY_BLOCKS Blöcke ein flush() — begrenzt
  Datenverlust bei SIGKILL (atexit feuert dort nicht).
"""

from __future__ import annotations

import atexit
import logging
import signal
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from .event_logger import SessionEventLogger

log = logging.getLogger("live.audio.recorder")

# Alle FLUSH_EVERY_BLOCKS (=100 ≈ 4 s @ 48 kHz/2048 samples) wird das WAV
# auf Platte geflusht. Limitiert Datenverlust bei abruptem Crash.
FLUSH_EVERY_BLOCKS = 100

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
        self.event_logger: Optional[SessionEventLogger] = None
        self._played_songs: list[str] = []   # Songs in Reihenfolge des Einsatzes
        self._rec_stem: str = ""             # Basis-Dateiname ohne Songnamen
        # Klartext-Logfile neben der WAV — für Anker-/Diagnoseausgaben.
        self._log_file = None                # type: ignore[assignment]
        self._log_path: Optional[Path] = None
        self._log_started_ts: float = 0.0

        # Robustes Schließen: atexit + SIGHUP/SIGTERM-Handler.
        # SIGKILL kann nicht abgefangen werden — dafür gibt's den periodischen
        # flush() in write_block().
        atexit.register(self._emergency_close)
        for sig in (signal.SIGHUP, signal.SIGTERM):
            try:
                prev = signal.getsignal(sig)
                signal.signal(sig, self._make_signal_handler(sig, prev))
            except (ValueError, OSError):
                # signal.signal() funktioniert nur im Main-Thread.
                # Wenn der Recorder aus einem Worker-Thread instanziiert wird,
                # bleibt nur der atexit-Hook.
                pass

    @property
    def is_recording(self) -> bool:
        return self._info is not None and self._info.running

    # --- Notfall-Schließer (atexit / signal) ----------------------------------

    def _emergency_close(self) -> None:
        """Schließt die WAV-Datei ohne Lock-Akquise oder Umbenennung.

        Wird von atexit + Signal-Handler aufgerufen. Ziel: RF64-Header
        finalisieren, damit die Datei lesbar bleibt. Kein Logging über
        ``log`` (dessen Handler können beim Interpreter-Shutdown schon
        geschlossen sein), sondern direkt auf stderr.
        """
        sf_file = self._sf_file
        if sf_file is None:
            return
        try:
            sf_file.close()
        except Exception:
            pass
        self._sf_file = None
        log_file = self._log_file
        if log_file is not None:
            try:
                log_file.flush()
                log_file.close()
            except Exception:
                pass
            self._log_file = None
        # event_logger schließt sich beim GC oder im regulären stop()-Pfad.

    def _make_signal_handler(self, sig: int, prev_handler):
        """Baut einen Signal-Handler, der zuerst die WAV-Datei sicher schließt
        und dann den vorherigen Handler (typischerweise Pythons default) ausführt.
        Wichtig: SIGTERM wird auch von uvicorn benutzt — wir dürfen den
        normalen Shutdown nicht blockieren.
        """
        def _handler(signum, frame):
            self._emergency_close()
            # Vorherigen Handler ausführen, damit der normale Shutdown läuft.
            if callable(prev_handler):
                try:
                    prev_handler(signum, frame)
                except Exception:
                    pass
            elif prev_handler == signal.SIG_DFL:
                # Default-Verhalten emulieren: Programm beenden.
                signal.signal(signum, signal.SIG_DFL)
                # Re-raise so the default action fires.
                import os as _os
                _os.kill(_os.getpid(), signum)
        return _handler

    def add_played_song(self, name: str) -> None:
        """Fügt einen gespielten Song zur laufenden Aufnahme hinzu.

        Doppelte aufeinanderfolgende Einträge werden ignoriert.
        Wird aus dem FastAPI WebSocket-Handler aufgerufen wenn ein Song gewählt wird.
        """
        if not name:
            return
        with self._lock:
            if not (self._info is not None and self._info.running):
                return
            if not self._played_songs or self._played_songs[-1] != name:
                self._played_songs.append(name)
                log.debug("Song zur Aufnahme hinzugefügt: %s", name)

    def log_text(self, msg: str) -> None:
        """Schreibt eine Zeile in das Klartext-Logfile neben der WAV.

        Nicht-blockierend; verwirft die Zeile lautlos wenn keine Aufnahme läuft.
        Wird in der Live-App vom AnchorMatcher-Sink benutzt.
        """
        f = self._log_file
        if f is None:
            return
        t_rel = time.time() - self._log_started_ts
        try:
            f.write(f"[{t_rel:8.2f}s] {msg}\n")
        except (OSError, ValueError):
            pass

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
            # Wenn schon eine Aufnahme läuft: NICHT implizit schließen+neu starten.
            # Früher: _close_locked() + neue Datei → Race mit Audio-Thread
            # (write_block lief lockfrei, konnte in halb-geschlossene Datei
            # schreiben → RF64-Header inkonsistent → "psf_fseek() failed").
            # Jetzt: bestehende Info zurückgeben, kein Wechsel.
            if self._sf_file is not None and self._info is not None:
                log.info(
                    "Aufnahme läuft bereits (%s) — start() ignoriert.",
                    self._info.path,
                )
                return self._info

            # Datums-Unterordner + HHMMSS-Dateiname (sekundengenau).
            now = datetime.now()
            date_dir = self.recordings_dir / now.strftime("%Y-%m-%d")
            date_dir.mkdir(parents=True, exist_ok=True)

            base_stem = now.strftime("%H%M%S")
            self._rec_stem = base_stem
            # Kollisionsschutz: falls trotzdem schon eine Datei existiert
            # (z.B. manueller Test mit überspringender Systemuhr), Suffix anhängen.
            n = 1
            while (date_dir / f"{self._rec_stem}.wav").exists():
                n += 1
                self._rec_stem = f"{base_stem}_{n}"
            self._played_songs = []
            filename = self._rec_stem + ".wav"
            path = date_dir / filename

            self._sf_file = sf.SoundFile(
                str(path),
                mode="w",
                samplerate=self.sample_rate,
                channels=self.channels,
                format="RF64",
                subtype="FLOAT",
            )

            started_ts = time.time()
            self._info = RecordingInfo(
                label=label,
                song_id=song_id,
                path=str(path),
                started_at=now.isoformat(),
                started_at_ts=started_ts,
                channels=self.channels,
                sample_rate=self.sample_rate,
                blocks_written=0,
                running=True,
            )

            # Event-Logger: JSONL-Datei neben der WAV
            jsonl_path = path.with_suffix(".jsonl")
            self.event_logger = SessionEventLogger(jsonl_path, started_ts)
            self.event_logger.log(
                "session_start",
                label=label,
                song_id=song_id,
                wav=path.name,
                channels=self.channels,
                sample_rate=self.sample_rate,
                started_at=now.isoformat(),
            )

            # Klartext-Logfile neben der WAV (Anker-Diagnose etc.)
            log_path = path.with_suffix(".log")
            try:
                self._log_file = log_path.open("w", encoding="utf-8", buffering=1)
                self._log_path = log_path
                self._log_started_ts = started_ts
                self._log_file.write(
                    f"# {now.isoformat()}  session_start  wav={path.name}\n"
                )
            except OSError as exc:
                log.warning("Logfile konnte nicht geöffnet werden: %s", exc)
                self._log_file = None
                self._log_path = None

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

        Race-Safety: holt eine lokale Referenz auf self._sf_file BEVOR
        sie benutzt wird — verhindert, dass ein paralleler stop() im
        Main-Thread den Pointer zwischen None-Check und write() auf None
        setzt. (GIL macht die Zuweisung atomar, aber zwei separate Reads
        sind nicht atomar.)
        """
        sf_file = self._sf_file
        info = self._info
        if sf_file is None:
            return
        try:
            sf_file.write(indata)
            if info is not None:
                info.blocks_written += 1
                # Periodischer Flush: begrenzt Datenverlust bei SIGKILL.
                # Header wird hier NICHT finalisiert (das macht erst close()),
                # aber Daten sind dann zumindest auf Platte — und der Repair-
                # Skript kann sie aus dem rohen data-Chunk wiederherstellen.
                if info.blocks_written % FLUSH_EVERY_BLOCKS == 0:
                    try:
                        sf_file.flush()
                    except Exception:
                        pass
        except Exception as exc:
            log.error("Fehler beim Schreiben des Audio-Blocks: %s", exc)
            # KEIN self.stop() mehr hier — das führte früher zu Deadlocks
            # und schloss in Race-Situationen die falsche (neue) Datei.
            # Stattdessen: Datei-Pointer löschen und atexit-Hook macht close().
            self._sf_file = None

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
        dest = src.parent / dest_name
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
        """Listet alle vorhandenen WAV-Dateien im Recordings-Verzeichnis.

        Durchsucht auch YYYY-MM-DD-Unterordner.
        """
        if not self.recordings_dir.exists():
            return []
        files = sorted(self.recordings_dir.rglob("*.wav"), reverse=True)
        result = []
        for f in files:
            if "_mixdown" in f.name:
                continue
            size_mb = round(f.stat().st_size / 1_048_576, 1)
            # Relativer Pfad ab recordings_dir als Anzeigename
            rel = f.relative_to(self.recordings_dir)
            result.append({
                "filename": str(rel),
                "path": str(f),
                "size_mb": size_mb,
                "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
        return result

    # --- Interne Hilfsmethoden (nur unter _lock aufrufen) ----------------------

    def _close_locked(self) -> RecordingInfo:
        """Schließt die SoundFile-Datei und benennt sie mit Songnamen um.

        Muss unter _lock aufgerufen werden.
        """
        assert self._sf_file is not None
        try:
            self._sf_file.close()
        except Exception as exc:
            log.error("Fehler beim Schließen der Aufnahme-Datei: %s", exc)

        self._sf_file = None
        info = self._info
        duration = 0.0
        if info is not None:
            info.running = False
            duration = round(info.blocks_written * 2048 / info.sample_rate, 1)
            if self.event_logger is not None:
                self.event_logger.log(
                    "session_end",
                    duration_sec=duration,
                    blocks=info.blocks_written,
                )
        if self.event_logger is not None:
            self.event_logger.close()
            self.event_logger = None
        # Klartext-Log schließen
        if self._log_file is not None:
            try:
                self._log_file.flush()
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None
        self._info = None

        # Umbenennen: Songnamen anhängen
        if info is not None:
            info = self._rename_with_songs(info)
            log.info(
                "Recording beendet: %s (%.1f s, %d Blöcke)",
                info.path, duration, info.blocks_written,
            )

        return info  # type: ignore[return-value]

    def _rename_with_songs(self, info: RecordingInfo) -> RecordingInfo:
        """Benennt WAV + JSONL um: {stem}_{Song1_Song2}.wav.

        Aufgerufen unter _lock, nach dem Schließen beider Dateien.
        """
        if not self._played_songs:
            return info

        def _safe(name: str, max_len: int = 24) -> str:
            s = "".join(c if c.isalnum() else "_" for c in name)
            # Mehrfache Unterstriche zusammenfassen
            while "__" in s:
                s = s.replace("__", "_")
            return s.strip("_")[:max_len]

        song_part = "_".join(_safe(n) for n in self._played_songs[:6] if _safe(n))
        if not song_part:
            return info

        old_wav = Path(info.path)
        new_wav = old_wav.parent / f"{self._rec_stem}_{song_part}.wav"
        old_jsonl = old_wav.with_suffix(".jsonl")
        new_jsonl = new_wav.with_suffix(".jsonl")
        old_log   = old_wav.with_suffix(".log")
        new_log   = new_wav.with_suffix(".log")

        try:
            old_wav.rename(new_wav)
            if old_jsonl.exists():
                old_jsonl.rename(new_jsonl)
            if old_log.exists():
                old_log.rename(new_log)
            info.path = str(new_wav)
            log.info("Recording umbenannt: %s", new_wav.name)
        except Exception as exc:
            log.error("Fehler beim Umbenennen der Aufnahme: %s", exc)

        return info
