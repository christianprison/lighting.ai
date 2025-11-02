"""
OSC-Listener für Behringer XR18 Meter-Values
"""
import logging
import threading
from typing import Callable, Optional, Dict, List
from pythonosc import dispatcher
from pythonosc import osc_server

from config import OSC_LISTEN_PORT

logger = logging.getLogger(__name__)


class OSCListener:
    """Empfängt OSC-Nachrichten vom Behringer XR18"""
    
    def __init__(self, port: int = OSC_LISTEN_PORT):
        self.port = port
        self.dispatcher = dispatcher.Dispatcher()
        self.server = None
        self.server_thread = None
        self.running = False
        
        # Callback für Meter-Values
        self.meter_callback: Optional[Callable[[Dict[int, float]], None]] = None
        
        # Aktuelle Meter-Values (Kanal-Index -> Wert)
        self.current_meters: Dict[int, float] = {}
        
        # Setup Dispatcher für XR18 Meter-Pfade
        # XR18 sendet Meter-Values über /meters/X mit X = Kanal-Index (0-17 für XR18)
        self._setup_dispatcher()
    
    def _setup_dispatcher(self):
        """Konfiguriert den OSC-Dispatcher für XR18-Pfade"""
        # Meter-Values: /meters/X wobei X der Kanal-Index ist
        # Format: /meters/0 -> Wert für Kanal 0
        self.dispatcher.map("/meters/*", self._handle_meter_value)
        
        # Weitere XR18-Pfade können hier hinzugefügt werden
        # Beispiel: /lr/mix/fader für Fader-Werte
    
    def _handle_meter_value(self, address: str, *args):
        """Behandelt eingehende Meter-Value-Nachrichten"""
        try:
            # Adresse ist z.B. "/meters/0", extrahiere Kanal-Index
            channel_index = int(address.split('/')[-1])
            
            # XR18 sendet Meter-Values als Float (0.0 bis 1.0 oder dB)
            value = float(args[0]) if args else 0.0
            
            # Aktualisiere aktuellen Meter-Wert
            self.current_meters[channel_index] = value
            
            # Informiere Callback falls vorhanden
            if self.meter_callback:
                try:
                    self.meter_callback(self.current_meters.copy())
                except Exception as e:
                    logger.error(f"Fehler in Meter-Callback: {e}")
            
            logger.debug(f"Meter-Update: Kanal {channel_index} = {value}")
            
        except (ValueError, IndexError) as e:
            logger.warning(f"Ungültige Meter-Nachricht: {address} {args} - {e}")
    
    def set_meter_callback(self, callback: Callable[[Dict[int, float]], None]):
        """Setzt Callback-Funktion für Meter-Value-Updates"""
        self.meter_callback = callback
    
    def get_current_meters(self) -> Dict[int, float]:
        """Gibt die aktuellen Meter-Values zurück"""
        return self.current_meters.copy()
    
    def get_channel_value(self, channel_index: int) -> Optional[float]:
        """Gibt den Meter-Wert für einen spezifischen Kanal zurück"""
        return self.current_meters.get(channel_index)
    
    def start(self, listen_address: str = "0.0.0.0"):
        """Startet den OSC-Server"""
        if self.running:
            logger.warning("OSC-Listener läuft bereits")
            return
        
        try:
            self.server = osc_server.ThreadingOSCUDPServer(
                (listen_address, self.port),
                self.dispatcher
            )
            self.running = True
            
            # Starte Server in separatem Thread
            self.server_thread = threading.Thread(
                target=self.server.serve_forever,
                daemon=True
            )
            self.server_thread.start()
            
            logger.info(f"OSC-Listener gestartet auf {listen_address}:{self.port}")
            
        except Exception as e:
            logger.error(f"Fehler beim Starten des OSC-Servers: {e}")
            self.running = False
            raise
    
    def stop(self):
        """Stoppt den OSC-Server"""
        if not self.running:
            return
        
        self.running = False
        
        if self.server:
            self.server.shutdown()
            self.server = None
        
        if self.server_thread:
            self.server_thread.join(timeout=2.0)
            self.server_thread = None
        
        logger.info("OSC-Listener gestoppt")
    
    def is_running(self) -> bool:
        """Prüft ob der OSC-Listener läuft"""
        return self.running

