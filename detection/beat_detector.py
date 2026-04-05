"""Onset-Erkennung für Kick (CH09) und Snare (CH10) aus XR18-Audio.

Einfachster möglicher Ansatz:
  - Pro Block: RMS-Energie auf Kick- und Snare-Kanal berechnen
  - Onset erkannt wenn Energie über adaptivem Median-Schwellwert liegt
  - Fester Cooldown verhindert Doppeltrigger innerhalb desselben Transienten

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

# Absoluter Energieboden — verhindert Trigger in quasi-stillen Passagen.
# Wert: Peak-RMS eines 512-Sample-Fensters bei float32 Vollaussteuerung.
# Erfahrungswert: echter Kick/Snare liegt bei 0.05–0.5, Rauschen bei <0.003.
ONSET_MIN_ENERGY = 4e-3

# Fester Mindest-Cooldown nach Onset-Erkennung (Sekunden).
# Verhindert Doppeltrigger auf denselben Transienten.
# Kick: 220 ms  → bei 160 BPM, 4-on-the-floor: Beats alle 375 ms → ok
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
    energy: float   # Peak-RMS-Energie beim Onset


# ---------------------------------------------------------------------------
# Per-Kanal Onset-Detektor
# ---------------------------------------------------------------------------

class ChannelOnsetDetector:
    """Online Onset-Detektor für einen Mono-Kanal.

    Vergleicht RMS-Energie des aktuellen Blocks gegen einen adaptiven
    Median-Schwellwert aus den letzten `history_len` Blöcken.
    Ein fester Cooldown (in Samples, unabhängig vom BPM) verhindert
    Doppeltrigger auf demselben Transienten.
    """

    def __init__(
        self,
        threshold_factor: float = 4.0,
        history_len: int = 50,
        cooldown_samples: int = 9600,   # 200 ms @ 48 kHz — Override in OnsetDetector
    ) -> None:
        self._threshold_factor = threshold_factor
        self._history: deque[float] = deque(maxlen=history_len)
        self._cooldown_left: int = 0
        self._cooldown_samples = cooldown_samples

    @staticmethod
    def _peak_rms(block: np.ndarray, n_windows: int = 4) -> float:
        """Maximales RMS über N gleichgroße Sub-Fenster des Blocks.

        Löst das Block-Boundary-Problem: Transient-Peaks (5–15 ms Kick/Snare),
        die nahe einer Block-Grenze liegen, werden nicht mehr auf zwei Blöcke
        verteilt und dadurch unsichtbar gemacht.
        """
        b = block.astype(np.float32)
        n = len(b)
        w = n // n_windows
        if w == 0:
            return float(np.sqrt(np.mean(b ** 2)))
        return max(
            float(np.sqrt(np.mean(b[i * w:(i + 1) * w] ** 2)))
            for i in range(n_windows)
        )

    def process(self, block: np.ndarray) -> tuple[bool, float]:
        """Verarbeitet einen Mono-Audio-Block.

        Returns
        -------
        (onset_detected, rms_energy)
        """
        rms = self._peak_rms(block)
        n = len(block)

        # Cooldown abbauen
        if self._cooldown_left > 0:
            self._cooldown_left -= n
            self._history.append(rms)
            return False, rms

        # Adaptiver Schwellwert: Median der History × Faktor
        self._history.append(rms)
        if len(self._history) < 6:
            return False, rms

        median_energy = float(np.median(np.array(self._history)[:-1]))
        threshold = max(median_energy * self._threshold_factor, ONSET_MIN_ENERGY)

        if rms > threshold:
            self._cooldown_left = self._cooldown_samples
            return True, rms

        return False, rms

    def reset(self) -> None:
        self._history.clear()
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
            threshold_factor=4.0,
            history_len=50,
            cooldown_samples=kick_cd,
        )
        self._snare = ChannelOnsetDetector(
            threshold_factor=3.5,
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

        kick_signal  = _ch(CH_KICK)
        snare_signal = _ch(CH_SNARE)

        events: list[OnsetEvent] = []

        kick_onset, kick_energy = self._kick.process(kick_signal)
        if kick_onset:
            events.append(OnsetEvent(type="kick", energy=kick_energy))

        snare_onset, snare_energy = self._snare.process(snare_signal)
        if snare_onset:
            events.append(OnsetEvent(type="snare", energy=snare_energy))

        return events

    def reset(self) -> None:
        """Setzt den Detektor zurück (neues Segment)."""
        self._kick.reset()
        self._snare.reset()
        log.debug("OnsetDetector zurückgesetzt")
