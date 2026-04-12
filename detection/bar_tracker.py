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
    tracker.finalize()          # ← nach Ende des Streams aufrufen!
    bar_times = tracker.get_latest_bars()

Performance-Design:
  _UPDATE_EVERY = 8 — Taktgitter nur alle 8 kick+snare-Events neu berechnen.
  Zwischen Updates ist get_latest_bars() stabil (gecachtes Ergebnis).
  Im Live-Betrieb folgt finalize() implizit bei jedem get_latest_bars()-Aufruf
  (Events kommen langsam genug, dass die letzte Gruppe selten > 8 ausstehende
  Events hat). In der Simulation: finalize() am Ende des Onset-Loops aufrufen.
"""
from __future__ import annotations

import bisect as _bisect
import logging
from typing import Optional

import numpy as np

log = logging.getLogger("detection.bar_tracker")

# Minimale Kicks bevor Phasen-Histogram sinnvoll ist
_MIN_KICKS_FOR_PHASE = 6

# Plausible Beat-IOI-Grenzen: 60–220 BPM → 0.27–1.0 s
_IOI_MIN = 0.27
_IOI_MAX = 1.0

# Taktgitter nur alle N kick+snare-Events neu berechnen (Performance).
# _update() bei jedem Event wäre O(n²) bei vielen Events.
# Mit _UPDATE_EVERY=8: ~8x weniger Aufrufe → deutlich schnellere Simulation.
_UPDATE_EVERY = 8


# ---------------------------------------------------------------------------
# Interne Hilfsfunktionen  (kein öffentliches API)
# ---------------------------------------------------------------------------

def _compute_bpm_from_events(kicks: list[float], snares: list[float]) -> int:
    """Berechnet BPM aus dem medianen IOI der letzten 8 Kick+Snare-Events.

    Nur die jüngsten 8 Events werden verwendet, damit eine Tempo-Änderung
    im Song oder nach einer Pause schnell übernommen wird.

    Nur die letzten 8 kombinierten Events werden verwendet — stabiler und
    O(1) statt O(n log n).  Returns 0 wenn nicht genügend Events vorhanden.
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


def _find_anchor_by_pattern(
    abs_kicks: list[float],
    abs_snares: list[float],
    grundrhythmus: dict,
    bar_sec: float,
    beat_sec: float,
    snap_r: float,
) -> Optional[float]:
    """Findet den Taktanker durch Pattern-Matching gegen den Song-Grundrhythmus.

    grundrhythmus: {"kick": [0.0, 2.0], "snare": [1.0, 3.0]}
    Positionen in Viertelschlägen (0.0=Beat1, 1.0=Beat2, 2.0=Beat3, 3.0=Beat4).

    Für jedes beobachtete Event und jede passende Pattern-Position wird eine
    Beat-1-Hypothese (= Beat-1-Zeit) erzeugt. Die Hypothese mit dem höchsten
    Pattern-Match-Score (Anzahl übereinstimmender Events) wird zurückgegeben.
    Bei Gleichstand gewinnt der früheste Kandidat (kleinste Zeit).

    Gibt None zurück wenn keine Events vorhanden oder kein Pattern definiert.
    """
    gr_kick_offsets  = [p * beat_sec for p in grundrhythmus.get("kick",  [])]
    gr_snare_offsets = [p * beat_sec for p in grundrhythmus.get("snare", [])]

    if not gr_kick_offsets and not gr_snare_offsets:
        return None

    all_events = [(t, "kick")  for t in abs_kicks ] \
               + [(t, "snare") for t in abs_snares]
    if not all_events:
        return None

    # Kandidaten: für jeden Event und jede passende Pattern-Offset → Beat-1-Zeit
    candidates: list[float] = []
    for t_ev, ev_type in all_events:
        offsets = gr_kick_offsets if ev_type == "kick" else gr_snare_offsets
        for off in offsets:
            candidates.append(t_ev - off)

    if not candidates:
        return None

    def match_score(anchor: float) -> int:
        """Anzahl beobachteter Events, die auf eine Pattern-Position passen."""
        count = 0
        for t_ev, ev_type in all_events:
            offsets = gr_kick_offsets if ev_type == "kick" else gr_snare_offsets
            rel = (t_ev - anchor) % bar_sec
            for off in offsets:
                if _circ_dist(rel, off, bar_sec) <= snap_r:
                    count += 1
                    break  # jedes Event zählt maximal 1
        return count

    # Scores vorberechnen (O(n²)), bei Gleichstand frühester Kandidat
    scored = [(c, match_score(c)) for c in candidates]
    best_score = max(s for _, s in scored)
    earliest_best = min(c for c, s in scored if s == best_score)
    return earliest_best


def _snare_pattern(snares: list[float], beat_sec: float) -> str:
    """Bestimmt ob Snare auf Offbeat (Beat 2+4) oder auf allen Vierteln schlägt."""
    if len(snares) < 4:
        return "unknown"
    s = sorted(snares)
    iois = [s[i + 1] - s[i] for i in range(len(s) - 1)]
    iois = [d for d in iois if d < beat_sec * 3.0]
    if not iois:
        return "unknown"
    median_ioi = float(np.median(iois))
    if median_ioi <= beat_sec * 1.3:
        return "allbeat"
    return "offbeat"


def _find_anchor_by_phase(
    abs_kicks: list[float],
    bar_sec: float,
    snap_r: float,
    kick_energies: list[float] = [],
) -> float:
    """Findet den ersten Kick der dominanten Beat-1-Phase.

    Vollständig vektorisiert mit numpy (O(n²) aber sehr schnell durch
    Matrix-Operationen statt Python-Schleifen):
      - Paarweise zirkuläre Abstands-Matrix (n×n)
      - Energie-gewichtete Summe pro Kandidat via Matrix-Multiplikation
      - Best-Phase durch argmax

    Gibt den frühesten Kick zurück, dessen Phase mit der Sieger-Phase
    übereinstimmt. Fallback: min(abs_kicks) falls zu wenig Daten.
    """
    if len(abs_kicks) < _MIN_KICKS_FOR_PHASE:
        return min(abs_kicks)

    energies = np.array(
        kick_energies if len(kick_energies) == len(abs_kicks) else [1.0] * len(abs_kicks),
        dtype=np.float64,
    )
    phases = np.fromiter(
        (t % bar_sec for t in abs_kicks), dtype=np.float64, count=len(abs_kicks)
    )

    # Paarweise zirkuläre Abstände (n×n) — vektorisiert statt Python-Doppelschleife
    diff  = np.abs(phases[:, None] - phases[None, :])          # (n, n)
    circ  = np.minimum(diff, bar_sec - diff)                   # zirkulär
    scores = (circ <= snap_r) @ energies                       # energie-gewichtete Scores (n,)

    best_phase = float(phases[np.argmax(scores)])

    for t in sorted(abs_kicks):
        d = abs(t % bar_sec - best_phase)
        if min(d, bar_sec - d) <= snap_r:
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
    """Korrigiert den Taktanker durch kombiniertes Kick+Snare-Scoring."""
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
        kick_score = sum(
            e for k, e in zip(kicks, energies)
            if (_circ_dist((k - candidate) % bar_sec, 0.0, bar_sec) <= snap_r
                or _circ_dist((k - candidate) % bar_sec, 2.0 * beat_sec, bar_sec) <= snap_r)
        )
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

    if scores[best_shift] <= scores[0]:
        if abs(scores[2] - scores[0]) < 1e-6 and len(kick_energies) == len(kicks):
            phase_0 = first_t % bar_sec
            phase_2 = (first_t + 2.0 * beat_sec) % bar_sec
            e_0 = sum(e for t, e in zip(kicks, kick_energies)
                      if _circ_dist(t % bar_sec, phase_0, bar_sec) <= snap_r)
            e_2 = sum(e for t, e in zip(kicks, kick_energies)
                      if _circ_dist(t % bar_sec, phase_2, bar_sec) <= snap_r)
            if e_2 > e_0 * 1.03:
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
    """Vergleicht mittlere Kick-ODF-Energie auf Beat-1-Phase vs Beat-3-Phase."""
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

    if avg_alt > avg_curr * 1.05:
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
    """Löst Beat-1-vs-Beat-3-Ambiguität per Crash-Cymbal-Events."""
    import sys

    if not crashes:
        return first_t

    candidates = [first_t, first_t + 2.0 * beat_sec]
    scores = []
    for cand in candidates:
        s = sum(
            1 for c in crashes
            if _circ_dist((c - cand) % bar_sec, 0.0, bar_sec) <= snap_r
        )
        scores.append(s)

    best = max(range(2), key=lambda i: scores[i])

    if best == 0 or scores[best] == scores[0]:
        return first_t

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
    grundrhythmus: Optional[dict] = None,
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

    Anker-Strategie (in Prioritätsreihenfolge):
      1. grundrhythmus vorhanden → Pattern-Matching gegen Song-Rhythmus
      2. Kein grundrhythmus, Crashes vorhanden → Crashes als Beat-1-Anker
      3. Kein grundrhythmus, keine Crashes, Kicks vorhanden → Energie-Histogramm
      4. Fallback: früheste Snare
    """
    import sys

    if bpm <= 0:
        return []
    beat_sec = 60.0 / bpm
    bar_sec  = 4.0 * beat_sec
    snap_r   = beat_sec * snap_factor

    if not kicks and not snares and not crashes:
        return []

    # ── Anker-Berechnung ─────────────────────────────────────────────────────
    if grundrhythmus is not None:
        # Pattern-Matching: direkter Abgleich gegen Song-Rhythmus-Muster
        pattern_anchor = _find_anchor_by_pattern(
            kicks, snares, grundrhythmus, bar_sec, beat_sec, snap_r
        )
        if pattern_anchor is not None:
            first_t = pattern_anchor
        elif kicks:
            first_t = min(kicks)
        elif snares:
            first_t = min(snares)
        else:
            return []
    elif crashes:
        # Kein Grundrhythmus: Crashes als Anker (landen fast immer auf Beat 1)
        first_t = _find_anchor_by_phase(crashes, bar_sec, snap_r)
    elif kicks:
        _energies = kick_energies if kick_energies else [1.0] * len(kicks)
        first_t = _find_anchor_by_phase(kicks, bar_sec, snap_r, _energies)
    elif snares:
        first_t = min(snares)
    else:
        return []

    if snares:
        _keng = kick_energies if kick_energies else []
        first_t = _snare_phase_correct(
            first_t, bar_sec, beat_sec, kicks, snares, snap_r, _keng
        )

    _DIAG = len(kicks) + len(snares) >= 20
    if kick_energies and len(kicks) >= _MIN_KICKS_FOR_PHASE:
        first_t = _energy_beat1_correct(
            first_t, bar_sec, beat_sec, kicks, kick_energies, snap_r
        )

    if crashes:
        first_t = _crash_beat1_correct(first_t, bar_sec, beat_sec, crashes, snap_r)

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

    # Vorwärts: greedy ab first_t — bisect statt linearer Suche (O(log n) pro Takt)
    sorted_kicks  = sorted(kicks)
    sorted_snares = sorted(snares)

    bar_times: list[float] = [first_t]
    t = first_t

    while t < seg_end_t:
        t_grid = t + bar_sec

        # Kick-Kandidaten im Fenster via bisect
        lo_k = _bisect.bisect_right(sorted_kicks, t)
        hi_k = _bisect.bisect_right(sorted_kicks, t_grid + snap_r)
        kick_c = [e for e in sorted_kicks[lo_k:hi_k] if abs(e - t_grid) <= snap_r]
        if kick_c:
            t = min(kick_c, key=lambda e: abs(e - t_grid))
            bar_times.append(t)
            continue

        # Snare-Kandidaten im Fenster via bisect
        lo_s = _bisect.bisect_right(sorted_snares, t)
        hi_s = _bisect.bisect_right(sorted_snares, t_grid + snap_r)
        snare_c = [e for e in sorted_snares[lo_s:hi_s] if abs(e - t_grid) <= snap_r]
        if snare_c:
            t = min(snare_c, key=lambda e: abs(e - t_grid))
            bar_times.append(t)
            continue

        t = t_grid  # kein Event → Raster voranschreiben, kein Taktstrich

    all_bars = pre_times + bar_times

    # ── Abschluss-Diagnostik ──────────────────────────────────────────────────
    if len(kicks) + len(snares) >= 20 and all_bars and snares:
        sorted_bars = sorted(all_bars)
        snare_positions = []
        for s in sorted(snares)[:10]:
            bi = _bisect.bisect_right(sorted_bars, s) - 1
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

    Jedes process_kick() / process_snare() erweitert den Event-Puffer.
    Das Taktgitter wird alle _UPDATE_EVERY Events neu berechnet (Performance).
    Nach Ende des Streams MUSS finalize() aufgerufen werden, um die letzten
    Events in die Berechnung einzubeziehen.

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
        grundrhythmus: Optional[dict] = None,
    ) -> None:
        self._bpm_initial    = float(bpm)
        self._seg_start_t    = seg_start_t
        self._seg_end_t      = seg_end_t
        self._snap_factor    = snap_factor
        self._use_observed   = use_observed_bpm
        self._grundrhythmus  = grundrhythmus   # {"kick": [...], "snare": [...]} oder None

        self._kicks:          list[float] = []
        self._snares:         list[float] = []
        self._crashes:        list[float] = []
        self._kick_energies:  list[float] = []
        self._snare_energies: list[float] = []
        self._bar_times:      list[float] = []
        self._current_bpm:    int = int(bpm) if bpm > 0 else 0
        self._event_count:    int = 0   # Zähler für Throttling

    # ── Streaming-Interface ──────────────────────────────────────────────────

    def process_kick(self, t: float, energy: float = 1.0) -> None:
        """Registriert einen Kick-Onset zum Zeitpunkt t (absolute WAV-Zeit)."""
        self._kicks.append(t)
        self._kick_energies.append(energy)
        self._event_count += 1
        if self._event_count % _UPDATE_EVERY == 0 or self._event_count <= _UPDATE_EVERY:
            self._update()

    def process_snare(self, t: float, energy: float = 1.0) -> None:
        """Registriert einen Snare-Onset zum Zeitpunkt t (absolute WAV-Zeit)."""
        self._snares.append(t)
        self._snare_energies.append(energy)
        self._event_count += 1
        if self._event_count % _UPDATE_EVERY == 0 or self._event_count <= _UPDATE_EVERY:
            self._update()

    def process_crash(self, t: float, energy: float = 1.0) -> None:
        """Registriert einen Crash-Cymbal-Onset.

        Crashes lösen keine Taktgitter-Neuberechnung aus (sie ändern das BPM
        nicht). Sie werden bei der nächsten _update()-Runde einbezogen.
        """
        self._crashes.append(t)

    def finalize(self) -> None:
        """Erzwingt finale Taktgitter-Berechnung nach Ende des Event-Streams.

        Aufrufen nachdem alle Events verarbeitet wurden (Ende des Onset-Loops
        in der Simulation, oder am Ende eines Song-Segments im Live-Betrieb).
        Stellt sicher, dass auch die letzten Events (die kein _UPDATE_EVERY
        vollständig gemacht haben) in die Berechnung einfließen.
        """
        if self._kicks or self._snares:
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
        self._crashes.clear()
        self._kick_energies.clear()
        self._snare_energies.clear()
        self._bar_times.clear()
        self._current_bpm = int(self._bpm_initial) if self._bpm_initial > 0 else 0
        self._event_count = 0

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
            self._grundrhythmus,
        )
        log.debug(
            "BarTracker update: bpm=%d  kicks=%d  snares=%d  bars=%d",
            self._current_bpm,
            len(self._kicks),
            len(self._snares),
            len(self._bar_times),
        )
