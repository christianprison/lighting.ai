"""Direct DMX control via sACN (E1.31) — Fallback mode.

Steuert eine Fixture direkt per sACN, ohne QLC+.
Solange kein Song/Part erkannt wird, blinkt die Fixture alle 500 ms
mit wechselnden Farben.

Fixture: "16 LED Pot Bibo 40°"
  DMX-Adresse 6 = Master Dimmer
  DMX-Adresse 7 = Red
  DMX-Adresse 8 = Green
  DMX-Adresse 9 = Blue

Alle DMX-Adressen sind 1-basiert (wie im DMX-Patchsheet üblich).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("live.dmx_fallback")

# ─── Fixture Config ────────────────────────────────────────────────────────
# "16 LED Pot Bibo 40°" — DMX-Adressen 1-basiert
_DIMMER_CH: int = 6   # Master Dimmer
_RED_CH: int = 7
_GREEN_CH: int = 8
_BLUE_CH: int = 9

# ─── Color sequence ────────────────────────────────────────────────────────
_COLORS: list[tuple[int, int, int]] = [
    (255,   0,   0),   # Rot
    (255, 100,   0),   # Orange
    (255, 255,   0),   # Gelb
    (  0, 255,   0),   # Grün
    (  0, 220, 255),   # Cyan
    (  0,  80, 255),   # Blau
    (160,   0, 255),   # Violett
    (255,   0, 160),   # Pink
    (255, 255, 255),   # Weiß
]

_FLASH_INTERVAL: float = 0.5  # Sekunden


@dataclass
class DmxFallbackConfig:
    universe: int = 1
    multicast: bool = True
    source_name: str = "lighting.ai fallback"


class DmxFallbackController:
    """Fallback-DMX-Controller: blinkt eine Fixture via sACN.

    - start_async(): sACN-Sender starten + Blink-Loop beginnen
    - stop_async():  Blink-Loop stoppen + Blackout senden + Sender stoppen
    - is_active:     True wenn Fallback-Modus läuft
    """

    def __init__(self, cfg: DmxFallbackConfig | None = None) -> None:
        self._cfg = cfg or DmxFallbackConfig()
        self._sender = None
        self._task: Optional[asyncio.Task] = None
        self._active: bool = False
        self._color_idx: int = 0

    # ── Public interface ───────────────────────────────────────────────────

    async def start_async(self) -> bool:
        """sACN-Sender initialisieren und Blink-Loop starten.

        Gibt True zurück wenn erfolgreich, False wenn sacn nicht installiert
        oder ein Fehler auftritt.
        """
        if self._active:
            return True

        try:
            import sacn  # noqa: F401 — nur Verfügbarkeitscheck
        except ImportError:
            log.error(
                "sacn-Library nicht installiert — bitte installieren: pip install sacn"
            )
            return False

        if not self._init_sender():
            return False

        self._active = True
        self._color_idx = 0
        self._task = asyncio.create_task(self._flash_loop())
        log.info(
            "DMX-Fallback gestartet — Universe %d, multicast=%s",
            self._cfg.universe,
            self._cfg.multicast,
        )
        return True

    async def stop_async(self) -> None:
        """Blink-Loop stoppen, Blackout senden, Sender beenden."""
        if not self._active:
            return

        self._active = False

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

        self._send_blackout()
        await asyncio.sleep(0.12)  # letzte Blackout-Frame übertragen lassen
        self._stop_sender()
        log.info("DMX-Fallback gestoppt")

    @property
    def is_active(self) -> bool:
        return self._active

    # ── Internal ───────────────────────────────────────────────────────────

    def _init_sender(self) -> bool:
        """sACN-Sender erzeugen und Universe aktivieren."""
        try:
            import sacn
            self._sender = sacn.sACNsender(
                source_name=self._cfg.source_name,
                fps=40,  # Übertragungsrate: 40 Hz (alle 25 ms einen Frame)
            )
            self._sender.start()
            self._sender.activate_output(self._cfg.universe)
            self._sender[self._cfg.universe].multicast = self._cfg.multicast
            self._sender[self._cfg.universe].dmx_data = (0,) * 512
            return True
        except Exception as exc:
            log.error("DMX-Fallback: sACN-Sender konnte nicht gestartet werden: %s", exc)
            self._sender = None
            return False

    def _stop_sender(self) -> None:
        if self._sender:
            try:
                self._sender.stop()
            except Exception:
                pass
            self._sender = None

    def _set_dmx(self, on: bool, r: int, g: int, b: int) -> None:
        """DMX-Daten im sACN-Sender aktualisieren (1-basierte Adressen)."""
        if not self._sender:
            return
        data = list(self._sender[self._cfg.universe].dmx_data)
        if on:
            data[_DIMMER_CH - 1] = 255
            data[_RED_CH - 1] = r
            data[_GREEN_CH - 1] = g
            data[_BLUE_CH - 1] = b
        else:
            data[_DIMMER_CH - 1] = 0
            data[_RED_CH - 1] = 0
            data[_GREEN_CH - 1] = 0
            data[_BLUE_CH - 1] = 0
        try:
            self._sender[self._cfg.universe].dmx_data = tuple(data)
        except Exception as exc:
            log.warning("DMX-Fallback: Fehler beim Senden: %s", exc)

    def _send_blackout(self) -> None:
        """Alle Kanäle auf 0 setzen."""
        if self._sender:
            try:
                self._sender[self._cfg.universe].dmx_data = (0,) * 512
            except Exception:
                pass

    async def _flash_loop(self) -> None:
        """500-ms-Blink-Loop mit Farbwechsel bei jedem 'An'."""
        on = False
        try:
            while self._active:
                on = not on
                if on:
                    r, g, b = _COLORS[self._color_idx % len(_COLORS)]
                    self._color_idx += 1
                    log.debug(
                        "DMX-Fallback: AN — RGB(%d,%d,%d) Farbe %d/%d",
                        r, g, b,
                        (self._color_idx - 1) % len(_COLORS) + 1,
                        len(_COLORS),
                    )
                else:
                    r, g, b = 0, 0, 0
                self._set_dmx(on, r, g, b)
                await asyncio.sleep(_FLASH_INTERVAL)
        except asyncio.CancelledError:
            pass
        finally:
            self._send_blackout()
