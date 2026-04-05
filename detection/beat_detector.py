"""Onset-Erkennung für Kick (CH09) und Snare (CH10) aus XR18-Audio.

Detektionsprinzip: Band-gefilterter ODF auf Sub-Window-Ebene
------------------------------------------------------------
Zwei Verbesserungen gegenüber einfachem Block-RMS-Threshold:

1. **Frequenzfilter** (IIR Butterworth, scipy):
   - Kick:  Tiefpass  250 Hz  — isoliert Kick-Body, verwirft Gitarren-/Snare-Bleed
   - Snare: Bandpass 200–5 kHz — verwirft Kick-Bleed unter 200 Hz

2. **Sub-Window ODF** (positive erste Ableitung auf 5.3 ms-Ebene):
   - Block (2048 Samples = 42.7 ms) wird in 8 × 256-Sample-Sub-Fenster geteilt
   - ODF = max(0, rms[n] - rms[n-1]) pro Sub-Window
   - Peak-ODF über alle Sub-Windows ist das Detektor-Merkmal
   - Letztes Sub-Window des Vorgängerblocks wird für die Blockgrenze mitgeführt
   - Effektive Zeitauflösung: 5.3 ms statt 42.7 ms

Kein PLL, kein BPM-Tracking, kein Beat-Counting, kein HMM.

Kanal-Indizes (0-basiert im XR18 USB-Stream):
  8  = CH09 Kick
  9  = CH10 Snare
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

log = logging.getLogger("detection.onset")

# ---------------------------------------------------------------------------
# Kanal-Indizes (0-basiert, XR18 USB)
# ---------------------------------------------------------------------------
CH_KICK  = 8
CH_SNARE = 9

# Absoluter Peak-ODF-Boden auf Sub-Window-Ebene (256 Samples = 5.3 ms).
# Echter Kick: Sub-Window-RMS-Sprung von ~0.005 → 0.15 → ODF ≈ 0.145
# Rauschen / Bleed nach Tiefpass: ODF-Schwankung typ. < 0.002
ONSET_MIN_ODF = 4e-3

# Sub-Window-Größe in Samples (5.3 ms @ 48 kHz)
SUB_WIN = 256

# Fester Cooldown nach Onset-Erkennung (Sekunden)
KICK_COOLDOWN_SEC  = 0.220
SNARE_COOLDOWN_SEC = 0.280


# ---------------------------------------------------------------------------
# Datenstruktur
# ---------------------------------------------------------------------------

@dataclass
class OnsetEvent:
    """Erkanntes Onset-Ereignis."""
    type: str       # "kick" | "snare"
    energy: float   # Peak-ODF-Wert beim Onset (Energieanstieg)


# ---------------------------------------------------------------------------
# Per-Kanal Onset-Detektor
# ---------------------------------------------------------------------------

class ChannelOnsetDetector:
    """ODF-basierter Onset-Detektor mit Frequenzfilter + Sub-Window-Auflösung.

    Verarbeitung pro Block:
      1. IIR-Filter (optional): Isoliert relevantes Frequenzband
      2. Sub-Window RMS: 8 × 256-Sample-Fenster pro 2048-Sample-Block
      3. Peak-ODF: maximaler positiver Energieanstieg über Sub-Windows
      4. Adaptiver Schwellwert: Median der ODF-History × Faktor
    """

    def __init__(
        self,
        threshold_factor: float = 2.5,
        history_len: int = 50,
        cooldown_samples: int = 9600,
        filter_sos: Optional[np.ndarray] = None,
    ) -> None:
        self._threshold_factor = threshold_factor
        self._odf_hist: deque[float] = deque(maxlen=history_len)
        self._prev_sub_rms: float = 0.0
        self._cooldown_left: int = 0
        self._cooldown_samples = cooldown_samples

        # IIR-Filter in sos-Form (scipy) oder None für ungefiltert
        self._sos: Optional[np.ndarray] = filter_sos
        if filter_sos is not None:
            # Kausal-Anfangszustand = 0 (Stille am Segmentanfang)
            self._sos_zi: np.ndarray = np.zeros((filter_sos.shape[0], 2))
        else:
            self._sos_zi = np.empty((0, 2))

    def _apply_filter(self, block: np.ndarray) -> np.ndarray:
        """Kausal-IIR-Filterung mit persistentem Zustand (für Streaming)."""
        if self._sos is None:
            return block
        from scipy.signal import sosfilt
        y, self._sos_zi = sosfilt(self._sos, block, zi=self._sos_zi)
        return y

    @staticmethod
    def _sub_window_rms(block: np.ndarray, w: int = SUB_WIN) -> np.ndarray:
        """RMS-Energie pro Sub-Window der Größe w Samples."""
        b = block.astype(np.float32)
        n = (len(b) // w) * w
        return np.sqrt(np.mean(b[:n].reshape(-1, w) ** 2, axis=1))

    def process(self, block: np.ndarray) -> tuple[bool, float]:
        """Verarbeitet einen Mono-Audio-Block.

        Returns
        -------
        (onset_detected, peak_odf)
        """
        fblock = self._apply_filter(block.astype(np.float32))
        sub_rms = self._sub_window_rms(fblock)

        # ODF über Sub-Windows — Blockgrenze zum Vorgänger mitführen
        all_rms = np.concatenate([[self._prev_sub_rms], sub_rms])
        peak_odf = float(np.max(np.maximum(0.0, np.diff(all_rms))))
        self._prev_sub_rms = float(sub_rms[-1])

        n = len(block)

        # Cooldown — ODF trotzdem in History (für stabilen Median)
        if self._cooldown_left > 0:
            self._cooldown_left -= n
            self._odf_hist.append(peak_odf)
            return False, peak_odf

        self._odf_hist.append(peak_odf)
        if len(self._odf_hist) < 6:
            return False, peak_odf

        median_odf = float(np.median(np.array(self._odf_hist)[:-1]))
        threshold = max(median_odf * self._threshold_factor, ONSET_MIN_ODF)

        if peak_odf > threshold:
            self._cooldown_left = self._cooldown_samples
            return True, peak_odf

        return False, peak_odf

    def reset(self) -> None:
        self._odf_hist.clear()
        self._prev_sub_rms = 0.0
        self._cooldown_left = 0
        if self._sos is not None:
            self._sos_zi[:] = 0.0


# ---------------------------------------------------------------------------
# Frequenzfilter-Fabrik
# ---------------------------------------------------------------------------

def _make_filters(sample_rate: int) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """Butterworth-IIR-Filter für Kick und Snare.

    Returns (kick_sos, snare_sos) oder (None, None) wenn scipy fehlt.
    """
    try:
        from scipy.signal import butter
        nyq = sample_rate / 2.0
        # Kick: Tiefpass 250 Hz — isoliert Kick-Körper, blockiert Gitarre/Snare
        kick_sos = butter(4, 250.0 / nyq, btype="low",  output="sos")
        # Snare: Bandpass 200–5 000 Hz — blockiert Kick-Bleed unter 200 Hz
        snare_sos = butter(4, [200.0 / nyq, 5000.0 / nyq], btype="band", output="sos")
        return kick_sos, snare_sos
    except Exception as exc:
        log.warning("scipy nicht verfügbar — Onset-Detection ohne Frequenzfilter: %s", exc)
        return None, None


# ---------------------------------------------------------------------------
# Onset-Detektor (Kick + Snare)
# ---------------------------------------------------------------------------

class OnsetDetector:
    """Erkennt Kick- und Snare-Onsets aus mehrkanaligem XR18-Audio (48 kHz).

    Gibt pro Block eine Liste von OnsetEvents zurück.
    Kein BPM-Tracking, kein Beat-Counting — nur rohe Impuls-Erkennung.

    Usage::

        detector = OnsetDetector(sample_rate=48_000)

        # Bei jedem Audio-Block (frames, channels):
        events = detector.process_block(indata)
        for ev in events:
            print(ev.type, ev.energy)

        # Reset (neues Segment):
        detector.reset()
    """

    def __init__(self, sample_rate: int = 48_000) -> None:
        self._sr = sample_rate
        kick_cd  = int(KICK_COOLDOWN_SEC  * sample_rate)
        snare_cd = int(SNARE_COOLDOWN_SEC * sample_rate)
        kick_sos, snare_sos = _make_filters(sample_rate)
        self._kick  = ChannelOnsetDetector(
            threshold_factor=2.5,
            history_len=50,
            cooldown_samples=kick_cd,
            filter_sos=kick_sos,
        )
        self._snare = ChannelOnsetDetector(
            threshold_factor=2.2,
            history_len=50,
            cooldown_samples=snare_cd,
            filter_sos=snare_sos,
        )

    def process_block(self, block: np.ndarray) -> list[OnsetEvent]:
        """Verarbeitet einen Audio-Block und gibt Onset-Ereignisse zurück.

        Parameters
        ----------
        block:
            shape (frames, channels), float32.
            Erwartet ≥10 Kanäle (0-basiert, XR18-Belegung).
            Wenn weniger Kanäle vorhanden → Fallback auf Stereo-Mix.
        """
        n_ch = block.shape[1] if block.ndim > 1 else 1

        def _ch(idx: int) -> np.ndarray:
            if n_ch > idx:
                return block[:, idx].astype(np.float32)
            return np.mean(block.astype(np.float32), axis=1)

        events: list[OnsetEvent] = []

        kick_onset, kick_odf = self._kick.process(_ch(CH_KICK))
        if kick_onset:
            events.append(OnsetEvent(type="kick", energy=kick_odf))

        snare_onset, snare_odf = self._snare.process(_ch(CH_SNARE))
        if snare_onset:
            events.append(OnsetEvent(type="snare", energy=snare_odf))

        return events

    def reset(self) -> None:
        """Setzt den Detektor zurück (neues Segment)."""
        self._kick.reset()
        self._snare.reset()
        log.debug("OnsetDetector zurückgesetzt")
