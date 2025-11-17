#!/usr/bin/env python3
"""
lighting.ai - Hauptanwendung
Offline-Lichtsteuerung via Artnet basierend auf Behringer XR18 OSC-Signalen
"""
import logging
import sys
from pathlib import Path

from kivy.app import App
from kivy.config import Config

# Lokale Module
from config import LOG_DIR, LOG_LEVEL
from database import Database
from mode_manager import ModeManager, OperationMode
from osc_listener import OSCListener
from artnet_controller import ArtNetController
from beat_detection import BeatDetector
from song_recognition import SongRecognizer

# GUI-Module
from gui.main_view import MainView

# Logging konfigurieren
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "lighting.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Kivy-Konfiguration
# Fenstergröße kann auch über Umgebungsvariablen KIVY_WINDOW_WIDTH und KIVY_WINDOW_HEIGHT gesetzt werden
import os
window_width = os.environ.get('KIVY_WINDOW_WIDTH', '1920')
window_height = os.environ.get('KIVY_WINDOW_HEIGHT', '1080')
Config.set('graphics', 'width', window_width)
Config.set('graphics', 'height', window_height)
Config.set('graphics', 'resizable', '1')
Config.set('graphics', 'fullscreen', '0')  # Fenstermodus, da Vollbild nicht funktioniert


class LightingApp(App):
    """Hauptanwendung"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Stelle sicher, dass Fenstergröße gesetzt ist
        from kivy.config import Config
        Config.set('graphics', 'width', '1920')
        Config.set('graphics', 'height', '1080')
        
        # Core-Komponenten
        self.database = Database()
        self.mode_manager = ModeManager()
        
        # Hardware-Komponenten
        self.osc_listener: OSCListener = None
        self.artnet_controller: ArtNetController = None
        
        # Analyse-Komponenten
        self.beat_detector: BeatDetector = None
        self.song_recognizer: SongRecognizer = None
        
        # GUI
        self.main_view = None
    
    def build(self):
        """Erstellt die Hauptanwendung"""
        # Stelle sicher, dass Fenstergröße gesetzt ist
        from kivy.config import Config
        Config.set('graphics', 'width', '1920')
        Config.set('graphics', 'height', '1080')
        
        logger.info("Starte lighting.ai")
        
        # Erstelle MainView (oben Input-Monitor, unten Tabs)
        self.main_view = MainView(database=self.database)
        
        # Initialisiere Komponenten (noch nicht aktiv)
        self._initialize_components()
        
        return self.main_view
    
    def on_start(self):
        """Wird aufgerufen nach dem Start der App - hier setzen wir die Fenstergröße"""
        from kivy.core.window import Window
        # Setze Fenstergröße direkt über Window-API
        Window.size = (1920, 1080)
        logger.info(f"Fenstergröße gesetzt auf: {Window.size}")
    
    def _initialize_components(self):
        """Initialisiert Hardware- und Analyse-Komponenten (lazy loading)"""
        # Komponenten werden erst gestartet wenn nötig
        logger.info("Komponenten initialisiert (bereit für Aktivierung)")
    
    def switch_to_mode_screen(self, mode: OperationMode):
        """Wechselt zum Tab für den ausgewählten Modus"""
        if not self.main_view or not hasattr(self.main_view, 'tabs'):
            return
        
        if mode == OperationMode.MAINTENANCE:
            self.main_view.tabs.switch_to(self.main_view.tabs.tab_list[0])
            self._start_maintenance_mode()
        elif mode == OperationMode.PROBE:
            self.main_view.tabs.switch_to(self.main_view.tabs.tab_list[1])
            self._start_probe_mode()
        elif mode == OperationMode.SHOW:
            self.main_view.tabs.switch_to(self.main_view.tabs.tab_list[2])
            self._start_show_mode()
    
    def _start_maintenance_mode(self):
        """Startet Wartungsmodus"""
        logger.info("Wartungsmodus gestartet")
        # Wartungsmodus benötigt keine Hardware-Anbindung
    
    def _start_probe_mode(self):
        """Startet Probe-Modus"""
        logger.info("Probe-Modus gestartet")
        self._start_hardware()
        self._start_analysis()
    
    def _start_show_mode(self):
        """Startet Show-Modus"""
        logger.info("Show-Modus gestartet")
        self._start_hardware()
        self._start_analysis()
    
    def _start_hardware(self):
        """Startet Hardware-Komponenten (OSC, Artnet)"""
        if self.osc_listener is None:
            try:
                self.osc_listener = OSCListener()
                self.osc_listener.set_meter_callback(self._on_meter_update)
                self.osc_listener.start()
                logger.info("OSC-Listener gestartet")
            except Exception as e:
                logger.error(f"Fehler beim Starten des OSC-Listeners: {e}")
        
        if self.artnet_controller is None:
            try:
                self.artnet_controller = ArtNetController()
                self.artnet_controller.start()
                logger.info("Artnet-Controller gestartet")
            except Exception as e:
                logger.error(f"Fehler beim Starten des Artnet-Controllers: {e}")
    
    def _start_analysis(self):
        """Startet Analyse-Komponenten (Beat Detection, Song Recognition)"""
        if self.beat_detector is None:
            self.beat_detector = BeatDetector()
            self.beat_detector.set_beat_callback(self._on_beat_detected)
            logger.info("Beat-Detector initialisiert")
        
        if self.song_recognizer is None:
            self.song_recognizer = SongRecognizer(self.database)
            self.song_recognizer.set_recognition_callback(self._on_song_recognized)
            logger.info("Song-Recognizer initialisiert")
    
    def _on_meter_update(self, meter_values: dict):
        """Callback für Meter-Value-Updates vom XR18"""
        # Update Beat-Detector
        if self.beat_detector:
            self.beat_detector.update_meters(meter_values)
        
        # Update Song-Recognizer
        if self.song_recognizer:
            self.song_recognizer.update_meters(meter_values)
        
        # Update Input-Monitor (ist permanent sichtbar)
        if self.main_view:
            self.main_view.update_meters(meter_values)
    
    def _on_beat_detected(self, beat_time: float):
        """Callback für erkannte Beats"""
        logger.debug(f"Beat erkannt bei {beat_time}")
        # Kann für visuelles Feedback oder Lichtsteuerung verwendet werden
    
    def _on_song_recognized(self, song_id: int, segment_index: int):
        """Callback für erkannte Songs/Segmente"""
        logger.info(f"Song erkannt: ID {song_id}, Segment {segment_index}")
        
        # Lade Licht-Programm für dieses Segment
        if self.artnet_controller and self.artnet_controller.is_running():
            light_program = self.database.get_light_program(song_id, segment_index)
            if light_program:
                self.artnet_controller.set_all_universes(light_program)
                logger.debug(f"Licht-Programm für Song {song_id}, Segment {segment_index} geladen")
    
    def on_stop(self):
        """Wird aufgerufen wenn die App beendet wird"""
        logger.info("Beende lighting.ai")
        
        # Stoppe Hardware-Komponenten
        if self.osc_listener:
            self.osc_listener.stop()
        
        if self.artnet_controller:
            self.artnet_controller.stop()
        
        # Schließe Datenbank
        if self.database:
            self.database.close()
        
        logger.info("Anwendung beendet")


def main():
    """Hauptfunktion"""
    app = LightingApp()
    app.run()


if __name__ == "__main__":
    main()

