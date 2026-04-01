"""sim_monitor.py — Modales Echtzeit-Visualisierungsfenster für die Simulation.

Öffnet sich beim Start der Simulation, überlagert die gesamte App,
zeigt alle detektierten Events live als scrollendes Zeitdiagramm (40 px/s).
"""
from __future__ import annotations

import math
from typing import Optional

from PyQt6.QtCore import Qt, QPoint, QRect, QSize
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPolygon, QFontMetrics,
)
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QScrollBar,
    QSizePolicy, QVBoxLayout, QWidget, QToolTip,
)

from simulator import SimBeat, SimPosition

# ── Farben ────────────────────────────────────────────────────────────────────
C_BG      = QColor("#08090d")
C_BG2     = QColor("#0e1017")
C_BG3     = QColor("#151820")
C_BORDER  = QColor("#1e2230")
C_T1      = QColor("#eef0f6")
C_T2      = QColor("#a0a4b8")
C_T3      = QColor("#5c6080")
C_GREEN   = QColor("#00dc82")
C_AMBER   = QColor("#f0a030")
C_CYAN    = QColor("#38bdf8")
C_RED     = QColor("#ff3b5c")
C_VIOLET  = QColor("#a78bfa")
C_WHITE   = QColor("#ffffff")
C_GREY    = QColor("#363a52")

C_TRIG_KICK     = QColor("#f0a030")   # amber  — Kick-Trigger
C_TRIG_OVERHEAD = QColor("#38bdf8")   # cyan   — Overhead-Trigger
C_TRIG_TIMER    = QColor("#363a52")   # dunkel — Timer-Fallback

FONT_MONO  = QFont("DM Mono", 8)
FONT_LABEL = QFont("Sora", 9)
FONT_TINY  = QFont("DM Mono", 7)

# ── Layout ────────────────────────────────────────────────────────────────────
LABEL_W = 110      # linke Spalte (fixiert)
PPS     = 40.0     # Pixel pro Sekunde
D_R     = 5        # Diamond-Radius (px)
SCROLL_H = 14

# Zeilen-Definitionen: key, Label, Höhe
_ROWS: list[dict] = [
    {"key": "beats",     "label": "Beats",       "h": 27},
    {"key": "downbeat",  "label": "Downbeat",     "h": 27},
    {"key": "bpm",       "label": "BPM",          "h": 48},
    {"key": "fill",      "label": "Tom-Fill",      "h": 27},
    {"key": "trigger",   "label": "Trigger",      "h": 27},
    {"key": "snare",     "label": "Snare",        "h": 27},
    {"key": "kick",      "label": "Kick",         "h": 27},
    {"key": "mix_rms",   "label": "Summe (RMS)",  "h": 48},
    {"key": "hmm_bar",   "label": "HMM Takt",     "h": 27},
    {"key": "hmm_part",  "label": "HMM Part",     "h": 27},
    {"key": "hmm_conf",  "label": "HMM Konfidenz","h": 48},
    {"key": "hmm_frz",   "label": "Eingefroren",  "h": 27},
    {"key": "hmm_cons",  "label": "Konsensus",    "h": 27},
]
_TOTAL_H = sum(r["h"] for r in _ROWS) + SCROLL_H

# row y-offsets (computed once)
_ROW_Y: list[int] = []
_y = 0
for _r in _ROWS:
    _ROW_Y.append(_y)
    _y += _r["h"]


def _diamond(cx: int, cy: int, r: int = D_R) -> QPolygon:
    return QPolygon([
        QPoint(cx,     cy - r),
        QPoint(cx + r, cy    ),
        QPoint(cx,     cy + r),
        QPoint(cx - r, cy    ),
    ])


# ── Canvas Widget ─────────────────────────────────────────────────────────────

class SimCanvas(QWidget):
    """Scrollbares Canvas das alle Simulations-Events zeichnet."""

    def __init__(self, initial_bpm: float, parent=None) -> None:
        super().__init__(parent)
        self._initial_bpm = initial_bpm
        self._scroll_x: int = 0
        self._max_t: float = 0.0

        # Event-Speicher
        self._beats:     list[SimBeat]     = []
        self._snares:    list[float]        = []   # snare onset times
        self._rms_vals:  list[tuple[float, float]] = []  # (t, rms)
        self._positions: list[SimPosition]  = []

        self._playhead_t: float = -1.0  # aktuelle Audio-Position (Sekunden relativ zu sim_start)

        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(_TOTAL_H)
        self.setMaximumHeight(_TOTAL_H)

    # ── Public API ────────────────────────────────────────────────────────────

    def add_beat(self, b: SimBeat) -> None:
        self._beats.append(b)
        self._max_t = max(self._max_t, b.t)
        self.update()

    def add_snare(self, t: float) -> None:
        self._snares.append(t)
        self._max_t = max(self._max_t, t)
        self.update()

    def add_rms(self, t: float, rms_val: float) -> None:
        self._rms_vals.append((t, rms_val))
        self._max_t = max(self._max_t, t)
        self.update()

    def add_position(self, p: SimPosition) -> None:
        self._positions.append(p)
        self._max_t = max(self._max_t, p.t)
        self.update()

    def set_playhead(self, t: float) -> None:
        self._playhead_t = t
        self.update()

    def set_scroll(self, x: int) -> None:
        self._scroll_x = x
        self.update()

    def content_width(self) -> int:
        return max(self.width(), int(self._max_t * PPS) + 200)

    def view_width(self) -> int:
        return self.width() - LABEL_W

    # ── Painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w = self.width()
        ox = self._scroll_x

        # ── Hintergrund + Zeilentrenner ───────────────────────────────────────
        p.fillRect(0, 0, w, _TOTAL_H, C_BG)
        for i, row in enumerate(_ROWS):
            y = _ROW_Y[i]
            bg = C_BG if i % 2 == 0 else C_BG2
            p.fillRect(LABEL_W, y, w - LABEL_W, row["h"], bg)
            p.setPen(C_BORDER)
            p.drawLine(0, y + row["h"] - 1, w, y + row["h"] - 1)

        # ── Content ───────────────────────────────────────────────────────────
        self._paint_beats(p, ox)
        self._paint_downbeats(p, ox)
        self._paint_bpm(p, ox)
        self._paint_fills(p, ox)
        self._paint_triggers(p, ox)
        self._paint_snares(p, ox)
        self._paint_kicks(p, ox)
        self._paint_mix_rms(p, ox)
        self._paint_hmm_bar(p, ox)
        self._paint_hmm_part(p, ox)
        self._paint_hmm_conf(p, ox)
        self._paint_hmm_frozen(p, ox)
        self._paint_hmm_consensus(p, ox)

        # ── Playhead-Linie ────────────────────────────────────────────────────
        if self._playhead_t >= 0:
            px = self._x(self._playhead_t, ox)
            if self._in_view(px):
                p.setPen(QPen(C_WHITE, 2))
                p.drawLine(px, 0, px, _TOTAL_H - SCROLL_H)
                # Kleine Zeitangabe oben
                p.setFont(FONT_TINY)
                p.setPen(C_WHITE)
                p.drawText(px + 3, 2, 50, 12, Qt.AlignmentFlag.AlignLeft,
                           f"{self._playhead_t:.1f}s")

        # ── Sticky Label-Spalte (über allem) ──────────────────────────────────
        p.fillRect(0, 0, LABEL_W, _TOTAL_H - SCROLL_H, C_BG2)
        p.setPen(C_BORDER)
        p.drawLine(LABEL_W - 1, 0, LABEL_W - 1, _TOTAL_H - SCROLL_H)
        p.setFont(FONT_LABEL)
        for i, row in enumerate(_ROWS):
            y = _ROW_Y[i]
            p.setPen(C_T2)
            p.drawText(6, y, LABEL_W - 8, row["h"],
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       row["label"])

    def _x(self, t: float, ox: int) -> int:
        return LABEL_W + int(t * PPS) - ox

    def _in_view(self, x: int) -> bool:
        return LABEL_W <= x <= self.width()

    # ── Row painters ─────────────────────────────────────────────────────────

    def _paint_beats(self, p: QPainter, ox: int) -> None:
        """Senkrechte Striche, Höhe proportional zu beat_num (1=voll, 4=kurz)."""
        ri = next(i for i, r in enumerate(_ROWS) if r["key"] == "beats")
        y0, h = _ROW_Y[ri], _ROWS[ri]["h"]
        p.setFont(FONT_TINY)
        for b in self._beats:
            x = self._x(b.t, ox)
            if not self._in_view(x):
                continue
            # beat_num 1 = hell + voll, 2-4 = dunkler + kürzer
            alpha = 220 if b.beat_num == 1 else (150 if b.beat_num == 2 else 90)
            c = QColor(C_AMBER.red(), C_AMBER.green(), C_AMBER.blue(), alpha)
            frac = 1.0 - (b.beat_num - 1) * 0.2  # 1.0, 0.8, 0.6, 0.4
            line_h = max(4, int(h * frac))
            p.setPen(QPen(c, 1))
            p.drawLine(x, y0 + h - line_h, x, y0 + h - 1)
            # Zahl oben
            p.setPen(c)
            p.drawText(x + 2, y0, 12, 12, Qt.AlignmentFlag.AlignLeft, str(b.beat_num))

    def _paint_downbeats(self, p: QPainter, ox: int) -> None:
        ri = next(i for i, r in enumerate(_ROWS) if r["key"] == "downbeat")
        y0, h = _ROW_Y[ri], _ROWS[ri]["h"]
        cy = y0 + h // 2
        p.setBrush(QBrush(C_GREEN))
        p.setPen(Qt.PenStyle.NoPen)
        for b in self._beats:
            if not b.is_downbeat:
                continue
            x = self._x(b.t, ox)
            if not self._in_view(x):
                continue
            p.drawPolygon(_diamond(x, cy))

    def _paint_bpm(self, p: QPainter, ox: int) -> None:
        """Zwei Kurven: initiale BPM (grau gestrichelt) + live BPM (amber)."""
        ri = next(i for i, r in enumerate(_ROWS) if r["key"] == "bpm")
        y0, h = _ROW_Y[ri], _ROWS[ri]["h"]
        if not self._beats:
            return
        bpm_vals = [b.bpm for b in self._beats]
        bpm_min = max(60, min(bpm_vals) - 5)
        bpm_max = min(220, max(bpm_vals) + 5)
        if bpm_max <= bpm_min:
            bpm_max = bpm_min + 10

        def bpm_y(bpm: float) -> int:
            frac = (bpm - bpm_min) / (bpm_max - bpm_min)
            return y0 + h - 4 - int(frac * (h - 8))

        # Referenzlinie (initiale BPM)
        ref_y = bpm_y(self._initial_bpm)
        p.setPen(QPen(C_T3, 1, Qt.PenStyle.DashLine))
        p.drawLine(LABEL_W, ref_y, self.width(), ref_y)

        # Live-BPM-Kurve
        p.setPen(QPen(C_AMBER, 1))
        prev_pt = None
        for b in self._beats:
            x = self._x(b.t, ox)
            y = bpm_y(b.bpm)
            if prev_pt and self._in_view(x):
                p.drawLine(prev_pt[0], prev_pt[1], x, y)
            prev_pt = (x, y)

        # BPM-Beschriftung am rechten Rand
        p.setFont(FONT_TINY)
        p.setPen(C_T3)
        p.drawText(LABEL_W + 4, y0 + 2, 60, 12, Qt.AlignmentFlag.AlignLeft,
                   f"{bpm_min:.0f}")
        p.drawText(LABEL_W + 4, y0 + h - 14, 60, 12, Qt.AlignmentFlag.AlignLeft,
                   f"{bpm_max:.0f}")

    def _paint_fills(self, p: QPainter, ox: int) -> None:
        ri = next(i for i, r in enumerate(_ROWS) if r["key"] == "fill")
        y0, h = _ROW_Y[ri], _ROWS[ri]["h"]
        cy = y0 + h // 2
        p.setBrush(QBrush(C_RED))
        p.setPen(Qt.PenStyle.NoPen)
        for b in self._beats:
            if not b.is_fill:
                continue
            x = self._x(b.t, ox)
            if not self._in_view(x):
                continue
            p.drawPolygon(_diamond(x, cy))

    def _paint_triggers(self, p: QPainter, ox: int) -> None:
        ri = next(i for i, r in enumerate(_ROWS) if r["key"] == "trigger")
        y0, h = _ROW_Y[ri], _ROWS[ri]["h"]
        cy = y0 + h // 2
        for b in self._beats:
            x = self._x(b.t, ox)
            if not self._in_view(x):
                continue
            c = (C_TRIG_KICK if b.trigger == "kick"
                 else C_TRIG_OVERHEAD if b.trigger == "overhead"
                 else C_TRIG_TIMER)
            p.setBrush(QBrush(c))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(_diamond(x, cy))

    def _paint_snares(self, p: QPainter, ox: int) -> None:
        ri = next(i for i, r in enumerate(_ROWS) if r["key"] == "snare")
        y0, h = _ROW_Y[ri], _ROWS[ri]["h"]
        cy = y0 + h // 2
        p.setBrush(QBrush(C_CYAN))
        p.setPen(Qt.PenStyle.NoPen)
        for t in self._snares:
            x = self._x(t, ox)
            if not self._in_view(x):
                continue
            p.drawPolygon(_diamond(x, cy))

    def _paint_kicks(self, p: QPainter, ox: int) -> None:
        ri = next(i for i, r in enumerate(_ROWS) if r["key"] == "kick")
        y0, h = _ROW_Y[ri], _ROWS[ri]["h"]
        cy = y0 + h // 2
        p.setBrush(QBrush(C_AMBER))
        p.setPen(Qt.PenStyle.NoPen)
        for b in self._beats:
            if b.trigger != "kick":
                continue
            x = self._x(b.t, ox)
            if not self._in_view(x):
                continue
            p.drawPolygon(_diamond(x, cy))

    def _paint_mix_rms(self, p: QPainter, ox: int) -> None:
        """Summensignal — RMS-Kurve der Stereo-Mix-Kanäle (Ch 16+17)."""
        ri = next(i for i, r in enumerate(_ROWS) if r["key"] == "mix_rms")
        y0, h = _ROW_Y[ri], _ROWS[ri]["h"]
        if not self._rms_vals:
            return

        rms_max = max(v for _, v in self._rms_vals) or 0.01
        pad = 3

        def rms_y(v: float) -> int:
            frac = min(1.0, v / rms_max)
            return y0 + h - pad - int(frac * (h - 2 * pad))

        # Filled area under curve (semi-transparent green)
        fill_color = QColor(C_GREEN.red(), C_GREEN.green(), C_GREEN.blue(), 40)
        prev_x = prev_y = None
        for t, v in self._rms_vals:
            x = self._x(t, ox)
            y = rms_y(v)
            if prev_x is not None and self._in_view(x):
                p.setBrush(QBrush(fill_color))
                p.setPen(Qt.PenStyle.NoPen)
                poly = QPolygon([
                    QPoint(prev_x, y0 + h - pad),
                    QPoint(prev_x, prev_y),
                    QPoint(x, y),
                    QPoint(x, y0 + h - pad),
                ])
                p.drawPolygon(poly)
            prev_x, prev_y = x, y

        # Curve line
        p.setPen(QPen(C_GREEN, 1))
        prev_pt = None
        for t, v in self._rms_vals:
            x = self._x(t, ox)
            y = rms_y(v)
            if prev_pt and self._in_view(x):
                p.drawLine(prev_pt[0], prev_pt[1], x, y)
            prev_pt = (x, y)

    def _paint_hmm_bar(self, p: QPainter, ox: int) -> None:
        ri = next(i for i, r in enumerate(_ROWS) if r["key"] == "hmm_bar")
        y0, h = _ROW_Y[ri], _ROWS[ri]["h"]
        p.setFont(FONT_MONO)
        for pos in self._positions:
            x = self._x(pos.t, ox)
            if not self._in_view(x):
                continue
            c = C_T3 if pos.is_frozen else C_GREEN
            p.setPen(c)
            p.drawText(x + 2, y0, 40, h,
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       str(pos.bar_num))

    def _paint_hmm_part(self, p: QPainter, ox: int) -> None:
        ri = next(i for i, r in enumerate(_ROWS) if r["key"] == "hmm_part")
        y0, h = _ROW_Y[ri], _ROWS[ri]["h"]
        p.setFont(FONT_MONO)
        for pos in self._positions:
            x = self._x(pos.t, ox)
            if not self._in_view(x):
                continue
            if not pos.part_name:
                continue
            c = C_GREEN if pos.is_part_consensus else C_T2
            # Vertikale Markierung + Text
            p.setPen(QPen(c, 1))
            p.drawLine(x, y0, x, y0 + h - 1)
            p.setPen(c)
            p.drawText(x + 3, y0, 120, h,
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       pos.part_name)

    def _paint_hmm_conf(self, p: QPainter, ox: int) -> None:
        """Konfidenz-Kurve 0–1 mit gestrichelter Konfidenz-Schwelle bei 0.30."""
        ri = next(i for i, r in enumerate(_ROWS) if r["key"] == "hmm_conf")
        y0, h = _ROW_Y[ri], _ROWS[ri]["h"]
        if not self._positions:
            return

        def conf_y(c: float) -> int:
            return y0 + h - 4 - int(max(0.0, min(1.0, c)) * (h - 8))

        # Schwellen-Linie bei 0.30
        thresh_y = conf_y(0.30)
        p.setPen(QPen(C_T3, 1, Qt.PenStyle.DashLine))
        p.drawLine(LABEL_W, thresh_y, self.width(), thresh_y)

        # Kurve
        p.setPen(QPen(C_GREEN, 1))
        prev_pt = None
        for pos in self._positions:
            x = self._x(pos.t, ox)
            y = conf_y(pos.confidence)
            if prev_pt and self._in_view(x):
                p.drawLine(prev_pt[0], prev_pt[1], x, y)
            prev_pt = (x, y)

        # Beschriftung
        p.setFont(FONT_TINY)
        p.setPen(C_T3)
        p.drawText(LABEL_W + 4, y0 + 2, 40, 12, Qt.AlignmentFlag.AlignLeft, "1.0")
        p.drawText(LABEL_W + 4, thresh_y - 12, 40, 12,
                   Qt.AlignmentFlag.AlignLeft, "0.3")

    def _paint_hmm_frozen(self, p: QPainter, ox: int) -> None:
        ri = next(i for i, r in enumerate(_ROWS) if r["key"] == "hmm_frz")
        y0, h = _ROW_Y[ri], _ROWS[ri]["h"]
        cy = y0 + h // 2
        p.setBrush(QBrush(C_RED))
        p.setPen(Qt.PenStyle.NoPen)
        for pos in self._positions:
            if not pos.is_frozen:
                continue
            x = self._x(pos.t, ox)
            if not self._in_view(x):
                continue
            p.drawPolygon(_diamond(x, cy))

    def _paint_hmm_consensus(self, p: QPainter, ox: int) -> None:
        ri = next(i for i, r in enumerate(_ROWS) if r["key"] == "hmm_cons")
        y0, h = _ROW_Y[ri], _ROWS[ri]["h"]
        cy = y0 + h // 2
        p.setBrush(QBrush(C_GREEN))
        p.setPen(Qt.PenStyle.NoPen)
        for pos in self._positions:
            if not pos.is_part_consensus:
                continue
            x = self._x(pos.t, ox)
            if not self._in_view(x):
                continue
            p.drawPolygon(_diamond(x, cy))

    # ── Tooltip on mousemove ──────────────────────────────────────────────────

    def mouseMoveEvent(self, ev) -> None:
        mx = int(ev.position().x())
        my = int(ev.position().y())
        if mx < LABEL_W:
            QToolTip.hideText()
            return

        t_cursor = (mx - LABEL_W + self._scroll_x) / PPS
        tip = self._tooltip_at(mx, my, t_cursor)
        if tip:
            QToolTip.showText(ev.globalPosition().toPoint(), tip, self)
        else:
            QToolTip.hideText()

    def _tooltip_at(self, mx: int, my: int, t_cursor: float) -> str:
        """Gibt Tooltip-Text für den nächsten Event nahe (mx, my) zurück."""
        TOL_T = 0.3   # ±0.3 s Toleranz

        # Zeile bestimmen
        row_idx = -1
        for i, row in enumerate(_ROWS):
            if _ROW_Y[i] <= my < _ROW_Y[i] + row["h"]:
                row_idx = i
                break
        if row_idx < 0:
            return ""

        key = _ROWS[row_idx]["key"]

        if key in ("beats", "downbeat", "fill", "trigger", "kick"):
            nearest = min(
                (b for b in self._beats if abs(b.t - t_cursor) <= TOL_T),
                key=lambda b: abs(b.t - t_cursor),
                default=None,
            )
            if nearest:
                return (f"t={nearest.t:.3f}s  Beat {nearest.beat_num}  "
                        f"BPM {nearest.bpm:.1f}  "
                        f"{'↓Downbeat  ' if nearest.is_downbeat else ''}"
                        f"{'Fill  ' if nearest.is_fill else ''}"
                        f"Trigger: {nearest.trigger}")

        elif key == "snare":
            nearest_t = min(
                (t for t in self._snares if abs(t - t_cursor) <= TOL_T),
                key=lambda t: abs(t - t_cursor),
                default=None,
            )
            if nearest_t is not None:
                return f"Snare Onset  t={nearest_t:.3f}s"

        elif key == "mix_rms":
            nearest = min(
                self._rms_vals,
                key=lambda tv: abs(tv[0] - t_cursor),
                default=None,
            )
            if nearest and abs(nearest[0] - t_cursor) <= TOL_T:
                return f"Summe RMS  t={nearest[0]:.3f}s  {nearest[1]:.4f}"

        elif key in ("hmm_bar", "hmm_part", "hmm_conf", "hmm_frz", "hmm_cons"):
            nearest = min(
                (pos for pos in self._positions if abs(pos.t - t_cursor) <= TOL_T),
                key=lambda pos: abs(pos.t - t_cursor),
                default=None,
            )
            if nearest:
                frz = "⛔ eingefroren" if nearest.is_frozen else "✓ aktiv"
                cons = "  ◆ Konsensus" if nearest.is_part_consensus else ""
                return (f"t={nearest.t:.3f}s  Takt {nearest.bar_num}  "
                        f"Part: '{nearest.part_name}'  "
                        f"Konf: {nearest.confidence:.2f}  {frz}{cons}")

        return ""


# ── Dialog ────────────────────────────────────────────────────────────────────

class SimMonitorDialog(QDialog):
    """Modales Vollbild-Fenster für die Simulation."""

    def __init__(self, initial_bpm: float, song_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Simulation — {song_name}")
        # Non-modal + Window flag ensures it's a proper top-level window
        # (not a child widget) even when parent is set.
        self.setModal(False)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setStyleSheet("""
            QDialog   { background:#08090d; color:#eef0f6; }
            QPushButton { background:#151820; border:1px solid #1e2230;
                          color:#eef0f6; padding:4px 12px;
                          font-family:'DM Mono',monospace; font-size:10px;
                          border-radius:3px; }
            QPushButton:hover { background:#1c1f2b; }
            QPushButton#close_btn { background:#ff3b5c22; border-color:#ff3b5c; color:#ff3b5c; }
            QScrollBar:horizontal { background:#0e1017; height:14px; }
            QScrollBar::handle:horizontal { background:#2a2e40; border-radius:4px; min-width:20px; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }
            QLabel#status_lbl { font-family:'DM Mono',monospace; font-size:10px;
                                 color:#a0a4b8; padding:0 8px; }
        """)

        self._canvas = SimCanvas(initial_bpm, self)
        self._auto_scroll = True

        # Scrollbar
        self._hbar = QScrollBar(Qt.Orientation.Horizontal, self)
        self._hbar.setMinimum(0)
        self._hbar.setMaximum(0)
        self._hbar.valueChanged.connect(self._on_scroll)
        self._hbar.sliderPressed.connect(lambda: setattr(self, "_auto_scroll", False))

        # Status-Label + Close-Button
        self._status_lbl = QLabel("Warte auf Events …")
        self._status_lbl.setObjectName("status_lbl")

        close_btn = QPushButton("✕ Schließen")
        close_btn.setObjectName("close_btn")
        close_btn.clicked.connect(self.close)

        # Layout
        top_bar = QHBoxLayout()
        top_bar.addWidget(self._status_lbl, stretch=1)
        top_bar.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top_bar)
        layout.addWidget(self._canvas, stretch=1)
        layout.addWidget(self._hbar)

    # ── Public API ────────────────────────────────────────────────────────────

    def add_beat(self, b: SimBeat) -> None:
        self._canvas.add_beat(b)
        self._update_scroll()

    def add_snare(self, t: float) -> None:
        self._canvas.add_snare(t)
        self._update_scroll()

    def add_rms(self, t: float, rms_val: float) -> None:
        self._canvas.add_rms(t, rms_val)
        self._update_scroll()

    def set_playhead(self, t: float) -> None:
        self._canvas.set_playhead(t)
        if self._auto_scroll:
            self._scroll_to_playhead(t)

    def add_position(self, pos: SimPosition) -> None:
        self._canvas.add_position(pos)
        self._update_scroll()

    def reset(self, initial_bpm: float, song_name: str) -> None:
        """Löscht alle bisherigen Daten und bereitet das Fenster für eine neue Simulation vor."""
        self.setWindowTitle(f"Simulation — {song_name}")
        self._canvas._beats.clear()
        self._canvas._snares.clear()
        self._canvas._rms_vals.clear()
        self._canvas._positions.clear()
        self._canvas._max_t = 0.0
        self._canvas._initial_bpm = initial_bpm
        self._canvas._scroll_x = 0
        self._canvas._playhead_t = -1.0
        self._auto_scroll = True
        self._hbar.setValue(0)
        self._hbar.setMaximum(0)
        self._status_lbl.setText("Warte auf Events …")
        self._canvas.update()

    def set_status(self, text: str) -> None:
        self._status_lbl.setText(text)

    # ── Scroll management ─────────────────────────────────────────────────────

    def _update_scroll(self) -> None:
        content_w = self._canvas.content_width()
        view_w    = self._canvas.view_width()
        if view_w <= 0:
            return   # canvas not yet sized — skip until resizeEvent fires
        max_scroll = max(0, content_w - view_w)
        self._hbar.setMaximum(max_scroll)
        self._hbar.setPageStep(view_w)

    def _scroll_to_playhead(self, t: float) -> None:
        """Scrollt so, dass die Playhead-Linie ~30% vom linken Rand sichtbar ist."""
        view_w = self._canvas.view_width()
        if view_w <= 0:
            return
        # Playhead bei 30% des sichtbaren Bereichs
        target = int(t * PPS) - view_w // 3
        max_scroll = self._hbar.maximum()
        self._hbar.setValue(max(0, min(target, max_scroll)))

    def _on_scroll(self, val: int) -> None:
        self._canvas.set_scroll(val)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._update_scroll()
