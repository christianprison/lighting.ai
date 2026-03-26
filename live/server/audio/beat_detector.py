"""Beat-Erkennung aus mehrkanaligem XR18-Audio (Phase 2).

Online-Algorithmus (PLL-basiert):
  1. Onset-Energie pro Block: Kick (CH09), Snare (CH10), Overheads (CH14/15)
  2. Phase-Locked Loop: trackt Beat-Periode und -Phase adaptiv
  3. Snare-Pattern: Beats 2+4 identifizieren Downbeat (Beat 1)
  4. Tom-Aktivität (CH11-13): Fill-Erkennung → Phrasenende

Kanal-Indizes (0-basiert im XR18 USB-Stream):
  8  = CH09 Kick
  9  = CH10 Snare
  10 = CH11 Tom Hi
  11 = CH12 Tom Mid
  12 = CH13 Tom Lo
  13 = CH14 Overhead 1
  14 = CH15 Overhead 2

Bibliotheksabhängigkeit: numpy (immer vorhanden). madmom (optional) kann als
Upgrade für robustere BPM-Schätzung über die Funktion `estimate_bpm_madmom`
genutzt werden.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger("live.audio.beat")

# ---------------------------------------------------------------------------
# Kanal-Indizes (0-basiert, XR18 USB)
# ---------------------------------------------------------------------------
CH_KICK = 8
CH_SNARE = 9
CH_TOM_HI = 10
CH_TOM_MID = 11
CH_TOM_LO = 12
CH_OH_L = 13
CH_OH_R = 14

# ---------------------------------------------------------------------------
# PLL-Parameter
# ---------------------------------------------------------------------------
# Adaptionsrate der Beat-Periode (0=keine, 1=sofort)
PLL_PERIOD_ALPHA = 0.12
# Toleranzfenster für Onset-zu-Beat-Matching (Bruchteil der Beat-Periode)
PLL_TOLERANCE = 0.30

# BPM-Grenzen
BPM_MIN = 60.0
BPM_MAX = 220.0

# Minimal-Energie damit ein Onset zählt (verhindert Stille-Artefakte)
ONSET_MIN_ENERGY = 5e-4

# Cooldown nach Onset-Erkennung (Bruchteil der Beat-Periode)
ONSET_COOLDOWN_FACTOR = 0.28


# ---------------------------------------------------------------------------
# Datenstrukturen
# ---------------------------------------------------------------------------

@dataclass
class BeatEvent:
    """Beat-Ereignis aus der Live-Erkennung."""
    beat_num: int        # 1–4
    bpm: float           # aktuelles Tempo
    is_downbeat: bool    # True wenn Beat 1 (Taktanfang)
    is_fill: bool        # True wenn Tom-Fill erkannt (Phrasenende)
    bar_num: int         # Taktnummer seit Start (0-basiert)
    trigger: str = "timer"  # "kick" | "overhead" | "timer"
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Per-Kanal Onset-Detektor
# ---------------------------------------------------------------------------

class ChannelOnsetDetector:
    """Online Onset-Detektor für einen Mono-Kanal.

    Vergleicht RMS-Energie des aktuellen Blocks gegen einen adaptiven
    Median-Schwellwert aus den letzten `history_len` Blöcken.
    """

    def __init__(
        self,
        threshold_factor: float = 2.0,
        history_len: int = 30,
        cooldown_factor: float = ONSET_COOLDOWN_FACTOR,
    ) -> None:
        self._threshold_factor = threshold_factor
        self._history: deque[float] = deque(maxlen=history_len)
        self._cooldown_samples: int = 0
        self._cooldown_factor = cooldown_factor

    def process(self, block: np.ndarray, beat_period_samples: float) -> tuple[bool, float]:
        """Verarbeitet einen Mono-Audio-Block.

        Parameters
        ----------
        block:
            Mono float32 Array (ein Channel, ein Block).
        beat_period_samples:
            Aktuelle Beat-Periode in Samples — bestimmt Cooldown-Länge.

        Returns
        -------
        (onset_detected, rms_energy)
        """
        rms = float(np.sqrt(np.mean(block.astype(np.float32) ** 2)))
        n = len(block)

        # Cooldown abbauen
        if self._cooldown_samples > 0:
            self._cooldown_samples -= n
            self._history.append(rms)
            return False, rms

        # Adaptiver Schwellwert: Median der History × Faktor
        self._history.append(rms)
        if len(self._history) < 4:
            return False, rms

        median_energy = float(np.median(np.array(self._history)[:-1]))
        threshold = max(median_energy * self._threshold_factor, ONSET_MIN_ENERGY)

        if rms > threshold:
            # Onset erkannt → Cooldown setzen
            self._cooldown_samples = int(beat_period_samples * self._cooldown_factor)
            return True, rms

        return False, rms

    def reset(self) -> None:
        self._history.clear()
        self._cooldown_samples = 0


# ---------------------------------------------------------------------------
# Beat-Detektor
# ---------------------------------------------------------------------------

class BeatDetector:
    """Online Beat-Detektor für mehrkanaliges XR18 USB-Audio (48 kHz).

    Verwendet einen Phase-Locked Loop (PLL) mit Kick (CH09) als primärem
    Trigger und Overheads (CH14/15) als Fallback. Die Snare (CH10) wird
    genutzt, um Beat 1 zu identifizieren: da Snare auf Beat 2 und 4 schlägt,
    zeigt ein Snare-Hit auf einem ungerade gezählten Beat, dass die interne
    Zählung um 1 versetzt ist.

    Toms (CH11-13): erhöhte Aktivität → Fill → Taktgrenze.

    Usage::

        detector = BeatDetector(sample_rate=48_000, initial_bpm=120.0)

        # Bei jedem sounddevice-Callback:
        events = detector.process_block(indata)   # indata: (frames, 18)
        for ev in events:
            print(ev.beat_num, ev.bpm)

        # Bei Song-Wechsel:
        detector.set_bpm(song.bpm)
        detector.reset()
    """

    def __init__(self, sample_rate: int = 48_000, initial_bpm: float = 120.0) -> None:
        self._sr = sample_rate

        # --- PLL-Zustand ---
        self._bpm = max(BPM_MIN, min(BPM_MAX, initial_bpm))
        self._beat_period = self._bpm_to_period(self._bpm)
        self._beat_phase: float = 0.0       # Samples seit letztem Beat
        self._total_samples: int = 0        # Gesamtzahl verarbeiteter Samples

        # Beat- und Takt-Zähler
        self._beat_num: int = 1             # 1–4
        self._bar_num: int = 0              # seit Start

        # --- Onset-Detektoren ---
        self._kick = ChannelOnsetDetector(threshold_factor=2.2, history_len=32)
        self._snare = ChannelOnsetDetector(threshold_factor=1.9, history_len=32)
        self._oh = ChannelOnsetDetector(threshold_factor=1.6, history_len=40)
        self._toms = ChannelOnsetDetector(threshold_factor=1.8, history_len=20)

        # Tom-Energie-History für Fill-Erkennung (Median-Vergleich)
        self._tom_energy_hist: deque[float] = deque(maxlen=24)

        # Letzter Zeitpunkt eines Kick-Onsets (samples), für Fallback-Timer
        self._last_kick_sample: int = 0

    # --- Public API -----------------------------------------------------------

    def set_bpm(self, bpm: float) -> None:
        """Aktualisiert BPM-Prior (aus DB beim Song-Wechsel).

        Passt die Beat-Periode sofort an, ohne den Phase-Zähler zurückzusetzen.
        So bleiben bereits laufende Beats synchron.
        """
        bpm = max(BPM_MIN, min(BPM_MAX, bpm))
        self._bpm = bpm
        self._beat_period = self._bpm_to_period(bpm)
        log.debug("BeatDetector: BPM → %.1f (period=%.0f samples)", bpm, self._beat_period)

    def reset(self, bpm: float | None = None) -> None:
        """Setzt Zustand zurück (neuer Song / manueller Reset)."""
        if bpm is not None:
            self.set_bpm(bpm)
        self._beat_phase = 0.0
        self._beat_num = 1
        self._bar_num = 0
        self._last_kick_sample = 0
        self._kick.reset()
        self._snare.reset()
        self._oh.reset()
        self._toms.reset()
        self._tom_energy_hist.clear()
        log.info("BeatDetector zurückgesetzt (BPM=%.1f)", self._bpm)

    @property
    def bpm(self) -> float:
        return round(self._bpm, 1)

    @property
    def beat_num(self) -> int:
        return self._beat_num

    @property
    def bar_num(self) -> int:
        return self._bar_num

    def process_block(self, block: np.ndarray) -> tuple[list[BeatEvent], bool]:
        """Verarbeitet einen Audio-Block und gibt Beat-Ereignisse zurück.

        Parameters
        ----------
        block:
            shape (frames, channels), float32.
            Erwartet ≥15 Kanäle (0-basiert, XR18-Belegung).
            Wenn weniger Kanäle vorhanden → Fallback auf Stereo-Mix.

        Returns
        -------
        (beat_events, snare_onset)
            beat_events: Liste von BeatEvent (meist leer oder 1 Element pro Block).
            snare_onset: True wenn in diesem Block ein Snare-Onset erkannt wurde.
        """
        frames = block.shape[0]
        n_ch = block.shape[1] if block.ndim > 1 else 1

        # Kanäle extrahieren (mit Fallback)
        def _ch(idx: int) -> np.ndarray:
            if n_ch > idx:
                return block[:, idx].astype(np.float32)
            # Fallback: Mono-Mix aus den vorhandenen Kanälen
            return np.mean(block.astype(np.float32), axis=1)

        kick = _ch(CH_KICK)
        snare = _ch(CH_SNARE)
        oh = (_ch(CH_OH_L) + _ch(CH_OH_R)) * 0.5
        toms_sum = (_ch(CH_TOM_HI) + _ch(CH_TOM_MID) + _ch(CH_TOM_LO)) / 3.0

        # --- Onset-Erkennung ---
        kick_onset, _ = self._kick.process(kick, self._beat_period)
        snare_onset, _ = self._snare.process(snare, self._beat_period)
        oh_onset, _ = self._oh.process(oh, self._beat_period * 0.5)
        _, tom_energy = self._toms.process(toms_sum, self._beat_period)

        # --- Fill-Erkennung ---
        self._tom_energy_hist.append(tom_energy)
        is_fill = self._detect_fill(tom_energy)

        # --- Akkumulierung ---
        self._beat_phase += frames
        self._total_samples += frames

        events: list[BeatEvent] = []

        # --- PLL-Update ---
        # Priorität: Kick > Overhead > Zeitbasiert
        beat_emitted = False

        if kick_onset:
            self._last_kick_sample = self._total_samples
            emitted = self._pll_update(is_fill, events, trigger="kick")
            beat_emitted = emitted

        if not beat_emitted and oh_onset:
            # Overhead als Fallback nur wenn keine Kick-Info in letzter Zeit
            samples_since_kick = self._total_samples - self._last_kick_sample
            if samples_since_kick > self._beat_period * 1.5:
                self._pll_update(is_fill, events, trigger="overhead")
                beat_emitted = True

        # Zeitbasierter Fallback: Beat erwürfeln wenn Phase überschritten
        if not beat_emitted and self._beat_phase >= self._beat_period:
            self._beat_phase -= self._beat_period
            events.append(self._make_event(is_fill, trigger="timer"))

        # --- Snare-Downbeat-Korrektur ---
        if snare_onset:
            self._snare_correction()

        return events, snare_onset

    # --- Interne Methoden -----------------------------------------------------

    def _bpm_to_period(self, bpm: float) -> float:
        return self._sr * 60.0 / bpm

    def _pll_update(self, is_fill: bool, events: list[BeatEvent], trigger: str = "kick") -> bool:
        """PLL-Schritt bei erkanntem Onset.

        Prüft ob der Onset nahe genug am erwarteten Beat liegt.
        Bei Treffer: Periode adaptieren, Event erzeugen, True zurückgeben.
        """
        expected = self._beat_period
        tolerance = expected * PLL_TOLERANCE

        # Nächster Beat erwartet nach ~1 Beat-Periode ab letztem Beat
        dist_to_expected = abs(self._beat_phase - expected)

        if dist_to_expected < tolerance:
            # Phase-Fehler
            phase_error = self._beat_phase - expected

            # Periode adaptiv anpassen (langsam, damit kein Jitter)
            new_period = expected + PLL_PERIOD_ALPHA * phase_error
            # BPM-Grenzen durchsetzen
            new_period = max(
                self._bpm_to_period(BPM_MAX),
                min(self._bpm_to_period(BPM_MIN), new_period),
            )
            self._beat_period = new_period
            self._bpm = self._sr * 60.0 / new_period

            # Phase zurücksetzen
            self._beat_phase -= expected

            events.append(self._make_event(is_fill, trigger=trigger))
            return True

        return False

    def _make_event(self, is_fill: bool, trigger: str = "timer") -> BeatEvent:
        """Erzeugt BeatEvent und inkrementiert Beat/Bar-Zähler."""
        ev = BeatEvent(
            beat_num=self._beat_num,
            bpm=round(self._bpm, 1),
            is_downbeat=(self._beat_num == 1),
            is_fill=is_fill,
            bar_num=self._bar_num,
            trigger=trigger,
        )
        self._beat_num += 1
        if self._beat_num > 4:
            self._beat_num = 1
            self._bar_num += 1
        return ev

    def _detect_fill(self, tom_energy: float) -> bool:
        """Erkennt Tom-Fill aus erhöhter Tom-Energie gegenüber dem Median."""
        if len(self._tom_energy_hist) < 8:
            return False
        median = float(np.median(np.array(self._tom_energy_hist)))
        # Fill: aktuelle Energie deutlich über Median UND über Minimum
        return tom_energy > median * 2.5 and tom_energy > ONSET_MIN_ENERGY * 2

    def _snare_correction(self) -> None:
        """Korrigiert Beat-Nummer wenn Snare auf ungeradem Beat erklingt.

        Snare schlägt normalerweise auf Beat 2 und 4 (gerade Beats).
        Wenn wir einen Snare-Onset bei Beat 1 oder 3 sehen, ist die interne
        Zählung um 1 versetzt → Beat-Nummer um +1 schieben.
        """
        if self._beat_num in (1, 3):
            old = self._beat_num
            self._beat_num = (self._beat_num % 4) + 1
            log.debug(
                "Snare-Korrektur: Beat %d → %d (Snare erwartet auf geradem Beat)",
                old, self._beat_num,
            )


# ---------------------------------------------------------------------------
# Optionale madmom-Integration (BPM-Schätzung aus längerem Puffer)
# ---------------------------------------------------------------------------

def estimate_bpm_madmom(audio: np.ndarray, sr: int = 48_000) -> float | None:
    """Schätzt BPM aus einem Audio-Puffer mit madmom (optional).

    Gibt None zurück wenn madmom nicht installiert ist.
    Kann für initiale BPM-Kalibrierung verwendet werden, bevor der PLL
    konvergiert hat.

    Parameters
    ----------
    audio:
        Mono float32 Array (mindestens 5 Sekunden empfohlen).
    sr:
        Sample-Rate.

    Returns
    -------
    float | None — geschätztes BPM oder None wenn madmom nicht verfügbar.
    """
    try:
        import madmom  # type: ignore  # noqa: F401
        from madmom.features.beats import RNNBeatProcessor, BeatTrackingProcessor
    except ImportError:
        log.debug("madmom nicht installiert — BPM-Schätzung übersprungen")
        return None

    try:
        proc = BeatTrackingProcessor(fps=100)
        act = RNNBeatProcessor()(audio.astype(np.float32))
        beats = proc(act)
        if len(beats) >= 4:
            intervals = np.diff(beats)
            median_interval = float(np.median(intervals))
            bpm = 60.0 / median_interval
            if BPM_MIN <= bpm <= BPM_MAX:
                log.info("madmom BPM-Schätzung: %.1f", bpm)
                return bpm
    except Exception as exc:
        log.warning("madmom BPM-Schätzung fehlgeschlagen: %s", exc)

    return None
