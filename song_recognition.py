"""
Song-Erkennung basierend auf Meter-Values-Vergleich mit Referenzdaten
"""
import logging
from typing import List, Dict, Optional, Tuple
from collections import deque
import time
import numpy as np

from database import Database

logger = logging.getLogger(__name__)


class SongRecognizer:
    """Erkennt Songs durch Vergleich von Live-Meter-Values mit Referenzdaten"""
    
    def __init__(self, database: Database, 
                 window_size: float = 4.0,  # Sekunden für Vergleichs-Fenster
                 similarity_threshold: float = 0.85):  # Ähnlichkeitsschwelle (0-1)
        
        self.database = database
        self.window_size = window_size
        self.similarity_threshold = similarity_threshold
        
        # Buffer für Live-Meter-Values (Zeit -> alle Kanal-Werte)
        self.live_buffer: deque = deque(maxlen=int(window_size * 100))  # ~100 Samples/Sekunde
        
        # Aktuell erkannt er Song
        self.current_song_id: Optional[int] = None
        self.current_segment_index: Optional[int] = None
        self.last_recognition_time: float = 0.0
        
        # Callback für Song-Erkennung
        self.recognition_callback: Optional[Callable[[int, int], None]] = None
    
    def set_recognition_callback(self, callback: Callable[[int, int], None]):
        """Setzt Callback für erkannte Songs/Segmente"""
        # Callback: callback(song_id, segment_index)
        self.recognition_callback = callback
    
    def update_meters(self, meter_values: Dict[int, float]):
        """
        Aktualisiert Live-Meter-Values und führt Song-Erkennung durch
        
        Args:
            meter_values: Dict mit Kanal-Index -> Meter-Wert
        """
        current_time = time.time()
        
        # Füge zu Buffer hinzu
        self.live_buffer.append({
            'time': current_time,
            'values': meter_values.copy()
        })
        
        # Führe Erkennung durch (nicht bei jedem Sample, um Performance zu schonen)
        if current_time - self.last_recognition_time > 0.5:  # Alle 0.5 Sekunden
            self._recognize_song()
            self.last_recognition_time = current_time
    
    def _recognize_song(self):
        """Führt Song-Erkennung durch"""
        if len(self.live_buffer) < 10:  # Zu wenig Daten
            return
        
        # Konvertiere Buffer in Array-Format für Vergleich
        live_features = self._extract_features(self.live_buffer)
        
        # Lade alle Songs aus Datenbank
        songs = self.database.get_all_songs()
        
        best_match = None
        best_similarity = 0.0
        best_segment = 0
        
        # Vergleiche mit jedem Song
        for song in songs:
            song_id = song['id']
            reference_data = self.database.get_reference_data(song_id)
            
            if not reference_data:
                continue
            
            # Finde bestes Matching-Segment
            similarity, segment_idx = self._compare_with_reference(
                live_features, reference_data
            )
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = song_id
                best_segment = segment_idx
        
        # Prüfe ob Match gut genug ist
        if best_match and best_similarity >= self.similarity_threshold:
            if (self.current_song_id != best_match or 
                self.current_segment_index != best_segment):
                
                # Neuer Song oder Segment erkannt
                self.current_song_id = best_match
                self.current_segment_index = best_segment
                
                logger.info(f"Song erkannt: Song-ID {best_match}, Segment {best_segment} "
                           f"(Ähnlichkeit: {best_similarity:.2%})")
                
                if self.recognition_callback:
                    try:
                        self.recognition_callback(best_match, best_segment)
                    except Exception as e:
                        logger.error(f"Fehler in Recognition-Callback: {e}")
    
    def _extract_features(self, buffer: deque) -> np.ndarray:
        """
        Extrahiert Features aus Meter-Values-Buffer
        
        Returns:
            Feature-Vektor als numpy-Array
        """
        if not buffer:
            return np.array([])
        
        # Konvertiere zu Array: Zeit x Kanäle
        max_channels = max(len(entry['values']) for entry in buffer)
        
        # Sammle alle Kanal-Werte über Zeit
        feature_list = []
        for entry in buffer:
            # Erstelle Vektor für diesen Zeitpunkt
            values = [entry['values'].get(ch, 0.0) for ch in range(max_channels)]
            feature_list.append(values)
        
        feature_array = np.array(feature_list)
        
        # Berechne statistische Features
        # - Mittelwert pro Kanal
        # - Standardabweichung pro Kanal
        # - Maximum pro Kanal
        # - Spektral-Features (FFT)
        
        features = []
        
        # Statistische Features
        features.extend(np.mean(feature_array, axis=0).tolist())
        features.extend(np.std(feature_array, axis=0).tolist())
        features.extend(np.max(feature_array, axis=0).tolist())
        
        # FFT-Features (erste N Koeffizienten)
        if len(feature_array) > 1:
            for ch in range(min(8, max_channels)):  # Nur erste 8 Kanäle
                fft = np.abs(np.fft.fft(feature_array[:, ch]))[:10]  # Erste 10 FFT-Koeffizienten
                features.extend(fft.tolist())
        
        return np.array(features)
    
    def _compare_with_reference(self, 
                                live_features: np.ndarray,
                                reference_data: List[Dict]) -> Tuple[float, int]:
        """
        Vergleicht Live-Features mit Referenzdaten
        
        Returns:
            (Similarity-Score, Segment-Index)
        """
        if not reference_data or len(live_features) == 0:
            return 0.0, 0
        
        best_similarity = 0.0
        best_segment = 0
        
        # Konvertiere Referenzdaten zu Features
        for ref_entry in reference_data:
            meter_values = ref_entry['meter_values']
            
            # Erstelle temporären Buffer für Referenz-Segment
            # (Vereinfachung: verwende einzelne Meter-Values als Feature)
            ref_features = np.array(meter_values)
            
            # Normalisiere Feature-Vektoren
            if len(live_features) != len(ref_features):
                # Pad oder trimme auf gleiche Länge
                min_len = min(len(live_features), len(ref_features))
                live_norm = live_features[:min_len]
                ref_norm = ref_features[:min_len]
            else:
                live_norm = live_features
                ref_norm = ref_features
            
            # Berechne Cosinus-Ähnlichkeit
            similarity = self._cosine_similarity(live_norm, ref_norm)
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_segment = ref_entry['segment_index']
        
        return best_similarity, best_segment
    
    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Berechnet Cosinus-Ähnlichkeit zwischen zwei Vektoren"""
        if len(vec1) == 0 or len(vec2) == 0:
            return 0.0
        
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def get_current_song(self) -> Optional[int]:
        """Gibt die ID des aktuell erkannten Songs zurück"""
        return self.current_song_id
    
    def get_current_segment(self) -> Optional[int]:
        """Gibt den Index des aktuellen Segments zurück"""
        return self.current_segment_index
    
    def reset(self):
        """Setzt den Song-Recognizer zurück"""
        self.live_buffer.clear()
        self.current_song_id = None
        self.current_segment_index = None
        self.last_recognition_time = 0.0
        logger.debug("Song-Recognizer zurückgesetzt")

