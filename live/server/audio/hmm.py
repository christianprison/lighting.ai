"""HMM-basierte Takt-Positionsschätzung.

Implementiert einen Online-Beam-Search-Approximation des Viterbi-Algorithmus
über den Zustandsraum (song_id, bar_num).

Zustandsraum: ~25 Songs × ~120 Takte ≈ 3000 Zustände — für Echtzeit trivial.

Übergangsmodell
---------------
Der "Normalfall" ist der nächste Takt (+1). Die Übergangswahrscheinlichkeit
fällt Gaußförmig um diesen Normalfall ab. Für Part- und Song-Grenzen ist die
Gauß-Breite (σ) weiter, um Wiederholungen und übersprungene Parts abzudecken.

  σ_takt   = 1   Takt   — innerhalb eines Parts kaum Sprünge
  σ_part   = 3   Takte  — Part-Grenzen: Wiederholung / ausgelassener Chorus möglich
  σ_song   = 10  Takte  — Song-zu-Song: breite Suche, Setliste kann abweichen

Emissionsmodell
---------------
Kosinus-Ähnlichkeit zwischen aktuellem Feature-Vektor und gespeichertem
Referenz-Vektor pro Takt. Gewichtung: Chroma 50%, MFCC 30%, Onset 20%.

Fallback
--------
Falls kein Takt die Konfidenz-Schwelle erreicht (Standard: 0.3), bleibt der
HMM am aktuellen Zustand — keine wilde Sprünge bei sehr lautem Fill.

Rehearsal Mode
--------------
Im Rehearsal Mode wird der Suchraum auf den manuell gesetzten aktiven Song
eingeschränkt. Das erhöht die Robustheit während der Probe drastisch.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import NamedTuple

import numpy as np

from .fingerprint import weighted_similarity
from .reference_db import BarRecord, FeatureVector, ReferenceDB

log = logging.getLogger("live.audio.hmm")

# --- Gauß-Breiten (σ in Takten) — empirisch zu tunen nach ersten Proben ---
SIGMA_WITHIN_PART = 1.0    # kaum Sprünge innerhalb eines Parts
SIGMA_PART_BOUNDARY = 3.0  # etwas breiter an Partgrenzen
SIGMA_SONG_BOUNDARY = 10.0 # breite Suche für Song-Wechsel

# Konfidenz-Schwelle: unter diesem Wert → Fallback (Position einfrieren)
CONFIDENCE_THRESHOLD = 0.30

# Beam-Breite: nur Top-K Hypothesen weiterverfolgen
BEAM_WIDTH = 50


# ---------------------------------------------------------------------------
# Datenstrukturen
# ---------------------------------------------------------------------------

class StateKey(NamedTuple):
    song_id: str
    bar_num: int  # absolut zum Song, 1-based


@dataclass
class HMMState:
    """Aktuell geschätzter Zustand des HMM."""
    song_id: str = ""
    bar_num: int = 0
    part_name: str = ""
    confidence: float = 0.0
    is_frozen: bool = False   # True wenn unter Konfidenz-Schwelle (Fallback)


@dataclass
class _Hypothesis:
    key: StateKey
    log_prob: float  # log-Wahrscheinlichkeit (numerisch stabiler als Produkte)


# ---------------------------------------------------------------------------
# HMM
# ---------------------------------------------------------------------------

class AudioHMM:
    """Online-HMM für Song/Takt-Positionsschätzung.

    Usage::

        hmm = AudioHMM(db)
        hmm.load_all_states()            # beim Startup aus DB laden

        # Rehearsal Mode: Suche auf einen Song einschränken
        hmm.set_active_song("5iZfKj")

        # Jeden Takt (auf Beat 1 getriggert):
        state = hmm.update(chroma, mfcc, onset)
        print(state.song_id, state.bar_num, state.confidence)
    """

    def __init__(self, db: ReferenceDB) -> None:
        self.db = db

        # Alle Zustände: StateKey → FeatureVector
        self._features: dict[StateKey, FeatureVector] = {}
        # Alle Bars: StateKey → BarRecord
        self._bars: dict[StateKey, BarRecord] = {}
        # Part-Grenzen pro Song: song_id → sorted list of (start_bar_num, part_name)
        self._part_map: dict[str, list[tuple[int, str]]] = {}

        # Aktueller Beam: Liste von Hypothesen, sortiert nach log_prob desc
        self._beam: list[_Hypothesis] = []

        # Eingeschränkter Suchraum für Rehearsal Mode (None = alle Songs)
        self._active_song_id: str | None = None

        # Letzter sicherer Zustand für Fallback
        self._last_confident: HMMState = HMMState()

    # --- Laden ---------------------------------------------------------------

    def load_all_states(self) -> int:
        """Lädt alle Feature-Vektoren aus der DB in den Speicher.

        Returns: Anzahl geladener Zustände.
        """
        self._features.clear()
        self._bars.clear()
        self._part_map.clear()

        features = self.db.get_all_features()
        for fv in features:
            bar = self.db.get_bar(fv.bar_id)
            if bar is None:
                continue
            key = StateKey(bar.song_id, bar.bar_num)
            self._features[key] = fv
            self._bars[key] = bar

        # Part-Grenzen aufbauen
        for key, bar in self._bars.items():
            song_id = key.song_id
            if song_id not in self._part_map:
                self._part_map[song_id] = []
            self._part_map[song_id].append((bar.bar_num, bar.part_name))

        for song_id in self._part_map:
            self._part_map[song_id].sort()

        # Beam initial gleichverteilt
        self._init_beam()

        n = len(self._features)
        log.info("HMM geladen: %d Zustände aus %d Songs", n, len(self._part_map))
        return n

    def _init_beam(self) -> None:
        """Gleichverteilte Prior-Wahrscheinlichkeit über alle Zustände."""
        keys = list(self._active_keys())
        if not keys:
            self._beam = []
            return
        log_prior = -math.log(len(keys))
        self._beam = [_Hypothesis(k, log_prior) for k in keys]

    def _active_keys(self) -> list[StateKey]:
        """Alle Zustände im aktuellen Suchraum."""
        if self._active_song_id is not None:
            return [k for k in self._features if k.song_id == self._active_song_id]
        return list(self._features.keys())

    # --- Rehearsal Mode -------------------------------------------------------

    def set_active_song(self, song_id: str | None) -> None:
        """Schränkt den Suchraum auf einen Song ein (Rehearsal Mode).

        song_id=None → alle Songs (Live Mode).
        """
        if song_id == self._active_song_id:
            return
        self._active_song_id = song_id
        self._init_beam()
        if song_id:
            log.info("Rehearsal Mode: aktiver Song = %s", song_id)
        else:
            log.info("Live Mode: alle Songs im Suchraum")

    # --- Update --------------------------------------------------------------

    def update(
        self,
        chroma: np.ndarray,
        mfcc: np.ndarray,
        onset: np.ndarray,
    ) -> HMMState:
        """Verarbeitet einen neuen Feature-Snapshot und gibt den neuen Zustand zurück.

        Wird einmal pro Takt aufgerufen (auf Beat 1 getriggert).
        """
        if not self._features:
            log.warning("HMM hat keine Zustände geladen")
            return HMMState()

        # 1) Übergang: Log-Übergangswahrscheinlichkeiten addieren
        transitioned = self._transition_step()

        # 2) Emission: Log-Emissionswahrscheinlichkeit addieren
        updated = self._emission_step(transitioned, chroma, mfcc, onset)

        # 3) Beam stutzen (Top-K)
        updated.sort(key=lambda h: h.log_prob, reverse=True)
        self._beam = updated[:BEAM_WIDTH]

        # 4) Bestes Ergebnis
        best = self._beam[0]
        best_key = best.key

        # Konfidenz aus normalisierten Wahrscheinlichkeiten ableiten
        log_probs = np.array([h.log_prob for h in self._beam])
        log_probs -= log_probs.max()  # numerische Stabilität
        probs = np.exp(log_probs)
        probs /= probs.sum()
        confidence = float(probs[0])

        # 5) Fallback: Position einfrieren falls unter Schwelle
        if confidence < CONFIDENCE_THRESHOLD:
            log.debug(
                "Konfidenz %.2f < %.2f — Position eingefroren bei %s T%d",
                confidence, CONFIDENCE_THRESHOLD,
                self._last_confident.song_id, self._last_confident.bar_num,
            )
            frozen = HMMState(
                song_id=self._last_confident.song_id,
                bar_num=self._last_confident.bar_num,
                part_name=self._last_confident.part_name,
                confidence=confidence,
                is_frozen=True,
            )
            return frozen

        bar = self._bars.get(best_key)
        state = HMMState(
            song_id=best_key.song_id,
            bar_num=best_key.bar_num,
            part_name=bar.part_name if bar else "",
            confidence=confidence,
            is_frozen=False,
        )
        self._last_confident = state
        return state

    # --- Interne Schritte ----------------------------------------------------

    def _transition_step(self) -> list[_Hypothesis]:
        """Berechnet die Prior für den nächsten Zeitschritt.

        Für jeden Zustand j wird das Maximum über alle möglichen Vorgänger i
        mit dem Übergangsgewicht T(i→j) berechnet (Viterbi-Rekursion).
        Wir verwenden Beam-Approximation statt vollständiger Viterbi-Matrix.
        """
        active = list(self._active_keys())
        if not active:
            return []

        # Aus dem aktuellen Beam propagieren
        new_beam: dict[StateKey, float] = {}

        for hyp in self._beam:
            src = hyp.key
            src_log_p = hyp.log_prob
            src_song_parts = self._part_map.get(src.song_id, [])
            src_part_name = self._part_for_bar(src.song_id, src.bar_num)

            # Für jeden möglichen Zielzustand im aktiven Raum
            for dst in active:
                log_t = self._log_transition(src, dst, src_part_name)
                candidate = src_log_p + log_t
                if dst not in new_beam or candidate > new_beam[dst]:
                    new_beam[dst] = candidate

        return [_Hypothesis(k, p) for k, p in new_beam.items()]

    def _emission_step(
        self,
        hypotheses: list[_Hypothesis],
        chroma: np.ndarray,
        mfcc: np.ndarray,
        onset: np.ndarray,
    ) -> list[_Hypothesis]:
        """Addiert Log-Emissionswahrscheinlichkeit (Fingerprint-Ähnlichkeit)."""
        result = []
        for hyp in hypotheses:
            fv = self._features.get(hyp.key)
            if fv is None:
                result.append(hyp)  # kein Feature → unverändert lassen
                continue
            sim = weighted_similarity(
                chroma, mfcc, onset,
                fv.chroma, fv.mfcc, fv.onset,
            )
            # sim ∈ [0, 1] → log(max(sim, ε)) als Emissionsterm
            log_emission = math.log(max(sim, 1e-9))
            result.append(_Hypothesis(hyp.key, hyp.log_prob + log_emission))
        return result

    def _log_transition(
        self,
        src: StateKey,
        dst: StateKey,
        src_part_name: str,
    ) -> float:
        """Log-Übergangswahrscheinlichkeit T(src → dst).

        Gauß-Modell um den Normalfall +1 Takt, mit unterschiedlichen σ
        je nach Nähe zur Part- oder Song-Grenze.
        """
        if src.song_id == dst.song_id:
            delta = dst.bar_num - src.bar_num

            # Part-Grenze prüfen
            dst_part_name = self._part_for_bar(dst.song_id, dst.bar_num)
            is_part_boundary = dst_part_name != src_part_name

            sigma = SIGMA_PART_BOUNDARY if is_part_boundary else SIGMA_WITHIN_PART

            # Gaußverteilung um +1 (nächster Takt)
            return _log_gaussian(delta, mu=1.0, sigma=sigma)
        else:
            # Song-Wechsel: breite Gaußverteilung, delta = Takt-Nr im Zielsong
            delta = dst.bar_num - 1  # Anfang des nächsten Songs
            return _log_gaussian(delta, mu=0.0, sigma=SIGMA_SONG_BOUNDARY) - math.log(10)

    def _part_for_bar(self, song_id: str, bar_num: int) -> str:
        """Gibt den Part-Namen für einen absoluten Takt zurück."""
        boundaries = self._part_map.get(song_id, [])
        part_name = ""
        for bn, pn in boundaries:
            if bn <= bar_num:
                part_name = pn
            else:
                break
        return part_name

    # --- Public helpers -------------------------------------------------------

    def reset(self) -> None:
        """Setzt den Beam auf gleichverteilten Prior zurück."""
        self._init_beam()
        self._last_confident = HMMState()
        log.info("HMM zurückgesetzt")

    def current_state(self) -> HMMState:
        """Gibt den letzten sicheren Zustand zurück (ohne Update)."""
        return self._last_confident


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _log_gaussian(x: float, mu: float, sigma: float) -> float:
    """Log-Wahrscheinlichkeit einer Normalverteilung N(mu, sigma) bei x."""
    return -0.5 * ((x - mu) / sigma) ** 2 - math.log(sigma * math.sqrt(2 * math.pi))
