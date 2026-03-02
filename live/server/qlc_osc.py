"""OSC client for QLC+ 4 control.

QLC+ must be configured with an OSC Input universe.
The OSC path format is: /{universe}/dmx/{channel}  (0-indexed)
Values are floats 0-255.

To trigger a button (start/stop function): send 255 then 0.
"""

from __future__ import annotations

import logging
import time

from pythonosc.udp_client import SimpleUDPClient

from .config import QlcConfig
from .qlc_parser import ACCENT_FUNCTIONS

log = logging.getLogger("live.qlc_osc")

# Default channel assignments for QLC+ Virtual Console buttons.
# These must match the External Input assignments in QLC+.
# Override in config.yaml if your setup differs.
DEFAULT_CHANNEL_MAP = {
    # Song chaser CueList controls (main playback widget)
    "cuelist_play": 1,
    "cuelist_stop": 2,
    "cuelist_next": 3,
    "cuelist_prev": 4,
    # Accent triggers
    "blind": 10,
    "blackout": 11,
    "strobe": 12,
    "alarm": 13,
    "fog_on": 14,
    "fog_off": 15,
    "fog_5s": 16,
    "fog_10s": 17,
    # Tap tempo
    "tap_tempo": 20,
}


class QlcOsc:
    """OSC client for controlling QLC+ 4."""

    def __init__(self, cfg: QlcConfig, channel_map: dict[str, int] | None = None):
        self.cfg = cfg
        self.client: SimpleUDPClient | None = None
        self.universe = cfg.osc_universe
        self.channel_map = channel_map or dict(DEFAULT_CHANNEL_MAP)
        self._connected = False

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
        """Trigger a button: send 255 then 0 (QLC+ needs the 0->255 transition)."""
        self._send(channel, 255.0)
        time.sleep(0.05)
        self._send(channel, 0.0)

    # --- High-level controls ---

    def start_cuelist(self) -> None:
        """Start/resume the active CueList playback."""
        ch = self.channel_map.get("cuelist_play", 1)
        self._trigger(ch)
        log.info("CueList play triggered (ch %d)", ch)

    def stop_cuelist(self) -> None:
        """Stop the active CueList."""
        ch = self.channel_map.get("cuelist_stop", 2)
        self._trigger(ch)
        log.info("CueList stop triggered (ch %d)", ch)

    def next_step(self) -> None:
        """Advance to next step in the active CueList."""
        ch = self.channel_map.get("cuelist_next", 3)
        self._trigger(ch)
        log.info("CueList next triggered (ch %d)", ch)

    def previous_step(self) -> None:
        """Go back to previous step in the active CueList."""
        ch = self.channel_map.get("cuelist_prev", 4)
        self._trigger(ch)
        log.info("CueList prev triggered (ch %d)", ch)

    def trigger_accent(self, accent_type: str) -> None:
        """Trigger an accent function (blind, blackout, strobe, fog, etc.)."""
        ch = self.channel_map.get(accent_type)
        if ch is None:
            log.warning("Unknown accent type: %s", accent_type)
            return
        self._trigger(ch)
        log.info("Accent '%s' triggered (ch %d)", accent_type, ch)

    def tap_tempo(self) -> None:
        """Send a tap tempo pulse."""
        ch = self.channel_map.get("tap_tempo", 20)
        self._trigger(ch)

    def select_song_page(self, page: int) -> None:
        """Select a song page on the QLC+ SoloFrame (if mapped).

        The page switching is typically done via the CueList widget
        in QLC+, which auto-selects when the chaser starts.
        This is a convenience method for direct page control.
        """
        # Page selection via OSC is not directly supported in QLC+ 4
        # but we can map specific channels to page buttons
        ch = self.channel_map.get(f"page_{page}")
        if ch is not None:
            self._trigger(ch)
            log.info("Page %d selected (ch %d)", page, ch)
        else:
            log.debug("No channel mapped for page %d", page)

    def start_function(self, func_id: int) -> None:
        """Start a QLC+ function by triggering its mapped channel.

        Requires a channel mapping entry like: "func_{id}": channel_number
        """
        ch = self.channel_map.get(f"func_{func_id}")
        if ch is not None:
            self._trigger(ch)
            log.info("Function %d started (ch %d)", func_id, ch)
        else:
            log.warning("No channel mapped for function %d", func_id)

    def stop_function(self, func_id: int) -> None:
        """Stop a QLC+ function (toggle off)."""
        # In QLC+ toggle buttons, a second trigger stops the function
        self.start_function(func_id)
