"""sim_monitor.py — Live-Monitor für die Echtzeit-Simulation.

Zeigt Kick/Snare-Onsets, Taktmarkierungen und Anker-Erkennungen
in Echtzeit während die Simulation läuft. Spielt gleichzeitig Audio ab.
"""
from __future__ import annotations

import time
from pathlib import Path

from PyQt6.QtCore import Qt, QPoint, QRect, QSize, QTimer, pyqtSignal
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
C_BG3     = QColor("#151820")
C_BORDER  = QColor("#1e2230")
C_T1      = QColor("#eef0f6")
C_T2      = QColor("#a0a4b8")
C_T3      = QColor("#5c6080")
C_GREEN   = QColor("#00dc82")
C_AMBER   = QColor("#f0a030")
C_CYAN    = QColor("#38bdf8")
C_RED     = QColor("#ff3b5c")
C_WHITE   = QColor("#ffffff")

FONT_MONO  = QFont("DM Mono", 8)
FONT_LABEL = QFont("Sora", 9)
FONT_TINY  = QFont("DM Mono", 7)

# ── Anker-Typ-Farben (entspricht Live-App Badge-Farben) ───────────────────────
_ANCHOR_COLORS: dict[str, QColor] = {
    "pete":      QColor("#38bdf8"),  # cyan
    "axel":      QColor("#f0a030"),  # amber
    "christian": QColor("#00dc82"),  # green
    "drum":      QColor("#ff3b5c"),  # red
    "guitar":    QColor("#a78bfa"),  # violet
    "bass":      QColor("#34d399"),  # mint
    "keys":      QColor("#fbbf24"),  # yellow
    "silence":   QColor("#64748b"),  # grey
    "other":     QColor("#a0a4b8"),  # t2
}

# ── Layout ────────────────────────────────────────────────────────────────────
LABEL_W  = 110     # linke Spalte (fixiert)
PPS      = 40.0    # Pixel pro Sekunde
D_R      = 5       # Diamond-Radius (Kick/Snare)
D_R_ANC  = 6       # Diamond-Radius (Anker)
SCROLL_H = 14

# Zeilen-Definitionen: key, Label, Höhe
_ROWS: list[dict] = [
    {"key": "kick",   "label": "Kick  CH09", "h": 36},
    {"key": "snare",  "label": "Snare CH10", "h": 36},
    {"key": "bar",    "label": "Takte",       "h": 30},
    {"key": "anchor", "label": "Anker",       "h": 52},
]
_TOTAL_H = sum(r["h"] for r in _ROWS) + SCROLL_H

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
    """Scrollbares Canvas mit Kick/Snare/Takt/Anker-Zeilen + Live-Playhead."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scroll_x: int = 0
        self._max_t: float = 0.0

        self._kicks:  list[float] = []
        self._snares: list[float] = []
        self._bars:   list[tuple[int, float]] = []   # (bar_num, t_rel)

        # Anker: pre-calculated display info
        self._anchors_info: list[dict] = []   # {id, t_expected, type, event, bar_num}
        self._matched_ids: set[str]    = set()

        self._playhead_t: float = -1.0

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

    def add_bar(self, bar_num: int, t: float) -> None:
        self._bars.append((bar_num, t))
        self._max_t = max(self._max_t, t)
        self.update()

    def set_anchors(self, anchors_info: list[dict]) -> None:
        self._anchors_info = anchors_info
        if anchors_info:
            self._max_t = max(
                self._max_t,
                max(a["t_expected"] for a in anchors_info) + 5.0,
            )
        self.update()

    def mark_matched(self, anchor_id: str) -> None:
        self._matched_ids.add(anchor_id)
        self.update()

    def set_playhead(self, t: float) -> None:
        self._playhead_t = t
        if t > 0:
            self._max_t = max(self._max_t, t + 4.0)
        self.update()

    def set_scroll(self, x: int) -> None:
        self._scroll_x = x
        self.update()

    def content_width(self) -> int:
        base = max(self.width(), int(self._max_t * PPS) + 300)
        return base

    def view_width(self) -> int:
        return self.width() - LABEL_W

    def reset(self) -> None:
        self._kicks.clear()
        self._snares.clear()
        self._bars.clear()
        self._anchors_info.clear()
        self._matched_ids.clear()
        self._playhead_t = -1.0
        self._max_t = 0.0
        self._scroll_x = 0
        self.update()

    # ── Painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w  = self.width()
        ox = self._scroll_x

        # Hintergrund + Zeilen
        p.fillRect(0, 0, w, _TOTAL_H, C_BG)
        for i, row in enumerate(_ROWS):
            y  = _ROW_Y[i]
            bg = C_BG if i % 2 == 0 else C_BG2
            p.fillRect(LABEL_W, y, w - LABEL_W, row["h"], bg)
            p.setPen(C_BORDER)
            p.drawLine(0, y + row["h"] - 1, w, y + row["h"] - 1)

        # ── Kicks ──────────────────────────────────────────────────────────────
        ri = next(i for i, r in enumerate(_ROWS) if r["key"] == "kick")
        y0, h = _ROW_Y[ri], _ROWS[ri]["h"]
        cy = y0 + h // 2
        p.setBrush(QBrush(C_AMBER))
        p.setPen(Qt.PenStyle.NoPen)
        for t in self._kicks:
            x = self._x(t, ox)
            if self._in_view(x):
                p.drawPolygon(_diamond(x, cy))

        # ── Snares ─────────────────────────────────────────────────────────────
        ri = next(i for i, r in enumerate(_ROWS) if r["key"] == "snare")
        y0, h = _ROW_Y[ri], _ROWS[ri]["h"]
        cy = y0 + h // 2
        p.setBrush(QBrush(C_CYAN))
        p.setPen(Qt.PenStyle.NoPen)
        for t in self._snares:
            x = self._x(t, ox)
            if self._in_view(x):
                p.drawPolygon(_diamond(x, cy))

        # ── Takte ──────────────────────────────────────────────────────────────
        ri = next(i for i, r in enumerate(_ROWS) if r["key"] == "bar")
        y0, h = _ROW_Y[ri], _ROWS[ri]["h"]
        p.setFont(FONT_TINY)
        for bar_num, t in self._bars:
            x = self._x(t, ox)
            if not self._in_view(x):
                continue
            p.setPen(QPen(C_WHITE, 1))
            p.setOpacity(0.35)
            p.drawLine(x, y0, x, y0 + h - 2)
            p.setOpacity(1.0)
            # Taktnummer: immer bei 1, danach jede 4. Takt
            if bar_num == 1 or bar_num % 4 == 1:
                p.setPen(C_T2)
                p.drawText(x + 2, y0, 28, h,
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           str(bar_num))

        # ── Anker ──────────────────────────────────────────────────────────────
        ri = next(i for i, r in enumerate(_ROWS) if r["key"] == "anchor")
        y0, h = _ROW_Y[ri], _ROWS[ri]["h"]
        cy_d = y0 + 14   # diamond y
        p.setFont(FONT_TINY)
        for anc in self._anchors_info:
            x = self._x(anc["t_expected"], ox)
            if not self._in_view(x):
                continue
            matched = anc["id"] in self._matched_ids
            base_color = _ANCHOR_COLORS.get(anc.get("type", "other"), C_T2)
            if matched:
                draw_color = base_color
                p.setOpacity(1.0)
            else:
                draw_color = base_color
                p.setOpacity(0.30)
            p.setBrush(QBrush(draw_color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(_diamond(x, cy_d, D_R_ANC))
            # Label: "T5: Crash" etc.
            label = anc.get("event", "")
            if len(label) > 13:
                label = label[:12] + "…"
            if matched:
                p.setPen(draw_color)
                p.setOpacity(1.0)
            else:
                p.setPen(C_T3)
                p.setOpacity(0.55)
            p.drawText(x - 32, cy_d + 8, 64, h - 22,
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       label)
        p.setOpacity(1.0)

        # ── Playhead (über allem) ──────────────────────────────────────────────
        if self._playhead_t >= 0:
            px = self._x(self._playhead_t, ox)
            if LABEL_W <= px <= w:
                pen = QPen(C_AMBER, 1)
                pen.setStyle(Qt.PenStyle.SolidLine)
                p.setPen(pen)
                p.drawLine(px, 0, px, _TOTAL_H - SCROLL_H)

        # ── Sticky Label-Spalte (über allem) ──────────────────────────────────
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
        TOL_T    = 0.15   # ±150 ms

        for i, row in enumerate(_ROWS):
            if _ROW_Y[i] <= my < _ROW_Y[i] + row["h"]:
                key = row["key"]
                if key == "kick":
                    nearest = self._nearest(self._kicks, t_cursor, TOL_T)
                    if nearest is not None:
                        QToolTip.showText(
                            ev.globalPosition().toPoint(),
                            f"Kick  t={nearest:.3f}s", self)
                    else:
                        QToolTip.hideText()
                elif key == "snare":
                    nearest = self._nearest(self._snares, t_cursor, TOL_T)
                    if nearest is not None:
                        QToolTip.showText(
                            ev.globalPosition().toPoint(),
                            f"Snare  t={nearest:.3f}s", self)
                    else:
                        QToolTip.hideText()
                elif key == "anchor":
                    hit = None
                    for anc in self._anchors_info:
                        if abs(anc["t_expected"] - t_cursor) <= TOL_T * 2:
                            hit = anc
                    if hit:
                        matched = hit["id"] in self._matched_ids
                        st = "✓ erkannt" if matched else "wartend …"
                        QToolTip.showText(
                            ev.globalPosition().toPoint(),
                            f"T{hit['bar_num']}  {hit.get('type','').upper()}: "
                            f"{hit.get('event','')}  [{st}]", self)
                    else:
                        QToolTip.hideText()
                else:
                    QToolTip.hideText()
                return
        QToolTip.hideText()

    def _nearest(self, pool: list[float], t: float, tol: float):
        matches = [x for x in pool if abs(x - t) <= tol]
        return min(matches, key=lambda x: abs(x - t)) if matches else None


# ── Dialog ────────────────────────────────────────────────────────────────────

class SimMonitorDialog(QDialog):
    """Live-Monitor während der Simulation.

    Zeigt Kick/Snare/Takt/Anker-Zeilen in Echtzeit.
    Der Playhead-Timer aktualisiert die Position mit ~25 fps.
    """

    cancel_requested = pyqtSignal()

    def __init__(self, initial_bpm: float, song_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Simulation — {song_name}")
        self.setModal(False)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setMinimumWidth(760)
        self.setStyleSheet("""
            QDialog { background:#08090d; color:#eef0f6; }
            QPushButton {
                background:#151820; border:1px solid #1e2230;
                color:#eef0f6; padding:4px 12px;
                font-family:'DM Mono',monospace; font-size:10px;
                border-radius:3px;
            }
            QPushButton:hover { background:#1c1f2b; }
            QPushButton#cancel_btn {
                background:#ff3b5c22; border-color:#ff3b5c; color:#ff3b5c;
            }
            QPushButton#cancel_btn:hover { background:#ff3b5c44; }
            QScrollBar:horizontal { background:#0e1017; height:14px; }
            QScrollBar::handle:horizontal {
                background:#2a2e40; border-radius:4px; min-width:20px;
            }
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal { width:0; }
            QLabel#info_lbl {
                font-family:'DM Mono',monospace; font-size:10px;
                color:#a0a4b8; padding:0 8px;
            }
            QLabel#bar_lbl {
                font-family:'Sora',sans-serif; font-size:12px;
                font-weight:600; color:#eef0f6; padding:0 8px;
            }
        """)

        self._is_running  = False
        self._n_kicks     = 0
        self._n_snares    = 0
        self._n_anchors   = 0
        self._n_matched   = 0
        self._current_bar = 0
        self._current_bpm = initial_bpm
        self._wall_start  = 0.0
        self._seg_dur     = 0.0   # Segment-Länge in Sekunden (für Anzeige)
        self._auto_scroll = True

        # Playhead-Timer (läuft nur im Echtzeit-Modus)
        self._playhead_timer = QTimer(self)
        self._playhead_timer.setInterval(40)   # 25 fps
        self._playhead_timer.timeout.connect(self._on_playhead_tick)

        # Widgets
        self._canvas = SimCanvas(self)

        self._bar_lbl = QLabel("Takt: —")
        self._bar_lbl.setObjectName("bar_lbl")

        self._info_lbl = QLabel("Lade …")
        self._info_lbl.setObjectName("info_lbl")

        self._cancel_btn = QPushButton("⏹ Stoppen")
        self._cancel_btn.setObjectName("cancel_btn")
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)

        self._hbar = QScrollBar(Qt.Orientation.Horizontal, self)
        self._hbar.setMinimum(0)
        self._hbar.setMaximum(0)
        self._hbar.valueChanged.connect(self._on_scroll)
        self._hbar.sliderPressed.connect(lambda: setattr(self, "_auto_scroll", False))

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(6, 4, 6, 2)
        top_bar.addWidget(self._bar_lbl)
        top_bar.addWidget(self._info_lbl, stretch=1)
        top_bar.addWidget(self._cancel_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top_bar)
        layout.addWidget(self._canvas, stretch=1)
        layout.addWidget(self._hbar)

    # ── Setup-API ─────────────────────────────────────────────────────────────

    def set_anchors(self, anchors: list[dict], bpm: float) -> None:
        """Lädt Anker und berechnet erwartete Zeiten aus BPM."""
        if not anchors or bpm <= 0:
            return
        bar_dur = 4 * 60.0 / bpm   # Sekunden pro Takt (4/4)
        infos = []
        for anc in sorted(anchors, key=lambda a: a.get("bar_num", 0)):
            bar_num = anc.get("bar_num", 1)
            infos.append({
                "id":         anc.get("id", ""),
                "t_expected": (bar_num - 1) * bar_dur,
                "type":       anc.get("type", "other"),
                "event":      anc.get("event", ""),
                "part_hint":  anc.get("part_hint", ""),
                "bar_num":    bar_num,
            })
        self._n_anchors = len(infos)
        self._canvas.set_anchors(infos)
        self._update_status()

    def start_realtime(self, seg_dur: float) -> None:
        """Startet den Playhead-Timer für Echtzeit-Modus."""
        self._is_running = True
        self._seg_dur    = seg_dur
        self._wall_start = time.monotonic()
        self._cancel_btn.setText("⏹ Stoppen")
        self._cancel_btn.setEnabled(True)
        self._playhead_timer.start()

    def stop_sim(self, n_kicks: int, n_snares: int, n_crashes: int) -> None:
        """Simulation abgeschlossen — Timer stoppen, Button auf Schließen."""
        self._is_running = False
        self._playhead_timer.stop()
        self._cancel_btn.setText("✕ Schließen")
        self._cancel_btn.setObjectName("")   # entfernt rotes Styling
        self._cancel_btn.setStyleSheet(
            "background:#151820; border:1px solid #1e2230; color:#eef0f6; "
            "padding:4px 12px; font-family:'DM Mono',monospace; font-size:10px; "
            "border-radius:3px;"
        )
        crash_str = f"  ★ {n_crashes} Crash" if n_crashes else ""
        self._info_lbl.setText(
            f"Fertig  ◆ {n_kicks}K  ◆ {n_snares}S{crash_str}  "
            f"⚓ {self._n_matched}/{self._n_anchors}"
        )

    # ── Live-Events ───────────────────────────────────────────────────────────

    def add_kick(self, t: float) -> None:
        self._n_kicks += 1
        self._canvas.add_kick(t)
        self._update_scroll()

    def add_snare(self, t: float) -> None:
        self._n_snares += 1
        self._canvas.add_snare(t)
        self._update_scroll()

    def add_bar(self, bar_num: int, t_rel: float, bpm: float) -> None:
        self._current_bar = bar_num
        self._current_bpm = bpm
        self._canvas.add_bar(bar_num, t_rel)
        self._update_bar_label()
        self._update_scroll()

    def mark_anchor_matched(self, anchor: dict) -> None:
        anc_id = anchor.get("id", "")
        if anc_id:
            self._canvas.mark_matched(anc_id)
            self._n_matched += 1
        self._update_status()

    def set_playhead(self, t: float) -> None:
        self._canvas.set_playhead(t)

    # ── Legacy-API (für load_jsonl nach Sim) ──────────────────────────────────

    def add_snare_legacy(self, t: float) -> None:
        self._canvas.add_snare(t)

    def set_status(self, text: str) -> None:
        self._info_lbl.setText(text)

    def reset(self, initial_bpm: float, song_name: str) -> None:
        self.setWindowTitle(f"Simulation — {song_name}")
        self._is_running   = False
        self._n_kicks      = 0
        self._n_snares     = 0
        self._n_matched    = 0
        self._n_anchors    = 0
        self._current_bar  = 0
        self._current_bpm  = initial_bpm
        self._auto_scroll  = True
        self._playhead_timer.stop()
        self._canvas.reset()
        self._hbar.setValue(0)
        self._hbar.setMaximum(0)
        self._bar_lbl.setText("Takt: —")
        self._info_lbl.setText("Lade …")
        self._cancel_btn.setText("⏹ Stoppen")
        self._cancel_btn.setObjectName("cancel_btn")
        self._cancel_btn.setStyleSheet("")

    def load_jsonl(self, path: Path) -> None:
        """Lädt alle Events aus einer fertigen Simulations-JSONL."""
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
            self._info_lbl.setText(f"Ladefehler: {exc}")
            return

        self._canvas._kicks  = kicks
        self._canvas._snares = snares
        all_t = kicks + snares
        self._canvas._max_t = max(all_t) if all_t else 0.0

        if song_name:
            self.setWindowTitle(f"Simulation — {song_name}")

        self._info_lbl.setText(
            f"{song_name}  —  ◆ {len(kicks)} Kicks (amber)  "
            f"| ◆ {len(snares)} Snares (cyan)"
        )
        self._update_scroll()
        self._canvas.update()

    # ── Interne Aktualisierungen ──────────────────────────────────────────────

    def _on_playhead_tick(self) -> None:
        elapsed = time.monotonic() - self._wall_start
        self._canvas.set_playhead(elapsed)
        mins = int(elapsed) // 60
        secs = int(elapsed) % 60
        total_mins = int(self._seg_dur) // 60
        total_secs = int(self._seg_dur) % 60
        self._info_lbl.setText(
            f"◆ {self._n_kicks}K  ◆ {self._n_snares}S  "
            f"⚓ {self._n_matched}/{self._n_anchors}  "
            f"{mins}:{secs:02d} / {total_mins}:{total_secs:02d}"
        )
        self._update_scroll(playhead_focused=True)

    def _on_cancel_clicked(self) -> None:
        if self._is_running:
            self._playhead_timer.stop()
            self._is_running = False
            self.cancel_requested.emit()
        else:
            self.close()

    def _update_bar_label(self) -> None:
        if self._current_bar > 0:
            bpm_str = f"{round(self._current_bpm)} BPM" if self._current_bpm > 0 else ""
            self._bar_lbl.setText(f"Takt: {self._current_bar}  {bpm_str}")

    def _update_status(self) -> None:
        if self._is_running:
            return  # Ticker übernimmt die Anzeige
        self._info_lbl.setText(
            f"◆ {self._n_kicks}K  ◆ {self._n_snares}S  "
            f"⚓ {self._n_matched}/{self._n_anchors}"
        )

    # ── Scroll management ─────────────────────────────────────────────────────

    def _update_scroll(self, playhead_focused: bool = False) -> None:
        view_w = self._canvas.view_width()
        if view_w <= 0:
            return
        content_w  = self._canvas.content_width()
        max_scroll = max(0, content_w - view_w)
        self._hbar.setMaximum(max_scroll)
        self._hbar.setPageStep(view_w)

        if self._auto_scroll:
            if playhead_focused and self._canvas._playhead_t >= 0:
                # Playhead ca. 70% von links halten
                target = max(0, int(self._canvas._playhead_t * PPS) - int(view_w * 0.7))
                self._hbar.setValue(min(target, max_scroll))
            else:
                self._hbar.setValue(max_scroll)

    def _on_scroll(self, val: int) -> None:
        self._canvas.set_scroll(val)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._update_scroll()
