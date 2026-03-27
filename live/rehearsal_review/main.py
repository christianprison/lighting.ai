"""main.py — Entry point for Rehearsal Post-Preparation."""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont, QFontDatabase

from mainwindow import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Rehearsal Post-Preparation")
    app.setOrganizationName("lighting.ai")

    # Use system font as fallback if Sora/DM Mono are not installed
    app.setFont(QFont("Sora", 10))

    win = MainWindow()
    win.showMaximized()

    # Open file passed as CLI argument, otherwise show file dialog immediately
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if p.exists() and p.suffix == ".jsonl":
            win._load_session(p)
    else:
        win._open_session()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
