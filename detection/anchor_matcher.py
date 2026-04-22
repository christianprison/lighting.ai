"""anchor_matcher.py — Streaming Anchor Matching.

Verarbeitet Song-Anker sequentiell (cursor-basiert): wartet stur auf den
jeweils nächsten Anker in der DB-Reihenfolge. Kein Lookahead.

Prime Directive: identischer Code in Simulation und Live.
"""
from __future__ import annotations

import os as _os
import sys
from collections import deque
from typing import Optional


def _log(msg: str) -> None:
    """Schreibt direkt auf fd 2 — umgeht jedes Python-IO-Buffering."""
    _os.write(2, (msg + "\n").encode("utf-8", errors="replace"))

import numpy as np

# Kanal-Indices (XR18-Belegung, 0-basiert)
CH_PETE    = 0
CH_AXEL    = 1
CH_CHRIS   = 2
CH_GUITAR  = 4
CH_BASS    = 5
CH_KICK    = 8
CH_SNARE   = 9
CH_OH_L    = 13
CH_OH_R    = 14

# RMS-Schwellwerte (close-miked Signale nach Fader)
_RMS_VOCAL_ON   = 0.012
_RMS_VOCAL_OFF  = 0.005
_RMS_GUITAR_ON  = 0.008
_RMS_GUITAR_OFF = 0.003
_RMS_BASS_ON    = 0.006
_RMS_BASS_OFF   = 0.002
_RMS_DRUM_ON    = 0.005   # Kick oder Snare
_RMS_DRUM_OFF   = 0.002
_RMS_SILENCE    = 0.002   # alle Kanäle

# Minimum-Abstand zwischen zwei aufeinanderfolgenden Anker-Matches
_MIN_MATCH_GAP = 1.5   # Sekunden

_RMS_DIAG_INTERVAL = 5.0   # Sekunden zwischen RMS-Diagnose-Prints

_VOCAL_BY_TYPE: dict[str, int] = {
    "pete":      CH_PETE,
    "axel":      CH_AXEL,
    "christian": CH_CHRIS,
}


def _rms(arr: np.ndarray) -> float:
    a = arr.astype(np.float32)
    return float(np.sqrt(np.mean(a * a))) if len(a) > 0 else 0.0


def _event_to_trigger(anc_type: str, event: str) -> str:
    """Gibt den Trigger-Key für einen Anker zurück."""
    t = anc_type.lower()
    e = event.lower()

    if t == "drum":
        if "crash" in e:
            return "crash"
        if "snare-roll" in e or "snare roll" in e:
            return "snare_roll"
        if "fill" in e:
            return "drum_fill"
        if "snare" in e:
            return "snare"
        if "pause" in e:
            return "drum_silence"
        # Einsatz, Beat beginnt, Nur Kick, Breakbeat → nächster Kick
        return "kick"

    if t in _VOCAL_BY_TYPE:
        if "schrei" in e or "ausruf" in e:
            return f"{t}_peak"
        if "pause" in e or "hört auf" in e:
            return f"{t}_silence"
        if "harmony" in e:
            return "harmony"
        return f"{t}_onset"

    if t == "guitar":
        if "pause" in e or "endet" in e:
            return "guitar_silence"
        return "guitar_onset"

    if t == "bass":
        if "pause" in e:
            return "bass_silence"
        return "bass_onset"

    if t == "silence":
        if "nur schlagzeug" in e:
            return "drums_only"
        return "full_silence"

    # keys + other: kein dedizierter Kanal → nächster Kick als Fallback
    return "kick"


class AnchorMatcher:
    """Sequentieller Streaming-Anker-Matcher.

    Wartet auf den ersten Anker, dann den zweiten usw.
    Drei Eintrittspunkte je Block:
      process_kick(t_abs, energy)  — nach Kick-Onset
      process_snare(t_abs, energy) — nach Snare-Onset
      process_crash(t_abs, energy) — nach Crash-Onset
      process_block(block, t_abs)  — einmal pro Block für RMS-basierte Trigger
    Jede Methode gibt den gematchten Anker (dict) oder None zurück.
    """

    _SNARE_ROLL_WIN = 0.4   # s — min 4 Snares in diesem Fenster
    _FILL_WIN       = 0.6   # s — min 5 Onsets (Kick+Snare) in diesem Fenster
    _RMS_BUF        = 30    # Blöcke für gleitenden RMS-Mittelwert

    def __init__(
        self,
        anchors: list,
        bpm: float,
        seg_start_t: float,
        sample_rate: int,
        block_size: int,
    ) -> None:
        self._anchors     = sorted(anchors, key=lambda a: (a.get("pos", 9999), a.get("bar_num", 0)))
        self._cursor      = 0
        self._bpm         = bpm
        self._seg_start_t = seg_start_t

        self._kick_times:     deque[float] = deque(maxlen=32)
        self._snare_times:    deque[float] = deque(maxlen=32)
        self._snare_energies: deque[float] = deque(maxlen=24)

        _tracked = (CH_PETE, CH_AXEL, CH_CHRIS, CH_GUITAR, CH_BASS,
                    CH_KICK, CH_SNARE, CH_OH_L, CH_OH_R)
        self._rms_buf:  dict[int, deque[float]] = {ch: deque(maxlen=self._RMS_BUF) for ch in _tracked}
        self._rms_prev: dict[int, float]        = {ch: 0.0 for ch in _tracked}

        self._last_match_t: float = -999.0
        self._last_logged_cursor: int = -1   # verhindert Wiederholung derselben Wartezeile
        self._last_rms_diag_t: float = -999.0

        _log(f"[ANKER] {len(self._anchors)} Anker geladen:")
        for i, a in enumerate(self._anchors):
            trigger = _event_to_trigger(a.get("type", ""), a.get("event", ""))
            _log(
                f"[ANKER]   #{i+1:02d}  {a.get('type','?'):10s}  "
                f"{a.get('event','?'):30s}  trigger={trigger}  bar={a.get('bar_num','?')}"
            )
        if self._anchors:
            self._log_waiting()

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def done(self) -> bool:
        return self._cursor >= len(self._anchors)

    def process_kick(self, t_abs: float, energy: float) -> Optional[dict]:
        self._kick_times.append(t_abs)
        trigger = self._current_trigger()
        if trigger in ("kick", "drum_onset"):
            return self._try_match(t_abs)
        if trigger == "drum_fill":
            return self._check_fill(t_abs)
        return None

    def process_snare(self, t_abs: float, energy: float) -> Optional[dict]:
        self._snare_times.append(t_abs)
        self._snare_energies.append(energy)
        trigger = self._current_trigger()
        if trigger == "snare":
            med = float(np.median(list(self._snare_energies))) if self._snare_energies else 0.0
            if energy >= max(med * 1.3, 0.01):
                return self._try_match(t_abs)
        elif trigger == "snare_roll":
            return self._check_snare_roll(t_abs)
        elif trigger == "drum_fill":
            return self._check_fill(t_abs)
        return None

    def process_crash(self, t_abs: float, energy: float) -> Optional[dict]:
        if self._current_trigger() == "crash":
            return self._try_match(t_abs)
        return None

    def process_block(self, block: np.ndarray, t_abs: float) -> Optional[dict]:
        """RMS-basierte Trigger: Einsatz/Pause von Vokal/Guitar/Bass/Stille."""
        n_ch = block.shape[1] if block.ndim == 2 else 1
        for ch, buf in self._rms_buf.items():
            if ch < n_ch:
                buf.append(_rms(block[:, ch]))

        trigger = self._current_trigger()
        if not trigger:
            return None
        return self._check_rms_trigger(trigger, t_abs)

    # ── Internes ───────────────────────────────────────────────────────────────

    def _log_waiting(self) -> None:
        """Loggt einmalig welchen Anker wir gerade erwarten."""
        if self._cursor == self._last_logged_cursor or self.done:
            return
        self._last_logged_cursor = self._cursor
        anc = self._anchors[self._cursor]
        trigger = _event_to_trigger(anc.get("type", ""), anc.get("event", ""))
        _log(
            f"[ANKER] warte auf #{self._cursor+1:02d}  "
            f"{anc.get('type','?'):10s}  {anc.get('event','?'):30s}  "
            f"trigger={trigger}"
        )

    def _current_trigger(self) -> str:
        if self.done:
            return ""
        anc = self._anchors[self._cursor]
        self._log_waiting()
        return _event_to_trigger(anc.get("type", ""), anc.get("event", ""))

    def _try_match(self, t: float) -> Optional[dict]:
        if self.done:
            return None
        if t - self._last_match_t < _MIN_MATCH_GAP:
            t_rel = t - self._seg_start_t
            remaining = _MIN_MATCH_GAP - (t - self._last_match_t)
            _log(
                f"[ANKER] cooldown aktiv — #{self._cursor+1} noch gesperrt "
                f"({remaining:.2f}s)  t={t_rel:.2f}s"
            )
            return None
        anc = dict(self._anchors[self._cursor])
        anc["t_detected"] = t
        t_rel = t - self._seg_start_t
        _log(
            f"[ANKER] ✓ ERKANNT #{self._cursor+1:02d}  "
            f"{anc.get('type','?'):10s}  {anc.get('event','?'):30s}  "
            f"t={t_rel:.2f}s"
        )
        self._cursor += 1
        self._last_match_t = t
        if not self.done:
            self._last_logged_cursor = -1   # nächste _log_waiting() soll sofort loggen
        else:
            _log("[ANKER] alle Anker erkannt.")
        return anc

    def _avg_rms(self, ch: int) -> float:
        buf = self._rms_buf.get(ch)
        return float(np.mean(list(buf))) if buf else 0.0

    def _check_snare_roll(self, t: float) -> Optional[dict]:
        recent = [s for s in self._snare_times if t - s <= self._SNARE_ROLL_WIN]
        if len(recent) >= 4:
            return self._try_match(t)
        return None

    def _check_fill(self, t: float) -> Optional[dict]:
        all_on = (
            [k for k in self._kick_times  if t - k <= self._FILL_WIN] +
            [s for s in self._snare_times if t - s <= self._FILL_WIN]
        )
        if len(all_on) >= 5:
            return self._try_match(t)
        return None

    def _onset_transition(self, ch: int, t: float, on: float, off: float) -> Optional[dict]:
        prev = self._rms_prev.get(ch, 0.0)
        curr = self._avg_rms(ch)
        if curr > on:
            self._rms_prev[ch] = curr
            if prev < on * 0.5:
                return self._try_match(t)
        elif curr < off:
            self._rms_prev[ch] = 0.0  # signal clearly quiet → reset so next onset is fresh
        return None

    def _silence_transition(self, ch: int, t: float, on: float, off: float) -> Optional[dict]:
        prev = self._rms_prev.get(ch, 0.0)
        curr = self._avg_rms(ch)
        if curr > on:
            self._rms_prev[ch] = curr  # track high watermark while loud
        if curr < off and prev > on:
            return self._try_match(t)
        return None

    def _maybe_rms_diag(self, trigger: str, t: float) -> None:
        """Periodische RMS-Diagnose für aktiven RMS-Trigger (alle 5 s)."""
        if t - self._last_rms_diag_t < _RMS_DIAG_INTERVAL:
            return
        self._last_rms_diag_t = t
        t_rel = t - self._seg_start_t
        info: list[str] = []
        for vtype, ch in _VOCAL_BY_TYPE.items():
            if trigger.startswith(vtype):
                curr = self._avg_rms(ch)
                info.append(
                    f"{vtype}(CH{ch})={curr:.4f}  "
                    f"thresh={_RMS_VOCAL_ON:.4f}  prev={self._rms_prev.get(ch, 0.0):.4f}"
                )
                break
        if trigger in ("guitar_onset", "guitar_silence"):
            curr = self._avg_rms(CH_GUITAR)
            info.append(
                f"guitar(CH{CH_GUITAR})={curr:.4f}  "
                f"thresh={_RMS_GUITAR_ON:.4f}  prev={self._rms_prev.get(CH_GUITAR, 0.0):.4f}"
            )
        elif trigger in ("bass_onset", "bass_silence"):
            curr = self._avg_rms(CH_BASS)
            info.append(
                f"bass(CH{CH_BASS})={curr:.4f}  "
                f"thresh={_RMS_BASS_ON:.4f}  prev={self._rms_prev.get(CH_BASS, 0.0):.4f}"
            )
        elif trigger in ("drum_silence", "drums_only"):
            kick = self._avg_rms(CH_KICK)
            snare = self._avg_rms(CH_SNARE)
            info.append(f"kick(CH{CH_KICK})={kick:.4f}  snare(CH{CH_SNARE})={snare:.4f}  thresh={_RMS_DRUM_ON:.4f}")
        elif trigger == "harmony":
            info.append("  ".join(f"{vt}(CH{ch})={self._avg_rms(ch):.4f}" for vt, ch in _VOCAL_BY_TYPE.items()))
        elif trigger == "full_silence":
            info.append("  ".join(
                f"CH{ch}={self._avg_rms(ch):.4f}"
                for ch in (CH_PETE, CH_AXEL, CH_GUITAR, CH_BASS, CH_KICK, CH_SNARE)
            ))
        if info:
            _log(f"[ANKER] RMS  trigger={trigger}  t={t_rel:.1f}s  " + "  ".join(info))

    def _check_rms_trigger(self, trigger: str, t: float) -> Optional[dict]:
        self._maybe_rms_diag(trigger, t)
        # Vokal-Trigger
        for vtype, ch in _VOCAL_BY_TYPE.items():
            if trigger == f"{vtype}_onset":
                return self._onset_transition(ch, t, _RMS_VOCAL_ON, _RMS_VOCAL_OFF)
            if trigger == f"{vtype}_silence":
                return self._silence_transition(ch, t, _RMS_VOCAL_ON, _RMS_VOCAL_OFF)
            if trigger == f"{vtype}_peak":
                curr = self._avg_rms(ch)
                self._rms_prev[ch] = curr
                hist = list(self._rms_buf[ch])
                if len(hist) >= 5:
                    med = float(np.median(hist[:-2]))
                    if curr > med * 2.5 and curr > _RMS_VOCAL_ON * 2:
                        return self._try_match(t)
                return None

        if trigger == "harmony":
            n_active = sum(1 for ch in _VOCAL_BY_TYPE.values() if self._avg_rms(ch) > _RMS_VOCAL_ON)
            if n_active >= 2:
                return self._try_match(t)

        elif trigger == "guitar_onset":
            return self._onset_transition(CH_GUITAR, t, _RMS_GUITAR_ON, _RMS_GUITAR_OFF)
        elif trigger == "guitar_silence":
            return self._silence_transition(CH_GUITAR, t, _RMS_GUITAR_ON, _RMS_GUITAR_OFF)
        elif trigger == "bass_onset":
            return self._onset_transition(CH_BASS, t, _RMS_BASS_ON, _RMS_BASS_OFF)
        elif trigger == "bass_silence":
            return self._silence_transition(CH_BASS, t, _RMS_BASS_ON, _RMS_BASS_OFF)

        elif trigger == "drum_silence":
            kick_now  = self._avg_rms(CH_KICK)
            snare_now = self._avg_rms(CH_SNARE)
            drum_now  = kick_now + snare_now
            drum_prev = self._rms_prev.get(CH_KICK, 0.0) + self._rms_prev.get(CH_SNARE, 0.0)
            if kick_now > _RMS_DRUM_ON:
                self._rms_prev[CH_KICK]  = kick_now
            if snare_now > _RMS_DRUM_ON:
                self._rms_prev[CH_SNARE] = snare_now
            if drum_now < _RMS_DRUM_OFF and drum_prev > _RMS_DRUM_ON:
                return self._try_match(t)

        elif trigger == "drums_only":
            drum_active = (self._avg_rms(CH_KICK) > _RMS_DRUM_ON or
                           self._avg_rms(CH_SNARE) > _RMS_DRUM_ON)
            others_quiet = all(
                self._avg_rms(ch) < _RMS_VOCAL_OFF
                for ch in (CH_PETE, CH_AXEL, CH_GUITAR, CH_BASS)
            )
            if drum_active and others_quiet:
                return self._try_match(t)

        elif trigger == "full_silence":
            chs = (CH_PETE, CH_AXEL, CH_GUITAR, CH_BASS, CH_KICK, CH_SNARE, CH_OH_L)
            if all(self._avg_rms(ch) < _RMS_SILENCE for ch in chs):
                return self._try_match(t)

        return None
