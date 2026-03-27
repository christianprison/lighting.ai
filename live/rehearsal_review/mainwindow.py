"""mainwindow.py — Main application window for Rehearsal Post-Preparation."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QProgressDialog, QScrollArea, QStatusBar, QToolBar,
    QVBoxLayout, QWidget,
)

from session import Session, SongSegment, load_session
from peaks import PeakWorker, DISPLAY_CHANNELS, TrackPeaks
from player import AudioPlayer
from timeline import TimelineWidget, CONTENT_H, LABEL_W, TRACKS
from overview import OverviewWidget

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
        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)

        self._play_act = tb.addAction("Play")
        self._play_act.triggered.connect(self._toggle_play)

        stop_act = tb.addAction("Stop")
        stop_act.triggered.connect(self._stop)

        tb.addSeparator()

        # Song selection dropdown
        self._song_combo = QComboBox()
        self._song_combo.setMinimumWidth(300)
        self._song_combo.setPlaceholderText("-- Song waehlen --")
        self._song_combo.currentIndexChanged.connect(self._on_song_combo_changed)
        tb.addWidget(self._song_combo)

        tb.addSeparator()

        zoom_lbl = QLabel("  Zoom:")
        zoom_lbl.setStyleSheet(
            "font-family:'DM Mono',monospace; font-size:10px; color:#a0a4b8;"
        )
        tb.addWidget(zoom_lbl)

        self._zoom_combo = QComboBox()
        self._zoom_combo.setObjectName("zoom_combo")
        for v in _ZOOM_PRESETS:
            self._zoom_combo.addItem(f"{v} px/s", v)
        self._zoom_combo.setCurrentIndex(3)   # default 80 px/s
        self._zoom_combo.currentIndexChanged.connect(self._on_zoom_combo_changed)
        tb.addWidget(self._zoom_combo)

        tb.addSeparator()

        self._datetime_lbl = QLabel("  —")
        self._datetime_lbl.setStyleSheet(
            "font-family:'DM Mono',monospace; font-size:10px; color:#eef0f6;"
        )
        tb.addWidget(self._datetime_lbl)

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
        else:
            super().keyPressEvent(event)

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
