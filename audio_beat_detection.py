"""
Beat-Detection für Audio-Dateien
Analysiert Audio-Dateien und erkennt Beats/Viertelnoten
"""
import numpy as np
from pathlib import Path
from typing import List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False
    logger.warning("librosa nicht verfügbar, Beat-Detection für Audio-Dateien nicht möglich")


def detect_beats_from_audio(audio_file_path: Path, 
                            bpm_hint: Optional[float] = None,
                            offset_sec: float = 0.0) -> Tuple[List[float], Optional[float]]:
    """
    Erkennt Beats/Viertelnoten aus einer Audio-Datei.
    
    Args:
        audio_file_path: Pfad zur Audio-Datei
        bpm_hint: Optional: Bekannte BPM für bessere Erkennung
        offset_sec: Offset in Sekunden (Startzeit des Songs im Audio)
    
    Returns:
        Tuple von (beat_times, detected_bpm)
        beat_times: Liste von Zeitpunkten in Sekunden (relativ zum Song-Start, nicht Audio-Start)
        detected_bpm: Erkannte BPM oder None
    """
    if not LIBROSA_AVAILABLE:
        logger.error("librosa nicht verfügbar")
        return [], None
    
    if not audio_file_path.exists():
        logger.error(f"Audio-Datei nicht gefunden: {audio_file_path}")
        return [], None
    
    try:
        # Lade Audio-Datei
        y, sr = librosa.load(str(audio_file_path), sr=None)
        
        # Berechne Beat-Tracking
        # Wenn BPM bekannt, verwende es als Hinweis
        if bpm_hint and bpm_hint > 0:
            tempo, beats = librosa.beat.beat_track(
                y=y, 
                sr=sr,
                start_bpm=bpm_hint,
                std_bpm=5.0  # Erlaube kleine Abweichungen
            )
        else:
            tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
        
        # Konvertiere Beat-Frames zu Zeitpunkten
        beat_times = librosa.frames_to_time(beats, sr=sr)
        
        # Korrigiere für Offset: Subtrahiere Offset, damit Beats relativ zum Song-Start sind
        # Nur Beats nach dem Offset sind relevant
        beat_times = [bt - offset_sec for bt in beat_times if bt >= offset_sec]
        
        # Entferne negative Werte (falls Offset größer als erster Beat)
        beat_times = [bt for bt in beat_times if bt >= 0]
        
        detected_bpm = float(tempo) if tempo > 0 else None
        
        logger.info(f"Beat-Detection abgeschlossen: {len(beat_times)} Beats erkannt, BPM: {detected_bpm:.1f}")
        
        return beat_times, detected_bpm
        
    except Exception as e:
        logger.error(f"Fehler bei Beat-Detection: {e}")
        import traceback
        traceback.print_exc()
        return [], None


def get_quarter_notes_from_beats(beat_times: List[float], 
                                 bpm: Optional[float] = None) -> List[float]:
    """
    Konvertiert Beat-Zeitpunkte zu Viertelnoten.
    Wenn BPM bekannt ist, werden fehlende Viertelnoten interpoliert.
    
    Args:
        beat_times: Liste von Beat-Zeitpunkten in Sekunden
        bpm: Optional: BPM für Interpolation
    
    Returns:
        Liste von Viertelnoten-Zeitpunkten in Sekunden
    """
    if not beat_times:
        return []
    
    if bpm and bpm > 0:
        # Berechne erwartete Viertelnoten basierend auf BPM
        quarter_note_interval = 60.0 / bpm  # Sekunden pro Viertelnote
        
        # Starte mit dem ersten Beat
        quarter_notes = [beat_times[0]]
        
        # Interpoliere fehlende Viertelnoten zwischen Beats
        for i in range(1, len(beat_times)):
            prev_beat = beat_times[i-1]
            current_beat = beat_times[i]
            
            # Berechne Anzahl der Viertelnoten zwischen den Beats
            time_diff = current_beat - prev_beat
            num_quarters = round(time_diff / quarter_note_interval)
            
            # Füge interpolierte Viertelnoten hinzu
            for j in range(1, num_quarters):
                quarter_time = prev_beat + j * quarter_note_interval
                if quarter_time < current_beat:
                    quarter_notes.append(quarter_time)
            
            quarter_notes.append(current_beat)
        
        return sorted(quarter_notes)
    else:
        # Wenn kein BPM bekannt, verwende Beats direkt als Viertelnoten
        return sorted(beat_times)

