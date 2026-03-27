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
    win.showMaximized()

    # Delay file open until the event loop is running so showMaximized() takes effect
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if p.exists() and p.suffix == ".jsonl":
            QTimer.singleShot(0, lambda: win._load_session(p))
    else:
        QTimer.singleShot(0, win._open_session)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
