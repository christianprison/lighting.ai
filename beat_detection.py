"""
Beat-Detection basierend auf OSC Meter-Values vom XR18
Fokus auf Bassdrum, Snare und Bassgitarre
"""
import logging
from typing import Dict, List, Optional, Callable
from collections import deque
import time

from config import BEAT_DETECTION_CHANNELS

logger = logging.getLogger(__name__)


class BeatDetector:
    """Erkennt Beats aus Meter-Values spezifischer Kanäle"""
    
    def __init__(self, 
                 threshold: float = 0.3,
                 min_beat_interval: float = 0.2,  # Mindestabstand zwischen Beats (Sekunden)
                 lookback_window: float = 2.0):  # Zeitfenster für Analyse (Sekunden)
        
        self.threshold = threshold
        self.min_beat_interval = min_beat_interval
        self.lookback_window = lookback_window
        
        # Kanäle für Beat-Detection
        self.beat_channels = BEAT_DETECTION_CHANNELS
        
        # History der Meter-Values (Zeitpunkt -> Kanal -> Wert)
        self.meter_history: deque = deque(maxlen=int(lookback_window * 100))  # ~100 Samples/Sekunde
        
        # Letzter erkannt er Beat
        self.last_beat_time: float = 0.0
        
        # Callback für erkannte Beats
        self.beat_callback: Optional[Callable[[float], None]] = None
        
        # BPM-Schätzung
        self.current_bpm: Optional[float] = None
        self.beat_times: deque = deque(maxlen=20)  # Letzte 20 Beat-Zeitpunkte
    
    def set_beat_callback(self, callback: Callable[[float], None]):
        """Setzt Callback für erkannte Beats"""
        self.beat_callback = callback
    
    def update_meters(self, meter_values: Dict[int, float]):
        """
        Aktualisiert Meter-Values und analysiert auf Beats
        
        Args:
            meter_values: Dict mit Kanal-Index -> Meter-Wert
        """
        current_time = time.time()
        
        # Extrahiere Werte für Beat-Detection-Kanäle
        beat_channel_values = {}
        for channel_name, channel_idx in self.beat_channels.items():
            if channel_idx in meter_values:
                beat_channel_values[channel_name] = meter_values[channel_idx]
        
        if not beat_channel_values:
            return
        
        # Speichere in History
        self.meter_history.append({
            'time': current_time,
            'values': beat_channel_values.copy()
        })
        
        # Analysiere auf Beat
        if self._detect_beat(beat_channel_values, current_time):
            self._on_beat_detected(current_time)
    
    def _detect_beat(self, channel_values: Dict[str, float], current_time: float) -> bool:
        """
        Erkennt ob ein Beat vorliegt
        
        Args:
            channel_values: Aktuelle Werte der Beat-Kanäle
            current_time: Aktueller Zeitstempel
        
        Returns:
            True wenn Beat erkannt
        """
        # Prüfe Mindestabstand
        if current_time - self.last_beat_time < self.min_beat_interval:
            return False
        
        # Kombiniere Werte der Beat-Kanäle (gewichtet)
        # Bassdrum hat höchste Priorität
        combined_value = (
            channel_values.get('bassdrum', 0.0) * 0.5 +
            channel_values.get('snare', 0.0) * 0.3 +
            channel_values.get('bass', 0.0) * 0.2
        )
        
        # Prüfe Threshold
        if combined_value < self.threshold:
            return False
        
        # Zusätzliche Prüfung: Peak-Detection
        # Ein Beat sollte ein lokales Maximum sein
        if len(self.meter_history) < 3:
            return True  # Zu wenig History, akzeptiere trotzdem
        
        # Vergleiche mit vorherigen Werten
        recent_values = []
        for entry in list(self.meter_history)[-5:]:  # Letzte 5 Einträge
            prev_combined = (
                entry['values'].get('bassdrum', 0.0) * 0.5 +
                entry['values'].get('snare', 0.0) * 0.3 +
                entry['values'].get('bass', 0.0) * 0.2
            )
            recent_values.append(prev_combined)
        
        # Aktueller Wert sollte höher sein als die meisten vorherigen
        if recent_values and combined_value <= max(recent_values[:-1] or [0]):
            return False
        
        return True
    
    def _on_beat_detected(self, beat_time: float):
        """Wird aufgerufen wenn ein Beat erkannt wurde"""
        self.last_beat_time = beat_time
        self.beat_times.append(beat_time)
        
        # Update BPM-Schätzung
        self._update_bpm()
        
        # Informiere Callback
        if self.beat_callback:
            try:
                self.beat_callback(beat_time)
            except Exception as e:
                logger.error(f"Fehler in Beat-Callback: {e}")
        
        logger.debug(f"Beat erkannt bei {beat_time:.3f}, BPM: {self.current_bpm:.1f if self.current_bpm else 'N/A'}")
    
    def _update_bpm(self):
        """Aktualisiert die BPM-Schätzung basierend auf Beat-Zeitpunkten"""
        if len(self.beat_times) < 2:
            return
        
        # Berechne durchschnittlichen Abstand zwischen Beats
        intervals = []
        beat_list = list(self.beat_times)
        
        for i in range(1, len(beat_list)):
            interval = beat_list[i] - beat_list[i-1]
            if 0.2 < interval < 2.0:  # Realistische Beat-Intervalle (30-300 BPM)
                intervals.append(interval)
        
        if intervals:
            avg_interval = sum(intervals) / len(intervals)
            self.current_bpm = 60.0 / avg_interval
            logger.debug(f"BPM aktualisiert: {self.current_bpm:.1f}")
    
    def get_bpm(self) -> Optional[float]:
        """Gibt die aktuelle BPM-Schätzung zurück"""
        return self.current_bpm
    
    def reset(self):
        """Setzt den Beat-Detector zurück"""
        self.meter_history.clear()
        self.beat_times.clear()
        self.last_beat_time = 0.0
        self.current_bpm = None
        logger.debug("Beat-Detector zurückgesetzt")

