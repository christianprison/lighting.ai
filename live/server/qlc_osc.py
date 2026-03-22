"""OSC client for QLC+ 4 control.

lighting.ai steuert QLC+ direkt per Collection-Trigger (kein CueList).
Jeder Step in einem Song-Chaser hat eine collection_id die per OSC
an den entsprechenden QLC+ Button gesendet wird.

OSC path format: /{universe}/dmx/{collection_id}
Values: float 255 → 0 (toggle trigger)
"""

from __future__ import annotations

import asyncio
import logging
import time

from pythonosc.udp_client import SimpleUDPClient

from .config import QlcConfig
from .qlc_parser import ACCENT_FUNCTIONS

log = logging.getLogger("live.qlc_osc")

# QLC+ function_id → collection_id (index for OSC path /X/dmx/{collection_id}).
# Extracted from Virtual Console buttons in lightingAI.qxw.
FUNCTION_TO_COLLECTION: dict[int, int] = {
    14: 103, 19: 25, 22: 85, 28: 44, 29: 73, 32: 75, 33: 76, 34: 77,
    70: 5, 71: 2, 74: 8, 75: 10, 76: 11, 77: 12, 78: 15, 79: 17,
    80: 18, 81: 20, 82: 24, 83: 51,
    136: 78, 143: 67, 152: 79, 158: 52, 160: 53, 163: 98, 165: 86,
    181: 56, 182: 57, 208: 84, 209: 82, 212: 58, 219: 80,
    224: 88, 225: 68, 226: 91, 227: 93, 228: 97, 229: 101, 230: 104,
    231: 92, 249: 16, 269: 95, 281: 100, 282: 99,
    362: 36, 363: 26, 372: 27, 471: 37, 473: 87, 475: 72,
    476: 70, 477: 71, 478: 47, 481: 28, 485: 45, 486: 30,
    488: 34, 490: 29, 491: 46, 493: 3, 496: 32, 498: 38,
    500: 41, 502: 42, 504: 33, 506: 35, 508: 39, 509: 23,
    510: 22, 511: 43, 514: 40, 515: 102, 517: 48, 519: 31,
    520: 7, 521: 4, 522: 89, 523: 19, 524: 13, 525: 14,
    526: 90, 527: 0, 528: 1, 529: 54, 531: 96, 533: 60,
    534: 6, 535: 59, 536: 55, 537: 9, 538: 94, 545: 21,
    553: 66, 554: 81, 555: 83, 559: 49, 564: 74, 565: 50,
    578: 65, 579: 62, 580: 63, 581: 61, 582: 64, 597: 69,
    # Accent / utility functions — map to QLC+ buttons manually
    31: 105,   # blind √
    36: 106,   # blackout (scene)
    37: 107,   # Fog 10s √
    38: 108,   # Fog on
    39: 109,   # Fog off
    279: 110,  # Alarm neu (rot/grün alternierend)
}

# Accent channel map for direct accent triggers (legacy, separate from collections)
DEFAULT_ACCENT_MAP = {
    "blind": 10,
    "blackout": 11,
    "strobe": 12,
    "alarm": 13,
    "fog_on": 14,
    "fog_off": 15,
    "fog_5s": 16,
    "fog_10s": 17,
    "tap_tempo": 20,
}


class QlcOsc:
    """OSC client for controlling QLC+ 4 via direct collection triggers."""

    def __init__(self, cfg: QlcConfig, accent_map: dict[str, int] | None = None):
        self.cfg = cfg
        self.client: SimpleUDPClient | None = None
        self.universe = cfg.osc_universe
        self.accent_map = accent_map or dict(DEFAULT_ACCENT_MAP)
        self._connected = False
        self._last_collection_id: int | None = None

    def connect(self) -> bool:
        """Create the UDP client. Returns True on success."""
        try:
            self.client = SimpleUDPClient(self.cfg.osc_host, self.cfg.osc_port)
            self._connected = True
            log.info("OSC client ready: %s:%d", self.cfg.osc_host, self.cfg.osc_port)
            return True
        except Exception as exc:
            log.error("OSC connect failed: %s", exc)
            self._connected = False
            return False

    @property
    def connected(self) -> bool:
        return self._connected

    def _send(self, channel: int, value: float) -> None:
        """Send a single OSC message to a QLC+ channel."""
        if not self.client:
            log.warning("OSC client not connected")
            return
        path = f"/{self.universe}/dmx/{channel}"
        self.client.send_message(path, float(value))

    def _trigger(self, channel: int) -> None:
        """Trigger a button: send 255 then 0 (QLC+ needs the 0→255 transition).

        Sync version — nur für Threads außerhalb des asyncio-Event-Loops.
        """
        self._send(channel, 255.0)
        time.sleep(0.05)
        self._send(channel, 0.0)

    async def _trigger_async(self, channel: int) -> None:
        """Async-Version von _trigger — blockiert den Event-Loop nicht."""
        self._send(channel, 255.0)
        await asyncio.sleep(0.05)
        self._send(channel, 0.0)

    # --- Collection trigger (Hauptsteuerung) ---

    def trigger_collection(self, collection_id: int) -> None:
        """Trigger a QLC+ collection button by its collection_id.

        This is the primary control method — each song step triggers
        its collection directly, bypassing the CueList.

        Automatically deactivates the previously active collection first
        (QLC+ toggle buttons: same OSC pulse = toggle off).
        """
        if self._last_collection_id is not None and self._last_collection_id != collection_id:
            self._trigger(self._last_collection_id)
            log.info("Collection %d deactivated (previous)", self._last_collection_id)
        self._trigger(collection_id)
        self._last_collection_id = collection_id
        log.info("Collection %d triggered", collection_id)

    def trigger_function(self, function_id: int) -> bool:
        """Trigger a QLC+ function by looking up its collection_id.

        Returns True if the function was found and triggered.
        Sync version — blockiert den aufrufenden Thread für ~50ms.
        """
        collection_id = FUNCTION_TO_COLLECTION.get(function_id)
        if collection_id is not None:
            self.trigger_collection(collection_id)
            log.info("Function %d → Collection %d triggered", function_id, collection_id)
            return True
        log.warning("No collection mapping for function %d", function_id)
        return False

    async def trigger_function_async(self, function_id: int) -> bool:
        """Async-Version von trigger_function — blockiert den Event-Loop nicht."""
        collection_id = FUNCTION_TO_COLLECTION.get(function_id)
        if collection_id is None:
            log.warning("No collection mapping for function %d", function_id)
            return False
        if self._last_collection_id is not None and self._last_collection_id != collection_id:
            await self._trigger_async(self._last_collection_id)
            log.info("Collection %d deactivated (previous)", self._last_collection_id)
        await self._trigger_async(collection_id)
        self._last_collection_id = collection_id
        log.info("Function %d → Collection %d triggered", function_id, collection_id)
        return True

    # --- Accent triggers ---

    def trigger_accent(self, accent_type: str) -> None:
        """Trigger an accent function (blind, blackout, strobe, fog, etc.)."""
        ch = self.accent_map.get(accent_type)
        if ch is None:
            log.warning("Unknown accent type: %s", accent_type)
            return
        self._trigger(ch)
        log.info("Accent '%s' triggered (ch %d)", accent_type, ch)

    async def trigger_accent_async(self, accent_type: str) -> None:
        """Async-Version von trigger_accent."""
        ch = self.accent_map.get(accent_type)
        if ch is None:
            log.warning("Unknown accent type: %s", accent_type)
            return
        await self._trigger_async(ch)
        log.info("Accent '%s' triggered (ch %d)", accent_type, ch)

    def tap_tempo(self) -> None:
        """Send a tap tempo pulse."""
        ch = self.accent_map.get("tap_tempo", 20)
        self._trigger(ch)

    async def tap_tempo_async(self) -> None:
        """Async-Version von tap_tempo."""
        ch = self.accent_map.get("tap_tempo", 20)
        await self._trigger_async(ch)
