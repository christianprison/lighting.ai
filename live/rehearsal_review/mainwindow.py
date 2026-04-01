"""mainwindow.py — Main application window for Rehearsal Post-Preparation."""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QInputDialog,
    QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QProgressDialog, QScrollArea, QSpinBox, QStatusBar, QToolBar,
    QVBoxLayout, QWidget,
)

from session import Session, SongSegment, load_session
from peaks import PeakWorker, DISPLAY_CHANNELS, TrackPeaks
from player import AudioPlayer
from timeline import TimelineWidget, CONTENT_H, LABEL_W, TRACKS
from overview import OverviewWidget
from annotation import (
    BarMarker, SongAnnotation,
    load_annotations, save_annotations,
)
from simulator import SimulatorWorker, SimBeat, SimPosition
from datetime import datetime as _dt
from sim_monitor import SimMonitorDialog

_APP_STYLE = """
QMainWindow, QWidget          { background:#08090d; color:#eef0f6; }
QMenuBar                      { background:#0e1017; border-bottom:1px solid #1e2230; }
QMenuBar::item:selected       { background:#1c1f2b; }
QMenu                         { background:#0e1017; border:1px solid #1e2230; }
QMenu::item:selected          { background:#1c1f2b; }
QToolBar                      { background:#0e1017; border-bottom:1px solid #1e2230;
                                spacing:4px; padding:4px; }
QToolButton                   { padding:5px 10px; font-family:'DM Mono',monospace;
                                font-size:10px; color:#eef0f6; border:1px solid #1e2230;
                                border-radius:3px; background:#151820; margin:1px; }
QToolButton:hover             { background:#1c1f2b; border-color:#2a2e40; }
QToolButton:pressed           { background:#0e1017; }
QToolButton:checked           { background:#00dc82; color:#08090d; border-color:#00dc82;
                                font-weight:bold; }
QToolButton:checked:hover     { background:#00f090; border-color:#00f090; }
QScrollArea                   { border:none; background:#08090d; }
QScrollBar:vertical           { background:#0e1017; width:8px; }
QScrollBar::handle:vertical   { background:#2a2e40; border-radius:4px; }
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical { height:0; }
QStatusBar                    { background:#0e1017; border-top:1px solid #1e2230;
                                font-family:'DM Mono',monospace; font-size:10px;
                                color:#a0a4b8; }
QProgressDialog               { background:#0e1017; color:#eef0f6; }
QProgressBar                  { background:#151820; border:1px solid #1e2230;
                                border-radius:3px; text-align:center; }
QProgressBar::chunk           { background:#00dc82; border-radius:2px; }
QComboBox                     { background:#151820; border:1px solid #1e2230;
                                color:#eef0f6; padding:3px 8px; border-radius:3px;
                                font-family:'Sora',sans-serif; font-size:11px; }
QComboBox:hover               { background:#1c1f2b; border-color:#2a2e40; }
QComboBox::drop-down          { border:none; width:20px; }
QComboBox QAbstractItemView   { background:#0e1017; border:1px solid #1e2230;
                                color:#eef0f6; selection-background-color:#1c1f2b;
                                font-family:'Sora',sans-serif; font-size:11px; }
QComboBox#zoom_combo          { font-family:'DM Mono',monospace; font-size:10px;
                                min-width:90px; max-width:110px; }
"""

_ZOOM_PRESETS: list[int] = [10, 20, 40, 80, 160, 320, 640, 1280, 2560, 5120, 10240, 20480, 40960]


_PANEL_STYLE = """
QDialog       { background:#0e1017; border:1px solid #1e2230; }
QListWidget   { background:#0e1017; border:none; outline:none; }
QListWidget::item {
    padding:6px 12px;
    border-bottom:1px solid #1e2230;
    font-family:'DM Mono',monospace; font-size:10px; color:#a0a4b8;
}
QListWidget::item:selected { background:#00dc8218; color:#00dc82; }
QListWidget::item:hover    { background:#1c1f2b; }
QScrollBar:vertical        { background:#0e1017; width:6px; }
QScrollBar::handle:vertical { background:#2a2e40; border-radius:3px; }
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical { height:0; }
"""

_TYPE_ICONS = {
    "beat":          ("·",  "#f0a030"),
    "beat_down":     ("↓",  "#f0a030"),
    "position":      ("◆",  "#38bdf8"),
    "user":          ("▶",  "#00dc82"),
    "session_start": ("▷",  "#5c6080"),
    "session_end":   ("■",  "#5c6080"),
}


def _fmt_event_row(ev, seg_start: float) -> str:
    """Return a single-line description for an event list row."""
    t = _fmt_t(ev.t - seg_start)
    et = ev.type

    if et == "beat":
        tag = "↓ Downbeat" if ev.data.get("is_downbeat") else "  Beat"
        extras: list[str] = []
        if "beat_num" in ev.data:
            extras.append(f"#{ev.data['beat_num']}")
        if "bpm" in ev.data:
            extras.append(f"{float(ev.data['bpm']):.1f} BPM")
        suffix = "  " + "  ".join(extras) if extras else ""
        return f"{t}   {tag}{suffix}"

    if et == "position":
        part = ev.data.get("part_name", "")
        conf = ev.data.get("confidence", 0)
        detail: list[str] = [f"◆ {part}"]
        if "bar_num" in ev.data:
            detail.append(f"Bar {ev.data['bar_num']}")
        detail.append(f"({float(conf):.0%})")
        return f"{t}   " + "  ".join(detail)

    if et == "user":
        action = ev.data.get("action", "?")
        d = ev.data.get("data", {}) if isinstance(ev.data.get("data"), dict) else {}
        parts: list[str] = [action]
        if action == "select_song":
            if d.get("name"):
                parts.append(d["name"])
            if d.get("song_id"):
                parts.append(f"[{d['song_id']}]")
        elif action == "send_template":
            tmpl = d.get("template", d.get("name", ""))
            if tmpl:
                parts.append(str(tmpl))
        else:
            for k, v in d.items():
                parts.append(f"{k}={v}")
        return f"{t}   " + "  ".join(parts)

    if et == "session_start":
        parts2: list[str] = ["▷ Session Start"]
        wav = ev.data.get("wav", "")
        if wav:
            parts2.append(str(wav))
        sr = ev.data.get("sample_rate")
        if sr is not None:
            parts2.append(f"{sr} Hz")
        ch = ev.data.get("channels")
        if ch is not None:
            parts2.append(f"{ch} ch")
        sa = ev.data.get("started_at", "")
        if sa:
            parts2.append(str(sa))
        return f"{t}   " + "  ".join(parts2)

    if et == "session_end":
        dur = ev.data.get("duration_sec")
        if dur is not None:
            m, s = divmod(int(float(dur)), 60)
            dur_str = f"{m}:{s:02d}"
        else:
            dur_str = "?"
        return f"{t}   ■ Session Ende  {dur_str}"

    # Unknown type: show all key=value pairs
    pairs = "  ".join(f"{k}={v}" for k, v in ev.data.items())
    return f"{t}   {et}  {pairs}" if pairs else f"{t}   {et}"


class EventListPanel(QDialog):
    """Non-modal floating panel showing all events for the active segment.

    Clicking a row seeks the timeline to that event's position.
    """
    seek_requested = pyqtSignal(float)   # t_in_segment

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Tool)
        self.setWindowTitle("Events")
        self.resize(480, 520)
        self.setStyleSheet(_PANEL_STYLE)

        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_item_clicked)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._list)

        self._seg_start: float = 0.0
        self._event_times: list[float] = []

    def load_segment(self, seg: "SongSegment") -> None:
        self._list.clear()
        self._seg_start = seg.start_t
        self._event_times = []
        for ev in seg.events:
            text = _fmt_event_row(ev, seg.start_t)
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, ev.t - seg.start_t)
            self._list.addItem(item)
            self._event_times.append(ev.t)

    def focus_at(self, wav_t: float) -> None:
        """Scroll to and select the last event at or before wav_t."""
        row = -1
        for i, t in enumerate(self._event_times):
            if t <= wav_t:
                row = i
            else:
                break
        if row >= 0:
            self._list.setCurrentRow(row)
            self._list.scrollToItem(
                self._list.item(row),
                QListWidget.ScrollHint.PositionAtCenter,
            )

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        t_in_seg: float = item.data(Qt.ItemDataRole.UserRole)
        self.seek_requested.emit(t_in_seg)


class _FragmentWorker(QThread):
    """QThread that runs silence-based fragment detection off the main thread."""
    finished = pyqtSignal(list)
    error    = pyqtSignal(str)
    progress = pyqtSignal(float, object)  # scan_t (float), windows (list of (t, bool))

    _RMS_THRESH = 0.005
    _WIN_SEC    = 0.05

    def __init__(
        self,
        wav_path: Path,
        start_t: float,
        end_t: float,
        sample_rate: int,
        ch_indices: list[int],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._wav_path   = wav_path
        self._start_t    = start_t
        self._end_t      = end_t
        self._sr         = sample_rate
        self._ch_indices = ch_indices
        self._win_count  = 0

    def run(self) -> None:
        try:
            rr_dir = os.path.dirname(os.path.abspath(__file__))
            if rr_dir not in sys.path:
                sys.path.insert(0, rr_dir)
            from fragment_detector import detect_fragments

            def _cb(scan_t: float, chunk_rms: list[float]) -> None:
                offset  = self._win_count * self._WIN_SEC
                windows = [
                    (offset + i * self._WIN_SEC, r >= self._RMS_THRESH)
                    for i, r in enumerate(chunk_rms)
                ]
                self._win_count += len(chunk_rms)
                self.progress.emit(scan_t, windows)

            frags = detect_fragments(
                wav_path=self._wav_path,
                seg_start_t=self._start_t,
                seg_end_t=self._end_t,
                sample_rate=self._sr,
                ch_indices=self._ch_indices,
                progress_callback=_cb,
            )
            self.finished.emit(frags)
        except Exception as exc:
            self.error.emit(str(exc))


class _ImportWorker(QThread):
    """QThread that runs recording_importer.import_from_recording off the main thread."""
    finished = pyqtSignal(str)   # success message
    error    = pyqtSignal(str)   # error message

    def __init__(self, wav_path, annotations, ref_db_path, db_json_path, sr,
                 repo_root, parent=None) -> None:
        super().__init__(parent)
        self._wav_path    = wav_path
        self._annotations = annotations
        self._ref_db_path = ref_db_path
        self._db_json_path = db_json_path
        self._sr          = sr
        self._repo_root   = repo_root

    def run(self) -> None:
        try:
            live_path = str(self._repo_root / "live")
            if live_path not in sys.path:
                sys.path.insert(0, live_path)
            from server.audio.recording_importer import import_from_recording
            stats = import_from_recording(
                wav_path=self._wav_path,
                annotations=self._annotations,
                ref_db_path=self._ref_db_path,
                db_json_path=self._db_json_path,
                session_sample_rate=self._sr,
            )
            msg = (
                f"Import abgeschlossen: "
                f"{stats.bars_inserted} neu, "
                f"{stats.bars_updated} gemittelt, "
                f"{stats.bars_skipped} übersprungen"
            )
            self.finished.emit(msg)
        except Exception as exc:
            self.error.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Rehearsal Post-Preparation — lighting.ai")
        self.setStyleSheet(_APP_STYLE)

        # Explicitly allow resize + maximize (prevents KDE/X11 from treating
        # the window as fixed-size due to child widget size hints)
        self.setMinimumSize(800, 500)
        self.setMaximumSize(16_777_215, 16_777_215)  # QWIDGETSIZE_MAX
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)

        self._session: Optional[Session] = None
        self._current_seg: Optional[SongSegment] = None
        self._peak_worker: Optional[PeakWorker] = None
        self._progress: Optional[QProgressDialog] = None
        self._overview_worker: Optional[PeakWorker] = None
        self._pending_seek_t: Optional[float] = None

        self._event_panel: Optional[EventListPanel] = None

        # Annotations: song_id → SongAnnotation
        self._annotations: dict[str, SongAnnotation] = {}
        self._annotation_mode: bool = False

        # Fragment detection results for the active segment
        self._detected_fragments: list = []
        self._fragment_worker: Optional[_FragmentWorker] = None

        # Simulation
        self._sim_worker:      Optional[SimulatorWorker] = None
        self._sim_monitor:     Optional[SimMonitorDialog] = None
        self._sim_overlay_act: Optional[object] = None   # QAction, gesetzt in _build_toolbar
        self._sim_start_wav_t: float = 0.0  # WAV-Offset bei Simulations-Start
        self._sim_t_in_seg:    float = 0.0  # Segment-relative Startposition für Seek

        self._player = AudioPlayer(self)
        self._player.position_changed.connect(self._on_position)
        self._player.playback_stopped.connect(self._on_stopped)
        self._player.error.connect(
            lambda msg: self._status.showMessage(f"Audio-Fehler: {msg}", 8000)
        )

        self._build_ui()
        self._build_menu()
        self._build_toolbar()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Overview minimap (full session)
        self._overview = OverviewWidget()
        self._overview.seek_requested.connect(self._on_overview_seek)

        # Timeline (full width — no left song-list panel)
        self._timeline = TimelineWidget()
        self._timeline.seek_requested.connect(self._on_seek)
        self._timeline.solo_mute_changed.connect(self._on_solo_mute_changed)
        self._timeline.event_label_clicked.connect(self._on_event_label_clicked)
        self._timeline.bar_marker_remove_requested.connect(self._on_remove_bar_marker)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(self._timeline)

        container = QWidget()
        vl = QVBoxLayout(container)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        vl.addWidget(self._overview)
        vl.addWidget(scroll)
        self.setCentralWidget(container)

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._pos_label = QLabel("-:--.-")
        self._pos_label.setStyleSheet(
            "font-family:'DM Mono',monospace; font-size:10px; color:#a0a4b8;"
        )
        self._status.addPermanentWidget(self._pos_label)

    def _build_menu(self) -> None:
        mb = self.menuBar()

        fm = mb.addMenu("Datei")
        open_a = QAction("Öffnen...", self)
        open_a.setShortcut(QKeySequence("Ctrl+O"))
        open_a.triggered.connect(self._open_session)
        fm.addAction(open_a)
        fm.addSeparator()
        quit_a = QAction("Beenden", self)
        quit_a.setShortcut(QKeySequence("Ctrl+Q"))
        quit_a.triggered.connect(QApplication.instance().quit)
        fm.addAction(quit_a)

        vm = mb.addMenu("Ansicht")
        zi = QAction("Zoom +", self)
        zi.setShortcut(QKeySequence("+"))
        zi.triggered.connect(lambda: self._zoom(1.25))
        vm.addAction(zi)
        zo = QAction("Zoom -", self)
        zo.setShortcut(QKeySequence("-"))
        zo.triggered.connect(lambda: self._zoom(0.8))
        vm.addAction(zo)
        zf = QAction("Zoom Anpassen", self)
        zf.setShortcut(QKeySequence("0"))
        zf.triggered.connect(self._zoom_fit)
        vm.addAction(zf)

    def _build_toolbar(self) -> None:
        # ── Toolbar 1: Transport + Navigation ────────────────────────────────
        tb1 = QToolBar()
        tb1.setMovable(False)
        self.addToolBar(tb1)

        self._play_act = tb1.addAction("Play")
        self._play_act.triggered.connect(self._toggle_play)

        stop_act = tb1.addAction("Stop")
        stop_act.triggered.connect(self._stop)

        tb1.addSeparator()

        self._song_combo = QComboBox()
        self._song_combo.setMinimumWidth(300)
        self._song_combo.setPlaceholderText("-- Song waehlen --")
        self._song_combo.currentIndexChanged.connect(self._on_song_combo_changed)
        tb1.addWidget(self._song_combo)

        tb1.addSeparator()

        self._detect_frags_act = tb1.addAction("Fragmente")
        self._detect_frags_act.setEnabled(False)
        self._detect_frags_act.setToolTip(
            "Song in gespielte Fragmente aufteilen\n"
            "(erkennt Stille-Lücken auf allen 16 Instrumenten-Kanälen)"
        )
        self._detect_frags_act.triggered.connect(self._detect_fragments)

        tb1.addSeparator()

        zoom_lbl = QLabel("  Zoom:")
        zoom_lbl.setStyleSheet(
            "font-family:'DM Mono',monospace; font-size:10px; color:#a0a4b8;"
        )
        tb1.addWidget(zoom_lbl)

        self._zoom_combo = QComboBox()
        self._zoom_combo.setObjectName("zoom_combo")
        for v in _ZOOM_PRESETS:
            self._zoom_combo.addItem(f"{v} px/s", v)
        self._zoom_combo.setCurrentIndex(3)
        self._zoom_combo.currentIndexChanged.connect(self._on_zoom_combo_changed)
        tb1.addWidget(self._zoom_combo)

        tb1.addSeparator()

        self._datetime_lbl = QLabel("  —")
        self._datetime_lbl.setStyleSheet(
            "font-family:'DM Mono',monospace; font-size:10px; color:#eef0f6;"
        )
        tb1.addWidget(self._datetime_lbl)

        # ── Toolbar 2: Annotation + Actions ──────────────────────────────────
        tb2 = QToolBar()
        tb2.setMovable(False)
        self.addToolBarBreak()
        self.addToolBar(tb2)

        self._annot_act = tb2.addAction("Annotieren")
        self._annot_act.setCheckable(True)
        self._annot_act.setToolTip(
            "Annotations-Modus: Takt-Marker setzen (B = Takt, P = Part-Start)"
        )
        self._annot_act.triggered.connect(self._on_toggle_annotation_mode)

        tb2.addWidget(QLabel("  ab Takt "))
        self._start_bar_spin = QSpinBox()
        self._start_bar_spin.setMinimum(1)
        self._start_bar_spin.setMaximum(999)
        self._start_bar_spin.setValue(1)
        self._start_bar_spin.setFixedWidth(56)
        self._start_bar_spin.setToolTip(
            "Erster annotierter Takt entspricht diesem DB-Takt.\n"
            "Anpassen wenn die Aufnahme nicht bei Takt 1 des Songs beginnt."
        )
        self._start_bar_spin.valueChanged.connect(self._on_start_bar_changed)
        tb2.addWidget(self._start_bar_spin)

        tb2.addSeparator()

        self._bar_act = tb2.addAction("Takt [B]")
        self._bar_act.setEnabled(False)
        self._bar_act.setToolTip("Takt-Marker an aktueller Cursor-Position setzen (B)")
        self._bar_act.triggered.connect(self._add_bar_marker)

        self._part_act = tb2.addAction("Part-Start [P]")
        self._part_act.setEnabled(False)
        self._part_act.setToolTip("Part-Start-Marker an aktueller Cursor-Position setzen (P)")
        self._part_act.triggered.connect(self._add_part_marker)

        self._frag_act = tb2.addAction("Fragment [F]")
        self._frag_act.setEnabled(False)
        self._frag_act.setToolTip(
            "Fragment-Start-Marker setzen — fragt nach Takt-Nummer ab der gezählt wird (F)"
        )
        self._frag_act.triggered.connect(self._add_fragment_marker)

        self._undo_annot_act = tb2.addAction("Undo [U]")
        self._undo_annot_act.setEnabled(False)
        self._undo_annot_act.setToolTip("Letzten Takt-Marker entfernen (U)")
        self._undo_annot_act.triggered.connect(self._undo_last_marker)

        tb2.addSeparator()

        self._save_annot_act = tb2.addAction("Speichern")
        self._save_annot_act.setEnabled(False)
        self._save_annot_act.setToolTip("Annotierungen als JSON speichern")
        self._save_annot_act.triggered.connect(self._save_annotations)

        self._import_act = tb2.addAction("→ reference.db")
        self._import_act.setEnabled(False)
        self._import_act.setToolTip(
            "Annotierte Takte in reference.db importieren (Feature-Extraktion)"
        )
        self._import_act.triggered.connect(self._run_recording_import)

        self._db_parts_act = tb2.addAction("DB-Parts")
        self._db_parts_act.setEnabled(False)
        self._db_parts_act.setToolTip(
            "Parts des aktuellen Songs aus reference.db anzeigen\n"
            "Doppelklick → Start-Takt setzen"
        )
        self._db_parts_act.triggered.connect(self._show_db_parts)

        tb2.addSeparator()

        self._sim_act = tb2.addAction("▶ Simulation")
        self._sim_act.setEnabled(False)
        self._sim_act.setToolTip(
            "Beat-Detection offline simulieren — Ergebnis wird in der Timeline dargestellt"
        )
        self._sim_act.triggered.connect(self._run_simulation)

        self._sim_overlay_act = tb2.addAction("⊙ Simulation")
        self._sim_overlay_act.setCheckable(True)
        self._sim_overlay_act.setChecked(False)
        self._sim_overlay_act.setEnabled(False)
        self._sim_overlay_act.setToolTip(
            "Umschalten: Simulation (volle Farben) ↔ Original (volle Farben)\n"
            "Im Simulation-Modus sind Original-Events auf 25 % gedimmt"
        )
        self._sim_overlay_act.toggled.connect(self._timeline.set_sim_overlay)

        self._sim_clear_act = tb2.addAction("✕ Sim")
        self._sim_clear_act.setEnabled(False)
        self._sim_clear_act.setToolTip("Simulations-Ergebnisse aus Timeline entfernen")
        self._sim_clear_act.triggered.connect(self._clear_simulation)

    # ── Loading ───────────────────────────────────────────────────────────────

    def _open_session(self) -> None:
        default_dir = str(
            Path(__file__).parent.parent / "data" / "recordings"
        )
        path, _ = QFileDialog.getOpenFileName(
            self, "Aufnahme öffnen", default_dir,
            "JSONL Event-Log (*.jsonl);;Alle Dateien (*)"
        )
        if path:
            self._load_session(Path(path))

    def _load_session(self, jsonl_path: Path) -> None:
        db = self._try_load_db(jsonl_path)
        try:
            session = load_session(jsonl_path, db)
        except Exception as exc:
            QMessageBox.critical(self, "Fehler", str(exc))
            return

        self._session = session
        self._current_seg = None
        self._player.stop()

        # Load existing annotations for this session
        self._annotations = load_annotations(jsonl_path)
        self._save_annot_act.setEnabled(True)
        self._import_act.setEnabled(True)
        self._db_parts_act.setEnabled(True)
        self._detect_frags_act.setEnabled(True)
        self._sim_act.setEnabled(True)

        # Fill song combo (block signals during rebuild)
        self._song_combo.blockSignals(True)
        self._song_combo.clear()
        for seg in session.songs:
            self._song_combo.addItem(seg.song_name, seg)
        self._song_combo.setCurrentIndex(-1)
        self._song_combo.blockSignals(False)

        # Pass recording start time to timeline ruler
        self._timeline.set_recording_started_at(
            getattr(session, "recording_started_at", None)
        )

        mix = " · Mixdown" if session.mixdown_path else ""
        if session.recording_started_at:
            dt_str = session.recording_started_at.strftime("%d.%m.%Y  %H:%M")
        else:
            dt_str = jsonl_path.stem
        self._datetime_lbl.setText(
            f"  {dt_str}  ·  {len(session.songs)} Songs"
            f"  ·  {session.n_channels} ch{mix}  "
        )
        self._status.showMessage(
            f"{jsonl_path}  --  {len(session.songs)} Songs"
            f"  --  {_fmt_dur(session.total_duration)}"
        )

        # Start overview peak extraction (full session, Main L+R or mixdown ch 0+1)
        if self._overview_worker and self._overview_worker.isRunning():
            self._overview_worker.cancel()
            self._overview_worker.wait(300)

        src = session.mixdown_path if session.mixdown_path else session.wav_path
        ch_indices = [0, 1] if session.mixdown_path else [16, 17]
        self._overview.set_session(session)

        ov_worker = PeakWorker(
            wav_path=src,
            ch_indices=ch_indices,
            start_t=0.0,
            end_t=session.total_duration,
            sample_rate=session.sample_rate,
            n_points=2000,
        )
        self._overview_worker = ov_worker
        ov_worker.finished.connect(self._on_overview_peaks_done)
        ov_worker.error.connect(
            lambda msg: self._status.showMessage(f"Overview-Fehler: {msg}", 5000)
        )
        ov_worker.start()

        # Select first song
        if self._song_combo.count():
            self._song_combo.setCurrentIndex(0)

    def _try_load_db(self, jsonl_path: Path) -> Optional[dict]:
        for p in [
            jsonl_path.parent.parent.parent / "db" / "lighting-ai-db.json",
            Path(__file__).parent.parent.parent / "db" / "lighting-ai-db.json",
        ]:
            if p.exists():
                try:
                    return json.loads(p.read_text("utf-8"))
                except Exception:
                    pass
        return None

    # ── Song selection ────────────────────────────────────────────────────────

    def _on_song_combo_changed(self, index: int) -> None:
        if index < 0:
            return
        seg: Optional[SongSegment] = self._song_combo.itemData(index)
        if seg is None:
            return

        self._current_seg = seg
        self._player.stop()
        self._play_act.setText("Play")

        self._timeline.set_segment(seg, None)
        self._overview.set_segment(seg)

        # Clear fragment detection results from previous song
        self._detected_fragments = []
        if self._fragment_worker is not None:
            self._fragment_worker.quit()
            self._fragment_worker = None
        self._timeline.set_fragment_boundaries([])
        self._timeline.clear_scan_progress()

        # Clear simulation results from previous song
        if self._sim_worker is not None:
            self._sim_worker.requestInterruption()
            self._sim_worker = None
        self._timeline.clear_sim_events()
        self._timeline.set_sim_overlay(False)
        if self._sim_overlay_act:
            self._sim_overlay_act.setChecked(False)
            self._sim_overlay_act.setEnabled(False)
        self._sim_clear_act.setEnabled(False)

        # Show existing annotations for this song
        ann = self._annotations.get(seg.song_id)
        self._timeline.set_bar_markers(ann.markers if ann else [])
        # Sync start_bar spinbox (block signal to avoid triggering _on_start_bar_changed)
        self._start_bar_spin.blockSignals(True)
        self._start_bar_spin.setValue(ann.start_bar_num if ann else 1)
        self._start_bar_spin.blockSignals(False)

        # Update event panel if open
        if self._event_panel and self._event_panel.isVisible():
            self._event_panel.load_segment(seg)

        # Cancel previous worker
        if self._peak_worker and self._peak_worker.isRunning():
            self._peak_worker.terminate()
            self._peak_worker.wait(300)
        if self._progress:
            self._progress.close()

        if self._session is None:
            return

        self._progress = QProgressDialog(
            f'Lade Wellenformen: "{seg.song_name}"...',
            None, 0, 100, self
        )
        self._progress.setWindowTitle("Wellenformen")
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(300)
        self._progress.setCancelButton(None)

        worker = PeakWorker(
            wav_path=self._session.wav_path,
            ch_indices=DISPLAY_CHANNELS,
            start_t=seg.start_t,
            end_t=seg.end_t,
            sample_rate=self._session.sample_rate,
            parent=self,
        )
        self._peak_worker = worker

        prg = self._progress
        cur = seg

        worker.progress.connect(lambda v: prg.setValue(v))
        worker.finished.connect(lambda peaks: self._on_peaks_done(cur, peaks, prg))
        worker.error.connect(lambda msg: self._on_peaks_error(msg, prg))
        worker.start()

    def _on_peaks_done(self, seg: SongSegment, peaks: TrackPeaks,
                       prg: QProgressDialog) -> None:
        prg.close()
        if self._current_seg is not seg:
            return
        self._timeline.set_peaks(peaks)
        self._load_audio(seg)
        self._zoom_fit()

        if self._pending_seek_t is not None:
            t_in_seg = self._pending_seek_t - seg.start_t
            self._pending_seek_t = None
            if 0.0 <= t_in_seg <= seg.duration:
                self._player.seek(t_in_seg)
                self._timeline.set_cursor(seg.start_t + t_in_seg)
                self._overview.set_playhead(seg.start_t + t_in_seg)

    def _on_peaks_error(self, msg: str, prg: QProgressDialog) -> None:
        prg.close()
        self._status.showMessage(f"Peak-Fehler: {msg}", 6000)

    def _load_audio(self, seg: SongSegment) -> None:
        if self._session is None:
            return
        try:
            self._player.load_segment(
                self._session.wav_path,
                seg.start_t,
                seg.end_t,
                mixdown_path=self._session.mixdown_path,
            )
        except Exception as exc:
            self._status.showMessage(f"Audio-Ladefehler: {exc}", 5000)

    def _on_event_label_clicked(self, wav_t: float) -> None:
        """Open (or bring to front) the event list panel, focused at wav_t."""
        if self._current_seg is None:
            return
        if self._event_panel is None:
            self._event_panel = EventListPanel(self)
            self._event_panel.seek_requested.connect(self._on_seek)
        self._event_panel.load_segment(self._current_seg)
        self._event_panel.focus_at(wav_t)
        self._event_panel.show()
        self._event_panel.raise_()

    def _on_solo_mute_changed(self, muted: frozenset, soloed: frozenset) -> None:
        """Reload audio mix when Solo/Mute state changes."""
        solo_chs = self._solo_to_channels(soloed)
        self._player.reload_mix(solo_chs)

    def _solo_to_channels(self, soloed: frozenset) -> Optional[list[int]]:
        """Convert soloed track indices to raw WAV channel indices.

        Returns None when nothing is soloed (= play normal mix).
        """
        if not soloed:
            return None
        channels: list[int] = []
        for idx in soloed:
            if idx >= len(TRACKS):
                continue
            track = TRACKS[idx]
            if "combined_chs" in track:
                channels.extend(track["combined_chs"])
            elif track["ch"] >= 0:
                channels.append(track["ch"])
        return channels if channels else None

    # ── Transport ─────────────────────────────────────────────────────────────

    def _toggle_play(self) -> None:
        if self._current_seg is None:
            return
        self._player.toggle()
        self._play_act.setText("Pause" if self._player.is_playing else "Play")

    def _stop(self) -> None:
        self._player.stop()
        self._play_act.setText("Play")
        if self._current_seg:
            self._timeline.set_cursor(self._current_seg.start_t)
            self._pos_label.setText(_fmt_t_precise(0.0))

    def _on_seek(self, t_in_seg: float) -> None:
        self._player.seek(t_in_seg)
        if self._current_seg:
            self._timeline.set_cursor(self._current_seg.start_t + t_in_seg)

    def _on_position(self, wav_t: float) -> None:
        self._timeline.set_cursor(wav_t)
        self._overview.set_playhead(wav_t)
        if self._current_seg:
            self._pos_label.setText(_fmt_t_precise(wav_t - self._current_seg.start_t))
        if self._event_panel and self._event_panel.isVisible():
            self._event_panel.focus_at(wav_t)
        # Playhead im Simulations-Monitor synchron halten
        if self._sim_monitor is not None and self._sim_monitor.isVisible():
            self._sim_monitor.set_playhead(max(0.0, wav_t - self._sim_start_wav_t))

    def _on_stopped(self) -> None:
        self._play_act.setText("Play")

    def _on_overview_peaks_done(self, track_peaks) -> None:
        import numpy as np
        chs = list(track_peaks.channel_peaks.values())
        if not chs:
            return
        if len(chs) == 1:
            pk_max = chs[0].peaks_max
            pk_min = chs[0].peaks_min
        else:
            pk_max = np.maximum(chs[0].peaks_max, chs[1].peaks_max)
            pk_min = np.minimum(chs[0].peaks_min, chs[1].peaks_min)
        self._overview.set_peaks(pk_max, pk_min)

    def _on_overview_seek(self, wav_t: float) -> None:
        if self._session is None:
            return

        # Find segment containing wav_t
        target_seg: Optional[SongSegment] = None
        for seg in self._session.songs:
            if seg.start_t <= wav_t <= seg.end_t:
                target_seg = seg
                break
        if target_seg is None and self._session.songs:
            target_seg = self._session.songs[-1]
        if target_seg is None:
            return

        if target_seg is self._current_seg:
            t_in_seg = max(0.0, wav_t - target_seg.start_t)
            self._player.seek(t_in_seg)
            self._timeline.set_cursor(wav_t)
            self._overview.set_playhead(wav_t)
        else:
            self._pending_seek_t = wav_t
            for i in range(self._song_combo.count()):
                if self._song_combo.itemData(i) is target_seg:
                    self._song_combo.setCurrentIndex(i)
                    break

    # ── Zoom ──────────────────────────────────────────────────────────────────

    def _on_zoom_combo_changed(self, index: int) -> None:
        v = self._zoom_combo.itemData(index)
        if v is not None:
            self._timeline.set_zoom(float(v))

    def _sync_zoom_combo(self) -> None:
        """Select the nearest preset in the zoom combo for the current zoom."""
        pps = self._timeline.zoom
        best_idx, best_dist = 0, float("inf")
        for i in range(self._zoom_combo.count()):
            v = self._zoom_combo.itemData(i)
            if v:
                dist = abs(math.log(pps / v))
                if dist < best_dist:
                    best_dist, best_idx = dist, i
        self._zoom_combo.blockSignals(True)
        self._zoom_combo.setCurrentIndex(best_idx)
        self._zoom_combo.blockSignals(False)

    def _zoom(self, factor: float) -> None:
        self._timeline.set_zoom(self._timeline.zoom * factor)
        self._sync_zoom_combo()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            self._toggle_play()
        elif event.key() == Qt.Key.Key_B and self._annotation_mode:
            self._add_bar_marker()
        elif event.key() == Qt.Key.Key_P and self._annotation_mode:
            self._add_part_marker()
        elif event.key() == Qt.Key.Key_F and self._annotation_mode:
            self._add_fragment_marker()
        elif event.key() == Qt.Key.Key_U and self._annotation_mode:
            self._undo_last_marker()
        else:
            super().keyPressEvent(event)

    # ── Annotation handlers ───────────────────────────────────────────────────

    def _show_db_parts(self) -> None:
        """Zeigt die Parts des aktuellen Songs aus der reference.db."""
        if self._current_seg is None:
            return

        # reference.db finden
        ref_db_path = None
        if self._session:
            candidate = self._session.wav_path.parent.parent / "reference.db"
            if candidate.exists():
                ref_db_path = candidate
        if ref_db_path is None:
            QMessageBox.warning(self, "DB-Parts", "reference.db nicht gefunden.")
            return

        try:
            import sys
            server_path = str(ref_db_path.parent.parent / "server")
            if server_path not in sys.path:
                sys.path.insert(0, server_path)
            from audio.reference_db import ReferenceDB
            ref_db = ReferenceDB(ref_db_path)
            parts = ref_db.get_parts_for_song(self._current_seg.song_id)
        except Exception as exc:
            QMessageBox.critical(self, "DB-Parts", f"Fehler: {exc}")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"DB-Parts — {self._current_seg.song_name}")
        dlg.setMinimumWidth(420)
        dlg.setStyleSheet(_PANEL_STYLE + """
            QDialog { background:#0e1017; }
            QLabel  { color:#a0a4b8; font-family:'DM Mono',monospace; font-size:10px;
                      padding:4px 8px; }
        """)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        if not parts:
            layout.addWidget(QLabel("Keine Parts in reference.db für diesen Song."))
        else:
            hint = QLabel("Doppelklick → Start-Takt setzen")
            hint.setStyleSheet("color:#5c6080; padding:2px 8px;")
            layout.addWidget(hint)

            lst = QListWidget()
            lst.setStyleSheet(_PANEL_STYLE)
            for part in parts:
                text = (f"T{part['first_bar']:>3}–{part['last_bar']:<3}  "
                        f"({part['bar_count']} Takte)   {part['part_name']}")
                lst.addItem(text)
            layout.addWidget(lst)

            def on_double_click(item):
                idx = lst.row(item)
                first_bar = parts[idx]["first_bar"]
                self._start_bar_spin.setValue(first_bar)
                self._status.showMessage(
                    f"Start-Takt auf {first_bar} gesetzt "
                    f"({parts[idx]['part_name']})", 4000
                )
                dlg.accept()

            lst.itemDoubleClicked.connect(on_double_click)

        dlg.exec()

    def _on_start_bar_changed(self, value: int) -> None:
        """Setzt start_bar_num der aktuellen Annotation und nummeriert neu."""
        ann = self._current_annotation()
        if ann is None:
            return
        ann.start_bar_num = value
        ann._renumber()
        self._timeline.set_bar_markers(ann.markers)
        self._status.showMessage(
            f"Start-Takt auf {value} gesetzt — Marker neu nummeriert", 3000
        )

    def _on_toggle_annotation_mode(self, checked: bool) -> None:
        self._annotation_mode = checked
        self._timeline.set_annotation_mode(checked)
        self._bar_act.setEnabled(checked)
        self._part_act.setEnabled(checked)
        self._frag_act.setEnabled(checked)
        self._undo_annot_act.setEnabled(checked)
        state_str = "EIN" if checked else "AUS"
        if not checked:
            n_snapped, n_failed = self._quantize_bar_markers()
            if n_snapped + n_failed > 0:
                msg = f"Quantisiert: {n_snapped} OK"
                if n_failed:
                    msg += f", {n_failed} nicht gefunden (? markiert)"
                self._status.showMessage(msg, 6000)
                return
        self._status.showMessage(
            f"Annotations-Modus {state_str}  —  B = Takt  P = Part-Start  "
            f"F = Fragment-Start  U = Undo  Rechtsklick = Marker löschen",
            6000,
        )

    def _current_annotation(self) -> Optional[SongAnnotation]:
        """Gibt die SongAnnotation für den aktiven Song zurück (legt sie ggf. an)."""
        if self._current_seg is None:
            return None
        sid = self._current_seg.song_id
        if sid not in self._annotations:
            self._annotations[sid] = SongAnnotation(
                song_id=sid,
                song_name=self._current_seg.song_name,
                segment_start_t=self._current_seg.start_t,
            )
        return self._annotations[sid]

    # ── Quantisierung ────────────────────────────────────────────────────────

    _QUANTIZE_WINDOW_SEC = 0.25   # ±Sekunden, innerhalb derer ein Beat gesucht wird

    def _quantize_bar_markers(self) -> tuple[int, int]:
        """Snappt alle Bar-Marker auf den nächsten Beat/Snare-Event.

        Returns:
            (n_snapped, n_failed) — wie viele Marker verschoben wurden
            bzw. keinen Beat in Reichweite hatten.
        """
        ann = self._current_annotation()
        seg = self._current_seg
        if ann is None or seg is None or not ann.markers:
            return 0, 0

        # Beat-Zeiten aus Session-Events sammeln (relativ zum Segment-Start)
        beat_times: list[float] = []
        for ev in seg.events:
            if ev.type in ("beat", "snare"):
                beat_times.append(ev.t - seg.start_t)

        if not beat_times:
            return 0, 0

        beat_times.sort()
        win = self._QUANTIZE_WINDOW_SEC
        n_snapped = 0
        n_failed = 0

        for m in ann.markers:
            # Nächsten Beat in ±win suchen
            best_t = None
            best_dist = float("inf")
            for bt in beat_times:
                d = abs(bt - m.t)
                if d <= win and d < best_dist:
                    best_dist = d
                    best_t = bt
            if best_t is not None:
                m.t = best_t
                m.quantize_failed = False
                n_snapped += 1
            else:
                m.quantize_failed = True
                n_failed += 1

        # Marker nach Snap neu sortieren und nummerieren
        ann.markers.sort(key=lambda m: m.t)
        ann._renumber()
        self._timeline.set_bar_markers(ann.markers)
        return n_snapped, n_failed

    def _add_bar_marker(self, part_name: str = "") -> None:
        """Setzt einen Takt-Marker an der aktuellen Cursor-Position."""
        ann = self._current_annotation()
        if ann is None or self._current_seg is None:
            return
        t_in_seg = max(0.0, self.cursor_t_in_seg())
        marker = ann.add_marker(t_in_seg, part_name=part_name)
        self._timeline.set_bar_markers(ann.markers)
        self._status.showMessage(
            f"Takt {marker.bar_num} gesetzt @ {t_in_seg:.3f} s"
            + (f"  [{part_name}]" if part_name else ""),
            3000,
        )

    def _add_part_marker(self) -> None:
        """Setzt einen Part-Start-Marker — bietet Part-Namen aus reference.db an."""
        if self._current_seg is None:
            return

        # Schätzung: Takt-Nummer an Cursor-Position
        ann = self._current_annotation()
        t_cursor = max(0.0, self.cursor_t_in_seg())
        estimated_bar = 1
        if ann and ann.markers:
            before = [m for m in ann.markers if m.t <= t_cursor]
            if before:
                estimated_bar = before[-1].bar_num + 1

        # Part-Namen aus reference.db laden
        db_parts: list[dict] = []
        try:
            if self._session:
                candidate = self._session.wav_path.parent.parent / "reference.db"
                if candidate.exists():
                    server_path = str(candidate.parent.parent / "server")
                    if server_path not in sys.path:
                        sys.path.insert(0, server_path)
                    from audio.reference_db import ReferenceDB
                    db_parts = ReferenceDB(candidate).get_parts_for_song(
                        self._current_seg.song_id
                    )
        except Exception:
            pass

        # Default: nächstgelegener Part nach geschätzter Takt-Nummer
        default_name = ""
        if db_parts:
            closest = min(db_parts, key=lambda p: abs(p["first_bar"] - estimated_bar))
            default_name = closest["part_name"]

        if db_parts:
            # Combo-Dialog mit DB-Vorschlägen
            items = [p["part_name"] for p in db_parts]
            default_idx = items.index(default_name) if default_name in items else 0
            name, ok = QInputDialog.getItem(
                self,
                "Part-Start",
                f"Part-Name (geschätzter Takt: {estimated_bar}):",
                items,
                current=default_idx,
                editable=False,
            )
        else:
            name, ok = QInputDialog.getText(
                self, "Part-Start", "Part-Name:",
                text=default_name,
            )

        if not ok or not name.strip():
            return
        self._add_bar_marker(part_name=name.strip())

    def _add_fragment_marker(self) -> None:
        """Setzt einen Fragment-Start-Marker (fragt nach Start-Takt-Nummer)."""
        if self._current_seg is None:
            return
        # Vorschlag: nächste Takt-Nummer nach dem letzten Marker
        ann = self._current_annotation()
        default = (ann.markers[-1].bar_num + 1) if (ann and ann.markers) else 1
        bar_num, ok = QInputDialog.getInt(
            self, "Fragment-Start", "Takt-Nummer ab der gezählt wird:",
            value=default, min=1, max=9999,
        )
        if not ok:
            return
        t_in_seg = max(0.0, self.cursor_t_in_seg())
        marker = ann.add_marker(t_in_seg, restart_bar_num=bar_num)
        self._timeline.set_bar_markers(ann.markers)
        self._status.showMessage(
            f"Fragment-Start: Takt {marker.bar_num} ab hier (→T{bar_num}) "
            f"@ {t_in_seg:.3f} s",
            4000,
        )

    def _undo_last_marker(self) -> None:
        """Entfernt den zuletzt gesetzten (= höchste bar_num) Marker."""
        ann = self._current_annotation()
        if ann is None or not ann.markers:
            self._status.showMessage("Keine Marker vorhanden", 2000)
            return
        removed = ann.markers.pop()
        ann._renumber()
        self._timeline.set_bar_markers(ann.markers)
        self._status.showMessage(
            f"Takt {removed.bar_num} @ {removed.t:.3f} s entfernt", 3000
        )

    def _on_remove_bar_marker(self, t_in_seg: float) -> None:
        """Entfernt den Marker, der t_in_seg am nächsten liegt (Rechtsklick)."""
        ann = self._current_annotation()
        if ann is None:
            return
        removed = ann.remove_nearest(t_in_seg)
        if removed:
            self._timeline.set_bar_markers(ann.markers)
            self._status.showMessage(
                f"Takt {removed.bar_num} @ {removed.t:.3f} s entfernt", 3000
            )

    def cursor_t_in_seg(self) -> float:
        """Aktuelle Cursor-Zeit relativ zum Segment-Start."""
        if self._current_seg is None:
            return 0.0
        return self._player.position_in_segment

    def _save_annotations(self) -> None:
        if self._session is None:
            return
        save_annotations(self._session.jsonl_path, self._annotations)
        total = sum(len(a.markers) for a in self._annotations.values())
        self._status.showMessage(
            f"Annotierungen gespeichert: {len(self._annotations)} Songs, {total} Takte",
            4000,
        )

    def _run_recording_import(self) -> None:
        """Startet den Feature-Import in einem Hintergrund-Thread."""
        if self._session is None or not self._annotations:
            QMessageBox.information(
                self, "Import", "Keine Annotierungen vorhanden."
            )
            return

        # Check if any annotations have markers
        total_markers = sum(len(a.markers) for a in self._annotations.values())
        if total_markers == 0:
            QMessageBox.information(
                self, "Import", "Keine Takt-Marker annotiert."
            )
            return

        # First save
        self._save_annotations()

        # Find reference.db and db.json
        repo_root = self._session.jsonl_path.parent.parent.parent.parent
        ref_db_path  = repo_root / "live" / "data" / "reference.db"
        db_json_path = repo_root / "db" / "lighting-ai-db.json"

        if not ref_db_path.exists():
            QMessageBox.warning(
                self, "Import",
                f"reference.db nicht gefunden:\n{ref_db_path}"
            )
            return

        self._import_act.setEnabled(False)
        self._status.showMessage(
            f"Import läuft: {total_markers} Takte aus "
            f"{len(self._annotations)} Songs …",
        )

        worker = _ImportWorker(
            wav_path=self._session.wav_path,
            annotations=dict(self._annotations),
            ref_db_path=ref_db_path,
            db_json_path=db_json_path,
            sr=self._session.sample_rate,
            repo_root=repo_root,
            parent=self,
        )
        worker.finished.connect(self._on_import_done)
        worker.error.connect(self._on_import_error)
        worker.start()

    def _on_import_done(self, msg: str) -> None:
        self._import_act.setEnabled(True)
        self._status.showMessage(msg, 8000)
        QMessageBox.information(self, "Import", msg)

    def _on_import_error(self, err: str) -> None:
        self._import_act.setEnabled(True)
        self._status.showMessage(f"Import-Fehler: {err}", 8000)
        QMessageBox.critical(self, "Import-Fehler", err)

    # ── Fragment detection ────────────────────────────────────────────────────

    def _detect_fragments(self) -> None:
        """Startet die Stille-basierte Fragment-Erkennung im Hintergrund-Thread."""
        if self._current_seg is None or self._session is None:
            return

        seg        = self._current_seg
        n_ch       = self._session.n_channels
        ch_indices = list(range(min(16, n_ch)))

        self._detect_frags_act.setEnabled(False)
        self._timeline.clear_scan_progress()
        self._status.showMessage(
            f'Fragment-Erkennung läuft: "{seg.song_name}" …'
        )

        worker = _FragmentWorker(
            wav_path=self._session.wav_path,
            start_t=seg.start_t,
            end_t=seg.end_t,
            sample_rate=self._session.sample_rate,
            ch_indices=ch_indices,
            parent=self,
        )
        worker.finished.connect(self._on_fragments_done)
        worker.error.connect(self._on_fragment_error)
        worker.progress.connect(
            lambda scan_t, windows: self._timeline.update_scan_progress(scan_t, windows)
        )
        self._fragment_worker = worker
        worker.start()

    def _on_fragments_done(self, fragments: list) -> None:
        self._detected_fragments = fragments
        self._detect_frags_act.setEnabled(True)

        # Pass start times of fragments 2, 3, … to timeline
        boundaries = [f.start_t for f in fragments[1:]]
        self._timeline.set_fragment_boundaries(boundaries)

        n = len(fragments)
        if n <= 1:
            dr = f"{fragments[0].drum_ratio:.0%}" if fragments else "—"
            msg = (
                f'1 Fragment — Song komplett oder keine Stille-Lücke ≥ 1,5 s erkannt '
                f'({fragments[0].fmt() if fragments else "—"}, Drums {dr})'
            )
        else:
            labels = "  |  ".join(
                f"F{i + 1}: {f.fmt()} [{f.drum_ratio:.0%}🥁]"
                for i, f in enumerate(fragments)
            )
            msg = f"{n} Fragmente erkannt — {labels}"

        self._status.showMessage(msg, 12000)

    def _on_fragment_error(self, err: str) -> None:
        self._detect_frags_act.setEnabled(True)
        self._status.showMessage(f"Fragment-Erkennung fehlgeschlagen: {err}", 8000)
        QMessageBox.critical(self, "Fragment-Erkennung", f"Fehler:\n{err}")

    # ── Simulation ────────────────────────────────────────────────────────────

    def _run_simulation(self) -> None:
        """Startet die Offline-Simulation der Live-Erkennung auf dem aktuellen Segment."""
        if self._current_seg is None or self._session is None:
            return

        seg = self._current_seg

        # BPM aus der Songdatenbank holen (falls vorhanden)
        bpm = 120.0
        try:
            repo_root = self._session.jsonl_path.parent.parent.parent.parent
            db_json   = repo_root / "db" / "lighting-ai-db.json"
            if db_json.exists():
                import json as _json
                db = _json.loads(db_json.read_text("utf-8"))
                bpm = float(db.get("songs", {}).get(seg.song_id, {}).get("bpm", 120.0))
        except Exception:
            pass

        # reference.db finden
        ref_db_path: Optional[Path] = None
        if self._session:
            candidate = self._session.wav_path.parent.parent / "reference.db"
            if candidate.exists():
                ref_db_path = candidate

        # Use current playhead position as simulation start (relative to seg start).
        # Clamp to [0, seg.duration - 1s] so we never start past the segment end.
        t_in_seg_start = max(0.0, min(
            self._player.position_in_segment,
            max(0.0, seg.duration - 1.0),
        ))
        sim_start_wav_t = seg.start_t + t_in_seg_start

        # JSONL-Ausgabedatei neben der Session ablegen
        stamp = _dt.now().strftime("%H%M%S")
        out_jsonl = (
            self._session.jsonl_path.parent
            / f"{self._session.jsonl_path.stem}_sim_{seg.song_id}_{stamp}.jsonl"
        )

        self._timeline.clear_sim_events()
        self._sim_act.setEnabled(False)
        self._sim_clear_act.setEnabled(True)
        self._sim_start_wav_t = sim_start_wav_t
        self._sim_t_in_seg    = t_in_seg_start
        self._status.showMessage(
            f'Simulation läuft: "{seg.song_name}" — BPM {bpm:.0f} …', 0
        )

        worker = SimulatorWorker(
            wav_path=self._session.wav_path,
            seg_start_t=sim_start_wav_t,
            seg_end_t=seg.end_t,
            sample_rate=self._session.sample_rate,
            n_channels=self._session.n_channels,
            song_id=seg.song_id,
            song_name=seg.song_name,
            bpm=bpm,
            output_jsonl=out_jsonl,
            ref_db_path=ref_db_path,
            use_hmm=False,
            parent=self,
        )
        worker.progress.connect(self._on_sim_progress)
        worker.finished.connect(self._on_sim_finished)
        worker.error.connect(self._on_sim_error)
        self._sim_worker = worker
        worker.start()

    def _clear_simulation(self) -> None:
        if self._sim_worker is not None:
            self._sim_worker.requestInterruption()
            self._sim_worker = None
        self._timeline.clear_sim_events()
        self._timeline.set_sim_overlay(False)
        self._sim_act.setEnabled(True)
        self._sim_overlay_act.setChecked(False)
        self._sim_overlay_act.setEnabled(False)
        self._sim_clear_act.setEnabled(False)
        self._status.showMessage("Simulations-Ergebnisse gelöscht", 3000)

    def _on_sim_progress(self, v: float) -> None:
        seg = self._current_seg
        name = seg.song_name if seg else "…"
        self._status.showMessage(f'Simulation: "{name}" — {v:.0%}', 0)

    def _on_sim_finished(self, result: dict) -> None:
        self._sim_act.setEnabled(True)
        self._sim_clear_act.setEnabled(True)
        self._sim_worker = None

        n_beats_all = result.get("n_beats_all", 0)
        n_downbeats = result.get("n_downbeats", 0)
        n_positions = result.get("n_positions", 0)
        jsonl_path  = result.get("jsonl_path")
        beats       = result.get("beats", [])
        positions   = result.get("positions", [])

        if n_beats_all == 0:
            QMessageBox.warning(
                self, "Simulation — keine Beats",
                "Die Simulation hat keine Beats erkannt.\n\n"
                "Mögliche Ursachen:\n"
                "• Die WAV-Datei endet vor dem gewählten Segment\n"
                "• Die Session-Sample-Rate stimmt nicht mit der WAV überein\n"
                "• Der Playhead stand am Segment-Ende"
            )
            return

        # Timeline mit Sim-Events befüllen (t relativ zu Segment-Start)
        for b in beats:
            self._timeline.add_sim_beat(
                self._sim_start_wav_t + b.t, b.is_downbeat
            )
        for pos in positions:
            self._timeline.add_sim_position(
                self._sim_start_wav_t + pos.t,
                pos.bar_num, pos.part_name, pos.confidence, pos.is_frozen,
            )

        # Vergleich mit manuellen Annotationen
        ann = self._current_annotation()
        if ann and ann.markers and positions:
            correct = sum(
                1 for m in ann.markers
                if (
                    (closest := min(positions, key=lambda p: abs(p.t - (m.t - self._sim_start_wav_t))))
                    and abs(closest.t - (m.t - self._sim_start_wav_t)) <= 1.0
                    and closest.bar_num == m.bar_num
                )
            )
            match_info = (
                f" — Takt-Match: {correct}/{len(ann.markers)} "
                f"({correct / len(ann.markers):.0%})"
            )
        else:
            match_info = ""

        summary = (
            f"Simulation: {n_downbeats} Downbeats, "
            f"{n_positions} Positionen{match_info}"
        )
        self._status.showMessage(summary, 12000)

        # Overlay-Toggle freischalten und Simulation-Ansicht aktivieren
        self._sim_overlay_act.setEnabled(True)
        self._sim_overlay_act.setChecked(True)   # sofort auf Sim-Ansicht umschalten

    def _on_sim_error(self, err: str) -> None:
        self._sim_act.setEnabled(True)
        self._sim_worker = None
        self._sim_clear_act.setEnabled(False)
        self._status.showMessage(f"Simulation fehlgeschlagen: {err}", 8000)
        QMessageBox.critical(self, "Simulation", f"Fehler:\n{err}")

    def _zoom_fit(self) -> None:
        if self._current_seg is None:
            return
        avail = max(1, self._timeline.width() - LABEL_W - 2)
        pps = avail / max(0.1, self._current_seg.duration)
        self._timeline.set_zoom(pps)
        self._sync_zoom_combo()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_t(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m}:{s:02d}"


def _fmt_t_precise(secs: float) -> str:
    m = int(secs // 60)
    s = secs % 60
    return f"{m}:{s:05.2f}"


def _fmt_dur(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m}:{s:02d} min"
