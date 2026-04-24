"""band_activity.py — Streaming Band-Aktivitätserkennung.

Erkennt wann die Band zu spielen beginnt (band_starts) oder aufhört (band_stops).

Prime Directive: process_block() ist streaming — kein Lookahead, kein Batch-Zugriff.
Identisch verwendbar in SimulatorWorker und AudioProcess.
"""
from __future__ import annotations

import numpy as np

# Relevante Kanäle (0-basiert): CH01, CH04, CH05, CH06, CH09, CH10, CH14
BAND_CHANNELS = (0, 3, 4, 5, 8, 9, 13)

_SILENT = 0
_ACTIVE = 1


class BandActivityDetector:
    """Streaming-Detektor für Band-Aktivität.

    Zustandsmaschine SILENT ↔ ACTIVE:
      SILENT → ACTIVE: >= start_ratio der Kanäle über threshold → "band_starts"
      ACTIVE → SILENT: <= stop_ratio der Kanäle aktiv, stop_hold_blocks Blöcke lang
                        → "band_stops" (Zeitstempel des ersten stillen Blocks)

    Parameters
    ----------
    threshold_rms:
        RMS-Schwellwert pro Kanal. Kanal gilt als aktiv wenn RMS > threshold_rms.
    start_ratio:
        Anteil aktiver Kanäle ab dem "band_starts" emittiert wird (0.0–1.0).
    stop_ratio:
        Anteil aktiver Kanäle unter dem der Stop-Zähler läuft (0.0–1.0).
    stop_hold_blocks:
        Anzahl aufeinanderfolgender Blöcke unter stop_ratio vor "band_stops".
    """

    def __init__(
        self,
        threshold_rms: float = 0.005,
        start_ratio: float = 0.70,
        stop_ratio: float = 0.20,
        stop_hold_blocks: int = 3,
    ) -> None:
        self._threshold   = threshold_rms
        self._start_ratio = start_ratio
        self._stop_ratio  = stop_ratio
        self._hold        = stop_hold_blocks

        self._state        = _SILENT
        self._silent_count = 0
        self._silent_since = 0.0

    def process_block(
        self,
        block_18ch: np.ndarray,
        t_abs: float,
    ) -> list[tuple[str, float]]:
        """Verarbeitet einen Block und gibt Events zurück.

        Parameters
        ----------
        block_18ch:
            Shape (frames, channels). Kanäle jenseits der verfügbaren werden
            übersprungen — der Detektor ist robust gegenüber WAVs mit < 18 Kanälen.
        t_abs:
            Absolute WAV-Zeit des Block-Mittelpunkts (Sekunden).

        Returns
        -------
        Liste von (event_type, t_abs)-Tupeln. Leer wenn kein Zustandswechsel.
        """
        if block_18ch.ndim != 2:
            return []
        n_ch = block_18ch.shape[1]

        n_active  = 0
        n_checked = 0
        for ch in BAND_CHANNELS:
            if ch >= n_ch:
                continue
            n_checked += 1
            rms = float(np.sqrt(np.mean(block_18ch[:, ch] ** 2)))
            if rms > self._threshold:
                n_active += 1

        if n_checked == 0:
            return []

        ratio  = n_active / n_checked
        events: list[tuple[str, float]] = []

        if self._state == _SILENT:
            if ratio >= self._start_ratio:
                self._state        = _ACTIVE
                self._silent_count = 0
                events.append(("band_starts", t_abs))
        else:  # _ACTIVE
            if ratio <= self._stop_ratio:
                if self._silent_count == 0:
                    self._silent_since = t_abs
                self._silent_count += 1
                if self._silent_count >= self._hold:
                    self._state        = _SILENT
                    self._silent_count = 0
                    events.append(("band_stops", self._silent_since))
            else:
                self._silent_count = 0

        return events

    def reset(self) -> None:
        """Setzt den Zustand zurück (z.B. bei Songwechsel)."""
        self._state        = _SILENT
        self._silent_count = 0
        self._silent_since = 0.0
