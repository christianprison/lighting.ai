"""bar_tracker.py — Inkrementeller Takt-Tracker für Kick/Snare-Events.

Verarbeitet Events einzeln (Streaming) und berechnet nach jedem Kick das
Taktgitter neu — ausschließlich auf Basis bisher gesehener Events, kein
Lookahead. Identischer Algorithmus für:

  - Offline-Simulation (rehearsal_review/simulator.py)
  - Live-Betrieb      (live/server/)

Beispiel (identisch in Sim + Live):

    tracker = BarTracker(bpm=120, seg_start_t=0.0, seg_end_t=240.0)
    for block in audio_stream:
        t_block = ...
        for ev in detector.process_block(block):
            if ev.type == "kick":
                tracker.process_kick(t_block)
            else:
                tracker.process_snare(t_block)
    bar_times = tracker.get_latest_bars()
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

log = logging.getLogger("detection.bar_tracker")

# Minimale Kicks bevor Phasen-Histogram sinnvoll ist
_MIN_KICKS_FOR_PHASE = 6

# Plausible Beat-IOI-Grenzen: 60–220 BPM → 0.27–1.0 s
_IOI_MIN = 0.27
_IOI_MAX = 1.0


# ---------------------------------------------------------------------------
# Interne Hilfsfunktionen  (kein öffentliches API)
# ---------------------------------------------------------------------------

def _compute_bpm_from_events(kicks: list[float], snares: list[float]) -> int:
    """Berechnet BPM aus dem medianen IOI der Kick+Snare-Events.

    Returns 0 wenn nicht genügend Events vorhanden.
    """
    all_t = sorted(kicks + snares)
    if len(all_t) < 4:
        return 0
    iois = [all_t[i + 1] - all_t[i] for i in range(len(all_t) - 1)]
    iois = [d for d in iois if _IOI_MIN <= d <= _IOI_MAX]
    if not iois:
        return 0
    beat_sec = float(np.median(iois))
    return round(60.0 / beat_sec)


def _circ_dist(a: float, b: float, period: float) -> float:
    d = abs(a - b) % period
    return min(d, period - d)


def _snare_pattern(snares: list[float], beat_sec: float) -> str:
    """Bestimmt ob Snare auf Offbeat (Beat 2+4) oder auf allen Vierteln schlägt.

    Returns:
        "offbeat"  — Snare typisch auf Beat 2 und 4 (medianer IOI ≈ 2 Beats)
        "allbeat"  — Snare auf jedem Viertel oder häufiger (IOI ≤ 1.3 Beats)
        "unknown"  — zu wenig Daten
    """
    if len(snares) < 4:
        return "unknown"
    s = sorted(snares)
    iois = [s[i + 1] - s[i] for i in range(len(s) - 1)]
    iois = [d for d in iois if d < beat_sec * 3.0]  # nur plausible IOIs
    if not iois:
        return "unknown"
    median_ioi = float(np.median(iois))
    if median_ioi <= beat_sec * 1.3:
        return "allbeat"   # Snare auf allen Vierteln oder häufiger
    return "offbeat"       # Snare nur auf Offbeats (Beat 2+4)


def _find_anchor_by_phase(
    abs_kicks: list[float],
    bar_sec: float,
    snap_r: float,
) -> float:
    """Findet den ersten Kick der dominanten Beat-1-Phase.

    Phasen-Histogram über alle bisher gesehenen Kicks: die Phase mit den
    meisten Stimmen ist der echte Beat-1-Offset. Intro-Noise trifft
    zufällige Phasen (je ~1 Stimme), Hauptteil-Kicks clustern auf einer
    Phase (viele Stimmen) → die Sieger-Phase ist automatisch der echte
    Beat-1-Offset.

    Gibt den frühesten Kick zurück, dessen Phase mit der Sieger-Phase
    übereinstimmt. Fallback: min(abs_kicks) falls zu wenig Daten.
    """
    if len(abs_kicks) < _MIN_KICKS_FOR_PHASE:
        return min(abs_kicks)

    phases = [t % bar_sec for t in abs_kicks]

    best_phase: float = phases[0]
    best_count: int = 0
    for p in phases:
        count = sum(1 for q in phases if _circ_dist(p, q, bar_sec) <= snap_r)
        if count > best_count:
            best_count = count
            best_phase = p

    for t in sorted(abs_kicks):
        if _circ_dist(t % bar_sec, best_phase, bar_sec) <= snap_r:
            return t

    return min(abs_kicks)


def _snare_phase_correct(
    first_t: float,
    bar_sec: float,
    beat_sec: float,
    snares: list[float],
    snap_r: float,
) -> float:
    """Korrigiert den Taktanker so dass Snares auf Beat 2+4 (Offbeat) landen.

    Nach der Anker-Bestimmung aus Kicks prüft diese Funktion, ob Snares
    tatsächlich auf Beat 2 und 4 fallen (Phase ≈ beat_sec bzw. 3·beat_sec
    relativ zum Anker). Falls nicht, testet sie alle 4 Viertel-Offsets
    und wählt den mit den meisten Offbeat-Snares.

    Anwendungsfall: ein Pickup-Snareschlag auf der "4" vor Takt 1 wird vom
    Onset-Detector fälschlich als Kick erkannt und kippt das Phasen-Histogramm
    um ein Viertel. Die Snare-Korrektur erkennt dies und verschiebt den Anker
    zurück auf Beat 1.

    Nur aktiv wenn Snares nachweislich im Offbeat-Muster schlagen
    (medianer Snare-IOI > 1.3 × beat_sec). Bei durchgehenden Viertel-Snares
    (z.B. Shuffle/Disco) wird nicht korrigiert.
    """
    if len(snares) < 4:
        return first_t
    if _snare_pattern(sorted(snares), beat_sec) != "offbeat":
        return first_t

    best_shift = 0
    best_score = -1

    for shift in range(4):
        candidate = first_t + shift * beat_sec
        score = sum(
            1 for s in snares
            if (_circ_dist((s - candidate) % bar_sec, beat_sec, bar_sec) <= snap_r
                or _circ_dist((s - candidate) % bar_sec, 3.0 * beat_sec, bar_sec) <= snap_r)
        )
        if score > best_score:
            best_score = score
            best_shift = shift

    if best_shift == 0:
        return first_t

    corrected = first_t + best_shift * beat_sec
    log.debug(
        "_snare_phase_correct: Anker %.3f → %.3f (+%d Viertel), "
        "offbeat_score=%d/%d Snares",
        first_t, corrected, best_shift, best_score, len(snares),
    )
    return corrected


def _compute_bar_grid(
    bpm: int,
    seg_start_t: float,
    seg_end_t: float,
    kicks: list[float],
    snares: list[float],
    snap_factor: float = 0.70,
) -> list[float]:
    """Berechnet Takt-Zeitstempel durch greedy Forward-Snap.

    Interner Kern von BarTracker — nicht direkt aufrufen.
    Arbeitet ausschließlich auf den übergebenen Events (kein Lookahead).

    Jeder folgende Takt wird vorwärts gesnapped:
      1. Kick im Fenster ±snap_factor × Beat → Kick gewinnt
      2. Kein Kick → Snare im selben Fenster
      3. Kein Event → mathematische Rasterposition, kein Taktstrich

    snap_r = 70 % eines Beats: Beat-2-Snare (100 % weg) und Beat-3-Kick
    (200 % weg) fallen nie ins Fenster.
    """
    if bpm <= 0:
        return []
    beat_sec = 60.0 / bpm
    bar_sec  = 4.0 * beat_sec
    snap_r   = beat_sec * snap_factor

    anchor_pool = kicks if kicks else snares
    if not anchor_pool:
        return []

    if kicks:
        first_t = _find_anchor_by_phase(kicks, bar_sec, snap_r)
    else:
        first_t = min(anchor_pool)

    # Snare-Phasen-Korrektur: sicherstellen dass Snares auf Beat 2+4 fallen.
    # Arbeitet auf dem berechneten Anker (nicht auf dem Phasen-Histogramm),
    # um auch Fehler aus dem Forward-Snap abzufangen.
    if snares:
        first_t = _snare_phase_correct(first_t, bar_sec, beat_sec, snares, snap_r)

    # Rückwärts: mathematisches Raster vor first_t bis seg_start_t
    pre_times: list[float] = []
    t = first_t - bar_sec
    while t >= seg_start_t - bar_sec * 0.1:
        pre_times.append(t)
        t -= bar_sec
    pre_times.reverse()

    # Vorwärts: greedy ab first_t
    bar_times: list[float] = [first_t]
    t = first_t

    while t < seg_end_t:
        t_grid = t + bar_sec

        kick_c = [e for e in kicks if t < e and abs(e - t_grid) <= snap_r]
        if kick_c:
            t = min(kick_c, key=lambda e: abs(e - t_grid))
            bar_times.append(t)
            continue

        snare_c = [e for e in snares if t < e and abs(e - t_grid) <= snap_r]
        if snare_c:
            t = min(snare_c, key=lambda e: abs(e - t_grid))
            bar_times.append(t)
            continue

        t = t_grid  # kein Event → Raster voranschreiben, kein Taktstrich

    return pre_times + bar_times


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

class BarTracker:
    """Inkrementeller Takt-Tracker: verarbeitet Kick/Snare-Events einzeln.

    Jedes process_kick() / process_snare() erweitert den Event-Puffer und
    löst eine Neu-Berechnung des Taktgitters aus — ausschließlich auf Basis
    der bisher gesehenen Events, kein Lookahead.

    Parameter:
        bpm:              Bekanntes BPM aus der Songdatenbank (Initialwert).
        seg_start_t:      Segment-Startzeit  (absolute WAV-Zeit in Sekunden).
        seg_end_t:        Segment-Endzeit    (absolute WAV-Zeit in Sekunden).
        snap_factor:      Snap-Fenster als Bruchteil eines Beats (default 0.70).
        use_observed_bpm: True  → BPM ab 4 Events aus den Events berechnen.
                          False → stets den übergebenen bpm-Wert verwenden.
    """

    def __init__(
        self,
        bpm: float,
        seg_start_t: float,
        seg_end_t: float,
        snap_factor: float = 0.70,
        use_observed_bpm: bool = True,
    ) -> None:
        self._bpm_initial    = float(bpm)
        self._seg_start_t    = seg_start_t
        self._seg_end_t      = seg_end_t
        self._snap_factor    = snap_factor
        self._use_observed   = use_observed_bpm

        self._kicks:     list[float] = []
        self._snares:    list[float] = []
        self._bar_times: list[float] = []
        self._current_bpm: int = int(bpm) if bpm > 0 else 0

    # ── Streaming-Interface ──────────────────────────────────────────────────

    def process_kick(self, t: float) -> None:
        """Registriert einen Kick-Onset zum Zeitpunkt t (absolute WAV-Zeit)."""
        self._kicks.append(t)
        self._update()

    def process_snare(self, t: float) -> None:
        """Registriert einen Snare-Onset zum Zeitpunkt t (absolute WAV-Zeit)."""
        self._snares.append(t)
        self._update()

    # ── Abfrage-Interface ───────────────────────────────────────────────────

    def get_latest_bars(self) -> list[float]:
        """Gibt die zuletzt berechneten Takt-Zeitstempel zurück (Kopie)."""
        return list(self._bar_times)

    def get_bpm(self) -> int:
        """Gibt den aktuell verwendeten BPM-Wert zurück."""
        return self._current_bpm

    def reset(self) -> None:
        """Setzt den Tracker zurück (alle Events und Berechnungen gelöscht)."""
        self._kicks.clear()
        self._snares.clear()
        self._bar_times.clear()
        self._current_bpm = int(self._bpm_initial) if self._bpm_initial > 0 else 0

    # ── Interne Berechnung ──────────────────────────────────────────────────

    def _update(self) -> None:
        """Aktualisiert BPM-Schätzung und berechnet Taktgitter neu."""
        if self._use_observed:
            observed = _compute_bpm_from_events(self._kicks, self._snares)
            self._current_bpm = observed if observed > 0 else int(self._bpm_initial)
        else:
            self._current_bpm = int(self._bpm_initial)

        if self._current_bpm <= 0:
            return

        self._bar_times = _compute_bar_grid(
            self._current_bpm,
            self._seg_start_t,
            self._seg_end_t,
            self._kicks,
            self._snares,
            self._snap_factor,
        )
        log.debug(
            "BarTracker update: bpm=%d  kicks=%d  snares=%d  bars=%d",
            self._current_bpm,
            len(self._kicks),
            len(self._snares),
            len(self._bar_times),
        )
