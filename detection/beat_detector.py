"""Onset-Erkennung für Kick (CH09) und Snare (CH10) aus XR18-Audio.

Detektionsprinzip: Onset Detection Function (ODF)
-------------------------------------------------
Statt rohem RMS wird die **positive erste Ableitung** des Block-RMS
als Onset-Merkmal verwendet:

    odf[n] = max(0,  rms[n] - rms[n-1])   # half-wave rectified flux

Vorteil gegenüber reinem RMS-Threshold:
- Feuert nur bei *steigender* Energie (Anschlag), nicht auf Sustain
- Selbst-normalisierend: laute Sustain-Abschnitte erhöhen den adaptiven
  Median der ODF und erhöhen damit den Schwellwert mit — genau wie erwünscht
- Deutlich weniger Falsch-Positive durch Bleed / Gitarren-/Bass-Anteile
  auf dem Kick-/Snare-Mikrofonkanal

Kein PLL, kein BPM-Tracking, kein Beat-Counting, kein HMM.
Nur rohe Impuls-Erkennung als Grundlage für alle weiteren Algorithmen.

Kanal-Indizes (0-basiert im XR18 USB-Stream):
  8  = CH09 Kick
  9  = CH10 Snare
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

import numpy as np

log = logging.getLogger("detection.onset")

# ---------------------------------------------------------------------------
# Kanal-Indizes (0-basiert, XR18 USB)
# ---------------------------------------------------------------------------
CH_KICK  = 8
CH_SNARE = 9

# Absoluter ODF-Boden: Mindest-Energieanstieg pro Block (~42 ms @ 48 kHz)
# damit ein Onset überhaupt in Frage kommt.
# Echter Kick: RMS-Sprung von ~0.005 → 0.15 → ODF ≈ 0.145
# Leiser Kick: 0.001 → 0.02 → ODF ≈ 0.019
# Rauschen / Bleed: ODF-Schwankung typ. < 0.003
ONSET_MIN_ODF = 5e-3

# Fester Mindest-Cooldown nach Onset-Erkennung (Sekunden).
# Kick: 220 ms → bei 160 BPM, 4-on-the-floor: Beats alle 375 ms → ok
# Snare: 280 ms → Snare auf 2+4 bei 160 BPM alle 750 ms → ok
KICK_COOLDOWN_SEC  = 0.220
SNARE_COOLDOWN_SEC = 0.280


# ---------------------------------------------------------------------------
# Datenstruktur
# ---------------------------------------------------------------------------

@dataclass
class OnsetEvent:
    """Erkanntes Onset-Ereignis."""
    type: str       # "kick" | "snare"
    energy: float   # ODF-Wert (Energieanstieg) beim Onset


# ---------------------------------------------------------------------------
# Per-Kanal Onset-Detektor (ODF-basiert)
# ---------------------------------------------------------------------------

class ChannelOnsetDetector:
    """ODF-basierter Onset-Detektor für einen Mono-Kanal.

    Detektionsmerkmal ist die positive erste Ableitung des Block-RMS.
    Der Schwellwert ist ein adaptiver Median der ODF-History, multipliziert
    mit einem Faktor — plus ein absoluter Boden (ONSET_MIN_ODF).

    Ein fester Cooldown (Samples, BPM-unabhängig) verhindert Doppeltrigger.
    """

    def __init__(
        self,
        threshold_factor: float = 2.5,
        history_len: int = 50,
        cooldown_samples: int = 9600,
    ) -> None:
        self._threshold_factor = threshold_factor
        self._odf_hist: deque[float] = deque(maxlen=history_len)
        self._prev_rms: float = 0.0
        self._cooldown_left: int = 0
        self._cooldown_samples = cooldown_samples

    @staticmethod
    def _block_rms(block: np.ndarray) -> float:
        """Ganzer-Block-RMS — glatter als Sub-Window-Max, ideal für Ableitung."""
        return float(np.sqrt(np.mean(block.astype(np.float32) ** 2)))

    def process(self, block: np.ndarray) -> tuple[bool, float]:
        """Verarbeitet einen Mono-Audio-Block.

        Returns
        -------
        (onset_detected, odf_value)
            odf_value: positiver Energieanstieg (erste Ableitung des RMS)
        """
        rms = self._block_rms(block)
        # Positive erste Ableitung (half-wave rectified flux)
        odf = max(0.0, rms - self._prev_rms)
        self._prev_rms = rms
        n = len(block)

        # Cooldown abbauen — ODF trotzdem in History schreiben (für Median)
        if self._cooldown_left > 0:
            self._cooldown_left -= n
            self._odf_hist.append(odf)
            return False, odf

        self._odf_hist.append(odf)
        if len(self._odf_hist) < 6:
            return False, odf

        # Adaptiver Schwellwert: Median der bisherigen ODF-Werte × Faktor
        # (aktuellen Block ausschließen → [:-1])
        median_odf = float(np.median(np.array(self._odf_hist)[:-1]))
        threshold = max(median_odf * self._threshold_factor, ONSET_MIN_ODF)

        if odf > threshold:
            self._cooldown_left = self._cooldown_samples
            return True, odf

        return False, odf

    def reset(self) -> None:
        self._odf_hist.clear()
        self._prev_rms = 0.0
        self._cooldown_left = 0


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
        self._kick  = ChannelOnsetDetector(
            threshold_factor=2.5,
            history_len=50,
            cooldown_samples=kick_cd,
        )
        self._snare = ChannelOnsetDetector(
            threshold_factor=2.2,
            history_len=50,
            cooldown_samples=snare_cd,
        )

    def process_block(self, block: np.ndarray) -> list[OnsetEvent]:
        """Verarbeitet einen Audio-Block und gibt Onset-Ereignisse zurück.

        Parameters
        ----------
        block:
            shape (frames, channels), float32.
            Erwartet ≥10 Kanäle (0-basiert, XR18-Belegung).
            Wenn weniger Kanäle vorhanden → Fallback auf Stereo-Mix.

        Returns
        -------
        list[OnsetEvent]  (leer wenn kein Onset erkannt)
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
