"""simulator.py — Offline-Simulation der Kick/Snare-Erkennung.

Läuft so schnell wie möglich (kein Echtzeit-Throttling).

Prime Directive: SimulatorWorker = Live-Algorithmus, kein Lookahead.
Chroma (Gitarre, Bass) und Vokal-VAD werden STREAMING berechnet —
identisch mit dem, was audio_process.py im Live-Betrieb tut.
Kein PostProcessWorker mehr: alle Features entstehen während des Onset-Loops.

SimulatorWorker — Kernsimulation + Streaming Feature-Extraktion:
    Schreibt alle erkannten Events als JSONL-Datei.
    Berechnet Guitar-Chroma pro Beat und Bass-Chroma+Rhythmus pro Takt
    über StreamingChromaExtractor (Rolling-Buffer, kein HPSS, kein Batch-CQT).
    Berechnet Vokal-VAD am Ende des Loops (fensterweise, zustandslos → identisch).
    Fortschritt 0→100 % für den Onset-Loop.
    Emittiert `finished` mit allen Ergebnissen.

JSONL-Format (eine JSON-Zeile pro Event, t relativ zu seg_start_t):
    {"t": 0.0,  "type": "sim_start", "data": {"song_id": …, …}}
    {"t": 1.23, "type": "kick",      "data": {"energy": 0.042}}
    {"t": 1.31, "type": "snare",     "data": {"energy": 0.078}}
"""
from __future__ import annotations

import json as _json
import os as _os
import sys
from pathlib import Path


def _log(msg: str) -> None:
    """Schreibt direkt auf fd 2 — umgeht Python-IO-Buffering."""
    _os.write(2, (msg + "\n").encode("utf-8", errors="replace"))

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

BLOCK_SIZE = 2048


# ---------------------------------------------------------------------------
# SimulatorWorker — Kernsimulation + Streaming Feature-Extraktion
# ---------------------------------------------------------------------------

class SimulatorWorker(QThread):
    """Offline-Simulation der Erkennungspipeline (Kick/Snare/Crash + BarTracker
    + Streaming Chroma/Bass/VAD).

    Fortschritt 0→100 % für den Onset-Loop.

    finished-Dict:
        jsonl_path, n_kicks, n_snares, n_crashes,
        kicks, snares, crashes, bar_times, bpm,
        chroma_data  — list[{"t": float, "chroma": list[float]}] pro Beat
        bass_data    — list[{"t": float, "chroma": list[float], "rhythm": float}] pro Takt
        vocal_data   — list[{"t": float, "active": bool, "rms": float}] pro 50ms-Fenster
        sample_rate, seg_start_t, seg_end_t, song_key
    """

    progress        = pyqtSignal(float)   # 0.0–1.0
    finished        = pyqtSignal(object)  # dict mit Ergebnissen
    error           = pyqtSignal(str)
    sim_started     = pyqtSignal(float)   # wall-clock time.monotonic() wenn Audio startet
    # Live-Signale (t_rel = Sekunden relativ zu seg_start_t)
    kick_detected   = pyqtSignal(float)
    snare_detected  = pyqtSignal(float)
    crash_detected  = pyqtSignal(float)
    bar_detected    = pyqtSignal(int, float, float)  # (bar_num, t_rel, bpm)
    anchor_matched  = pyqtSignal(object)             # anchor dict mit t_detected

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
        grundrhythmus: dict | None = None,
        realtime: bool = False,
        anchors: list | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._wav_path      = wav_path
        self._seg_start_t   = seg_start_t
        self._seg_end_t     = seg_end_t
        self._song_id       = song_id
        self._song_name     = song_name
        self._bpm           = bpm
        self._output_jsonl  = output_jsonl
        self._song_key      = song_key
        self._grundrhythmus = grundrhythmus
        self._realtime      = realtime
        self._anchors       = anchors or []
        self._sd            = None   # sounddevice-Modul, gesetzt sobald sd.play() läuft

    def stop_audio(self) -> None:
        """Stoppt den sounddevice-Playback sofort (aufrufbar von außen)."""
        sd = self._sd
        if sd is not None:
            try:
                sd.stop()
            except Exception:
                pass

    # ── Haupt-Loop ────────────────────────────────────────────────────────────

    def run(self) -> None:
        try:
            self._run_inner()
        except Exception as exc:
            self.error.emit(str(exc))

    def _run_inner(self) -> None:
        import soundfile as sf
        from detection.beat_detector import (
            OnsetDetector, _CrashDetector, CH_GUITAR, CH_BASS, CH_LEAD_VOCAL,
        )
        from detection.bar_tracker import BarTracker
        from detection.chroma_extractor import StreamingChromaExtractor
        from detection.anchor_matcher import AnchorMatcher

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

        import time as _time

        # Setup BEVOR Audio startet — sonst driftet Logging gegenueber Audio

        # Streaming Feature-Extraktoren
        guitar_extractor = StreamingChromaExtractor(
            sample_rate=sr,
            window_sec=0.5,
            use_cqt=False,
        )
        bar_sec = max(2.0, 4.0 * 60.0 / self._bpm) if self._bpm > 0 else 2.5
        bass_extractor = StreamingChromaExtractor(
            sample_rate=sr,
            window_sec=min(bar_sec * 1.2, 3.0),
            target_sr=8_000,
            bp_low=30.0,
            bp_high=300.0,
            use_cqt=True,
            fmin_hz=32.703,
        )

        # Detektor + BarTracker + AnchorMatcher (AnchorMatcher loggt Ankerliste)
        detector = OnsetDetector(sample_rate=sr)
        tracker = BarTracker(
            bpm=self._bpm,
            seg_start_t=self._seg_start_t,
            seg_end_t=self._seg_end_t,
            grundrhythmus=self._grundrhythmus,
        )
        matcher = AnchorMatcher(
            anchors=self._anchors,
            bpm=self._bpm,
            seg_start_t=self._seg_start_t,
            sample_rate=sr,
            block_size=BLOCK_SIZE,
        ) if self._anchors else None

        kicks:   list[float] = []
        snares:  list[float] = []
        crashes: list[tuple[float, float]] = []
        blocks_done  = 0
        chroma_data: list[dict] = []
        bass_data:   list[dict] = []
        _last_n_bars = 0
        vocal_buf:   list[np.ndarray] = []
        _crash_rms_max = 0.0

        # ── Segment komplett in RAM laden — ein Seek, danach kein Datei-I/O mehr ─
        # Auf >4 GB WAV mit ungültigem Size-Header löst jeder sf.SoundFile.seek()
        # einen linearen Scan von Byte 0 aus (~30–60 s bei HDD). Lösung: Segment
        # einmalig laden; alle Block-Iterationen und Audio-Playback nutzen RAM.
        _sd_playing = False
        _stereo_buf = None
        _wall_start = 0.0

        _log(f"[SIM] Lade Segment in RAM ({total_frames} Frames, ~{int(total_frames * wav_ch * 4 / 1024 / 1024)} MB) ...")
        with sf.SoundFile(self._wav_path) as _wav_f:
            _wav_f.seek(start_sample)
            raw_all = _wav_f.read(total_frames, dtype="float32", always_2d=True)
        seg_frames = raw_all.shape[0]
        _log(f"[SIM] Segment geladen: {seg_frames} Frames, {raw_all.shape[1]} Kanäle")

        # ── Echtzeit-Audio starten (aus bereits geladenem Buffer — kein Seek mehr) ──
        if self._realtime:
            try:
                import sounddevice as _sd_mod
                self._sd = _sd_mod
                ch_l = min(16, raw_all.shape[1] - 1)
                ch_r = min(17, raw_all.shape[1] - 1)
                _stereo_buf = np.ascontiguousarray(raw_all[:, [ch_l, ch_r]])
                _sd_mod.play(_stereo_buf, sr, device="pulse", blocksize=4096)
                _sd_playing = True
                _wall_start = _time.monotonic()
                self.sim_started.emit(_wall_start)
                _log("[SIM] Echtzeit-Modus: Audio gestartet")
            except Exception as exc:
                self._sd = None
                _wall_start = _time.monotonic()
                _log(f"[SIM] Audio-Playback fehlgeschlagen: {exc}")

        # ── JSONL schreiben + Blöcke aus RAM verarbeiten (kein Datei-I/O) ─────
        self._output_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with open(self._output_jsonl, "w", encoding="utf-8") as jf:
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

            blk_pos = 0
            while blk_pos < seg_frames and not self.isInterruptionRequested():
                blk_end = min(blk_pos + BLOCK_SIZE, seg_frames)
                block   = raw_all[blk_pos:blk_end]
                if block.shape[0] == 0:
                    break
                blk_pos = blk_end

                t_mid = blocks_done * BLOCK_SIZE / sr + (block.shape[0] / 2) / sr

                # ── Streaming Feature-Extraktoren befüllen ────────────────────
                # Zuerst befüllen, dann Onset-Detection: der Buffer enthält das
                # aktuelle Audio wenn get_chroma() beim Beat-Event aufgerufen wird.
                if block.shape[1] > CH_GUITAR:
                    guitar_extractor.push_block(block[:, CH_GUITAR])
                if block.shape[1] > CH_BASS:
                    bass_extractor.push_block(block[:, CH_BASS])
                if block.shape[1] > CH_LEAD_VOCAL:
                    vocal_buf.append(block[:, CH_LEAD_VOCAL].copy())

                # Diagnosewert: max OH-RMS (signed, ohne Highpass)
                if block.shape[1] > 14:
                    oh_diag = 0.5 * (block[:, 13].astype(np.float32)
                                     + block[:, 14].astype(np.float32))
                    _crash_rms_max = max(_crash_rms_max, float(np.sqrt(np.mean(oh_diag ** 2))))

                # ── Onset-Detection + BarTracker (streaming) ─────────────────
                for ev in detector.process_block(block):
                    t_abs = self._seg_start_t + t_mid

                    energy_f = float(ev.energy)

                    if ev.type == "kick":
                        kicks.append(t_mid)
                        if len(kicks) <= 5:
                            _log(f"[SIM] kick #{len(kicks)}  t={t_mid:.2f}s  energy={energy_f:.4f}")
                        tracker.process_kick(t_abs, energy=energy_f)
                        chroma_vec = guitar_extractor.get_chroma()
                        if chroma_vec is not None:
                            chroma_data.append({"t": t_abs, "chroma": chroma_vec})
                        self.kick_detected.emit(t_mid)
                        if matcher:
                            _m = matcher.process_kick(t_abs, energy_f)
                            if _m:
                                self.anchor_matched.emit(_m)

                    elif ev.type == "snare":
                        snares.append(t_mid)
                        tracker.process_snare(t_abs, energy=energy_f)
                        chroma_vec = guitar_extractor.get_chroma()
                        if chroma_vec is not None:
                            chroma_data.append({"t": t_abs, "chroma": chroma_vec})
                        self.snare_detected.emit(t_mid)
                        if matcher:
                            _m = matcher.process_snare(t_abs, energy_f)
                            if _m:
                                self.anchor_matched.emit(_m)

                    elif ev.type == "crash":
                        crashes.append((t_mid, energy_f))
                        tracker.process_crash(t_abs, energy=energy_f)
                        self.crash_detected.emit(t_mid)
                        if matcher:
                            _m = matcher.process_crash(t_abs, energy_f)
                            if _m:
                                self.anchor_matched.emit(_m)

                    jf.write(_json.dumps({
                        "t": round(t_mid, 4),
                        "type": ev.type,
                        "data": {"energy": round(float(ev.energy), 6)},
                    }) + "\n")

                # ── Neue Takte prüfen → Bass-Chroma extrahieren ───────────────
                current_bars = tracker.get_latest_bars()
                bpm_now = tracker.get_bpm() or self._bpm
                for i, bar_t in enumerate(current_bars):
                    if i < _last_n_bars:
                        continue
                    bar_num = i + 1
                    bass_chroma = bass_extractor.get_chroma()
                    bass_rhythm = bass_extractor.get_rhythm_score(self._bpm)
                    if bass_chroma is not None:
                        bass_data.append({
                            "t":      bar_t,
                            "chroma": bass_chroma,
                            "rhythm": bass_rhythm,
                        })
                    self.bar_detected.emit(bar_num, bar_t - self._seg_start_t, bpm_now)
                _last_n_bars = len(current_bars)

                # ── AnchorMatcher: RMS-basierte Trigger (Einsatz/Pause) ────────
                if matcher and not matcher.done:
                    _m = matcher.process_block(block, self._seg_start_t + t_mid)
                    if _m:
                        self.anchor_matched.emit(_m)

                blocks_done += 1
                if blocks_done % 50 == 0:
                    self.progress.emit(min(0.99, blk_pos / max(1, seg_frames)))
                if blocks_done % 200 == 0:
                    _log(f"[SIM] ♥ {blocks_done} Blöcke  t={t_mid:.0f}s  kicks={len(kicks)}  snares={len(snares)}")

                # ── Echtzeit-Throttle ─────────────────────────────────────────
                if self._realtime:
                    audio_done = blocks_done * BLOCK_SIZE / sr
                    wall_elapsed = _time.monotonic() - _wall_start
                    sleep_s = audio_done - wall_elapsed
                    if sleep_s > 0.001:
                        _time.sleep(sleep_s)

        del raw_all  # ~1 GB Segment-Buffer freigeben

        # ── Abbruch-Cleanup ───────────────────────────────────────────────────
        if self.isInterruptionRequested():
            self.stop_audio()
            return

        # ── Vokal-VAD (fensterweise RMS — zustandslos → am Ende = live-identisch) ──
        vocal_data: list[dict] = []
        if vocal_buf:
            try:
                from chroma_viz import extract_vocal_activity
                vocal_data = extract_vocal_activity(
                    np.concatenate(vocal_buf),
                    sample_rate=sr,
                    seg_start_t=self._seg_start_t,
                )
                n_active = sum(1 for e in vocal_data if e["active"])
                print(
                    f"[SIM] Vocal VAD: {len(vocal_data)} Fenster, "
                    f"{n_active} aktiv ({100*n_active//max(1,len(vocal_data))} %)",
                    file=sys.stderr,
                )
            except Exception as e:
                print(f"[SIM] Vocal VAD fehlgeschlagen: {e}", file=sys.stderr)

        # ── Finale Taktgitter-Berechnung (letzte Events einbeziehen) ─────────
        tracker.finalize()
        bar_times_final = tracker.get_latest_bars()
        bpm_final       = tracker.get_bpm()

        # Verbleibende Takte nach finalize() → Bass-Chroma für letzten Takt
        for bar_t in bar_times_final[_last_n_bars:]:
            bass_chroma = bass_extractor.get_chroma()
            bass_rhythm = bass_extractor.get_rhythm_score(self._bpm)
            if bass_chroma is not None:
                bass_data.append({
                    "t":      bar_t,
                    "chroma": bass_chroma,
                    "rhythm": bass_rhythm,
                })

        print(
            f"[SIM] Fertig: {blocks_done} Blöcke, "
            f"{len(kicks)} Kicks, {len(snares)} Snares, "
            f"{len(chroma_data)} Guitar-Chroma, "
            f"{len(bass_data)} Bass-Takte "
            f"→ {self._output_jsonl.name}",
            file=sys.stderr,
        )
        print(
            f"[SIM] Crashes: {len(crashes)} erkannt  "
            f"(threshold RMS >{_CrashDetector.CRASH_RMS_MIN:.4f}, "
            f"raw OH >{_CrashDetector.OH_RAW_RMS_MIN:.4f}, "
            f"max OH-RMS im Segment: {_crash_rms_max:.4f})",
            file=sys.stderr,
        )

        # Playback stoppen falls noch aktiv (normalerweise bereits ausgelaufen)
        self.stop_audio()

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
            # Streaming Features (Prime Directive: kein Batch-HPSS mehr)
            "chroma_data": chroma_data,   # Guitar-Chroma pro Beat
            "bass_data":   bass_data,     # Bass-Chroma+Rhythmus pro Takt
            "vocal_data":  vocal_data,    # Vokal-VAD pro 50ms-Fenster
            "sample_rate": sr,
            "seg_start_t": self._seg_start_t,
            "seg_end_t":   self._seg_end_t,
            "song_key":    self._song_key,
        })
