"""
Beat-Detection für Audio-Dateien
Analysiert Audio-Dateien und erkennt Beats/Viertelnoten
"""
import numpy as np
from pathlib import Path
from typing import List, Optional, Tuple
import logging

# Workaround für NumPy 2.x Kompatibilität mit madmom
# NumPy 2.x hat np.int entfernt, aber madmom verwendet es noch
if not hasattr(np, 'int'):
    np.int = int  # type: ignore
if not hasattr(np, 'float'):
    np.float = float  # type: ignore
if not hasattr(np, 'complex'):
    np.complex = complex  # type: ignore

logger = logging.getLogger(__name__)
# Stelle sicher, dass Logger auch in Datei schreibt
from config import LOG_DIR
log_file = LOG_DIR / "beat_detection.log"

# WICHTIG: Prüfe ob bereits ein Handler existiert (wird in admin_db_panel.py erstellt)
# Wenn ja, verwende diesen, ansonsten erstelle einen neuen
if not logger.handlers:
    # Lösche alte Logdatei nur wenn wir den Handler hier erstellen
    # (wird sonst in admin_db_panel.py gemacht)
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

try:
    from madmom.features.beats import RNNBeatProcessor, DBNBeatTrackingProcessor
    import soundfile as sf
    MADMOM_AVAILABLE = True
except ImportError as e:
    MADMOM_AVAILABLE = False
    logger.warning(f"madmom nicht verfügbar, Beat-Detection für Audio-Dateien nicht möglich: {e}")


def detect_beats_from_audio(audio_file_path: Path, 
                            bpm_hint: Optional[float] = None,
                            offset_sec: float = 0.0) -> Tuple[List[float], Optional[float], Optional[float]]:
    """
    Erkennt Beats/Viertelnoten aus einer Audio-Datei mit madmom.
    
    Args:
        audio_file_path: Pfad zur Audio-Datei
        bpm_hint: Optional: Bekannte BPM für bessere Erkennung
        offset_sec: Offset in Sekunden (Startzeit des Songs im Audio)
    
    Returns:
        Tuple von (beat_times, detected_bpm, audio_duration)
        beat_times: Liste von Zeitpunkten in Sekunden (relativ zum Song-Start, nicht Audio-Start)
        detected_bpm: Erkannte BPM oder None
        audio_duration: Dauer der Audio-Datei in Sekunden oder None
    """
    if not MADMOM_AVAILABLE:
        logger.error("madmom nicht verfügbar")
        return [], None, None
    
    if not audio_file_path.exists():
        logger.error(f"Audio-Datei nicht gefunden: {audio_file_path}")
        return [], None, None
    
    try:
        logger.info(f"Lade Audio-Datei: {audio_file_path}")
        
        # Bestimme Audio-Dauer mit soundfile
        try:
            with sf.SoundFile(str(audio_file_path)) as f:
                if f.samplerate is None or f.samplerate <= 0:
                    logger.warning(f"Ungültige Sample-Rate: {f.samplerate}")
                    audio_duration = None
                else:
                    audio_duration = len(f) / f.samplerate
                    logger.info(f"Audio-Dauer bestimmt: {audio_duration:.2f}s, Sample-Rate={f.samplerate}Hz")
        except Exception as e:
            logger.warning(f"Konnte Audio-Dauer nicht bestimmen: {e}")
            audio_duration = None
        
        # Initialisiere Beat-Processor
        logger.info("Initialisiere madmom Beat-Processor...")
        beat_processor = RNNBeatProcessor()
        
        # Bestimme BPM-Bereich für DBN-Processor
        min_bpm = 50.0
        max_bpm = 200.0
        if bpm_hint is not None and bpm_hint > 0:
            # Verwende BPM-Hint mit ±20% Toleranz
            min_bpm = max(50.0, bpm_hint * 0.8)
            max_bpm = min(200.0, bpm_hint * 1.2)
            logger.info(f"Verwende BPM-Hint: {bpm_hint:.1f} (Bereich: {min_bpm:.1f}-{max_bpm:.1f})")
        
        # Stelle sicher, dass min_bpm und max_bpm gültige Werte sind
        if min_bpm is None or min_bpm <= 0:
            min_bpm = 50.0
        if max_bpm is None or max_bpm <= 0:
            max_bpm = 200.0
        if min_bpm >= max_bpm:
            min_bpm = 50.0
            max_bpm = 200.0
        
        # Stelle sicher, dass min_bpm und max_bpm Float-Werte sind
        # RNNBeatProcessor verwendet standardmäßig fps=100, daher müssen wir das auch für DBNBeatTrackingProcessor setzen
        try:
            min_bpm_float = float(min_bpm)
            max_bpm_float = float(max_bpm)
            fps = 100.0  # Standard fps für RNNBeatProcessor
            logger.info(f"Initialisiere DBN-Processor mit min_bpm={min_bpm_float:.1f}, max_bpm={max_bpm_float:.1f}, fps={fps:.1f}")
            dbn_processor = DBNBeatTrackingProcessor(min_bpm=min_bpm_float, max_bpm=max_bpm_float, fps=fps)
            logger.info(f"DBN-Processor erfolgreich initialisiert")
        except Exception as e:
            logger.error(f"Fehler bei DBN-Processor-Initialisierung: {e}", exc_info=True)
            raise
        
        # Führe Beat-Detection durch
        logger.info("Starte madmom Beat-Detection (kann etwas dauern)...")
        logger.info(f"Verarbeite Datei: {audio_file_path}")
        logger.info("RNNBeatProcessor verarbeitet Audio (dies kann 30-60 Sekunden dauern)...")
        beat_activations = None
        try:
            import time
            start_time = time.time()
            
            # Versuche zuerst, die Datei direkt mit RNNBeatProcessor zu laden
            # Falls das fehlschlägt (z.B. wegen fehlendem ffmpeg), lade mit soundfile
            try:
                logger.info(f"Versuche Datei direkt zu laden: {str(audio_file_path)}")
                beat_activations = beat_processor(str(audio_file_path))
            except Exception as direct_load_error:
                logger.warning(f"Direktes Laden fehlgeschlagen ({direct_load_error}), lade mit soundfile...")
                # Lade Audio mit soundfile (funktioniert ohne ffmpeg)
                with sf.SoundFile(str(audio_file_path)) as audio_file:
                    # Lade gesamtes Audio in einen numpy-Array
                    audio_data = audio_file.read(dtype='float32')
                    sample_rate = audio_file.samplerate
                    
                    logger.info(f"Audio geladen: Shape={audio_data.shape}, Sample-Rate={sample_rate}Hz")
                    
                    # RNNBeatProcessor kann auch direkt Audio-Daten verarbeiten
                    # Wenn es mehrkanalig ist, konvertiere zu Mono
                    if len(audio_data.shape) > 1:
                        audio_data = np.mean(audio_data, axis=1)
                        logger.info(f"Konvertiert zu Mono: Shape={audio_data.shape}")
                    
                    # Verarbeite Audio mit RNNBeatProcessor
                    logger.info("Verarbeite Audio-Daten mit RNNBeatProcessor...")
                    beat_activations = beat_processor.process(audio_data, sample_rate=sample_rate)
            
            elapsed = time.time() - start_time
            logger.info(f"RNNBeatProcessor abgeschlossen in {elapsed:.1f} Sekunden")
            
            if beat_activations is None:
                logger.error("Beat-Aktivierungen sind None!")
                return [], None, audio_duration
            
            logger.info(f"Beat-Aktivierungen berechnet: Typ={type(beat_activations)}, Shape={beat_activations.shape if hasattr(beat_activations, 'shape') else 'N/A'}, Länge={len(beat_activations) if hasattr(beat_activations, '__len__') else 'N/A'}")
            
            if len(beat_activations) == 0:
                logger.warning("Keine Beat-Aktivierungen gefunden!")
                return [], None, audio_duration
        except Exception as e:
            logger.error(f"Fehler bei Beat-Aktivierungs-Berechnung: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
            return [], None, audio_duration
        
        # Führe Beat-Tracking durch
        logger.info("Starte Beat-Tracking...")
        try:
            # Prüfe ob beat_activations gültig ist
            if beat_activations is None:
                logger.error("beat_activations ist None, kann Beat-Tracking nicht durchführen!")
                return [], None, audio_duration
            
            # Prüfe ob beat_activations ein Array ist
            if not isinstance(beat_activations, np.ndarray):
                logger.error(f"beat_activations ist kein numpy-Array, sondern {type(beat_activations)}")
                return [], None, audio_duration
            
            if len(beat_activations) == 0:
                logger.warning("beat_activations ist leer!")
                return [], None, audio_duration
            
            logger.info(f"Rufe dbn_processor auf mit beat_activations Shape: {beat_activations.shape}")
            beat_times = dbn_processor(beat_activations)
            logger.info(f"Beat-Tracking abgeschlossen: Typ={type(beat_times)}, Länge={len(beat_times) if hasattr(beat_times, '__len__') else 'N/A'}")
            
            if beat_times is None or len(beat_times) == 0:
                logger.warning("Keine Beats vom DBN-Processor erhalten!")
                return [], None, audio_duration
        except Exception as e:
            logger.error(f"Fehler bei Beat-Tracking: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
            return [], None, audio_duration
        
        # beat_times ist bereits ein numpy-Array von Zeitpunkten in Sekunden
        beat_times = beat_times.tolist() if hasattr(beat_times, 'tolist') else list(beat_times)
        
        logger.info(f"Beat-Zeitpunkte (vor Offset-Korrektur): {len(beat_times)} Beats")
        if len(beat_times) > 0:
            logger.info(f"Erster Beat: {beat_times[0]:.2f}s, Letzter Beat: {beat_times[-1]:.2f}s")
        
        # Korrigiere für Offset: Subtrahiere Offset, damit Beats relativ zum Song-Start sind
        # Nur Beats nach dem Offset sind relevant
        logger.info(f"Wende Offset an: {offset_sec}s")
        beat_times_before_offset = len(beat_times)
        beat_times = [bt - offset_sec for bt in beat_times if bt >= offset_sec]
        logger.info(f"Beats nach Offset-Filterung: {len(beat_times)} (vorher: {beat_times_before_offset})")
        
        # Entferne negative Werte (falls Offset größer als erster Beat)
        beat_times = [bt for bt in beat_times if bt >= 0]
        logger.info(f"Beats nach Negativ-Filterung: {len(beat_times)}")
        
        # Berechne BPM aus den Beats
        detected_bpm = None
        if len(beat_times) > 1:
            # Berechne durchschnittliches Intervall zwischen Beats
            intervals = [beat_times[i+1] - beat_times[i] for i in range(len(beat_times)-1)]
            avg_interval = sum(intervals) / len(intervals) if intervals else None
            if avg_interval and avg_interval > 0:
                detected_bpm = 60.0 / avg_interval
                logger.info(f"BPM aus Beats berechnet: {detected_bpm:.1f} (durchschnittliches Intervall: {avg_interval:.3f}s)")
        
        if detected_bpm:
            logger.info(f"Beat-Detection abgeschlossen: {len(beat_times)} Beats erkannt, BPM: {detected_bpm:.1f}")
        else:
            logger.warning(f"Beat-Detection abgeschlossen: {len(beat_times)} Beats erkannt, BPM: None")
        
        # Gib auch die Audio-Dauer zurück
        return beat_times, detected_bpm, audio_duration
        
    except Exception as e:
        logger.error(f"Fehler bei Beat-Detection: {e}", exc_info=True)
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        traceback.print_exc()
        return [], None, None


def get_quarter_notes_from_beats(beat_times: List[float], 
                                 bpm: Optional[float] = None,
                                 audio_duration: Optional[float] = None) -> List[float]:
    """
    Konvertiert Beat-Zeitpunkte zu gleichmäßigen Viertelnoten.
    Wenn BPM bekannt ist, werden perfekt gleichmäßige Viertelnoten generiert.
    
    Args:
        beat_times: Liste von Beat-Zeitpunkten in Sekunden (nur als Referenz für Startpunkt)
        bpm: Optional: BPM für gleichmäßige Viertelnoten-Generierung
        audio_duration: Optional: Dauer der Audio-Datei in Sekunden
    
    Returns:
        Liste von gleichmäßigen Viertelnoten-Zeitpunkten in Sekunden
    """
    if not beat_times:
        return []
    
    if bpm and bpm > 0:
        # Berechne gleichmäßige Viertelnoten basierend auf BPM
        quarter_note_interval = 60.0 / bpm  # Sekunden pro Viertelnote
        
        # Verwende den ersten Beat als Startpunkt
        start_time = beat_times[0] if beat_times else 0.0
        
        # Generiere gleichmäßige Viertelnoten ab dem Startpunkt
        quarter_notes = []
        current_time = start_time
        
        # Bestimme Endzeit: verwende letzter Beat oder audio_duration
        if audio_duration and audio_duration > 0:
            end_time = audio_duration
        elif beat_times:
            end_time = beat_times[-1] + (quarter_note_interval * 4)  # 4 Viertelnoten nach letztem Beat
        else:
            end_time = start_time + 60.0  # Fallback: 1 Minute
        
        # Generiere gleichmäßige Viertelnoten
        while current_time <= end_time:
            quarter_notes.append(current_time)
            current_time += quarter_note_interval
        
        logger.info(f"Generiert {len(quarter_notes)} gleichmäßige Viertelnoten (BPM: {bpm:.1f}, Interval: {quarter_note_interval:.3f}s)")
        return quarter_notes
    else:
        # Wenn kein BPM bekannt, verwende Beats direkt als Viertelnoten
        # (aber sortiert, falls nicht bereits sortiert)
        logger.warning("Kein BPM verfügbar, verwende ungleichmäßige Beats als Viertelnoten")
        return sorted(beat_times)

