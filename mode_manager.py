"""
Mode-Manager für die verschiedenen Betriebsmodi
"""
import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class OperationMode(Enum):
    """Betriebsmodi der Anwendung"""
    MAINTENANCE = "wartung"  # Wartung: Pflege der Referenzdaten, Testen
    PROBE = "probe"          # Probe: Ad-hoc Songerkennung, Datenerfassung
    SHOW = "show"            # Show: Robuster Live-Modus mit Setlist


class ModeManager:
    """Verwaltet den aktuellen Betriebsmodus"""
    
    def __init__(self):
        self.current_mode: Optional[OperationMode] = None
        self.logger = logging.getLogger(__name__)
    
    def set_mode(self, mode: OperationMode):
        """Setzt den Betriebsmodus"""
        if self.current_mode == mode:
            return
        
        old_mode = self.current_mode
        self.current_mode = mode
        
        self.logger.info(f"Modus geändert: {old_mode} -> {mode}")
    
    def get_mode(self) -> Optional[OperationMode]:
        """Gibt den aktuellen Modus zurück"""
        return self.current_mode
    
    def is_maintenance(self) -> bool:
        """Prüft ob Wartungsmodus aktiv ist"""
        return self.current_mode == OperationMode.MAINTENANCE
    
    def is_probe(self) -> bool:
        """Prüft ob Probe-Modus aktiv ist"""
        return self.current_mode == OperationMode.PROBE
    
    def is_show(self) -> bool:
        """Prüft ob Show-Modus aktiv ist"""
        return self.current_mode == OperationMode.SHOW
    
    def requires_internet(self) -> bool:
        """Prüft ob der aktuelle Modus Internet benötigt"""
        # Show-Modus muss offline funktionieren
        return self.current_mode != OperationMode.SHOW
    
    def get_mode_display_name(self) -> str:
        """Gibt den Anzeigenamen des aktuellen Modus zurück"""
        if self.current_mode == OperationMode.MAINTENANCE:
            return "Wartung"
        elif self.current_mode == OperationMode.PROBE:
            return "Probe"
        elif self.current_mode == OperationMode.SHOW:
            return "Show"
        return "Kein Modus"

