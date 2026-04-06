"""sim_monitor.py — Visualisierungsfenster für Kick/Snare-Simulations-Events.

Zeigt nach Abschluss der Simulation die erkannten Kick- und Snare-Onsets
als Diamonds auf einer horizontalen Zeitachse.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QPoint, QRect, QSize
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPolygon,
)
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QScrollBar,
    QSizePolicy, QVBoxLayout, QWidget, QToolTip,
)

# ── Farben ────────────────────────────────────────────────────────────────────
C_BG      = QColor("#08090d")
C_BG2     = QColor("#0e1017")
C_BORDER  = QColor("#1e2230")
C_T2      = QColor("#a0a4b8")
C_T3      = QColor("#5c6080")
C_GREEN   = QColor("#00dc82")
C_AMBER   = QColor("#f0a030")
C_CYAN    = QColor("#38bdf8")
C_WHITE   = QColor("#ffffff")

FONT_MONO  = QFont("DM Mono", 8)
FONT_LABEL = QFont("Sora", 9)
FONT_TINY  = QFont("DM Mono", 7)

# ── Layout ────────────────────────────────────────────────────────────────────
LABEL_W  = 110     # linke Spalte (fixiert)
PPS      = 40.0    # Pixel pro Sekunde
D_R      = 5       # Diamond-Radius (px)
SCROLL_H = 14

# Zeilen-Definitionen: key, Label, Höhe
_ROWS: list[dict] = [
    {"key": "kick",  "label": "Kick  CH09",  "h": 40},
    {"key": "snare", "label": "Snare CH10",  "h": 40},
]
_TOTAL_H = sum(r["h"] for r in _ROWS) + SCROLL_H

# row y-offsets (einmalig berechnet)
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
    """Scrollbares Canvas das Kick- und Snare-Onsets als Diamonds zeichnet."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scroll_x: int = 0
        self._max_t: float = 0.0

        self._kicks:  list[float] = []
        self._snares: list[float] = []

        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(_TOTAL_H)
        self.setMaximumHeight(_TOTAL_H)

    # ── Public API ────────────────────────────────────────────────────────────

    def add_kick(self, t: float) -> None:
        self._kicks.append(t)
        self._max_t = max(self._max_t, t)
        self.update()

    def add_snare(self, t: float) -> None:
        self._snares.append(t)
        self._max_t = max(self._max_t, t)
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
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w   = self.width()
        ox  = self._scroll_x

        # Hintergrund + Zeilentrenner
        p.fillRect(0, 0, w, _TOTAL_H, C_BG)
        for i, row in enumerate(_ROWS):
            y  = _ROW_Y[i]
            bg = C_BG if i % 2 == 0 else C_BG2
            p.fillRect(LABEL_W, y, w - LABEL_W, row["h"], bg)
            p.setPen(C_BORDER)
            p.drawLine(0, y + row["h"] - 1, w, y + row["h"] - 1)

        # Kicks — amber Diamonds (mitte der Zeile)
        ri_kick = next(i for i, r in enumerate(_ROWS) if r["key"] == "kick")
        y0k, hk = _ROW_Y[ri_kick], _ROWS[ri_kick]["h"]
        cyk = y0k + hk // 2
        p.setBrush(QBrush(C_AMBER))
        p.setPen(Qt.PenStyle.NoPen)
        for t in self._kicks:
            x = self._x(t, ox)
            if self._in_view(x):
                p.drawPolygon(_diamond(x, cyk))

        # Snares — cyan Diamonds (mitte der Zeile)
        ri_snare = next(i for i, r in enumerate(_ROWS) if r["key"] == "snare")
        y0s, hs = _ROW_Y[ri_snare], _ROWS[ri_snare]["h"]
        cys = y0s + hs // 2
        p.setBrush(QBrush(C_CYAN))
        p.setPen(Qt.PenStyle.NoPen)
        for t in self._snares:
            x = self._x(t, ox)
            if self._in_view(x):
                p.drawPolygon(_diamond(x, cys))

        # Sticky Label-Spalte (über allem)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
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

    # ── Tooltip ───────────────────────────────────────────────────────────────

    def mouseMoveEvent(self, ev) -> None:
        mx = int(ev.position().x())
        my = int(ev.position().y())
        if mx < LABEL_W:
            QToolTip.hideText()
            return

        t_cursor = (mx - LABEL_W + self._scroll_x) / PPS
        TOL_T    = 0.15   # ±150 ms Toleranz

        # Zeile bestimmen
        for i, row in enumerate(_ROWS):
            if _ROW_Y[i] <= my < _ROW_Y[i] + row["h"]:
                key = row["key"]
                pool = self._kicks if key == "kick" else self._snares
                nearest = min(
                    (t for t in pool if abs(t - t_cursor) <= TOL_T),
                    key=lambda t: abs(t - t_cursor),
                    default=None,
                )
                if nearest is not None:
                    QToolTip.showText(
                        ev.globalPosition().toPoint(),
                        f"{key.capitalize()} Onset  t={nearest:.3f}s",
                        self,
                    )
                else:
                    QToolTip.hideText()
                return
        QToolTip.hideText()


# ── Dialog ────────────────────────────────────────────────────────────────────

class SimMonitorDialog(QDialog):
    """Fenster für die Simulations-Nachbereitung (Kick/Snare-Onsets)."""

    def __init__(self, initial_bpm: float, song_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Simulation — {song_name}")
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

        self._canvas = SimCanvas(self)
        self._auto_scroll = True

        self._hbar = QScrollBar(Qt.Orientation.Horizontal, self)
        self._hbar.setMinimum(0)
        self._hbar.setMaximum(0)
        self._hbar.valueChanged.connect(self._on_scroll)
        self._hbar.sliderPressed.connect(lambda: setattr(self, "_auto_scroll", False))

        self._status_lbl = QLabel("Lade …")
        self._status_lbl.setObjectName("status_lbl")

        close_btn = QPushButton("✕ Schließen")
        close_btn.setObjectName("close_btn")
        close_btn.clicked.connect(self.close)

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

    def add_kick(self, t: float) -> None:
        self._canvas.add_kick(t)
        self._update_scroll()

    def add_snare(self, t: float) -> None:
        self._canvas.add_snare(t)
        self._update_scroll()

    def set_playhead(self, t: float) -> None:
        """Kein aktiver Playhead in dieser Ansicht — no-op."""

    def set_status(self, text: str) -> None:
        self._status_lbl.setText(text)

    def reset(self, initial_bpm: float, song_name: str) -> None:
        """Löscht alle bisherigen Daten für eine neue Simulation."""
        self.setWindowTitle(f"Simulation — {song_name}")
        self._canvas._kicks.clear()
        self._canvas._snares.clear()
        self._canvas._max_t = 0.0
        self._canvas._scroll_x = 0
        self._auto_scroll = True
        self._hbar.setValue(0)
        self._hbar.setMaximum(0)
        self._status_lbl.setText("Lade …")
        self._canvas.update()

    def load_jsonl(self, path: Path) -> None:
        """Lädt alle Events aus einer Simulations-JSONL und zeigt sie an."""
        import json as _json

        kicks:  list[float] = []
        snares: list[float] = []
        song_name = ""

        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = _json.loads(line)
                    except Exception:
                        continue
                    t     = float(ev.get("t", 0.0))
                    etype = ev.get("type", "")
                    data  = ev.get("data", {})

                    if etype == "sim_start":
                        song_name = data.get("song_name", data.get("song_id", ""))
                    elif etype == "kick":
                        kicks.append(t)
                    elif etype == "snare":
                        snares.append(t)
        except Exception as exc:
            self._status_lbl.setText(f"Ladefehler: {exc}")
            return

        self._canvas._kicks  = kicks
        self._canvas._snares = snares
        all_t = kicks + snares
        self._canvas._max_t = max(all_t) if all_t else 0.0

        if song_name:
            self.setWindowTitle(f"Simulation — {song_name}")

        self._status_lbl.setText(
            f"{song_name}  —  ◆ {len(kicks)} Kicks (amber)  "
            f"| ◆ {len(snares)} Snares (cyan)"
        )
        self._update_scroll()
        self._canvas.update()

    # ── Scroll management ─────────────────────────────────────────────────────

    def _update_scroll(self) -> None:
        view_w = self._canvas.view_width()
        if view_w <= 0:
            return
        content_w  = self._canvas.content_width()
        max_scroll = max(0, content_w - view_w)
        self._hbar.setMaximum(max_scroll)
        self._hbar.setPageStep(view_w)
        if self._auto_scroll:
            self._hbar.setValue(max_scroll)

    def _on_scroll(self, val: int) -> None:
        self._canvas.set_scroll(val)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._update_scroll()
