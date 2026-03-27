"""timeline.py — Scrollable, zoomable waveform + event timeline widget.

Layout (top to bottom):
  Time ruler   (RULER_H px)
  Event strip  (EVENTS_H px)
  Track rows   (track["h"] px each, separated by TRACK_GAP)

Left LABEL_W pixels are the sticky label column — drawn last so they
always appear on top of the scrolled waveform content.
"""
from __future__ import annotations

import math
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
LABEL_W   = 160
RULER_H   = 28
EVENTS_H  = 52
MIX_H     = 88
TRACK_H   = 54
TRACK_GAP = 2
SCROLL_H  = 14

# ── Colors ────────────────────────────────────────────────────────────────────
C_BG     = QColor("#08090d")
C_BG2    = QColor("#0e1017")
C_BG3    = QColor("#151820")
C_BORDER = QColor("#1e2230")
C_T1     = QColor("#eef0f6")
C_T2     = QColor("#a0a4b8")
C_T3     = QColor("#5c6080")
C_T4     = QColor("#363a52")
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

# ── Track definitions (in display order) ─────────────────────────────────────
TRACKS: list[dict] = []
for _ch in DISPLAY_CHANNELS:
    _is_sum = _ch in SUM_CHANNELS
    TRACKS.append({
        "ch":     _ch,
        "label":  CHANNEL_LABELS.get(_ch, f"CH {_ch + 1}"),
        "color":  WF_SUM if _is_sum else WF_CH,
        "fill":   WF_SUM_F if _is_sum else WF_CH_F,
        "h":      MIX_H if _is_sum else TRACK_H,
        "is_sum": _is_sum,
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


class TimelineWidget(QWidget):
    """Waveform + event timeline for one SongSegment.

    The left LABEL_W pixels are always visible (sticky).
    The rest scrolls horizontally.
    seek_requested emits seconds relative to segment start.
    """

    seek_requested = pyqtSignal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.segment: Optional[SongSegment] = None
        self.peaks: Optional[TrackPeaks] = None
        self.cursor_t: float = 0.0      # seconds in WAV

        self._pps: float = 80.0         # pixels per second
        self._scroll_x: int = 0

        self._hbar = QScrollBar(Qt.Orientation.Horizontal, self)
        self._hbar.valueChanged.connect(self._on_scroll)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(CONTENT_H)

    # ── Public API ────────────────────────────────────────────────────────────

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
        # Auto-scroll to keep cursor visible
        if self.segment:
            cx = int((wav_t - self.segment.start_t) * self._pps)
            vw = self._visible_w()
            if cx < self._scroll_x:
                self._hbar.setValue(max(0, cx - 40))
            elif cx > self._scroll_x + vw - 40:
                self._hbar.setValue(cx - vw + 80)
        self.update()

    def set_zoom(self, pps: float) -> None:
        self._pps = max(4.0, min(800.0, pps))
        self._sync_scrollbar()
        self.update()

    @property
    def zoom(self) -> float:
        return self._pps

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
        if event.button() == Qt.MouseButton.LeftButton and self.segment:
            x = event.position().x()
            if x >= LABEL_W:
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
                       "Keine Aufnahme geladen\n\nDatei  →  Öffnen…")
            return

        vl = self._scroll_x                       # visible left in waveform coords
        vr = self._scroll_x + self._visible_w()   # visible right

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

        secs_vis = max(1.0, self._visible_w() / self._pps)
        if   secs_vis > 300: major, minor = 60, 10
        elif secs_vis > 120: major, minor = 30, 5
        elif secs_vis > 60:  major, minor = 15, 5
        elif secs_vis > 30:  major, minor = 10, 2
        elif secs_vis > 10:  major, minor = 5, 1
        elif secs_vis > 4:   major, minor = 2, 0.5
        else:                major, minor = 1, 0.25

        p.setFont(FONT_TIME)
        t = math.floor(vl / self._pps / minor) * minor
        while t * self._pps <= vr:
            x = LABEL_W + int(t * self._pps) - self._scroll_x
            if x >= LABEL_W:
                is_major = abs(t % major) < minor * 0.1
                if is_major:
                    p.setPen(C_T2)
                    p.drawLine(x, RULER_H - 12, x, RULER_H - 1)
                    p.drawText(x + 3, 2, 80, RULER_H - 4,
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
                    label_map = {"next": "→", "prev": "←",
                                 "goto": "⤷", "accent": "★"}
                    p.setPen(QPen(C_GREEN, 2))
                    p.drawLine(ex, y0 + EVENTS_H // 3, ex, y0 + EVENTS_H - 2)
                    p.setPen(C_GREEN)
                    p.drawText(ex + 2, y0 + EVENTS_H // 3, 20, EVENTS_H // 2,
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                               label_map.get(action, "?"))

    # ── Waveform track ────────────────────────────────────────────────────────

    def _paint_track(self, p: QPainter, _idx: int, track: dict,
                     y: int, vl: int, vr: int) -> None:
        h = track["h"]
        w = self.width()
        mid = y + h // 2
        half = (h - 8) // 2

        bg = C_BG2 if track["is_sum"] else C_BG3
        p.fillRect(LABEL_W, y, w - LABEL_W, h, bg)
        p.setPen(C_BORDER)
        p.drawLine(LABEL_W, y + h - 1, w, y + h - 1)

        # Centre line
        p.setPen(QPen(C_T4, 1))
        p.drawLine(LABEL_W, mid, w, mid)

        if self.peaks is None:
            p.setPen(C_T4)
            p.setFont(FONT_MONO)
            p.drawText(LABEL_W + 6, y, w - LABEL_W - 8, h,
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       "Lade…")
            return

        cp = self.peaks.channel_peaks.get(track["ch"])
        if cp is None or cp.n_points == 0:
            return

        ww = self._wf_width()
        if ww == 0:
            return

        n = cp.n_points
        # Map visible pixel range to peak indices (+ 2 px margin)
        pi_start = max(0, int((vl - 2) / ww * n))
        pi_end   = min(n, int((vr + 2) / ww * n) + 1)

        color  = track["color"]
        fill_c = track["fill"]

        top_pts: list[QPoint] = []
        bot_pts: list[QPoint] = []

        for pi in range(pi_start, pi_end):
            x = LABEL_W + int(pi / n * ww) - self._scroll_x
            vmax = float(cp.peaks_max[pi])
            vmin = float(cp.peaks_min[pi])
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
        # Opaque background to cover waveforms underneath
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
        p.setFont(FONT_LABEL)
        for i, track in enumerate(TRACKS):
            y = TRACK_Y[i]
            th = track["h"]
            bg = C_BG2 if track["is_sum"] else C_BG3
            p.fillRect(0, y, LABEL_W, th, bg)

            # Colour swatch
            p.fillRect(2, y + th // 2 - 3, 4, 6, track["color"])

            p.setPen(C_T1 if track["is_sum"] else C_T2)
            p.drawText(10, y, LABEL_W - 12, th,
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       track["label"])

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
        # Triangle head
        p.setBrush(QBrush(CURSOR_C))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygon([
            QPoint(cx - 5, RULER_H),
            QPoint(cx + 5, RULER_H),
            QPoint(cx, RULER_H + 9),
        ]))
