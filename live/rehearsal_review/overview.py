"""overview.py — Full-session overview waveform (mini-map navigation)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import numpy as np
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPolygon,
)
from PyQt6.QtWidgets import QWidget, QSizePolicy

from session import Session, SongSegment

# ── Colors (matching design system) ──────────────────────────────────────────
_BG     = QColor("#08090d")
_BG2    = QColor("#0e1017")
_BORDER = QColor("#1e2230")
_T3     = QColor("#a0a4b8")
_T4     = QColor("#5c6080")
_T1     = QColor("#eef0f6")
_GREEN  = QColor("#00dc82")
_WF     = QColor("#00dc82")
_WF_F   = QColor(0x00, 0xdc, 0x82, 45)
_CURSOR = QColor("#ff3b5c")
_SEG_HL = QColor(0x00, 0xdc, 0x82, 30)
_SEG_LN = QColor(0x00, 0xdc, 0x82, 160)

_FONT      = QFont("DM Mono", 8)
_FONT_RULE = QFont("DM Mono", 7)
_FONT_NAME = QFont("Sora", 8)

RULER_H = 18   # clock-time ruler
NAME_H  = 16   # song name strip below ruler
HEIGHT  = 106  # total: RULER_H(18) + NAME_H(16) + waveform(70) + border(2)


class OverviewWidget(QWidget):
    """Full-session waveform mini-map with click-to-seek.

    Shows the Main L/R mix for the entire recording duration.
    Three horizontal bands:
      - Clock-time ruler (RULER_H px)
      - Song name strip  (NAME_H px)  — names above waveform, not overlaid
      - Waveform area
    """

    seek_requested = pyqtSignal(float)   # absolute WAV time

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._session: Optional[Session] = None
        self._pk_max: Optional[np.ndarray] = None
        self._pk_min: Optional[np.ndarray] = None
        self._cursor_t: float = 0.0
        self._seg_start: float = 0.0
        self._seg_end: float = 0.0
        self._cursor_px: int = -1

        self.setFixedHeight(HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_session(self, session: Session) -> None:
        self._session = session
        self._pk_max = None
        self._pk_min = None
        self._cursor_t = 0.0
        self._cursor_px = -1
        self._seg_start = 0.0
        self._seg_end = 0.0
        self.update()

    def set_peaks(self, pk_max: np.ndarray, pk_min: np.ndarray) -> None:
        """Receive combined L+R peak envelopes (shape: (n,) float32)."""
        self._pk_max = pk_max
        self._pk_min = pk_min
        self.update()

    def set_playhead(self, wav_t: float) -> None:
        """Update cursor position (absolute WAV seconds)."""
        old_px = self._cursor_px
        self._cursor_t = wav_t
        new_px = self._t_to_x(wav_t)
        self._cursor_px = new_px
        h = self.height()
        for px in (old_px, new_px):
            if px >= 0:
                self.update(QRect(px - 2, 0, 5, h))

    def set_segment(self, seg: SongSegment) -> None:
        """Highlight the currently active segment."""
        old_s, old_e = self._seg_start, self._seg_end
        self._seg_start = seg.start_t
        self._seg_end = seg.end_t
        h = self.height()
        for t0, t1 in ((old_s, old_e), (seg.start_t, seg.end_t)):
            x0 = max(0, self._t_to_x(t0) - 1)
            x1 = min(self.width(), self._t_to_x(t1) + 2)
            if x1 > x0:
                self.update(QRect(x0, 0, x1 - x0, h))

    # ── Internal ──────────────────────────────────────────────────────────────

    def _t_to_x(self, t: float) -> int:
        if not self._session or self._session.total_duration <= 0 or self.width() <= 0:
            return -1
        return int(t / self._session.total_duration * self.width())

    # ── Qt events ─────────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._session:
            t = event.position().x() / self.width() * self._session.total_duration
            self.seek_requested.emit(max(0.0, min(t, self._session.total_duration)))

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        wf_y = RULER_H + NAME_H          # waveform area starts here
        wf_h = h - wf_y - 1             # waveform height (leave 1px for bottom border)

        p.fillRect(0, 0, w, h, _BG2)

        if self._session is None:
            p.setPen(_T3)
            p.setFont(_FONT)
            p.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter,
                       "Keine Session geladen")
            p.end()
            return

        # ── Clock-time ruler (every 15 minutes = 900 s) ──
        rec_start = getattr(self._session, "recording_started_at", None)
        dur = self._session.total_duration
        if dur > 0:
            tick = 900  # every 15 minutes
            p.setFont(_FONT_RULE)
            t = 0.0
            while t <= dur:
                x = int(t / dur * w)
                p.setPen(QPen(_T3, 1))
                p.drawLine(x, 0, x, RULER_H - 2)
                if rec_start is not None:
                    lbl = (rec_start + timedelta(seconds=t)).strftime("%H:%M")
                else:
                    m_, s_ = divmod(int(t), 60)
                    lbl = f"{m_}:{s_:02d}"
                p.setPen(_T1)
                p.drawText(x + 3, 0, 55, RULER_H,
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           lbl)
                t += tick

        p.setPen(QPen(_T4, 1))
        p.drawLine(0, RULER_H - 1, w, RULER_H - 1)

        # ── Song name strip ──
        p.fillRect(0, RULER_H, w, NAME_H, _BG)
        p.setFont(_FONT_NAME)
        for seg in self._session.songs:
            if seg.song_id:
                x = self._t_to_x(seg.start_t)
                if x < 0:
                    continue
                # Vertical divider at segment start
                p.setPen(QPen(_T4, 1))
                p.drawLine(x, RULER_H, x, RULER_H + NAME_H - 1)
                # Full song name
                p.setPen(_T3)
                p.drawText(x + 4, RULER_H, w - x - 4, NAME_H,
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           seg.song_name)
            else:
                # Fallback single-segment: show session name
                p.setPen(_T3)
                p.drawText(4, RULER_H, w - 8, NAME_H,
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           seg.song_name)

        p.setPen(QPen(_T4, 1))
        p.drawLine(0, RULER_H + NAME_H - 1, w, RULER_H + NAME_H - 1)

        # ── Current segment highlight ──
        if self._seg_end > self._seg_start:
            x1 = self._t_to_x(self._seg_start)
            x2 = self._t_to_x(self._seg_end)
            if x1 >= 0 and x2 > x1:
                p.fillRect(x1, wf_y, x2 - x1, wf_h, _SEG_HL)
                p.setPen(QPen(_SEG_LN, 1))
                p.drawLine(x1, wf_y, x1, h)
                p.drawLine(x2, wf_y, x2, h)

        # ── Waveform ──
        if self._pk_max is not None and len(self._pk_max) > 0:
            n = len(self._pk_max)
            mid = wf_y + wf_h // 2
            half = wf_h // 2 - 3

            top_pts: list[QPoint] = []
            bot_pts: list[QPoint] = []
            for pi in range(n):
                x = int(pi / n * w)
                top_pts.append(QPoint(x, mid - int(float(self._pk_max[pi]) * half)))
                bot_pts.append(QPoint(x, mid - int(float(self._pk_min[pi]) * half)))

            poly = QPolygon(top_pts + list(reversed(bot_pts)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(_WF_F))
            p.drawPolygon(poly)
            p.setPen(QPen(_WF, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(len(top_pts) - 1):
                p.drawLine(top_pts[i], top_pts[i + 1])
                p.drawLine(bot_pts[i], bot_pts[i + 1])

        # ── Cursor ──
        cx = self._cursor_px if self._cursor_px >= 0 else self._t_to_x(self._cursor_t)
        if 0 <= cx < w:
            p.setPen(QPen(_CURSOR, 2))
            p.drawLine(cx, wf_y, cx, h)

        # ── Bottom border ──
        p.setPen(QPen(_BORDER, 1))
        p.drawLine(0, h - 1, w, h - 1)

        p.end()
