"""simulator.py — Offline-Simulation der Live-Audio-Erkennung.

Läuft so schnell wie möglich (kein Echtzeit-Throttling), schreibt alle
erkannten Events als JSONL-Datei und emittiert dann `finished`.
Die Darstellung erfolgt nachgelagert über SimMonitorDialog.load_jsonl().

JSONL-Format (eine JSON-Zeile pro Event, t relativ zu seg_start_t):
    {"t": 0.0,  "type": "sim_start",  "data": {"song_id": …, "bpm": …, …}}
    {"t": 1.23, "type": "beat",       "data": {"beat_num": 1, "bpm": 120.5, …}}
    {"t": 1.23, "type": "snare",      "data": {}}
    {"t": 4.10, "type": "position",   "data": {"bar_num": 2, "part_name": …, …}}
"""
from __future__ import annotations

import json as _json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

# Block-Größe und Konfiguration identisch mit AudioProcess
BLOCK_SIZE      = 2048
SAMPLE_RATE     = 48_000
CHANNEL_MIX_L   = 16
CHANNEL_MIX_R   = 17
SNAPSHOT_MIN_SEC = 0.5
RING_MAX_BLOCKS  = SAMPLE_RATE // BLOCK_SIZE   # ~23 Blöcke/s


# ---------------------------------------------------------------------------
# Datenstrukturen
# ---------------------------------------------------------------------------

@dataclass
class SimBeat:
    """Ein Beat-Ereignis aus der Simulation."""
    t: float           # Sekunden relativ zum Segment-Start
    beat_num: int      # 1–4
    bpm: float
    is_downbeat: bool
    is_fill: bool
    trigger: str = "timer"   # "kick" | "overhead" | "timer"


@dataclass
class SimPosition:
    """Eine Takt-Positionsschätzung aus der Simulation."""
    t: float           # Sekunden relativ zum Segment-Start
    song_id: str
    bar_num: int
    part_name: str
    confidence: float
    is_frozen: bool
    is_part_consensus: bool = False


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class SimulatorWorker(QThread):
    """QThread der die Live-Erkennungspipeline offline auf einer WAV-Datei ausführt.

    Läuft als schnelles Batch-Processing und schreibt alle Events in eine
    JSONL-Datei.  Keine Echtzeit-Signale mehr — Darstellung erfolgt über
    SimMonitorDialog.load_jsonl() nach Abschluss.
    """

    progress = pyqtSignal(float)    # 0.0–1.0
    finished = pyqtSignal(object)   # dict: {jsonl_path, n_beats_all, n_downbeats,
                                    #        n_positions, beats, positions}
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
        ref_db_path: Optional[Path] = None,
        use_hmm: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._wav_path     = wav_path
        self._seg_start_t  = seg_start_t
        self._seg_end_t    = seg_end_t
        self._sr           = sample_rate
        self._n_ch         = n_channels
        self._song_id      = song_id
        self._song_name    = song_name
        self._bpm          = bpm
        self._output_jsonl = output_jsonl
        self._ref_db_path  = ref_db_path
        self._use_hmm      = use_hmm

    # ── Haupt-Loop ────────────────────────────────────────────────────────────

    def run(self) -> None:
        try:
            self._run_inner()
        except Exception as exc:
            self.error.emit(str(exc))

    def _run_inner(self) -> None:
        import soundfile as sf

        from detection.beat_detector import BeatDetector
        from detection.hmm import AudioHMM
        from detection.reference_db import ReferenceDB

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
            f"→  start_sample={start_sample}  end_sample={end_sample}  "
            f"remaining={end_sample - start_sample}",
            file=sys.stderr,
        )

        if start_sample >= end_sample:
            msg = (
                f"Kein Audio zu verarbeiten:\n"
                f"  WAV: {wav_frames} Frames @ {wav_sr} Hz "
                f"({wav_frames/wav_sr:.1f} s, {wav_ch} Kanäle)\n"
                f"  Segment: {self._seg_start_t:.1f} s – {self._seg_end_t:.1f} s\n"
                f"  → start_sample={start_sample} ≥ end_sample={end_sample}"
            )
            self.error.emit(msg)
            return

        total_frames = end_sample - start_sample

        # ── Algorithmen initialisieren ────────────────────────────────────────
        beat_det = BeatDetector(sample_rate=sr, initial_bpm=self._bpm)

        hmm: Optional[AudioHMM] = None
        if self._use_hmm and self._ref_db_path and self._ref_db_path.exists():
            try:
                ref_db = ReferenceDB(self._ref_db_path)
                hmm = AudioHMM(ref_db)
                hmm.load_all_states()
                hmm.set_active_song(self._song_id)
            except Exception as exc:
                print(f"[SIM] HMM-Init fehlgeschlagen ({exc}) — HMM deaktiviert",
                      file=sys.stderr)
                hmm = None
                self._use_hmm = False

        # ── Verarbeitungs-Loop → JSONL schreiben ─────────────────────────────
        ring_buffer:    list[np.ndarray] = []
        snapshot_pending = False
        beats:     list[SimBeat]     = []
        snares:    list[float]       = []
        positions: list[SimPosition] = []
        blocks_done = 0

        self._output_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with (
            sf.SoundFile(self._wav_path) as wav_f,
            open(self._output_jsonl, "w", encoding="utf-8") as jf,
        ):
            # Header
            jf.write(_json.dumps({
                "t": 0.0,
                "type": "sim_start",
                "data": {
                    "song_id":    self._song_id,
                    "song_name":  self._song_name,
                    "bpm":        self._bpm,
                    "seg_start_t": self._seg_start_t,
                    "seg_end_t":   self._seg_end_t,
                    "wav":        str(self._wav_path),
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

                t_block     = blocks_done * BLOCK_SIZE / sr
                t_block_mid = t_block + (block.shape[0] / 2) / sr

                # Kanal-Padding falls WAV weniger Kanäle hat als erwartet
                if block.shape[1] < wav_ch:
                    pad = np.zeros(
                        (block.shape[0], wav_ch - block.shape[1]), dtype=np.float32
                    )
                    block = np.concatenate([block, pad], axis=1)

                # ── Beat-Detection ────────────────────────────────────────────
                beat_events, snare_onset = beat_det.process_block(block)

                if snare_onset:
                    snares.append(t_block_mid)
                    jf.write(_json.dumps({"t": t_block_mid, "type": "snare", "data": {}}) + "\n")

                for ev in beat_events:
                    sb = SimBeat(
                        t=t_block_mid,
                        beat_num=ev.beat_num,
                        bpm=ev.bpm,
                        is_downbeat=ev.is_downbeat,
                        is_fill=ev.is_fill,
                        trigger=ev.trigger,
                    )
                    beats.append(sb)
                    jf.write(_json.dumps({
                        "t": t_block_mid,
                        "type": "beat",
                        "data": {
                            "beat_num":    ev.beat_num,
                            "bpm":         ev.bpm,
                            "is_downbeat": ev.is_downbeat,
                            "is_fill":     ev.is_fill,
                            "trigger":     ev.trigger,
                            "vox_rms":     round(beat_det.vox_rms, 6),
                        },
                    }) + "\n")
                    if ev.is_downbeat:
                        snapshot_pending = True

                # ── Stereo-Mix → Ring-Buffer ──────────────────────────────────
                if block.shape[1] > CHANNEL_MIX_R:
                    stereo = block[:, [CHANNEL_MIX_L, CHANNEL_MIX_R]]
                else:
                    stereo = block[:, :min(2, block.shape[1])]
                ring_buffer.append(stereo)
                if len(ring_buffer) > RING_MAX_BLOCKS:
                    ring_buffer.pop(0)

                # ── HMM-Snapshot auf Downbeat ─────────────────────────────────
                if snapshot_pending and hmm is not None and self._use_hmm:
                    snapshot_pending = False
                    audio = np.concatenate(ring_buffer, axis=0)
                    mono  = np.mean(audio, axis=1).astype(np.float32)
                    if len(mono) >= int(sr * SNAPSHOT_MIN_SEC):
                        try:
                            from detection.fingerprint import extract_features_from_array
                            chroma, mfcc, onset, _ = extract_features_from_array(
                                mono, sr=sr, bpm=beat_det.bpm or self._bpm
                            )
                            state = hmm.update(
                                chroma, mfcc, onset,
                                elapsed_sec=beat_det.elapsed_sec,
                            )
                            if state.song_id:
                                sp = SimPosition(
                                    t=t_block,
                                    song_id=state.song_id,
                                    bar_num=state.bar_num,
                                    part_name=state.part_name,
                                    confidence=state.confidence,
                                    is_frozen=state.is_frozen,
                                    is_part_consensus=state.is_part_consensus,
                                )
                                positions.append(sp)
                                jf.write(_json.dumps({
                                    "t": t_block,
                                    "type": "position",
                                    "data": {
                                        "song_id":          state.song_id,
                                        "bar_num":          state.bar_num,
                                        "part_name":        state.part_name,
                                        "confidence":       state.confidence,
                                        "is_frozen":        state.is_frozen,
                                        "is_part_consensus": state.is_part_consensus,
                                    },
                                }) + "\n")
                        except Exception:
                            pass

                blocks_done += 1

                if blocks_done % 50 == 0:
                    self.progress.emit(
                        min(1.0, (blocks_done * BLOCK_SIZE) / max(1, total_frames))
                    )

        print(
            f"[SIM] Fertig: {blocks_done} Blöcke, {len(beats)} Beats, "
            f"{len(positions)} Positionen → {self._output_jsonl.name}",
            file=sys.stderr,
        )
        self.progress.emit(1.0)
        self.finished.emit({
            "jsonl_path":  self._output_jsonl,
            "n_beats_all": len(beats),
            "n_downbeats": sum(1 for b in beats if b.is_downbeat),
            "n_positions": len(positions),
            "beats":       beats,
            "snares":      snares,
            "positions":   positions,
        })
