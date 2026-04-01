"""simulator.py — Offline-Simulation der Live-Audio-Erkennung.

Spielt einen Song-Abschnitt aus einer 18-Kanal-WAV-Datei durch denselben
BeatDetector + AudioHMM-Algorithmus wie der Live-Betrieb und gibt Beat-
und Positionsereignisse aus.  Dient zur Nachbereitung und Parameter-
Optimierung nach der Probe.

Verwendung::

    worker = SimulatorWorker(
        wav_path=Path("recording.wav"),
        seg_start_t=0.0, seg_end_t=220.0,
        sample_rate=48000, n_channels=18,
        song_id="5Ij0Ns", bpm=120.0,
        ref_db_path=Path("live/data/reference.db"),
    )
    worker.beat.connect(on_beat)
    worker.position.connect(on_position)
    worker.finished.connect(on_done)
    worker.start()
"""
from __future__ import annotations

import os
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
    """QThread der die Live-Erkennungspipeline offline auf einer WAV-Datei ausführt."""

    beat     = pyqtSignal(object)        # SimBeat
    snare    = pyqtSignal(float)         # t (Snare-Onset)
    position = pyqtSignal(object)        # SimPosition
    progress = pyqtSignal(float)         # 0.0–1.0
    finished = pyqtSignal(list, list)    # beats: list[SimBeat], positions: list[SimPosition]
    error    = pyqtSignal(str)

    def __init__(
        self,
        wav_path: Path,
        seg_start_t: float,
        seg_end_t: float,
        sample_rate: int,
        n_channels: int,
        song_id: str,
        bpm: float,
        ref_db_path: Optional[Path] = None,
        use_hmm: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._wav_path    = wav_path
        self._seg_start_t = seg_start_t
        self._seg_end_t   = seg_end_t
        self._sr          = sample_rate
        self._n_ch        = n_channels
        self._song_id     = song_id
        self._bpm         = bpm
        self._ref_db_path = ref_db_path
        self._use_hmm     = use_hmm

    def set_use_hmm(self, enabled: bool) -> None:
        """Kann vom Main-Thread während der Simulation aufgerufen werden."""
        self._use_hmm = enabled

    # ── Haupt-Loop ────────────────────────────────────────────────────────────

    def run(self) -> None:
        try:
            self._run_inner()
        except Exception as exc:
            self.error.emit(str(exc))

    def _run_inner(self) -> None:
        import soundfile as sf

        # Server-Pfad in sys.path eintragen damit die Live-Module importierbar sind
        rr_dir     = os.path.dirname(os.path.abspath(__file__))
        repo_root  = Path(rr_dir).parent.parent
        server_dir = str(repo_root / "live")
        if server_dir not in sys.path:
            sys.path.insert(0, server_dir)

        from server.audio.beat_detector import BeatDetector
        from server.audio.hmm import AudioHMM
        from server.audio.reference_db import ReferenceDB

        # ── WAV-Datei vorab prüfen ────────────────────────────────────────────
        with sf.SoundFile(self._wav_path) as f:
            wav_sr     = f.samplerate
            wav_frames = f.frames
            wav_ch     = f.channels

        # Tatsächliche Sample-Rate der WAV-Datei verwenden (statt Session-Wert)
        # damit Seek-Position und Block-Zeitstempel stimmen.
        sr = wav_sr

        # Lese-Parameter (mit echter SR berechnet)
        start_sample = int(self._seg_start_t * sr)
        end_sample   = int(self._seg_end_t   * sr)
        # Sicherstellen dass end_sample in Grenzen liegt
        end_sample   = min(end_sample, wav_frames)
        start_sample = min(start_sample, wav_frames)

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
                f"  → start_sample={start_sample} ≥ end_sample={end_sample}\n\n"
                f"Prüfe ob die WAV-Datei vollständig ist und das Segment "
                f"nicht über das Dateiende hinausragt."
            )
            print(f"[SIM] FEHLER: {msg}", file=sys.stderr)
            self.error.emit(msg)
            return

        total_frames = end_sample - start_sample

        # BeatDetector — mit echter SR der WAV kalibrieren
        beat_det = BeatDetector(sample_rate=sr, initial_bpm=self._bpm)

        # HMM nur laden wenn initial aktiviert UND reference.db vorhanden.
        # Die DB wird im Worker-Thread geöffnet; SQLite-Locking-Fehler werden
        # abgefangen damit die Beat-Detection trotzdem läuft.
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

        # Ring-Buffer für Stereo-Mix (wie AudioProcess)
        ring_buffer:    list[np.ndarray] = []
        snapshot_pending = False

        beats:     list[SimBeat]     = []
        positions: list[SimPosition] = []

        blocks_done = 0

        with sf.SoundFile(self._wav_path) as f:
            f.seek(start_sample)
            actual_pos = f.tell()
            remaining = end_sample - actual_pos
            print(
                f"[SIM] seek({start_sample}) → tell()={actual_pos}  "
                f"remaining={remaining}  interrupted={self.isInterruptionRequested()}",
                file=sys.stderr,
            )

            while remaining > 0 and not self.isInterruptionRequested():
                to_read = min(BLOCK_SIZE, remaining)
                block = f.read(to_read, dtype="float32", always_2d=True)
                if block.shape[0] == 0:
                    break
                remaining -= block.shape[0]

                # Block-Zeit relativ zum Simulationsstart (immer ab 0)
                t_block = blocks_done * BLOCK_SIZE / sr

                # Kanal-Anzahl auf erwartete Kanalzahl angleichen
                if block.shape[1] < wav_ch:
                    pad = np.zeros((block.shape[0], wav_ch - block.shape[1]),
                                   dtype=np.float32)
                    block = np.concatenate([block, pad], axis=1)

                # ── Pfad 1: Beat-Detection ────────────────────────────────────
                beat_events, snare_onset = beat_det.process_block(block)
                t_block_mid = t_block + (block.shape[0] / 2) / sr
                if snare_onset:
                    self.snare.emit(t_block_mid)
                for ev in beat_events:
                    sim_beat = SimBeat(
                        t=t_block_mid,
                        beat_num=ev.beat_num,
                        bpm=ev.bpm,
                        is_downbeat=ev.is_downbeat,
                        is_fill=ev.is_fill,
                        trigger=ev.trigger,
                    )
                    beats.append(sim_beat)
                    self.beat.emit(sim_beat)
                    if ev.is_downbeat:
                        snapshot_pending = True

                # ── Pfad 2: Stereo-Mix → Ring-Buffer ─────────────────────────
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
                            from server.audio.fingerprint import extract_features_from_array
                            chroma, mfcc, onset, _ = extract_features_from_array(
                                mono, sr=sr, bpm=beat_det.bpm or self._bpm
                            )
                            state = hmm.update(chroma, mfcc, onset)
                            if state.song_id:
                                sim_pos = SimPosition(
                                    t=t_block,
                                    song_id=state.song_id,
                                    bar_num=state.bar_num,
                                    part_name=state.part_name,
                                    confidence=state.confidence,
                                    is_frozen=state.is_frozen,
                                    is_part_consensus=state.is_part_consensus,
                                )
                                positions.append(sim_pos)
                                self.position.emit(sim_pos)
                        except Exception:
                            pass  # Feature-Extraktion fehlgeschlagen → ignorieren

                blocks_done += 1

                if blocks_done % 100 == 0:
                    print(
                        f"[SIM] Block {blocks_done}: {len(beats)} Beats bisher  "
                        f"beat_phase={beat_det._beat_phase:.0f}/{beat_det._beat_period:.0f}",
                        file=sys.stderr,
                    )
                if blocks_done % 50 == 0:
                    self.progress.emit(
                        min(1.0, (blocks_done * BLOCK_SIZE) / max(1, total_frames))
                    )

        print(
            f"[SIM] Fertig: {blocks_done} Blöcke, {len(beats)} Beats, "
            f"{len(positions)} Positionen  "
            f"(interrupted={self.isInterruptionRequested()})",
            file=sys.stderr,
        )
        self.progress.emit(1.0)
        self.finished.emit(beats, positions)
