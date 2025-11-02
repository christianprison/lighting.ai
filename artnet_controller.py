"""
Artnet-Controller für DMX-Lichtsteuerung
Unterstützt mehrere Universen für Pixel-Matrizen
"""
import logging
from typing import Dict, List, Optional
from pyartnet import ArtNetNode
import asyncio

from config import ARTNET_BROADCAST_IP, ARTNET_PORT, ARTNET_UNIVERSES

logger = logging.getLogger(__name__)


class ArtNetController:
    """Verwaltet Artnet-Output für DMX-Lichtsteuerung"""
    
    def __init__(self, 
                 broadcast_ip: str = ARTNET_BROADCAST_IP,
                 port: int = ARTNET_PORT,
                 universes: int = ARTNET_UNIVERSES):
        self.broadcast_ip = broadcast_ip
        self.port = port
        self.num_universes = universes
        
        self.node: Optional[ArtNetNode] = None
        self.universe_channels: Dict[int, any] = {}  # Universe-Index -> Channel-Objekt
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.loop_thread = None
        self.running = False
    
    def _run_event_loop(self):
        """Startet asyncio Event-Loop in separatem Thread"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
    
    def start(self):
        """Initialisiert Artnet-Node und Universen"""
        if self.running:
            logger.warning("Artnet-Controller läuft bereits")
            return
        
        try:
            # Erstelle Event-Loop Thread
            import threading
            self.loop_thread = threading.Thread(target=self._run_event_loop, daemon=True)
            self.loop_thread.start()
            
            # Warte bis Loop läuft
            import time
            time.sleep(0.1)
            
            # Erstelle Artnet-Node im Event-Loop
            future = asyncio.run_coroutine_threadsafe(
                self._async_start(),
                self.loop
            )
            future.result(timeout=5.0)
            
            self.running = True
            logger.info(f"Artnet-Controller gestartet: {self.broadcast_ip}:{self.port}, {self.num_universes} Universen")
            
        except Exception as e:
            logger.error(f"Fehler beim Starten des Artnet-Controllers: {e}")
            raise
    
    async def _async_start(self):
        """Asynchroner Start des Artnet-Nodes"""
        self.node = ArtNetNode(self.broadcast_ip, self.port, max_fps=40)
        
        # Erstelle Channels für alle Universen
        for universe_idx in range(self.num_universes):
            channel = self.node.add_universe(universe_idx)
            channel.add_channel(start=1, width=512)  # 512 DMX-Kanäle pro Universe
            self.universe_channels[universe_idx] = channel
        
        await self.node.start()
    
    def set_dmx_values(self, universe: int, dmx_values: List[int], 
                      fade_time: float = 0.0):
        """
        Setzt DMX-Werte für ein Universe
        
        Args:
            universe: Universe-Index (0-basiert)
            dmx_values: Liste mit DMX-Werten (max 512)
            fade_time: Fade-Zeit in Sekunden
        """
        if not self.running or self.loop is None:
            logger.warning("Artnet-Controller nicht gestartet")
            return
        
        if universe < 0 or universe >= self.num_universes:
            logger.error(f"Ungültiges Universe: {universe} (max: {self.num_universes-1})")
            return
        
        if len(dmx_values) > 512:
            logger.warning(f"Zu viele DMX-Werte: {len(dmx_values)}, wird auf 512 gekürzt")
            dmx_values = dmx_values[:512]
        
        # Pad auf 512 Werte falls nötig
        while len(dmx_values) < 512:
            dmx_values.append(0)
        
        try:
            channel = self.universe_channels.get(universe)
            if channel:
                # Konvertiere in Bytes
                dmx_bytes = bytes(dmx_values)
                
                # Sende asynchron
                asyncio.run_coroutine_threadsafe(
                    channel.set_values(dmx_bytes, fade_time),
                    self.loop
                )
                
        except Exception as e:
            logger.error(f"Fehler beim Setzen von DMX-Werten: {e}")
    
    def set_all_universes(self, dmx_values_per_universe: Dict[int, List[int]],
                         fade_time: float = 0.0):
        """Setzt DMX-Werte für mehrere Universen gleichzeitig"""
        for universe, values in dmx_values_per_universe.items():
            self.set_dmx_values(universe, values, fade_time)
    
    def blackout(self, fade_time: float = 0.0):
        """Schaltet alle Universen auf 0 (Blackout)"""
        zero_values = [0] * 512
        for universe in range(self.num_universes):
            self.set_dmx_values(universe, zero_values, fade_time)
        logger.info("Blackout ausgeführt")
    
    def stop(self):
        """Stoppt den Artnet-Controller"""
        if not self.running:
            return
        
        self.running = False
        
        if self.loop:
            # Blackout vor dem Stoppen
            self.blackout(fade_time=0.5)
            
            # Stoppe Event-Loop
            self.loop.call_soon_threadsafe(self.loop.stop)
            
            if self.loop_thread:
                self.loop_thread.join(timeout=2.0)
            
            self.loop = None
            self.loop_thread = None
        
        self.universe_channels.clear()
        self.node = None
        
        logger.info("Artnet-Controller gestoppt")
    
    def is_running(self) -> bool:
        """Prüft ob der Controller läuft"""
        return self.running

