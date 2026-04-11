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
    """Berechnet BPM aus dem medianen IOI der letzten 8 Kick+Snare-Events.

    Nur die jüngsten 8 Events werden verwendet, damit eine Tempo-Änderung
    im Song oder nach einer Pause schnell übernommen wird.

    Returns 0 wenn nicht genügend Events vorhanden.
    """
    all_t = sorted(kicks + snares)
    recent = all_t[-8:]   # nur die letzten 8 Events
    if len(recent) < 4:
        return 0
    iois = [recent[i + 1] - recent[i] for i in range(len(recent) - 1)]
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
    kick_energies: list[float] = [],
) -> float:
    """Findet den ersten Kick der dominanten Beat-1-Phase.

    Phasen-Histogram über alle bisher gesehenen Kicks: die Phase mit dem
    höchsten Energie-Gewicht ist der echte Beat-1-Offset. Intro-Noise trifft
    zufällige Phasen (je ~1 Stimme), Hauptteil-Kicks clustern auf einer
    Phase (hohe Energie) → die Sieger-Phase ist automatisch der echte
    Beat-1-Offset.

    kick_energies: ODF-Energie pro Kick (gewichtet statt 1 pro Kick).
    Wenn leer, wird jeder Kick mit 1.0 gewichtet (identisches Verhalten).

    Gibt den frühesten Kick zurück, dessen Phase mit der Sieger-Phase
    übereinstimmt. Fallback: min(abs_kicks) falls zu wenig Daten.
    """
    if len(abs_kicks) < _MIN_KICKS_FOR_PHASE:
        return min(abs_kicks)

    energies = kick_energies if len(kick_energies) == len(abs_kicks) else [1.0] * len(abs_kicks)
    phases = [t % bar_sec for t in abs_kicks]

    best_phase: float = phases[0]
    best_score: float = 0.0
    for j, p in enumerate(phases):
        score = sum(
            energies[k] for k, q in enumerate(phases)
            if _circ_dist(p, q, bar_sec) <= snap_r
        )
        if score > best_score:
            best_score = score
            best_phase = p

    for t in sorted(abs_kicks):
        if _circ_dist(t % bar_sec, best_phase, bar_sec) <= snap_r:
            return t

    return min(abs_kicks)


def _snare_phase_correct(
    first_t: float,
    bar_sec: float,
    beat_sec: float,
    kicks: list[float],
    snares: list[float],
    snap_r: float,
    kick_energies: list[float] = [],
) -> float:
    """Korrigiert den Taktanker durch kombiniertes Kick+Snare-Scoring.

    Testet alle 4 Viertel-Offsets des Ankers und wählt den, bei dem die
    meisten Kicks auf Beat 1+3 UND die meisten Snares auf Beat 2+4 fallen
    (energie-gewichteter kombinierter Score).

    Anwendungsfall: ein Pickup-Snareschlag auf der "4" vor Takt 1 wird vom
    Onset-Detector fälschlich als Kick erkannt → Phasen-Histogram wählt
    Beat-4-Phase als Anker → Taktgitter 1 Viertel zu früh.

    Kick-Score ist energie-gewichtet: Downbeat (Beat 1) wird typischerweise
    lauter gespielt → höhere ODF-Energie → shift, der Beat 1 auf mehr Energie
    konzentriert, gewinnt bei Gleichstand.

    Korrektur wird nur angewendet wenn der beste Shift strikt besser ist.
    Bei Gleichstand zwischen Shift 0 und Shift 2 (Beat-1-vs-Beat-3-Ambiguität)
    entscheidet die Energie-Summe auf der jeweiligen Phase.
    """
    if len(snares) < 4:
        return first_t

    import sys

    energies = kick_energies if len(kick_energies) == len(kicks) else [1.0] * len(kicks)

    scores: list[float] = []
    for shift in range(4):
        candidate = first_t + shift * beat_sec
        snare_score = sum(
            1 for s in snares
            if (_circ_dist((s - candidate) % bar_sec, beat_sec, bar_sec) <= snap_r
                or _circ_dist((s - candidate) % bar_sec, 3.0 * beat_sec, bar_sec) <= snap_r)
        )
        # Energie-gewichteter Kick-Score: stärkere Kicks auf Beat 1+3 erhöhen Score
        kick_score = sum(
            e for k, e in zip(kicks, energies)
            if (_circ_dist((k - candidate) % bar_sec, 0.0, bar_sec) <= snap_r
                or _circ_dist((k - candidate) % bar_sec, 2.0 * beat_sec, bar_sec) <= snap_r)
        )
        # Snares zählen ganzzahlig, Kick-Energie normiert auf Vergleichbarkeit
        n_kicks_on_beat = sum(
            1 for k in kicks
            if (_circ_dist((k - candidate) % bar_sec, 0.0, bar_sec) <= snap_r
                or _circ_dist((k - candidate) % bar_sec, 2.0 * beat_sec, bar_sec) <= snap_r)
        )
        avg_kick_e = kick_score / max(1, n_kicks_on_beat)
        scores.append(snare_score + avg_kick_e)

    best_shift = max(range(4), key=lambda i: scores[i])

    if best_shift == 0:
        return first_t

    # Korrektur nur wenn bester Shift strikt besser als Shift-0
    if scores[best_shift] <= scores[0]:
        # Beat-1-vs-Beat-3-Gleichstand: Energie-Summe als Tie-Breaker.
        # shift=2 landet auf dem anderen Kandidaten (beat1↔beat3).
        # Der mit höherer Gesamt-Kick-Energie ist typischerweise Beat 1 (Downbeat).
        if abs(scores[2] - scores[0]) < 1e-6 and len(kick_energies) == len(kicks):
            phase_0 = first_t % bar_sec
            phase_2 = (first_t + 2.0 * beat_sec) % bar_sec
            e_0 = sum(e for t, e in zip(kicks, kick_energies)
                      if _circ_dist(t % bar_sec, phase_0, bar_sec) <= snap_r)
            e_2 = sum(e for t, e in zip(kicks, kick_energies)
                      if _circ_dist(t % bar_sec, phase_2, bar_sec) <= snap_r)
            if e_2 > e_0 * 1.03:  # alternative Phase 3 %+ energiereicher → Beat 1
                corrected = first_t + 2.0 * beat_sec
                print(
                    f"[BAR] _snare_phase_correct tie-break: {first_t:.3f} → {corrected:.3f} "
                    f"(+2 Beats via Energie-Tie-Breaker, e0={e_0:.4f} e2={e_2:.4f})",
                    file=sys.stderr,
                )
                return corrected
        return first_t

    corrected = first_t + best_shift * beat_sec
    print(
        f"[BAR] _snare_phase_correct: {first_t:.3f} → {corrected:.3f} "
        f"(+{best_shift} Beats, scores={[f'{s:.2f}' for s in scores]})",
        file=sys.stderr,
    )
    return corrected


def _energy_beat1_correct(
    first_t: float,
    bar_sec: float,
    beat_sec: float,
    kicks: list[float],
    kick_energies: list[float],
    snap_r: float,
) -> float:
    """Vergleicht mittlere Kick-ODF-Energie auf Beat-1-Phase vs Beat-3-Phase.

    Hintergrund: Drummer akzentuieren Beat 1 (Downbeat) typischerweise etwas stärker
    als Beat 3 (sekundärer Downbeat) — höhere ODF-Energie beim Kick.
    Ist die alternative Phase (first_t + 2*beat) SIGNIFIKANT energiereicher,
    ist sie wahrscheinlicher Beat 1.

    Schwelle: alt_avg > curr_avg * 1.05  →  Korrektur (5 % Unterschied reicht).
    Gibt first_t unverändert zurück wenn kein klarer Gewinner.
    """
    import sys

    if not kick_energies or len(kick_energies) != len(kicks):
        return first_t

    phase_curr = first_t % bar_sec
    phase_alt  = (first_t + 2.0 * beat_sec) % bar_sec

    e_curr = [e for t, e in zip(kicks, kick_energies)
              if _circ_dist(t % bar_sec, phase_curr, bar_sec) <= snap_r]
    e_alt  = [e for t, e in zip(kicks, kick_energies)
              if _circ_dist(t % bar_sec, phase_alt,  bar_sec) <= snap_r]

    if not e_curr or not e_alt:
        return first_t

    avg_curr = sum(e_curr) / len(e_curr)
    avg_alt  = sum(e_alt)  / len(e_alt)

    _DIAG = len(kicks) >= 10
    if _DIAG:
        print(
            f"[BAR] energy_beat1: phase_curr_avg={avg_curr:.4f}  "
            f"phase_alt_avg={avg_alt:.4f}  ratio={avg_alt/max(avg_curr,1e-9):.2f}",
            file=sys.stderr,
        )

    if avg_alt > avg_curr * 1.05:   # alternative Phase >5 % energiereicher → Beat 1
        corrected = first_t + 2.0 * beat_sec
        print(
            f"[BAR] energy_beat1: {first_t:.3f} → {corrected:.3f} (+2 Beats, "
            f"avg {avg_curr:.4f} → {avg_alt:.4f})",
            file=sys.stderr,
        )
        return corrected

    return first_t


def _crash_beat1_correct(
    first_t: float,
    bar_sec: float,
    beat_sec: float,
    crashes: list[float],
    snap_r: float,
) -> float:
    """Löst Beat-1-vs-Beat-3-Ambiguität per Crash-Cymbal-Events.

    Crashes passieren fast immer auf Beat 1 (seltener Beat 3, fast nie Beat 2/4).
    Gegeben zwei Kandidaten für den Taktanker (first_t = Beat-1 ODER Beat-3):
    Wähle den Kandidaten, auf den die meisten Crashes als Beat 1 fallen.

    Crash auf Beat 1: (crash_t - cand) % bar_sec ≈ 0
    Crash auf Beat 3: (crash_t - (cand+2*beat)) % bar_sec ≈ 0
      → das ist dann ein Beat-3-Crash, kein Beat-1-Crash

    Wenn kein eindeutiger Gewinner → first_t unverändert.
    """
    import sys

    if not crashes:
        return first_t

    # Kandidat A: first_t ist Beat 1  (unverändert)
    # Kandidat B: first_t ist Beat 3  → echter Beat 1 = first_t + 2 * beat_sec
    candidates = [first_t, first_t + 2.0 * beat_sec]
    scores = []
    for cand in candidates:
        # Zähle Crashes, die auf Beat 1 (Phase ≈ 0) relativ zu cand fallen
        s = sum(
            1 for c in crashes
            if _circ_dist((c - cand) % bar_sec, 0.0, bar_sec) <= snap_r
        )
        scores.append(s)

    best = max(range(2), key=lambda i: scores[i])

    if best == 0 or scores[best] == scores[0]:
        return first_t   # kein eindeutiger Gewinner oder bereits richtig

    corrected = candidates[best]
    print(
        f"[BAR] crash_beat1_correct: {first_t:.3f} → {corrected:.3f} "
        f"(+{best * 2} Beats, crash_scores={scores})",
        file=sys.stderr,
    )
    return corrected


def _compute_bar_grid(
    bpm: int,
    seg_start_t: float,
    seg_end_t: float,
    kicks: list[float],
    snares: list[float],
    snap_factor: float = 0.70,
    kick_energies: list[float] = [],
    crashes: list[float] = [],
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
    import sys

    if bpm <= 0:
        return []
    beat_sec = 60.0 / bpm
    bar_sec  = 4.0 * beat_sec
    snap_r   = beat_sec * snap_factor

    anchor_pool = kicks if kicks else snares
    if not anchor_pool:
        return []

    if kicks:
        _energies = kick_energies if kick_energies else [1.0] * len(kicks)
        first_t = _find_anchor_by_phase(kicks, bar_sec, snap_r, _energies)
    else:
        first_t = min(anchor_pool)

    # Snare-Phasen-Korrektur: sicherstellen dass Snares auf Beat 2+4 fallen.
    # Energie-gewichteter Score + Energie-Tie-Breaker für Beat-1-vs-Beat-3.
    if snares:
        _keng = kick_energies if kick_energies else []
        first_t = _snare_phase_correct(
            first_t, bar_sec, beat_sec, kicks, snares, snap_r, _keng
        )

    # Beat-1-vs-Beat-3-Korrektur (Energie-basiert): vergleicht mittlere Kick-ODF
    # auf den beiden Phasen. Beat 1 ist typischerweise lauter → höhere ODF.
    # Unabhängiges Signal von Snare-Scoring — bricht die Kick/Snare-Symmetrie.
    _DIAG = len(kicks) + len(snares) >= 20
    if kick_energies and len(kicks) >= _MIN_KICKS_FOR_PHASE:
        first_t = _energy_beat1_correct(
            first_t, bar_sec, beat_sec, kicks, kick_energies, snap_r
        )

    # Beat-1-vs-Beat-3-Korrektur (Crash-basiert): Crashes passieren fast nur auf
    # Beat 1 → sehr zuverlässige Phasen-Fixierung. Überschreibt Energie-Korrektur.
    if crashes:
        first_t = _crash_beat1_correct(first_t, bar_sec, beat_sec, crashes, snap_r)

    # ── Diagnostik (nur bei ausreichend Events, um Rauschen zu vermeiden) ─────
    if _DIAG:
        print(
            f"[BAR] grid: seg_start={seg_start_t:.3f}  anchor={first_t:.3f}"
            f"  offset={(first_t - seg_start_t) / beat_sec:+.2f} beats"
            f"  bpm={bpm}",
            file=sys.stderr,
        )

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

    all_bars = pre_times + bar_times

    # ── Abschluss-Diagnostik (nur wenn genug Daten da sind) ───────────────────
    if len(kicks) + len(snares) >= 20 and all_bars and snares:
        import bisect
        sorted_bars = sorted(all_bars)
        snare_positions = []
        for s in sorted(snares)[:10]:
            bi = bisect.bisect_right(sorted_bars, s) - 1
            if 0 <= bi < len(sorted_bars):
                pos = (s - sorted_bars[bi]) / beat_sec
                snare_positions.append(f"{pos:.2f}")
        print(
            f"[BAR] Snare-Positionen in Takten (Beat 2≈1.0, Beat 4≈3.0): "
            f"{snare_positions}",
            file=sys.stderr,
        )
        print(
            f"[BAR] Erste 5 Takte (abs): "
            f"{[f'{t:.3f}' for t in sorted_bars[:5]]}",
            file=sys.stderr,
        )

    return all_bars


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
        self._crashes:   list[float] = []
        self._kick_energies:  list[float] = []
        self._snare_energies: list[float] = []
        self._bar_times: list[float] = []
        self._current_bpm: int = int(bpm) if bpm > 0 else 0

    # ── Streaming-Interface ──────────────────────────────────────────────────

    def process_kick(self, t: float, energy: float = 1.0) -> None:
        """Registriert einen Kick-Onset zum Zeitpunkt t (absolute WAV-Zeit)."""
        self._kicks.append(t)
        self._kick_energies.append(energy)
        self._update()

    def process_snare(self, t: float, energy: float = 1.0) -> None:
        """Registriert einen Snare-Onset zum Zeitpunkt t (absolute WAV-Zeit)."""
        self._snares.append(t)
        self._snare_energies.append(energy)
        self._update()

    def process_crash(self, t: float, energy: float = 1.0) -> None:
        """Registriert einen Crash-Cymbal-Onset zum Zeitpunkt t (absolute WAV-Zeit).

        Crashes werden für die Beat-1-vs-Beat-3-Phasenkorrektur genutzt.
        Sie lösen keine Taktgitter-Neuberechnung aus (crashes ändern das BPM nicht).
        """
        self._crashes.append(t)

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
        self._crashes.clear()
        self._kick_energies.clear()
        self._snare_energies.clear()
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
            self._kick_energies,
            self._crashes,
        )
        log.debug(
            "BarTracker update: bpm=%d  kicks=%d  snares=%d  bars=%d",
            self._current_bpm,
            len(self._kicks),
            len(self._snares),
            len(self._bar_times),
        )
