"""main.py — Entry point for Rehearsal Post-Preparation."""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont

from mainwindow import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Rehearsal Post-Preparation")
    app.setOrganizationName("lighting.ai")
    app.setFont(QFont("Sora", 10))

    win = MainWindow()
    win.show()   # show at default size first so the window handle is created

    # showMaximized() must run inside the event loop on Linux/KDE;
    # calling it before app.exec() sets the state flag but not the geometry.
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if p.exists() and p.suffix == ".jsonl":
            QTimer.singleShot(0, lambda: (win.showMaximized(), win._load_session(p)))
        else:
            QTimer.singleShot(0, lambda: (win.showMaximized(), win._open_session()))
    else:
        QTimer.singleShot(0, lambda: (win.showMaximized(), win._open_session()))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
