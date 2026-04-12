"""simulator.py — Offline-Simulation der Kick/Snare-Erkennung.

Läuft so schnell wie möglich (kein Echtzeit-Throttling).

Zwei separate Worker:

SimulatorWorker  — Kernsimulation (identisch mit Live-Betrieb):
    Schreibt alle erkannten Events als JSONL-Datei, puffert Rohsignal für
    Lead-Guitar- (CH4) und Bass-Kanal (CH5). Fortschritt 0→100 % für
    den Onset-Loop. Emittiert `finished` mit Kick/Snare/Crash/BarTimes/BPM
    + Rohsignal-Arrays für PostProcessWorker.

PostProcessWorker — Chroma + Bass-Visualisierung (nur Sim, nicht Live):
    Verarbeitet die gepufferten Rohsignale mit librosa.
    Läuft nach dem SimulatorWorker, hat einen eigenen Fortschrittsbalken.
    Emittiert `finished` mit chroma_data + bass_data.

JSONL-Format (eine JSON-Zeile pro Event, t relativ zu seg_start_t):
    {"t": 0.0,  "type": "sim_start", "data": {"song_id": …, …}}
    {"t": 1.23, "type": "kick",      "data": {"energy": 0.042}}
    {"t": 1.31, "type": "snare",     "data": {"energy": 0.078}}
"""
from __future__ import annotations

import json as _json
import sys
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

BLOCK_SIZE = 2048


# ---------------------------------------------------------------------------
# SimulatorWorker — Kernsimulation (Prime Directive: identisch mit Live)
# ---------------------------------------------------------------------------

class SimulatorWorker(QThread):
    """Offline-Simulation der Erkennungspipeline (Kick/Snare/Crash + BarTracker).

    Fortschritt 0→100 % für den Onset-Loop.  Chroma/Bass-Extraktion läuft
    separat im PostProcessWorker — so schließt der Simulations-Dialog sobald
    die eigentliche Erkennung fertig ist.
    """

    progress = pyqtSignal(float)   # 0.0–1.0
    finished = pyqtSignal(object)  # dict mit Ergebnissen + Rohsignal-Arrays
    error    = pyqtSignal(str)

    def __init__(
        self,
        wav_path: Path,
        seg_start_t: float,
        seg_end_t: float,
        sample_rate: int,
        n_channels: int,
        song_id: str,
        song_name: str,
        bpm: float,
        output_jsonl: Path,
        ref_db_path=None,   # nicht mehr verwendet, bleibt für API-Compat
        use_hmm: bool = False,  # nicht mehr verwendet
        song_key: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._wav_path     = wav_path
        self._seg_start_t  = seg_start_t
        self._seg_end_t    = seg_end_t
        self._song_id      = song_id
        self._song_name    = song_name
        self._bpm          = bpm
        self._output_jsonl = output_jsonl
        self._song_key     = song_key

    # ── Haupt-Loop ────────────────────────────────────────────────────────────

    def run(self) -> None:
        try:
            self._run_inner()
        except Exception as exc:
            self.error.emit(str(exc))

    def _run_inner(self) -> None:
        import soundfile as sf
        from detection.beat_detector import OnsetDetector, _CrashDetector
        from detection.bar_tracker import BarTracker

        # ── WAV-Datei vorab prüfen ────────────────────────────────────────────
        with sf.SoundFile(self._wav_path) as f:
            wav_sr     = f.samplerate
            wav_frames = f.frames
            wav_ch     = f.channels

        sr           = wav_sr
        start_sample = min(int(self._seg_start_t * sr), wav_frames)
        end_sample   = min(int(self._seg_end_t   * sr), wav_frames)

        print(
            f"[SIM] WAV: {self._wav_path.name}  {wav_sr} Hz  "
            f"{wav_frames} frames ({wav_frames/wav_sr:.1f}s)  {wav_ch}ch",
            file=sys.stderr,
        )
        print(
            f"[SIM] Segment: {self._seg_start_t:.2f}s – {self._seg_end_t:.2f}s  "
            f"→  start={start_sample}  end={end_sample}",
            file=sys.stderr,
        )

        if start_sample >= end_sample:
            self.error.emit(
                f"Kein Audio zu verarbeiten:\n"
                f"  WAV: {wav_frames} Frames @ {wav_sr} Hz "
                f"({wav_frames/wav_sr:.1f} s, {wav_ch} Kanäle)\n"
                f"  Segment: {self._seg_start_t:.1f} s – {self._seg_end_t:.1f} s\n"
                f"  → start_sample={start_sample} ≥ end_sample={end_sample}"
            )
            return

        total_frames = end_sample - start_sample

        # ── Detektor + BarTracker initialisieren ─────────────────────────────
        detector = OnsetDetector(sample_rate=sr)
        tracker = BarTracker(
            bpm=self._bpm,
            seg_start_t=self._seg_start_t,
            seg_end_t=self._seg_end_t,
        )

        kicks:   list[float] = []
        snares:  list[float] = []
        crashes: list[tuple[float, float]] = []   # (t_rel, rms_energy)
        blocks_done = 0

        # Chroma- und Bass-Kanal im selben Pass puffern — kein zweites File-Read
        # (Prime Directive: Simulation = Live, ein Algorithmus, kein Lookahead).
        CHROMA_CH = 4   # CH05 = Lead Guitar L
        BASS_CH   = 5   # CH06 = Bass
        chroma_buf: list[np.ndarray] = []
        bass_buf:   list[np.ndarray] = []
        _crash_rms_max = 0.0   # Diagnosewert: höchster OH-RMS im Durchlauf

        self._output_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with (
            sf.SoundFile(self._wav_path) as wav_f,
            open(self._output_jsonl, "w", encoding="utf-8") as jf,
        ):
            # Header-Zeile
            jf.write(_json.dumps({
                "t": 0.0,
                "type": "sim_start",
                "data": {
                    "song_id":     self._song_id,
                    "song_name":   self._song_name,
                    "bpm":         self._bpm,
                    "seg_start_t": self._seg_start_t,
                    "seg_end_t":   self._seg_end_t,
                    "wav":         str(self._wav_path),
                },
            }) + "\n")

            wav_f.seek(start_sample)
            remaining = end_sample - wav_f.tell()

            while remaining > 0 and not self.isInterruptionRequested():
                to_read = min(BLOCK_SIZE, remaining)
                block = wav_f.read(to_read, dtype="float32", always_2d=True)
                if block.shape[0] == 0:
                    break
                remaining -= block.shape[0]

                t_mid = blocks_done * BLOCK_SIZE / sr + (block.shape[0] / 2) / sr

                # Chroma-Kanal puffern (Lead Guitar L) + Bass-Kanal puffern
                if block.shape[1] > CHROMA_CH:
                    chroma_buf.append(block[:, CHROMA_CH].copy())
                if block.shape[1] > BASS_CH:
                    bass_buf.append(block[:, BASS_CH].copy())

                # Diagnosewert: max OH-RMS (signed, ohne Highpass)
                if block.shape[1] > 14:
                    oh_diag = 0.5 * (block[:, 13].astype(np.float32)
                                     + block[:, 14].astype(np.float32))
                    _crash_rms_max = max(_crash_rms_max, float(np.sqrt(np.mean(oh_diag ** 2))))

                # ── Onset-Detection + BarTracker (streaming) ─────────────────
                for ev in detector.process_block(block):
                    if ev.type == "kick":
                        kicks.append(t_mid)
                        tracker.process_kick(self._seg_start_t + t_mid, energy=float(ev.energy))
                    elif ev.type == "snare":
                        snares.append(t_mid)
                        tracker.process_snare(self._seg_start_t + t_mid, energy=float(ev.energy))
                    elif ev.type == "crash":
                        crashes.append((t_mid, float(ev.energy)))
                        tracker.process_crash(self._seg_start_t + t_mid, energy=float(ev.energy))
                    jf.write(_json.dumps({
                        "t": round(t_mid, 4),
                        "type": ev.type,
                        "data": {"energy": round(float(ev.energy), 6)},
                    }) + "\n")

                blocks_done += 1
                if blocks_done % 50 == 0:
                    raw = (blocks_done * BLOCK_SIZE) / max(1, total_frames)
                    self.progress.emit(min(0.99, raw))

        # ── Finale Taktgitter-Berechnung (letzte Events einbeziehen) ─────────
        tracker.finalize()
        bar_times_final = tracker.get_latest_bars()
        bpm_final       = tracker.get_bpm()

        print(
            f"[SIM] Fertig: {blocks_done} Blöcke, "
            f"{len(kicks)} Kicks, {len(snares)} Snares "
            f"→ {self._output_jsonl.name}",
            file=sys.stderr,
        )
        print(
            f"[SIM] Crashes: {len(crashes)} erkannt  "
            f"(threshold RMS >{_CrashDetector.CRASH_RMS_MIN:.4f}, "
            f"max OH-RMS im Segment: {_crash_rms_max:.4f})",
            file=sys.stderr,
        )

        self.progress.emit(1.0)
        self.finished.emit({
            "jsonl_path":  self._output_jsonl,
            "n_kicks":     len(kicks),
            "n_snares":    len(snares),
            "n_crashes":   len(crashes),
            "kicks":       kicks,
            "snares":      snares,
            "crashes":     crashes,
            "bar_times":   bar_times_final,
            "bpm":         bpm_final,
            # Rohsignal-Arrays für PostProcessWorker (Chroma + Bass-Visualisierung)
            "chroma_buf":  np.concatenate(chroma_buf) if chroma_buf else np.array([], dtype=np.float32),
            "bass_buf":    np.concatenate(bass_buf)   if bass_buf   else np.array([], dtype=np.float32),
            "sample_rate": sr,
            "seg_start_t": self._seg_start_t,
            "seg_end_t":   self._seg_end_t,
            "song_key":    self._song_key,
        })


# ---------------------------------------------------------------------------
# PostProcessWorker — Chroma + Bass-Visualisierung (nur Sim, nicht Live)
# ---------------------------------------------------------------------------

class PostProcessWorker(QThread):
    """Extrahiert Chroma (Lead Guitar) und Bass-Chroma+Rhythmus nach der Simulation.

    Läuft separat vom SimulatorWorker, damit der Simulations-Dialog (der den
    Live-Algorithmus repräsentiert) sofort schließt und ein eigener
    Post-Processing-Dialog die Visualisierungs-Arbeit zeigt.
    """

    progress = pyqtSignal(float)   # 0.0–1.0
    finished = pyqtSignal(object)  # dict: {chroma_data, bass_data}

    def __init__(
        self,
        chroma_buf: np.ndarray,
        bass_buf: np.ndarray,
        sample_rate: int,
        seg_start_t: float,
        seg_end_t: float,
        bar_times: list[float],
        bpm: int,
        song_key: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._chroma_buf  = chroma_buf
        self._bass_buf    = bass_buf
        self._sr          = sample_rate
        self._seg_start_t = seg_start_t
        self._seg_end_t   = seg_end_t
        self._bar_times   = bar_times
        self._bpm         = bpm
        self._song_key    = song_key

    def run(self) -> None:
        try:
            self._run_inner()
        except Exception as exc:
            print(f"[POST] Fehler: {exc}", file=sys.stderr)
            self.finished.emit({"chroma_data": [], "bass_data": []})

    def _run_inner(self) -> None:
        chroma_data: list[dict] = []
        bass_data:   list[dict] = []

        # ── Chroma (Lead Guitar, pro Beat) ────────────────────────────────────
        if len(self._chroma_buf) > 0 and self._bar_times and self._bpm > 0:
            try:
                from chroma_viz import extract_chroma_at_beats_from_array, compute_beat_times
                beat_times = compute_beat_times(self._bar_times, self._bpm)
                beat_times = [t for t in beat_times
                              if self._seg_start_t <= t <= self._seg_end_t]

                chroma_data = extract_chroma_at_beats_from_array(
                    self._chroma_buf,
                    seg_start_t=self._seg_start_t,
                    sample_rate=self._sr,
                    beat_times_abs=beat_times,
                    window_sec=0.28,
                    song_key=self._song_key,
                    progress_callback=lambda f: self.progress.emit(f * 0.5),
                )
                print(f"[POST] Chroma: {len(chroma_data)} Beats extrahiert", file=sys.stderr)
            except Exception as e:
                print(f"[POST] Chroma fehlgeschlagen: {e}", file=sys.stderr)

        # ── Bass (pro Takt) ────────────────────────────────────────────────────
        if len(self._bass_buf) > 0 and self._bar_times and self._bpm > 0:
            try:
                from chroma_viz import extract_bass_at_bars_from_array
                bass_data = extract_bass_at_bars_from_array(
                    self._bass_buf,
                    seg_start_t=self._seg_start_t,
                    sample_rate=self._sr,
                    bar_times_abs=self._bar_times,
                    bpm=self._bpm,
                    song_key=self._song_key,
                    progress_callback=lambda f: self.progress.emit(0.5 + f * 0.5),
                )
                print(f"[POST] Bass: {len(bass_data)} Takte extrahiert", file=sys.stderr)
            except Exception as e:
                print(f"[POST] Bass fehlgeschlagen: {e}", file=sys.stderr)

        self.progress.emit(1.0)
        self.finished.emit({"chroma_data": chroma_data, "bass_data": bass_data})
