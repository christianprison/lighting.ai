"""timeline.py — Scrollable, zoomable waveform + event timeline widget.

Layout (top to bottom):
  Time ruler   (RULER_H px)
  Event strip  (EVENTS_H px)
  Track rows   (track["h"] px each, separated by TRACK_GAP)

Left LABEL_W pixels are the sticky label column — drawn last so they
always appear on top of the scrolled waveform content.
Label column right portion contains per-track M (mute) and S (solo) buttons.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
from PyQt6.QtCore import Qt, QPoint, QRect, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPolygon,
)
from PyQt6.QtWidgets import QWidget, QScrollBar, QSizePolicy, QToolTip

from session import SongSegment
from peaks import TrackPeaks, CHANNEL_LABELS, SUM_CHANNELS, DISPLAY_CHANNELS
from annotation import BarMarker

# ── Layout ────────────────────────────────────────────────────────────────────
LABEL_W   = 196
RULER_H   = 28
EVENTS_H  = 26   # halved from 52
ANNOT_H   = 0    # annotation strip entfernt (war immer leer)
MIX_H     = 44
TRACK_H   = 27
TRACK_GAP = 2
SCROLL_H  = 14

# Solo/Mute button geometry (relative to left edge of label column)
BTN_W    = 18
BTN_H    = 13
BTN_M_X  = LABEL_W - 44   # M button left x
BTN_S_X  = LABEL_W - 24   # S button left x

# ── Colors ────────────────────────────────────────────────────────────────────
C_BG     = QColor("#08090d")
C_BG2    = QColor("#0e1017")
C_BG3    = QColor("#151820")
C_BORDER = QColor("#1e2230")
C_T1     = QColor("#eef0f6")
C_T2     = QColor("#c4c8d8")
C_T3     = QColor("#a0a4b8")
C_T4     = QColor("#5c6080")
C_GREEN  = QColor("#00dc82")
C_AMBER  = QColor("#f0a030")
C_CYAN   = QColor("#38bdf8")
C_RED    = QColor("#ff3b5c")

WF_SUM   = QColor("#00dc82")
WF_CH    = QColor("#38bdf8")
WF_SUM_F = QColor(0x00, 0xdc, 0x82, 55)
WF_CH_F  = QColor(0x38, 0xbd, 0xf8, 45)
CURSOR_C = QColor("#ff3b5c")

FONT_MONO  = QFont("DM Mono", 8)
FONT_LABEL = QFont("Sora", 9)
FONT_TIME  = QFont("DM Mono", 9)
FONT_BTN   = QFont("DM Mono", 7)

# ── Per-track event markers ───────────────────────────────────────────────────
# Channels that get ALL beat markers (◆ for every beat)
BEAT_MARKER_CHS: frozenset[int] = frozenset({13, 14})   # OH L, OH R
# Channels that get snare markers
SNARE_MARKER_CHS: frozenset[int] = frozenset({9})        # Snare
# Channels that get downbeat-only markers
KICK_MARKER_CHS: frozenset[int] = frozenset({8})         # Kick

_DIAMOND_R = 4   # half-size of diamond marker (pixels)

# ── Track definitions (in display order) ─────────────────────────────────────
# Main L+R entfernt — die Overview-Zeile oben zeigt dieselbe Hüllkurve (CH 16+17)

TRACKS: list[dict] = []

# Tom channels merged into one overlay track
_TOM_CHS = (10, 11, 12)
_tom_added = False

# OH channels merged into one overlay track (like Toms)
_OH_CHS = (13, 14)
_oh_added = False

for _ch in DISPLAY_CHANNELS:
    if _ch in SUM_CHANNELS:
        continue   # skip individual Main L / Main R
    if _ch in _TOM_CHS:
        if not _tom_added:
            TRACKS.append({
                "ch":           -1,
                "combined_chs": _TOM_CHS,
                "label":        "Toms",
                "color":        WF_CH,
                "fill":         WF_CH_F,
                "h":            TRACK_H,
                "is_sum":       False,
            })
            _tom_added = True
        continue   # skip individual Tom H / M / L
    if _ch in _OH_CHS:
        if not _oh_added:
            TRACKS.append({
                "ch":           -1,
                "combined_chs": _OH_CHS,
                "label":        "OH L+R",
                "color":        WF_CH,
                "fill":         WF_CH_F,
                "h":            TRACK_H,
                "is_sum":       False,
            })
            _oh_added = True
        continue   # skip individual OH L / OH R
    TRACKS.append({
        "ch":     _ch,
        "label":  CHANNEL_LABELS.get(_ch, f"CH {_ch + 1}"),
        "color":  WF_CH,
        "fill":   WF_CH_F,
        "h":      TRACK_H,
        "is_sum": False,
    })

# Pre-compute y offsets
_y = RULER_H + EVENTS_H + ANNOT_H
TRACK_Y: list[int] = []
for _t in TRACKS:
    TRACK_Y.append(_y)
    _y += _t["h"] + TRACK_GAP

CONTENT_H: int = _y + SCROLL_H


def _fmt_t(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m}:{s:02d}"


def _first_quarter_hour(dt: datetime) -> datetime:
    """Return the first quarter-hour boundary (HH:00/15/30/45) at or after dt."""
    m = dt.minute
    rem = m % 15
    if rem == 0 and dt.second == 0 and dt.microsecond == 0:
        return dt
    next_m = ((m // 15) + 1) * 15
    if next_m >= 60:
        return dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return dt.replace(minute=next_m, second=0, microsecond=0)


class TimelineWidget(QWidget):
    """Waveform + event timeline for one SongSegment.

    The left LABEL_W pixels are always visible (sticky).
    The rest scrolls horizontally.
    seek_requested emits seconds relative to segment start.
    """

    seek_requested = pyqtSignal(float)
    # Emitted whenever Solo/Mute state changes; args: (muted_indices, soloed_indices)
    solo_mute_changed = pyqtSignal(object, object)
    # Emitted when user clicks the events label cell; arg: current wav_t
    event_label_clicked = pyqtSignal(float)
    # Annotation: emitted when user right-clicks a bar marker to remove it
    bar_marker_remove_requested = pyqtSignal(float)  # t_in_seg of nearest marker

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.segment: Optional[SongSegment] = None
        self.peaks: Optional[TrackPeaks] = None
        self.cursor_t: float = 0.0      # seconds in WAV

        self._pps: float = 80.0         # pixels per second
        self._scroll_x: int = 0
        self._cursor_px: int = -1
        self._rec_started_at: Optional[datetime] = None

        # Solo / Mute state (track indices into TRACKS list)
        self._muted: set[int] = set()
        self._soloed: set[int] = set()

        # Annotation state
        self._annotation_mode: bool = False
        self._bar_markers: list[BarMarker] = []

        # Detected fragment boundaries (start times of fragments 2, 3, …)
        # relative to segment start, in seconds
        self._fragment_boundaries: list[float] = []

        # Live scan progress: list of (t_rel, is_active) per RMS window
        self._scan_windows: list[tuple[float, bool]] = []
        self._scan_pos: float = -1.0   # current scan head (seconds)

        # Simulation results (kick/snare onsets = abs WAV t; crashes = (abs WAV t, rms_energy))
        self._sim_kicks:   list[float] = []
        self._sim_snares:  list[float] = []
        self._sim_crashes: list[tuple[float, float]] = []   # (abs_wav_t, rms_energy)

        # Chroma-Daten pro Beat (aus chroma_viz)
        self._chroma_data: list[dict] = []   # list of {t, chroma} from chroma_viz

        # Overlay-Modus: wenn True, JSONL-Events bei 25 % Opazität,
        # Sim-Events in vollen AMBER/CYAN-Farben (wie JSONL-Events).
        # Wenn False, Sim-Events als halbtransparentes Violett-Overlay.
        self._sim_overlay: bool = False

        # Sim BPM-Timeline + Taktgitter
        # _sim_bpm_timeline: list of (abs_wav_t, bpm) — changes only
        self._sim_bpm_timeline: list[tuple[float, int]] = []
        self._sim_bar_times:    list[float]             = []

        self._hbar = QScrollBar(Qt.Orientation.Horizontal, self)
        self._hbar.valueChanged.connect(self._on_scroll)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(CONTENT_H)
        self.setMouseTracking(True)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_recording_started_at(self, dt: Optional[datetime]) -> None:
        self._rec_started_at = dt

    def set_segment(self, seg: SongSegment, peaks: Optional[TrackPeaks] = None) -> None:
        self.segment = seg
        self.peaks = peaks
        self.cursor_t = seg.start_t
        self._scroll_x = 0
        self._hbar.setValue(0)
        self._sync_scrollbar()
        self.update()

    def set_peaks(self, peaks: TrackPeaks) -> None:
        self.peaks = peaks
        self.update()

    def set_cursor(self, wav_t: float) -> None:
        self.cursor_t = wav_t

        if self.segment is None:
            return

        cx_new = int((wav_t - self.segment.start_t) * self._pps)
        vw = self._visible_w()
        scrolled = False
        if cx_new < self._scroll_x:
            self._hbar.setValue(max(0, cx_new - 40))
            scrolled = True
        elif cx_new > self._scroll_x + vw - 40:
            self._hbar.setValue(cx_new - vw + 80)
            scrolled = True

        new_px = LABEL_W + cx_new - self._scroll_x
        if scrolled:
            self._cursor_px = new_px
            self.update()
        else:
            old_px = self._cursor_px
            self._cursor_px = new_px
            h = self.height()
            left = min(old_px if old_px >= 0 else new_px, new_px) - 3
            right = max(old_px if old_px >= 0 else new_px, new_px) + 3
            self.update(QRect(max(LABEL_W, left), 0, right - left + 1, h))

    def set_zoom(self, pps: float) -> None:
        self._pps = max(4.0, min(40_960.0, pps))
        self._sync_scrollbar()
        self.update()

    @property
    def zoom(self) -> float:
        return self._pps

    # ── Annotation ────────────────────────────────────────────────────────────

    def set_annotation_mode(self, enabled: bool) -> None:
        """Schaltet den Annotations-Modus ein/aus."""
        self._annotation_mode = enabled
        self.update()

    def set_bar_markers(self, markers: list[BarMarker]) -> None:
        """Setzt die anzuzeigenden Takt-Marker (ersetzt bisherige)."""
        self._bar_markers = list(markers)
        self.update()

    def set_fragment_boundaries(self, boundaries: list[float]) -> None:
        """Setzt erkannte Fragmentgrenzen (Start-Zeiten von Fragment 2, 3, …).

        Zeiten sind relativ zum Segment-Start in Sekunden.
        """
        self._fragment_boundaries = list(boundaries)
        self.update()

    def update_scan_progress(self, scan_pos: float, new_windows: list[tuple[float, bool]]) -> None:
        """Fügt neue Scan-Fenster hinzu und setzt den Scan-Kopf.

        Wird aus dem Fragment-Erkennungs-Thread aufgerufen (via QTimer.singleShot).
        """
        self._scan_windows.extend(new_windows)
        self._scan_pos = scan_pos
        self.update()

    def clear_scan_progress(self) -> None:
        """Löscht die Scan-Visualisierung."""
        self._scan_windows = []
        self._scan_pos = -1.0
        self.update()

    def add_sim_kick(self, t: float) -> None:
        self._sim_kicks.append(t)
        self.update()

    def add_sim_snare(self, t: float) -> None:
        self._sim_snares.append(t)
        self.update()

    def add_sim_crash(self, t: float, energy: float = 0.0) -> None:
        self._sim_crashes.append((t, energy))
        self.update()

    def clear_sim_events(self) -> None:
        """Löscht alle Simulations-Ergebnisse."""
        self._sim_kicks:   list[float]             = []
        self._sim_snares:  list[float]             = []
        self._sim_crashes: list[tuple[float,float]]= []
        self._sim_bpm_timeline = []
        self._sim_bar_times    = []
        self._chroma_data      = []
        self.update()

    def set_chroma_data(self, data: list[dict]) -> None:
        """Setzt Chroma-Daten (Liste von {t, chroma}) für die Lead-Guitar-Zeile."""
        self._chroma_data = data
        self.update()

    def set_sim_bpm_and_bars(
        self,
        bpm_timeline: list[tuple[float, int]],
        bar_times: list[float],
    ) -> None:
        """Setzt BPM-Timeline und Taktgitter für den Simulations-Overlay."""
        self._sim_bpm_timeline = bpm_timeline
        self._sim_bar_times    = bar_times
        self.update()

    def set_sim_overlay(self, enabled: bool) -> None:
        """Overlay-Modus: Sim-Events in vollen Farben, JSONL-Events bei 25 % Opazität."""
        self._sim_overlay = enabled
        self.update()

    # ── Solo / Mute ───────────────────────────────────────────────────────────

    def _toggle_mute(self, idx: int) -> None:
        if idx in self._muted:
            self._muted.discard(idx)
        else:
            self._muted.add(idx)
            self._soloed.discard(idx)
        self.update()
        self.solo_mute_changed.emit(frozenset(self._muted), frozenset(self._soloed))

    def _toggle_solo(self, idx: int) -> None:
        if idx in self._soloed:
            self._soloed.discard(idx)
        else:
            self._soloed.add(idx)
            self._muted.discard(idx)
        self.update()
        self.solo_mute_changed.emit(frozenset(self._muted), frozenset(self._soloed))

    def _current_event_label(self) -> tuple[str, QColor]:
        """Return (short text, color) for the last event before cursor_t."""
        if not self.segment or not self.segment.events:
            return "EVENTS  ▸", C_T3
        last = None
        for ev in self.segment.events:
            if ev.t <= self.cursor_t:
                last = ev
            else:
                break
        if last is None:
            return "EVENTS  ▸", C_T3
        t_rel = _fmt_t(last.t - self.segment.start_t)
        etype = last.type
        if etype == "beat":
            sym = "↓" if last.data.get("is_downbeat") else "·"
            return f"{t_rel} {sym}", C_AMBER
        if etype == "position":
            part = last.data.get("part_name", "")
            return f"{t_rel} {part}", C_CYAN
        if etype == "user":
            action = last.data.get("action", "?")
            lmap = {"next": "→ next", "prev": "← prev", "goto": "goto",
                    "select_song": "song", "send_template": "tmpl",
                    "accent": "★"}
            return f"{t_rel} {lmap.get(action, action)}", C_GREEN
        if etype in ("session_start", "session_end"):
            return f"{t_rel} {etype}", C_T3
        return f"{t_rel} {etype}", C_T3

    def _is_dim(self, idx: int) -> bool:
        if idx in self._muted:
            return True
        if self._soloed and idx not in self._soloed:
            return True
        return False

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _wf_width(self) -> int:
        return int(self.segment.duration * self._pps) if self.segment else 0

    def _visible_w(self) -> int:
        return max(0, self.width() - LABEL_W)

    def _sync_scrollbar(self) -> None:
        ww = self._wf_width()
        vw = self._visible_w()
        self._hbar.setMaximum(max(0, ww - vw))
        self._hbar.setPageStep(vw)
        self._hbar.setGeometry(LABEL_W, self.height() - SCROLL_H, vw, SCROLL_H)

    def _on_scroll(self, v: int) -> None:
        self._scroll_x = v
        self.update()

    # ── Marker helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _marker_color_for(ev, track_chs: frozenset) -> Optional[QColor]:
        """Return the marker color for *ev* on a track with *track_chs*, or None."""
        if ev.type == "beat":
            if track_chs & BEAT_MARKER_CHS:
                return C_RED if ev.data.get("is_downbeat") else C_AMBER
            if track_chs & KICK_MARKER_CHS:
                # Kick-Kanal: alle kick-getriggerten Beats zeigen (nicht nur Downbeats),
                # damit die tatsächliche Kick-Erkennungsrate sichtbar ist.
                if ev.data.get("trigger") == "kick":
                    return C_RED if ev.data.get("is_downbeat") else C_AMBER
        elif ev.type == "snare" and track_chs & SNARE_MARKER_CHS:
            return C_CYAN
        return None

    @staticmethod
    def _build_marker_tooltip(ev, t_in_seg: float) -> str:
        """Build a human-readable tooltip string for a marker event."""
        m, s = divmod(t_in_seg, 60)
        ts = f"{int(m)}:{s:05.2f}"
        if ev.type == "beat":
            sym = "↓ Downbeat" if ev.data.get("is_downbeat") else "Beat"
            parts = [sym]
            if "beat_num" in ev.data:
                parts.append(f"#{ev.data['beat_num']}")
            if "bpm" in ev.data:
                parts.append(f"{float(ev.data['bpm']):.1f} BPM")
            return f"{ts}   " + "  ".join(parts)
        if ev.type == "snare":
            parts = ["Snare"]
            for k, v in ev.data.items():
                parts.append(f"{k}={v}")
            return f"{ts}   " + "  ".join(parts)
        return f"{ts}   {ev.type}  {ev.data}"

    def _track_chs_for(self, track: dict) -> frozenset[int]:
        """Return the set of WAV channel indices for a track dict."""
        if "combined_chs" in track:
            return frozenset(track["combined_chs"])
        ch = track.get("ch", -1)
        return frozenset({ch}) if ch >= 0 else frozenset()

    # ── Qt events ─────────────────────────────────────────────────────────────

    def resizeEvent(self, _event) -> None:
        self._sync_scrollbar()

    def wheelEvent(self, event) -> None:
        dy = event.angleDelta().y()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_zoom(self._pps * (1.12 if dy > 0 else 0.88))
        else:
            step = max(40, self._visible_w() // 6)
            self._hbar.setValue(self._scroll_x + (-step if dy > 0 else step))

    def mousePressEvent(self, event) -> None:
        x = int(event.position().x())
        y = int(event.position().y())

        # Clicks in label column
        if x < LABEL_W:
            # Events cell → emit click with current wav_t for dialog
            if RULER_H <= y < RULER_H + EVENTS_H:
                self.event_label_clicked.emit(self.cursor_t)
                return
            # S/M button clicks
            for i, (track, ty) in enumerate(zip(TRACKS, TRACK_Y)):
                th = track["h"]
                if ty <= y < ty + th:
                    btn_y = ty + (th - BTN_H) // 2
                    if btn_y <= y < btn_y + BTN_H:
                        if BTN_M_X <= x < BTN_M_X + BTN_W:
                            self._toggle_mute(i)
                        elif BTN_S_X <= x < BTN_S_X + BTN_W:
                            self._toggle_solo(i)
                    break
            return

        # Annotation strip: right-click removes nearest marker
        annot_y0 = RULER_H + EVENTS_H
        if (annot_y0 <= y < annot_y0 + ANNOT_H
                and event.button() == Qt.MouseButton.RightButton
                and self.segment):
            t = (x - LABEL_W + self._scroll_x) / self._pps
            t = max(0.0, min(t, self.segment.duration))
            self.bar_marker_remove_requested.emit(t)
            return

        if event.button() == Qt.MouseButton.LeftButton and self.segment:
            t = (x - LABEL_W + self._scroll_x) / self._pps
            t = max(0.0, min(t, self.segment.duration))
            self.seek_requested.emit(t)

    def mouseMoveEvent(self, event) -> None:
        x = int(event.position().x())
        y = int(event.position().y())

        if x <= LABEL_W or self.segment is None:
            QToolTip.hideText()
            return

        seg = self.segment
        pps = self._pps
        ox = self._scroll_x
        hit_r = _DIAMOND_R + 4   # hit radius in px
        crash_r = _DIAMOND_R + 3 + 4   # crash diamond is larger

        # ── Sim-Crash-Tooltip auf OH L+R Row ──────────────────────────────────
        if self._sim_overlay and self._sim_crashes:
            oh_idx = next((i for i, t in enumerate(TRACKS) if t["label"] == "OH L+R"), None)
            if oh_idx is not None:
                oh_ty = TRACK_Y[oh_idx]
                oh_th = TRACKS[oh_idx]["h"]
                if oh_ty <= y < oh_ty + oh_th:
                    crash_cy = oh_ty + oh_th // 2
                    if abs(y - crash_cy) <= crash_r:
                        for t_c, e_c in self._sim_crashes:
                            ex = LABEL_W + int((t_c - seg.start_t) * pps) - ox
                            if abs(ex - x) <= crash_r:
                                # Confidence: RMS relativ zu CRASH_RMS_MIN
                                try:
                                    from detection.beat_detector import _CrashDetector
                                    thresh = _CrashDetector.CRASH_RMS_MIN
                                except Exception:
                                    thresh = 0.025
                                conf_pct = min(100, int(e_c / max(thresh, 1e-9) * 50))
                                t_rel = t_c - seg.start_t
                                m, s = divmod(t_rel, 60)
                                ts = f"{int(m)}:{s:05.2f}"
                                tip = (f"Crash  {ts}\n"
                                       f"RMS {e_c:.3f}  |  "
                                       f"Erkennungssicherheit ~{conf_pct} %")
                                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                                return

        for track, ty in zip(TRACKS, TRACK_Y):
            th = track["h"]
            if not (ty <= y < ty + th):
                continue
            track_chs = self._track_chs_for(track)
            cy = ty + th - 2 - _DIAMOND_R   # diamond center y (bottom of track)
            if abs(y - cy) > hit_r:
                break
            for ev in seg.events:
                ex = LABEL_W + int((ev.t - seg.start_t) * pps) - ox
                if abs(ex - x) > hit_r:
                    continue
                color = self._marker_color_for(ev, track_chs)
                if color is None:
                    continue
                tip = self._build_marker_tooltip(ev, ev.t - seg.start_t)
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                return
            break

        QToolTip.hideText()

    # ── Tooltip / ToolTip event ───────────────────────────────────────────────

    def event(self, ev) -> bool:
        from PyQt6.QtCore import QEvent
        if ev.type() == QEvent.Type.ToolTip:
            pos = ev.pos()
            tip = self._chroma_tip_at(pos)
            if tip:
                QToolTip.showText(ev.globalPos(), tip, self)
                return True
            QToolTip.hideText()
            return True
        return super().event(ev)

    def _chroma_tip_at(self, pos) -> str:
        """Gibt Tooltip-Text zurück wenn die Maus nahe einem Chroma-Shape ist."""
        if not self._chroma_data or self.segment is None:
            return ""

        lg_idx = next(
            (i for i, t in enumerate(TRACKS) if t["label"] == "Lead Guitar"),
            None,
        )
        if lg_idx is None:
            return ""

        ty = TRACK_Y[lg_idx]
        th = TRACKS[lg_idx]["h"]

        if not (ty <= pos.y() <= ty + th):
            return ""

        seg_t0 = self.segment.start_t
        pps    = self._pps
        ox     = self._scroll_x
        CLICK_R = 10

        for entry in self._chroma_data:
            bx = LABEL_W + int((entry["t"] - seg_t0) * pps) - ox
            if abs(bx - pos.x()) <= CLICK_R:
                try:
                    from chroma_viz import chroma_tooltip
                    return chroma_tooltip(entry["chroma"])
                except ImportError:
                    return ""
        return ""

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        w, h = self.width(), self.height() - SCROLL_H
        p.fillRect(0, 0, w, h, C_BG)

        if self.segment is None:
            p.setPen(C_T3)
            p.setFont(FONT_LABEL)
            p.drawText(QRect(0, 0, w, h),
                       Qt.AlignmentFlag.AlignCenter,
                       "Keine Aufnahme geladen\n\nDatei  ->  Oeffnen...")
            return

        vl = self._scroll_x
        vr = self._scroll_x + self._visible_w()

        self._paint_ruler(p, vl, vr)
        self._paint_events(p, vl, vr)
        self._paint_annotation_strip(p, vl, vr)
        for i, track in enumerate(TRACKS):
            self._paint_track(p, i, track, TRACK_Y[i], vl, vr)

        # Taktstriche über alle Drum-Tracks (wenn Sim-Overlay aktiv)
        self._paint_sim_bars(p, vl, vr)

        # Chroma-Shapes im Lead-Guitar-Track (wenn Sim-Overlay aktiv)
        self._paint_chroma_shapes(p, vl, vr)

        # Sticky labels drawn OVER waveforms
        self._paint_labels(p, h)

        # Playback cursor
        self._paint_cursor(p, h)

        p.end()

    # ── Sim bar grid ──────────────────────────────────────────────────────────

    def _paint_sim_bars(self, p: QPainter, vl: int, vr: int) -> None:
        """Zeichnet Taktstriche + BPM-Verlauf über alle Schlagzeug-Tracks.

        Taktstriche: halbdurchsichtige weiße Linien über Kick..OH L+R.
        Taktnummern: alle 5 Takte amber in Tom-Zeile (unterer Bereich).
        BPM-Anzeige: in Tom-Zeile (oberer Bereich) bei jeder Änderung ≥ 1 BPM.
        """
        if not self._sim_overlay:
            return
        if self.segment is None:
            return

        # Drum-Track-Span ermitteln
        drum_labels = {"Kick", "Snare", "Toms", "OH L+R"}
        drum_indices = [i for i, t in enumerate(TRACKS) if t["label"] in drum_labels]
        if not drum_indices:
            return

        y_top    = TRACK_Y[drum_indices[0]]
        last_i   = drum_indices[-1]
        y_bottom = TRACK_Y[last_i] + TRACKS[last_i]["h"] - 1

        # Tom-Zeile für Taktnummern + BPM
        tom_indices = [i for i, t in enumerate(TRACKS) if t["label"] == "Toms"]
        tom_i = tom_indices[0] if tom_indices else None

        seg_t0 = self.segment.start_t
        pps    = self._pps
        ox     = self._scroll_x
        w      = self.width()

        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen_bar = QPen(QColor(255, 255, 255, 110), 1)
        C_NUM   = QColor(0xee, 0xf0, 0xf6, 230)   # fast weiß, gut lesbar

        # ── Taktstriche + Taktnummern ──────────────────────────────────────────
        for bar_num, bar_t in enumerate(self._sim_bar_times, start=1):
            bx = LABEL_W + int((bar_t - seg_t0) * pps) - ox
            if bx < LABEL_W or bx > w:
                continue

            p.setPen(pen_bar)
            p.drawLine(bx, y_top, bx, y_bottom)

            if bar_num % 5 == 0 and tom_i is not None:
                ty = TRACK_Y[tom_i]
                th = TRACKS[tom_i]["h"]
                # Taktnummer im unteren Drittel: dunkler Hintergrund + helle Schrift
                lbl   = str(bar_num)
                lbl_w = 26
                lbl_y = ty + th * 2 // 3
                lbl_h = th // 3
                p.fillRect(bx + 1, lbl_y, lbl_w, lbl_h, QColor(0, 0, 0, 160))
                p.setFont(FONT_BTN)
                p.setPen(C_NUM)
                p.drawText(bx + 2, lbl_y, lbl_w, lbl_h,
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           lbl)

        # ── BPM-Timeline in Tom-Zeile (oberes Drittel) ────────────────────────
        if self._sim_bpm_timeline and tom_i is not None:
            ty = TRACK_Y[tom_i]
            th = TRACKS[tom_i]["h"]
            bpm_y    = ty + 1
            bpm_h    = th * 2 // 3   # obere 2/3 der Zeile (Platz ohne Taktnummern)
            C_BPM    = QColor(0xee, 0xf0, 0xf6, 240)   # helles Weiß
            p.setFont(FONT_BTN)
            for bpm_t, bpm_val in self._sim_bpm_timeline:
                bx = LABEL_W + int((bpm_t - seg_t0) * pps) - ox
                if bx < LABEL_W or bx > w:
                    continue
                lbl_w = 32
                p.fillRect(bx + 2, bpm_y, lbl_w, bpm_h, QColor(0, 0, 0, 160))
                p.setPen(C_BPM)
                p.drawText(bx + 3, bpm_y, lbl_w, bpm_h,
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           str(bpm_val))

    # ── Chroma shapes (Lead Guitar row) ──────────────────────────────────────

    def _paint_chroma_shapes(self, p: QPainter, vl: int, vr: int) -> None:
        """Zeichnet Chroma-Shapes im Lead-Guitar-Track (nur im Sim-Overlay-Modus)."""
        if not self._sim_overlay:
            return
        if not self._chroma_data or self.segment is None:
            return

        # Lead-Guitar-Track finden
        lg_idx = next(
            (i for i, t in enumerate(TRACKS) if t["label"] == "Lead Guitar"),
            None,
        )
        if lg_idx is None:
            return

        try:
            from chroma_viz import chroma_to_rgb, chroma_shape_type
        except ImportError:
            return

        seg_t0 = self.segment.start_t
        pps    = self._pps
        ox     = self._scroll_x
        w      = self.width()

        ty = TRACK_Y[lg_idx]
        th = TRACKS[lg_idx]["h"]
        cy = ty + th // 2

        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        for entry in self._chroma_data:
            bx = LABEL_W + int((entry["t"] - seg_t0) * pps) - ox
            if bx < LABEL_W or bx > w:
                continue

            chroma = entry["chroma"]
            rgb = chroma_to_rgb(chroma)
            color = QColor(rgb[0], rgb[1], rgb[2], 220)
            shape = chroma_shape_type(chroma)

            r = min(th // 2 - 2, 8)
            if r < 1:
                continue

            p.setPen(QPen(color, 1))
            p.setBrush(QBrush(color))

            if shape == "line":
                pen = QPen(color, 2)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawLine(bx, cy - r, bx, cy + r)
            elif shape == "triangle":
                poly = QPolygon([
                    QPoint(bx,     cy - r),
                    QPoint(bx - r, cy + r),
                    QPoint(bx + r, cy + r),
                ])
                p.setPen(QPen(color, 1))
                p.setBrush(QBrush(color))
                p.drawPolygon(poly)
            elif shape == "diamond":
                poly = QPolygon([
                    QPoint(bx,     cy - r),
                    QPoint(bx + r, cy),
                    QPoint(bx,     cy + r),
                    QPoint(bx - r, cy),
                ])
                p.setPen(QPen(color, 1))
                p.setBrush(QBrush(color))
                p.drawPolygon(poly)
            else:  # circle
                p.setPen(QPen(color, 1))
                p.setBrush(QBrush(color))
                p.drawEllipse(QPoint(bx, cy), r, r)

        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    # ── Ruler ─────────────────────────────────────────────────────────────────

    def _paint_ruler(self, p: QPainter, vl: int, vr: int) -> None:
        p.fillRect(LABEL_W, 0, self.width() - LABEL_W, RULER_H, C_BG2)
        p.setPen(C_BORDER)
        p.drawLine(LABEL_W, RULER_H - 1, self.width(), RULER_H - 1)

        if self.segment is None:
            return

        p.setFont(FONT_TIME)

        if self._rec_started_at is not None:
            # Clock-time ticks only at full quarter hours (HH:00/15/30/45)
            seg_offset = self.segment.start_t
            abs_seg_start = self._rec_started_at + timedelta(seconds=seg_offset)
            qh = _first_quarter_hour(abs_seg_start)
            while True:
                t = (qh - abs_seg_start).total_seconds()
                x = LABEL_W + int(t * self._pps) - self._scroll_x
                if x > self.width():
                    break
                if x >= LABEL_W:
                    p.setPen(C_T2)
                    p.drawLine(x, RULER_H - 12, x, RULER_H - 1)
                    p.drawText(x + 3, 2, 90, RULER_H - 4,
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                               qh.strftime("%H:%M"))
                qh += timedelta(minutes=15)
        else:
            # Fallback: dynamic relative time ticks (no clock data)
            secs_vis = max(1.0, self._visible_w() / self._pps)
            if   secs_vis > 300: major, minor = 60, 10
            elif secs_vis > 120: major, minor = 30, 5
            elif secs_vis > 60:  major, minor = 15, 5
            elif secs_vis > 30:  major, minor = 10, 2
            elif secs_vis > 10:  major, minor = 5, 1
            elif secs_vis > 4:   major, minor = 2, 0.5
            else:                major, minor = 1, 0.25
            t = math.floor(vl / self._pps / minor) * minor
            while t * self._pps <= vr:
                x = LABEL_W + int(t * self._pps) - self._scroll_x
                if x >= LABEL_W:
                    is_major = abs(t % major) < minor * 0.1
                    if is_major:
                        p.setPen(C_T2)
                        p.drawLine(x, RULER_H - 12, x, RULER_H - 1)
                        p.drawText(x + 3, 2, 90, RULER_H - 4,
                                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                   _fmt_t(t))
                    else:
                        p.setPen(C_T4)
                        p.drawLine(x, RULER_H - 5, x, RULER_H - 1)
                t += minor

    # ── Annotation strip ──────────────────────────────────────────────────────

    def _paint_annotation_strip(self, p: QPainter, vl: int, vr: int) -> None:
        """Zeichnet den Takt-Annotations-Streifen unterhalb der Events-Spur."""
        if ANNOT_H <= 0:
            return
        y0 = RULER_H + EVENTS_H
        w = self.width()

        # Hintergrund
        bg = QColor("#1c1028") if self._annotation_mode else C_BG2
        p.fillRect(LABEL_W, y0, w - LABEL_W, ANNOT_H, bg)
        # Oberer Rand — amber wenn aktiv, sonst normal
        if self._annotation_mode:
            p.setPen(QPen(QColor("#f0a030"), 2))
            p.drawLine(LABEL_W, y0, w, y0)
        p.setPen(C_BORDER)
        p.drawLine(LABEL_W, y0 + ANNOT_H - 1, w, y0 + ANNOT_H - 1)

        # ── Live scan activity map ────────────────────────────────────────────
        # Drawn as a thin bar at the bottom of the strip while detection runs.
        if self._scan_windows:
            pps  = self._pps
            ox   = self._scroll_x
            bh   = 7                          # activity bar height (px)
            by   = y0 + ANNOT_H - bh - 1     # bar top y
            ww   = max(1, int(0.05 * pps))    # pixel width per 50 ms window
            C_ACT = QColor(0x00, 0xdc, 0x82, 110)   # green – active
            C_SIL = QColor(0x5c, 0x60, 0x80,  70)   # grey  – silent
            for t_win, is_active in self._scan_windows:
                ex = LABEL_W + int(t_win * pps) - ox
                if ex > w:
                    break
                if ex + ww < LABEL_W:
                    continue
                p.fillRect(max(LABEL_W, ex), by, ww, bh,
                           C_ACT if is_active else C_SIL)
            # Scan-head line
            if self._scan_pos >= 0:
                sx = LABEL_W + int(self._scan_pos * pps) - ox
                if LABEL_W <= sx <= w:
                    p.setPen(QPen(C_CYAN, 2))
                    p.drawLine(sx, y0, sx, y0 + ANNOT_H - 1)

        # Fragment boundaries (violet, drawn before bar markers so they sit behind)
        C_FRAG = QColor("#a78bfa")
        if self.segment and self._fragment_boundaries:
            pps = self._pps
            ox  = self._scroll_x
            p.setFont(FONT_MONO)
            for k, bnd_t in enumerate(self._fragment_boundaries):
                bx = LABEL_W + int(bnd_t * pps) - ox
                if bx < LABEL_W or bx > w:
                    continue
                p.setPen(QPen(C_FRAG, 2))
                p.drawLine(bx, y0, bx, y0 + ANNOT_H - 2)
                p.setPen(C_FRAG)
                p.drawText(bx + 3, y0 + 1, 40, ANNOT_H - 2,
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           f"F{k + 2}")

        if not self.segment or not self._bar_markers:
            return

        seg = self.segment
        pps = self._pps
        ox  = self._scroll_x
        p.setFont(FONT_MONO)

        C_FRAG_MARKER = QColor("#ffffff")  # Fragment-Start: weißer Marker

        for m in self._bar_markers:
            ex = LABEL_W + int(m.t * pps) - ox
            if ex < LABEL_W or ex > w:
                continue

            is_frag = m.restart_bar_num is not None
            is_part = bool(m.part_name)

            if is_frag:
                # Fragment-Start: breite weiße Linie + "→T{n}" Label
                p.setPen(QPen(C_FRAG_MARKER, 2))
                p.drawLine(ex, y0, ex, y0 + ANNOT_H - 1)
                p.setPen(C_FRAG_MARKER)
                frag_label = f"→T{m.restart_bar_num}"
                if is_part:
                    frag_label += f" {m.part_name}"
                p.drawText(ex + 3, y0 + 1, 120, ANNOT_H - 2,
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           frag_label)
            else:
                c = C_GREEN if is_part else C_AMBER

                # Vertikale Linie — volle Streifen-Höhe
                p.setPen(QPen(c, 1))
                p.drawLine(ex, y0, ex, y0 + ANNOT_H - 2)

                # Takt-Nummer (klein, oben links neben der Linie)
                label = f"{m.bar_num}"
                if is_part:
                    label = f"{m.bar_num} {m.part_name}"
                p.setPen(c)
                p.drawText(ex + 2, y0 + 1, 120, ANNOT_H - 2,
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           label)

                # Quantisierung fehlgeschlagen → rotes „?" oben an der Linie
                if getattr(m, "quantize_failed", False):
                    p.setFont(FONT_BTN)
                    p.setPen(C_RED)
                    p.drawText(ex - 5, y0, 12, 12,
                               Qt.AlignmentFlag.AlignCenter, "?")
                    p.setFont(FONT_MONO)


    # ── Events strip ─────────────────────────────────────────────────────────

    def _paint_events(self, p: QPainter, vl: int, vr: int) -> None:
        y0 = RULER_H
        w = self.width()
        p.fillRect(LABEL_W, y0, w - LABEL_W, EVENTS_H, C_BG2)
        p.setPen(C_BORDER)
        p.drawLine(LABEL_W, y0 + EVENTS_H - 1, w, y0 + EVENTS_H - 1)

        if not self.segment:
            return

        p.setFont(FONT_MONO)
        seg = self.segment
        pps = self._pps
        ox = self._scroll_x

        # Im Overlay-Modus mit Sim-Events: Original-JSONL komplett ausblenden
        _hide_orig = self._sim_overlay and bool(
            self._sim_kicks or self._sim_snares or self._sim_crashes
        )

        if not _hide_orig:
            if self._sim_overlay:
                p.setOpacity(0.25)
            for ev in seg.events:
                ex = LABEL_W + int((ev.t - seg.start_t) * pps) - ox
                if ex < LABEL_W or ex > w:
                    continue

                if ev.type == "beat":
                    down = ev.data.get("is_downbeat", False)
                    c = C_AMBER if down else C_T4
                    p.setPen(QPen(c, 1))
                    p.drawLine(ex, y0 + (2 if down else EVENTS_H // 2),
                               ex, y0 + EVENTS_H - 2)

                elif ev.type == "snare":
                    p.setPen(QPen(C_CYAN, 1))
                    p.drawLine(ex, y0, ex, y0 + EVENTS_H // 3)

                elif ev.type == "position":
                    conf = float(ev.data.get("confidence", 0))
                    part = str(ev.data.get("part_name", ""))
                    if conf > 0.65 and part:
                        alpha = int(min(1.0, conf) * 200)
                        c = QColor(C_CYAN.red(), C_CYAN.green(), C_CYAN.blue(), alpha)
                        p.setPen(QPen(c, 1))
                        p.drawLine(ex, y0, ex, y0 + EVENTS_H // 2)
                        if conf > 0.82:
                            p.setPen(c)
                            p.drawText(ex + 2, y0, 70, EVENTS_H // 2,
                                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                       part)

                elif ev.type == "user":
                    action = ev.data.get("action", "")
                    if action in ("next", "prev", "goto", "accent"):
                        label_map = {"next": "->", "prev": "<-",
                                     "goto": "~>", "accent": "*"}
                        p.setPen(QPen(C_GREEN, 2))
                        p.drawLine(ex, y0 + EVENTS_H // 3, ex, y0 + EVENTS_H - 2)
                        p.setPen(C_GREEN)
                        p.drawText(ex + 2, y0 + EVENTS_H // 3, 20, EVENTS_H // 2,
                                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                   label_map.get(action, "?"))

        # ── Simulierte Kick/Snare-Onsets als Diamonds ────────────────────────
        p.setOpacity(1.0)

        def _diamond(cx: int, cy: int, r: int = 4) -> QPolygon:
            return QPolygon([
                QPoint(cx,     cy - r),
                QPoint(cx + r, cy    ),
                QPoint(cx,     cy + r),
                QPoint(cx - r, cy    ),
            ])

        R = 4
        cy_top    = y0 + EVENTS_H // 4      # Snares oben
        cy_bottom = y0 + EVENTS_H * 3 // 4  # Kicks unten

        C_VIO = QColor("#a78bfa")

        if self._sim_snares:
            c = C_CYAN if self._sim_overlay else C_VIO
            p.setBrush(QBrush(c))
            p.setPen(Qt.PenStyle.NoPen)
            for t_s in self._sim_snares:
                bx = LABEL_W + int(t_s * pps) - ox
                if LABEL_W <= bx <= w:
                    p.drawPolygon(_diamond(bx, cy_top, R))

        if self._sim_kicks:
            c = C_AMBER if self._sim_overlay else C_VIO
            p.setBrush(QBrush(c))
            p.setPen(Qt.PenStyle.NoPen)
            for t_k in self._sim_kicks:
                bx = LABEL_W + int(t_k * pps) - ox
                if LABEL_W <= bx <= w:
                    p.drawPolygon(_diamond(bx, cy_bottom, R))

        # Crash-Onsets: rotes Stern-Symbol in der Mitte des Events-Strips
        if self._sim_crashes:
            C_CRASH = QColor("#ff3b5c")
            cy_mid = y0 + EVENTS_H // 2
            p.setBrush(QBrush(C_CRASH))
            p.setPen(Qt.PenStyle.NoPen)
            for t_c in self._sim_crashes:
                bx = LABEL_W + int(t_c * pps) - ox
                if LABEL_W <= bx <= w:
                    p.drawPolygon(_diamond(bx, cy_mid, R + 3))   # größer als Kick/Snare

        p.setOpacity(1.0)

    # ── Waveform track ────────────────────────────────────────────────────────

    def _paint_track(self, p: QPainter, idx: int, track: dict,
                     y: int, vl: int, vr: int) -> None:
        h = track["h"]
        w = self.width()
        mid = y + h // 2
        half = (h - 8) // 2

        bg = C_BG2 if track["is_sum"] else C_BG3
        p.fillRect(LABEL_W, y, w - LABEL_W, h, bg)
        p.setPen(C_BORDER)
        p.drawLine(LABEL_W, y + h - 1, w, y + h - 1)

        p.setPen(QPen(C_T4, 1))
        p.drawLine(LABEL_W, mid, w, mid)

        if self.peaks is None:
            p.setPen(C_T4)
            p.setFont(FONT_MONO)
            p.drawText(LABEL_W + 6, y, w - LABEL_W - 8, h,
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       "Lade...")
            return

        # Resolve peak data — works for any number of combined_chs
        if "combined_chs" in track:
            valid = [self.peaks.channel_peaks.get(ch) for ch in track["combined_chs"]]
            valid = [cp for cp in valid if cp and cp.n_points > 0]
            if not valid:
                return
            n = min(cp.n_points for cp in valid)
            pk_max = valid[0].peaks_max[:n].copy()
            pk_min = valid[0].peaks_min[:n].copy()
            for cp in valid[1:]:
                np.maximum(pk_max, cp.peaks_max[:n], out=pk_max)
                np.minimum(pk_min, cp.peaks_min[:n], out=pk_min)
        else:
            cp = self.peaks.channel_peaks.get(track["ch"])
            if cp is None or cp.n_points == 0:
                return
            pk_max, pk_min, n = cp.peaks_max, cp.peaks_min, cp.n_points

        ww = self._wf_width()
        if ww == 0:
            return

        # Apply Solo/Mute dimming
        if self._is_dim(idx):
            color = QColor(track["color"])
            color.setAlpha(35)
            fill_c = QColor(track["fill"])
            fill_c.setAlpha(12)
        else:
            color = track["color"]
            fill_c = track["fill"]

        pi_start = max(0, int((vl - 2) / ww * n))
        pi_end   = min(n, int((vr + 2) / ww * n) + 1)

        top_pts: list[QPoint] = []
        bot_pts: list[QPoint] = []

        # 2× vertical gain for individual tracks; clamp to keep within row bounds
        gain = 1.0 if track["is_sum"] else 2.0

        for pi in range(pi_start, pi_end):
            x = LABEL_W + int(pi / n * ww) - self._scroll_x
            vmax = min(1.0, float(pk_max[pi]) * gain)
            vmin = max(-1.0, float(pk_min[pi]) * gain)
            top_pts.append(QPoint(x, mid - int(vmax * half)))
            bot_pts.append(QPoint(x, mid - int(vmin * half)))

        if not top_pts:
            return

        poly = QPolygon(top_pts + list(reversed(bot_pts)))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(fill_c))
        p.drawPolygon(poly)

        p.setPen(QPen(color, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(len(top_pts) - 1):
            p.drawLine(top_pts[i], top_pts[i + 1])
            p.drawLine(bot_pts[i], bot_pts[i + 1])

        # Beat / snare / downbeat diamonds on designated tracks
        self._paint_event_markers(p, track, y, h, vl, vr)

    def _paint_event_markers(self, p: QPainter, track: dict,
                              ty: int, th: int, vl: int, vr: int) -> None:
        """Draw diamond markers for beat/snare/downbeat events on designated tracks.

        Im Sim-Overlay-Modus werden die Original-JSONL-Events abgedunkelt und
        die Sim-Events (kick/snare/downbeat) voll sichtbar überlagert.
        """
        if not self.segment:
            return
        track_chs = self._track_chs_for(track)
        all_marker_chs = BEAT_MARKER_CHS | SNARE_MARKER_CHS | KICK_MARKER_CHS
        if not (track_chs & all_marker_chs):
            return

        seg = self.segment
        pps = self._pps
        ox = self._scroll_x
        w = self.width()
        r = _DIAMOND_R
        cy = ty + th - 2 - r   # bottom-aligned diamond center

        def _draw_diamond(ex: int, color: QColor, alpha: int = 180, radius: int = r) -> None:
            d = QPolygon([
                QPoint(ex,          cy - radius),
                QPoint(ex + radius, cy),
                QPoint(ex,          cy + radius),
                QPoint(ex - radius, cy),
            ])
            fill = QColor(color)
            fill.setAlpha(alpha)
            p.setPen(QPen(color, 1))
            p.setBrush(QBrush(fill))
            p.drawPolygon(d)

        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # ── Original-JSONL-Events ──────────────────────────────────────────────
        # Im Overlay-Modus mit Sim-Events: Probe-Marker komplett ausblenden
        _hide_orig = self._sim_overlay and bool(self._sim_kicks or self._sim_snares)
        if not _hide_orig:
            orig_alpha = 50 if self._sim_overlay else 180
            for ev in seg.events:
                ex = LABEL_W + int((ev.t - seg.start_t) * pps) - ox
                if ex < LABEL_W - r or ex > w + r:
                    continue
                color = self._marker_color_for(ev, track_chs)
                if color is None:
                    continue
                _draw_diamond(ex, color, alpha=orig_alpha)

        # ── Sim-Kick/Snare auf Kanal-Rows überlagern (nur im Overlay-Modus) ──
        if self._sim_overlay and (self._sim_kicks or self._sim_snares):
            seg_t0 = seg.start_t

            if track_chs & SNARE_MARKER_CHS:
                for t_s in self._sim_snares:
                    ex = LABEL_W + int((t_s - seg_t0) * pps) - ox
                    if LABEL_W - r <= ex <= w + r:
                        _draw_diamond(ex, C_CYAN, alpha=220)

            if track_chs & KICK_MARKER_CHS:
                for t_k in self._sim_kicks:
                    ex = LABEL_W + int((t_k - seg_t0) * pps) - ox
                    if LABEL_W - r <= ex <= w + r:
                        _draw_diamond(ex, C_AMBER, alpha=220)

        # ── Sim-Crashes auf OH L+R Row (roter Diamond, größer) ────────────────
        if self._sim_overlay and self._sim_crashes and (track_chs & BEAT_MARKER_CHS):
            seg_t0 = seg.start_t
            crash_cy = ty + th // 2   # vertikal zentriert (nicht unten wie Beats)
            for t_c, _e_c in self._sim_crashes:
                ex = LABEL_W + int((t_c - seg_t0) * pps) - ox
                if not (LABEL_W - r - 2 <= ex <= w + r + 2):
                    continue
                cr = r + 3   # größerer Radius für Crash
                d = QPolygon([
                    QPoint(ex,          crash_cy - cr),
                    QPoint(ex + cr, crash_cy),
                    QPoint(ex,          crash_cy + cr),
                    QPoint(ex - cr, crash_cy),
                ])
                fill = QColor(C_RED)
                fill.setAlpha(200)
                p.setPen(QPen(C_RED, 1))
                p.setBrush(QBrush(fill))
                p.drawPolygon(d)

        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    # ── Labels column (sticky) ────────────────────────────────────────────────

    def _paint_labels(self, p: QPainter, h: int) -> None:
        p.fillRect(0, 0, LABEL_W, h, C_BG)

        # Ruler cell
        p.fillRect(0, 0, LABEL_W, RULER_H, C_BG2)

        # Events cell — shows last event before cursor; click opens full list
        p.fillRect(0, RULER_H, LABEL_W, EVENTS_H, C_BG2)
        summary, color = self._current_event_label()
        p.setFont(FONT_MONO)
        p.setPen(color)
        p.drawText(6, RULER_H, LABEL_W - 10, EVENTS_H,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   summary)

        # Track cells
        for i, track in enumerate(TRACKS):
            y = TRACK_Y[i]
            th = track["h"]
            bg = C_BG2 if track["is_sum"] else C_BG3
            p.fillRect(0, y, LABEL_W, th, bg)

            # Colour swatch
            p.fillRect(2, y + th // 2 - 3, 4, 6, track["color"])

            # Label text (leave room for S/M buttons on the right)
            p.setFont(FONT_LABEL)
            p.setPen(C_T1 if track["is_sum"] else C_T2)
            p.drawText(10, y, LABEL_W - 52, th,
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       track["label"])

            # S/M buttons
            btn_y = y + (th - BTN_H) // 2

            # M button
            m_on = i in self._muted
            p.fillRect(BTN_M_X, btn_y, BTN_W, BTN_H,
                       C_RED if m_on else C_BG3)
            p.setPen(C_T1 if m_on else C_T4)
            p.setFont(FONT_BTN)
            p.drawText(BTN_M_X, btn_y, BTN_W, BTN_H,
                       Qt.AlignmentFlag.AlignCenter, "M")

            # S button
            s_on = i in self._soloed
            p.fillRect(BTN_S_X, btn_y, BTN_W, BTN_H,
                       C_AMBER if s_on else C_BG3)
            p.setPen(C_BG if s_on else C_T4)
            p.setFont(FONT_BTN)
            p.drawText(BTN_S_X, btn_y, BTN_W, BTN_H,
                       Qt.AlignmentFlag.AlignCenter, "S")

            p.setPen(C_BORDER)
            p.drawLine(0, y + th - 1, LABEL_W, y + th - 1)

        # Right border of label column
        p.setPen(QPen(C_BORDER, 1))
        p.drawLine(LABEL_W - 1, 0, LABEL_W - 1, h)

    # ── Cursor ────────────────────────────────────────────────────────────────

    def _paint_cursor(self, p: QPainter, h: int) -> None:
        if self.segment is None:
            return
        t = self.cursor_t - self.segment.start_t
        cx = LABEL_W + int(t * self._pps) - self._scroll_x
        if cx < LABEL_W or cx > self.width():
            return
        p.setPen(QPen(CURSOR_C, 2))
        p.drawLine(cx, RULER_H, cx, h)
        p.setBrush(QBrush(CURSOR_C))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygon([
            QPoint(cx - 5, RULER_H),
            QPoint(cx + 5, RULER_H),
            QPoint(cx, RULER_H + 9),
        ]))
