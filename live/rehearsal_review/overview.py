"""overview.py — Full-session overview waveform (mini-map navigation)."""
from __future__ import annotations

from typing import Optional

import numpy as np
from PyQt6.QtCore import Qt, QRect, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPolygon, QPoint,
)
from PyQt6.QtWidgets import QWidget, QSizePolicy

from session import Session, SongSegment

# ── Colors (matching design system) ──────────────────────────────────────────
_BG2    = QColor("#0e1017")
_BORDER = QColor("#1e2230")
_T3     = QColor("#a0a4b8")
_T4     = QColor("#5c6080")
_GREEN  = QColor("#00dc82")
_WF     = QColor("#00dc82")
_WF_F   = QColor(0x00, 0xdc, 0x82, 45)
_CURSOR = QColor("#ff3b5c")
_SEG_HL = QColor(0x00, 0xdc, 0x82, 30)
_SEG_LN = QColor(0x00, 0xdc, 0x82, 160)

_FONT = QFont("DM Mono", 8)

HEIGHT = 72   # fixed widget height in px


class OverviewWidget(QWidget):
    """Full-session waveform mini-map with click-to-seek.

    Shows the Main L/R mix for the entire recording duration.
    The currently selected segment is highlighted green.
    Clicking emits seek_requested(wav_t) with absolute WAV seconds.
    """

    seek_requested = pyqtSignal(float)   # absolute WAV time

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._session: Optional[Session] = None
        self._pk_max: Optional[np.ndarray] = None   # combined L+R max envelope
        self._pk_min: Optional[np.ndarray] = None   # combined L+R min envelope
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

        p.fillRect(0, 0, w, h, _BG2)

        if self._session is None:
            p.setPen(_T3)
            p.setFont(_FONT)
            p.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter,
                       "Keine Session geladen")
            p.end()
            return

        # ── Waveform ──
        if self._pk_max is not None and len(self._pk_max) > 0:
            n = len(self._pk_max)
            mid = h // 2
            half = h // 2 - 5

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

        # ── Segment markers (song boundaries) ──
        p.setFont(_FONT)
        for seg in self._session.songs:
            if not seg.song_id:
                continue  # skip fallback "whole session" entry
            x = self._t_to_x(seg.start_t)
            if x < 0:
                continue
            p.setPen(QPen(_T4, 1))
            p.drawLine(x, 0, x, h)
            p.setPen(_T3)
            p.drawText(x + 3, 2, 110, h // 2,
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       seg.song_name[:16])

        # ── Current segment highlight ──
        if self._seg_end > self._seg_start:
            x1 = self._t_to_x(self._seg_start)
            x2 = self._t_to_x(self._seg_end)
            if x1 >= 0 and x2 > x1:
                p.fillRect(x1, 0, x2 - x1, h, _SEG_HL)
                p.setPen(QPen(_SEG_LN, 1))
                p.drawLine(x1, 0, x1, h)
                p.drawLine(x2, 0, x2, h)

        # ── Cursor ──
        cx = self._cursor_px if self._cursor_px >= 0 else self._t_to_x(self._cursor_t)
        if 0 <= cx < w:
            p.setPen(QPen(_CURSOR, 2))
            p.drawLine(cx, 0, cx, h)

        # ── Bottom border ──
        p.setPen(QPen(_BORDER, 1))
        p.drawLine(0, h - 1, w, h - 1)

        p.end()
