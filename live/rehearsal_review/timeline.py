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
from PyQt6.QtWidgets import QWidget, QScrollBar, QSizePolicy

from session import SongSegment
from peaks import TrackPeaks, CHANNEL_LABELS, SUM_CHANNELS, DISPLAY_CHANNELS

# ── Layout ────────────────────────────────────────────────────────────────────
LABEL_W   = 196
RULER_H   = 28
EVENTS_H  = 26   # halved from 52
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

# ── Track definitions (in display order) ─────────────────────────────────────

# Combined Main L+R as single virtual track (ch=-1, merges ch 16+17)
TRACKS: list[dict] = [
    {
        "ch":           -1,
        "combined_chs": (16, 17),
        "label":        "Main L+R",
        "color":        WF_SUM,
        "fill":         WF_SUM_F,
        "h":            MIX_H,
        "is_sum":       True,
    },
]
for _ch in DISPLAY_CHANNELS:
    if _ch in SUM_CHANNELS:
        continue   # skip individual Main L / Main R
    TRACKS.append({
        "ch":     _ch,
        "label":  CHANNEL_LABELS.get(_ch, f"CH {_ch + 1}"),
        "color":  WF_CH,
        "fill":   WF_CH_F,
        "h":      TRACK_H,
        "is_sum": False,
    })

# Pre-compute y offsets
_y = RULER_H + EVENTS_H
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

        self._hbar = QScrollBar(Qt.Orientation.Horizontal, self)
        self._hbar.valueChanged.connect(self._on_scroll)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(CONTENT_H)

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
        self._pps = max(4.0, min(800.0, pps))
        self._sync_scrollbar()
        self.update()

    @property
    def zoom(self) -> float:
        return self._pps

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

        # Check S/M button clicks in label column
        if x < LABEL_W:
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

        if event.button() == Qt.MouseButton.LeftButton and self.segment:
            t = (x - LABEL_W + self._scroll_x) / self._pps
            t = max(0.0, min(t, self.segment.duration))
            self.seek_requested.emit(t)

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
        for i, track in enumerate(TRACKS):
            self._paint_track(p, i, track, TRACK_Y[i], vl, vr)

        # Sticky labels drawn OVER waveforms
        self._paint_labels(p, h)

        # Playback cursor
        self._paint_cursor(p, h)

        p.end()

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

        # Resolve peak data (combined or single channel)
        if "combined_chs" in track:
            chs = track["combined_chs"]
            cp1 = self.peaks.channel_peaks.get(chs[0])
            cp2 = self.peaks.channel_peaks.get(chs[1])
            if cp1 and cp2 and cp1.n_points > 0 and cp2.n_points > 0:
                n = min(cp1.n_points, cp2.n_points)
                pk_max = np.maximum(cp1.peaks_max[:n], cp2.peaks_max[:n])
                pk_min = np.minimum(cp1.peaks_min[:n], cp2.peaks_min[:n])
            elif cp1 and cp1.n_points > 0:
                pk_max, pk_min, n = cp1.peaks_max, cp1.peaks_min, cp1.n_points
            elif cp2 and cp2.n_points > 0:
                pk_max, pk_min, n = cp2.peaks_max, cp2.peaks_min, cp2.n_points
            else:
                return
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

        for pi in range(pi_start, pi_end):
            x = LABEL_W + int(pi / n * ww) - self._scroll_x
            vmax = float(pk_max[pi])
            vmin = float(pk_min[pi])
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

    # ── Labels column (sticky) ────────────────────────────────────────────────

    def _paint_labels(self, p: QPainter, h: int) -> None:
        p.fillRect(0, 0, LABEL_W, h, C_BG)

        # Ruler cell
        p.fillRect(0, 0, LABEL_W, RULER_H, C_BG2)

        # Events cell
        p.fillRect(0, RULER_H, LABEL_W, EVENTS_H, C_BG2)
        p.setPen(C_T3)
        p.setFont(FONT_MONO)
        p.drawText(6, RULER_H, LABEL_W - 8, EVENTS_H,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "EVENTS")

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
