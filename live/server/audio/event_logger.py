"""Session-Event-Logger — schreibt ein JSONL-Logfile synchron zur WAV-Aufnahme.

Format: Eine JSON-Zeile pro Ereignis, sortiert nach `t` (Sekunden seit
Aufnahme-Start = wav_offset).  Das ermöglicht den direkten Abgleich mit
der 18-Kanal-WAV.

Ereignis-Typen
--------------
session_start   Aufnahme geöffnet
session_end     Aufnahme geschlossen (mit Dauer)
beat            Erkannter Takt (Quelle + BPM)
position        HMM-Positions-Update (Song / Part / Bar / Konfidenz)
user            User-Interaktion via WebSocket (Timo drückt was)
server_log      Ungewöhnliche Server-Log-Meldung (WARNING / ERROR / CRITICAL)

Datei-Ablage: live/data/recordings/{session_id}.jsonl
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("live.audio.event_logger")


class SessionEventLogger:
    """Schreibt Ereignisse zeilenweise als JSON in eine JSONL-Datei.

    Thread-sicher: kann gleichzeitig aus Audio-Thread, FastAPI-Thread und
    Logging-Handler aufgerufen werden.
    """

    def __init__(self, path: Path, started_at_ts: float) -> None:
        self._path = path
        self._started_at_ts = started_at_ts
        self._lock = threading.Lock()
        try:
            self._file = path.open("w", encoding="utf-8", buffering=1)  # line-buffered
        except OSError as exc:
            log.error("EventLogger: Datei konnte nicht geöffnet werden: %s", exc)
            self._file = None  # type: ignore[assignment]

    # ------------------------------------------------------------------

    def log(self, event_type: str, wav_offset: float | None = None, **fields: Any) -> None:
        """Schreibt einen Ereignis-Eintrag.

        Parameters
        ----------
        event_type:
            Kategorie (z.B. ``"beat"``, ``"user"``, ``"server_log"``).
        wav_offset:
            Präziser Zeitstempel in Sekunden seit Aufnahme-Start, berechnet
            aus dem ADC-Zeitstempel des Audio-Callbacks (time_info.inputBufferAdcTime).
            Falls None, wird time.time() als Fallback genutzt — weniger präzise.
        **fields:
            Beliebige weitere Felder — werden direkt ins JSON-Objekt aufgenommen.
        """
        if wav_offset is not None:
            t = round(wav_offset, 4)
        else:
            t = round(time.time() - self._started_at_ts, 4)
        entry: dict[str, Any] = {"t": t, "type": event_type}
        entry.update(fields)
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with self._lock:
            if self._file is not None and not self._file.closed:
                try:
                    self._file.write(line + "\n")
                except OSError as exc:
                    log.error("EventLogger: Schreibfehler: %s", exc)

    def close(self) -> None:
        """Flush und Schließen der Datei."""
        with self._lock:
            if self._file is not None and not self._file.closed:
                try:
                    self._file.flush()
                    self._file.close()
                except OSError:
                    pass
