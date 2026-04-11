"""Onset-Erkennung für Kick (CH09) und Snare (CH10) aus XR18-Audio.

Detektionsprinzip: Band-gefilterter ODF auf Sub-Window-Ebene
------------------------------------------------------------
1. **Frequenzfilter** (IIR Butterworth, scipy):
   - Kick:  Tiefpass   250 Hz  — isoliert Kick-Body, verwirft Snare/Gitarren-Bleed
   - Snare: Bandpass 800–9 kHz — verwirft Kick-Bleed (Kick-Energie fällt >500 Hz stark ab)

2. **Sub-Window ODF** (positive erste Ableitung auf 5.3 ms-Ebene):
   - Block (2048 Samples = 42.7 ms) → 8 × 256-Sample-Sub-Fenster
   - Peak-ODF über alle Sub-Windows ist das Detektor-Merkmal
   - Letzter Sub-Window-RMS-Wert wird über Blockgrenzen mitgeführt

3. **Dual-Gate**: Onset nur wenn BEIDE Bedingungen erfüllt:
   - ODF-Peak > adaptiver Schwellwert (Median × Faktor, min. ONSET_MIN_ODF)
   - Mittlerer RMS des gefilterten Signals > ABS_RMS_MIN
   → Verhindert Trigger in quasi-stillen Passagen auch bei niedrigem Median

4. **Silence-Aware Warmup**:
   - Nach ≥ SILENCE_BLOCKS aufeinanderfolgenden stillen Blöcken gilt der
     Detektor als "kalt" (z.B. nach Pause oder Neuansatz des Songs)
   - Der erste ODF-Spike nach der Stille triggert NICHT, damit der adaptive
     Median sich zunächst auf das neue Signalniveau einstellen kann

Kein PLL, kein BPM-Tracking, kein Beat-Counting, kein HMM.

Kanal-Indizes (0-basiert im XR18 USB-Stream):
  8  = CH09 Kick
  9  = CH10 Snare
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

log = logging.getLogger("detection.onset")

# ---------------------------------------------------------------------------
# Kanal-Indizes (0-basiert, XR18 USB)
# ---------------------------------------------------------------------------
CH_KICK   = 8
CH_SNARE  = 9
CH_OH_L   = 13   # Overhead Left  — enthält Crash-Cymbals
CH_OH_R   = 14   # Overhead Right — enthält Crash-Cymbals

# Absoluter ODF-Boden (Sub-Window-Ebene, 256 Samples = 5.3 ms)
ONSET_MIN_ODF = 4e-3

# Sub-Window-Größe in Samples (5.3 ms @ 48 kHz)
SUB_WIN = 256

# Fester Cooldown nach Onset-Erkennung (Sekunden)
KICK_COOLDOWN_SEC  = 0.220
SNARE_COOLDOWN_SEC = 0.280

# Anzahl aufeinanderfolgender "stiller" Blöcke bis Warm-up ausgelöst wird (~0.5 s)
SILENCE_BLOCKS = 12
# ODF-Wert unterhalb dessen ein Block als "still" gilt
SILENCE_ODF_THRESH = 1e-3


# ---------------------------------------------------------------------------
# Datenstruktur
# ---------------------------------------------------------------------------

@dataclass
class OnsetEvent:
    """Erkanntes Onset-Ereignis."""
    type: str       # "kick" | "snare" | "crash"
    energy: float   # Peak-ODF-Wert beim Onset


# ---------------------------------------------------------------------------
# Per-Kanal Onset-Detektor
# ---------------------------------------------------------------------------

class ChannelOnsetDetector:
    """ODF-basierter Onset-Detektor mit Frequenzfilter, Sub-Window-Auflösung,
    Dual-Gate und Silence-Aware Warmup."""

    def __init__(
        self,
        threshold_factor: float = 2.5,
        history_len: int = 50,
        cooldown_samples: int = 9600,
        filter_sos: Optional[np.ndarray] = None,
        abs_rms_min: float = 3e-3,
    ) -> None:
        self._threshold_factor = threshold_factor
        self._abs_rms_min = abs_rms_min
        self._odf_hist: deque[float] = deque(maxlen=history_len)
        self._prev_sub_rms: float = 0.0
        self._cooldown_left: int = 0
        self._cooldown_samples = cooldown_samples

        # Silence tracking: startet im "kalt"-Zustand
        self._silence_count: int = SILENCE_BLOCKS

        # IIR-Filter in sos-Form (scipy) oder None
        self._sos: Optional[np.ndarray] = filter_sos
        if filter_sos is not None:
            self._sos_zi: np.ndarray = np.zeros((filter_sos.shape[0], 2))
        else:
            self._sos_zi = np.empty((0, 2))

    def _apply_filter(self, block: np.ndarray) -> np.ndarray:
        if self._sos is None:
            return block
        from scipy.signal import sosfilt
        y, self._sos_zi = sosfilt(self._sos, block, zi=self._sos_zi)
        return y

    @staticmethod
    def _sub_window_rms(block: np.ndarray, w: int = SUB_WIN) -> np.ndarray:
        b = block.astype(np.float32)
        n = (len(b) // w) * w
        return np.sqrt(np.mean(b[:n].reshape(-1, w) ** 2, axis=1))

    def process(self, block: np.ndarray) -> tuple[bool, float]:
        """Verarbeitet einen Mono-Audio-Block.

        Returns (onset_detected, peak_odf)
        """
        fblock = self._apply_filter(block.astype(np.float32))
        sub_rms = self._sub_window_rms(fblock)

        # Zu kurzer Block (< SUB_WIN Samples) → kein ODF berechenbar
        if sub_rms.size == 0:
            return False, 0.0

        # Peak-ODF über Sub-Windows (Blockgrenze mitführen)
        all_rms = np.concatenate([[self._prev_sub_rms], sub_rms])
        peak_odf = float(np.max(np.maximum(0.0, np.diff(all_rms))))
        mean_rms  = float(np.mean(sub_rms))
        self._prev_sub_rms = float(sub_rms[-1])

        n = len(block)

        # Silence-Tracking: Zähler hoch in Stille, runter bei Signal
        if peak_odf < SILENCE_ODF_THRESH:
            self._silence_count = min(self._silence_count + 1, SILENCE_BLOCKS + 1)
        else:
            self._silence_count = max(0, self._silence_count - 2)

        # Cooldown
        if self._cooldown_left > 0:
            self._cooldown_left -= n
            self._odf_hist.append(peak_odf)
            return False, peak_odf

        self._odf_hist.append(peak_odf)
        if len(self._odf_hist) < 6:
            return False, peak_odf

        # Adaptiver Schwellwert
        median_odf = float(np.median(np.array(self._odf_hist)[:-1]))
        threshold  = max(median_odf * self._threshold_factor, ONSET_MIN_ODF)

        # Dual-Gate: ODF + absoluter RMS
        odf_ok = peak_odf > threshold
        rms_ok = mean_rms  > self._abs_rms_min

        if odf_ok and rms_ok:
            # Silence-Aware Warmup: ersten Spike nach langer Stille überspringen
            if self._silence_count >= SILENCE_BLOCKS:
                self._silence_count = 0   # Warmup einmal konsumiert
                return False, peak_odf
            self._cooldown_left = self._cooldown_samples
            return True, peak_odf

        return False, peak_odf

    def reset(self) -> None:
        self._odf_hist.clear()
        self._prev_sub_rms = 0.0
        self._cooldown_left = 0
        self._silence_count = SILENCE_BLOCKS   # nach Reset wieder "kalt"
        if self._sos is not None:
            self._sos_zi[:] = 0.0


# ---------------------------------------------------------------------------
# Frequenzfilter-Fabrik
# ---------------------------------------------------------------------------

def _make_filters(
    sample_rate: int,
) -> tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
    """Butterworth-IIR-Filter für Kick, Snare und Crash.

    Returns (kick_sos, snare_sos, crash_sos) oder (None, None, None) wenn scipy fehlt.
    """
    try:
        from scipy.signal import butter
        nyq = sample_rate / 2.0
        # Kick: Tiefpass 150 Hz — Kick-Body, verwirft Snare/Gitarren-Bleed
        kick_sos = butter(4, 150.0 / nyq, btype="low", output="sos")
        # Snare: Bandpass 800–9 000 Hz — Snare-Crack, verwirft Kick-Bleed (<500 Hz)
        snare_sos = butter(4, [800.0 / nyq, 9000.0 / nyq], btype="band", output="sos")
        # Crash: Hochpass 5 000 Hz — isoliert Crash-Oberton-Cluster, unterdrückt HiHat-Körper
        # Crashes haben sehr hohe Energie in 5–20 kHz (Nyquist bei 48 kHz = 24 kHz)
        crash_sos = butter(4, 5000.0 / nyq, btype="high", output="sos")
        return kick_sos, snare_sos, crash_sos
    except Exception as exc:
        log.warning("scipy nicht verfügbar — Onset-Detection ohne Frequenzfilter: %s", exc)
        return None, None, None


# ---------------------------------------------------------------------------
# Onset-Detektor (Kick + Snare)
# ---------------------------------------------------------------------------

class OnsetDetector:
    """Erkennt Kick-, Snare- und Crash-Onsets aus mehrkanaligem XR18-Audio (48 kHz)."""

    # Crash-Cooldown: Cymbals halten lange (mindestens 1,5 s pro Crash)
    CRASH_COOLDOWN_SEC = 1.5

    def __init__(self, sample_rate: int = 48_000) -> None:
        self._sr = sample_rate
        kick_cd  = int(KICK_COOLDOWN_SEC  * sample_rate)
        snare_cd = int(SNARE_COOLDOWN_SEC * sample_rate)
        crash_cd = int(self.CRASH_COOLDOWN_SEC * sample_rate)
        kick_sos, snare_sos, crash_sos = _make_filters(sample_rate)
        self._kick  = ChannelOnsetDetector(
            threshold_factor=3.0,
            history_len=50,
            cooldown_samples=kick_cd,
            filter_sos=kick_sos,
            abs_rms_min=5e-3,
        )
        self._snare = ChannelOnsetDetector(
            threshold_factor=2.2,
            history_len=50,
            cooldown_samples=snare_cd,
            filter_sos=snare_sos,
            abs_rms_min=3e-3,
        )
        # Crash: hoher threshold_factor + hoher abs_rms_min → nur starke Crashes
        # Der adaptive Median auf dem Hochpass-Signal ist niedrig (wenig Energie >5 kHz),
        # daher threshold_factor=3.5 und abs_rms_min=8e-3 für Selektivität.
        self._crash = ChannelOnsetDetector(
            threshold_factor=3.5,
            history_len=50,
            cooldown_samples=crash_cd,
            filter_sos=crash_sos,
            abs_rms_min=8e-3,
        )

    def process_block(self, block: np.ndarray) -> list[OnsetEvent]:
        """Verarbeitet einen Audio-Block und gibt Onset-Ereignisse zurück.

        block: shape (frames, channels), float32, XR18-Belegung (mind. 15 Kanäle).
        Gibt "kick", "snare" und "crash" Events zurück.
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

        # Crash: L+R summiert (max) → mehr Energie, robustere Erkennung
        if n_ch > max(CH_OH_L, CH_OH_R):
            oh_mix = np.maximum(
                np.abs(block[:, CH_OH_L].astype(np.float32)),
                np.abs(block[:, CH_OH_R].astype(np.float32)),
            )
        elif n_ch > CH_OH_L:
            oh_mix = block[:, CH_OH_L].astype(np.float32)
        else:
            oh_mix = None

        if oh_mix is not None:
            crash_onset, crash_odf = self._crash.process(oh_mix)
            if crash_onset:
                events.append(OnsetEvent(type="crash", energy=crash_odf))

        return events

    def reset(self) -> None:
        self._kick.reset()
        self._snare.reset()
        self._crash.reset()
        log.debug("OnsetDetector zurückgesetzt")
