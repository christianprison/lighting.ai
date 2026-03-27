"""mainwindow.py — Main application window for Rehearsal Post-Preparation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QProgressDialog, QScrollArea, QSplitter,
    QStatusBar, QToolBar, QVBoxLayout, QWidget,
)

from session import Session, SongSegment, load_session
from peaks import PeakWorker, DISPLAY_CHANNELS, TrackPeaks
from player import AudioPlayer
from timeline import TimelineWidget, CONTENT_H

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
QListWidget                   { background:#0e1017; border:none; outline:none; }
QListWidget::item             { padding:9px 14px; border-bottom:1px solid #1e2230;
                                font-family:'Sora',sans-serif; font-size:11px; }
QListWidget::item:selected    { background:#00dc8218; color:#00dc82; }
QListWidget::item:hover       { background:#1c1f2b; }
QScrollArea                   { border:none; background:#08090d; }
QScrollBar:vertical           { background:#0e1017; width:8px; }
QScrollBar::handle:vertical   { background:#2a2e40; border-radius:4px; }
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical { height:0; }
QStatusBar                    { background:#0e1017; border-top:1px solid #1e2230;
                                font-family:'DM Mono',monospace; font-size:10px;
                                color:#5c6080; }
QProgressDialog               { background:#0e1017; color:#eef0f6; }
QProgressBar                  { background:#151820; border:1px solid #1e2230;
                                border-radius:3px; text-align:center; }
QProgressBar::chunk           { background:#00dc82; border-radius:2px; }
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Rehearsal Post-Preparation — lighting.ai")
        self.resize(1440, 940)
        self.setStyleSheet(_APP_STYLE)

        self._session: Optional[Session] = None
        self._current_seg: Optional[SongSegment] = None
        self._peak_worker: Optional[PeakWorker] = None
        self._progress: Optional[QProgressDialog] = None

        self._player = AudioPlayer(self)
        self._player.position_changed.connect(self._on_position)
        self._player.playback_stopped.connect(self._on_stopped)

        self._build_ui()
        self._build_menu()
        self._build_toolbar()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle { background:#1e2230; }")

        # Left panel: song list
        left = QWidget()
        left.setFixedWidth(230)
        left.setStyleSheet("background:#0e1017; border-right:1px solid #1e2230;")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)

        hdr = QLabel("  SONGS")
        hdr.setFixedHeight(36)
        hdr.setStyleSheet(
            "background:#151820; border-bottom:1px solid #1e2230;"
            "font-family:'DM Mono',monospace; font-size:9px;"
            "letter-spacing:2px; color:#5c6080; padding-left:4px;"
        )
        lv.addWidget(hdr)

        self._song_list = QListWidget()
        self._song_list.currentItemChanged.connect(self._on_song_selected)
        lv.addWidget(self._song_list)

        splitter.addWidget(left)

        # Right panel: timeline inside a vertical scroll area
        self._timeline = TimelineWidget()
        self._timeline.seek_requested.connect(self._on_seek)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(self._timeline)
        scroll.setMinimumHeight(CONTENT_H)

        splitter.addWidget(scroll)
        splitter.setSizes([230, 1210])

        self.setCentralWidget(splitter)

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._pos_label = QLabel("–:––.–")
        self._pos_label.setStyleSheet(
            "font-family:'DM Mono',monospace; font-size:10px; color:#a0a4b8;"
        )
        self._status.addPermanentWidget(self._pos_label)

    def _build_menu(self) -> None:
        mb = self.menuBar()

        fm = mb.addMenu("Datei")
        open_a = QAction("Öffnen…", self)
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
        zo = QAction("Zoom −", self)
        zo.setShortcut(QKeySequence("-"))
        zo.triggered.connect(lambda: self._zoom(0.8))
        vm.addAction(zo)
        zf = QAction("Zoom Anpassen", self)
        zf.setShortcut(QKeySequence("0"))
        zf.triggered.connect(self._zoom_fit)
        vm.addAction(zf)

    def _build_toolbar(self) -> None:
        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)

        self._play_act = tb.addAction("▶  PLAY")
        self._play_act.setShortcut(QKeySequence("Space"))
        self._play_act.triggered.connect(self._toggle_play)

        stop_act = tb.addAction("■  STOP")
        stop_act.triggered.connect(self._stop)

        tb.addSeparator()

        self._zoom_lbl = QLabel("  80 px/s  ")
        self._zoom_lbl.setStyleSheet(
            "font-family:'DM Mono',monospace; font-size:10px; color:#5c6080;"
        )
        tb.addWidget(self._zoom_lbl)

        tb.addSeparator()

        self._file_lbl = QLabel("  Keine Datei geladen")
        self._file_lbl.setStyleSheet(
            "font-family:'DM Mono',monospace; font-size:10px; color:#5c6080;"
        )
        tb.addWidget(self._file_lbl)

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

        self._song_list.clear()
        for seg in session.songs:
            item = QListWidgetItem(f"  {seg.song_name}")
            item.setToolTip(
                f"{_fmt_t(seg.start_t)} → {_fmt_t(seg.end_t)}"
                f"  ({_fmt_dur(seg.duration)})"
            )
            item.setData(Qt.ItemDataRole.UserRole, seg)
            self._song_list.addItem(item)

        mix = " · Mixdown vorhanden" if session.mixdown_path else ""
        self._file_lbl.setText(
            f"  {jsonl_path.name}  |  {session.n_channels} ch  |"
            f"  {session.sample_rate} Hz  |  {len(session.songs)} Songs{mix}  "
        )
        self._status.showMessage(
            f"{jsonl_path}  —  {len(session.songs)} Songs"
            f"  —  {_fmt_dur(session.total_duration)}"
        )

        if self._song_list.count():
            self._song_list.setCurrentRow(0)

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

    def _on_song_selected(self, current, _previous) -> None:
        if current is None:
            return
        seg: SongSegment = current.data(Qt.ItemDataRole.UserRole)
        self._current_seg = seg
        self._player.stop()
        self._play_act.setText("▶  PLAY")

        self._timeline.set_segment(seg, None)

        # Cancel previous worker
        if self._peak_worker and self._peak_worker.isRunning():
            self._peak_worker.terminate()
            self._peak_worker.wait(300)
        if self._progress:
            self._progress.close()

        if self._session is None:
            return

        self._progress = QProgressDialog(
            f"Lade Wellenformen: „{seg.song_name}"…",
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

        prg = self._progress   # local capture for lambdas
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

    # ── Transport ─────────────────────────────────────────────────────────────

    def _toggle_play(self) -> None:
        if self._current_seg is None:
            return
        self._player.toggle()
        self._play_act.setText("⏸  PAUSE" if self._player.is_playing else "▶  PLAY")

    def _stop(self) -> None:
        self._player.stop()
        self._play_act.setText("▶  PLAY")
        if self._current_seg:
            self._timeline.set_cursor(self._current_seg.start_t)
            self._pos_label.setText(_fmt_t_precise(0.0))

    def _on_seek(self, t_in_seg: float) -> None:
        self._player.seek(t_in_seg)
        if self._current_seg:
            self._timeline.set_cursor(self._current_seg.start_t + t_in_seg)

    def _on_position(self, wav_t: float) -> None:
        self._timeline.set_cursor(wav_t)
        if self._current_seg:
            self._pos_label.setText(_fmt_t_precise(wav_t - self._current_seg.start_t))

    def _on_stopped(self) -> None:
        self._play_act.setText("▶  PLAY")

    # ── Zoom ──────────────────────────────────────────────────────────────────

    def _zoom(self, factor: float) -> None:
        self._timeline.set_zoom(self._timeline.zoom * factor)
        self._zoom_lbl.setText(f"  {self._timeline.zoom:.0f} px/s  ")

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            self._toggle_play()
        else:
            super().keyPressEvent(event)

    def _zoom_fit(self) -> None:
        if self._current_seg is None:
            return
        avail = max(1, self._timeline.width() - 162)
        pps = avail / max(0.1, self._current_seg.duration)
        self._timeline.set_zoom(pps)
        self._zoom_lbl.setText(f"  {self._timeline.zoom:.0f} px/s  ")


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
