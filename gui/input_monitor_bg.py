"""
Input-Monitor mit Hintergrundbild und absolut positionierten Instrument-Icons
"""
from kivy.uix.widget import Widget
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.graphics import Rectangle, Color
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from pathlib import Path
from typing import Dict, Optional

from database import Database
from gui.instrument_icon import InstrumentIcon
from config import PROJECT_ROOT


class BackgroundInputMonitor(FloatLayout):
    """Input-Monitor mit Hintergrundbild und absolut positionierten Icons"""
    
    def __init__(self, database: Database, **kwargs):
        super().__init__(**kwargs)
        self.database = database
        self.instrument_widgets: Dict[str, InstrumentIcon] = {}
        self.channel_mappings: Dict[str, Dict] = {}
        self.bg_image_widget = None
        
        # Lade Kanalzuordnungen
        self.load_channel_mappings()
        
        # Erstelle UI
        self._build_ui()
        
        # Update-Timer (30 FPS)
        self.update_event = Clock.schedule_interval(self._update_display, 1.0 / 30.0)
    
    def load_channel_mappings(self):
        """Lädt die Kanalzuordnungen aus der Datenbank"""
        mappings = self.database.get_all_channel_mappings()
        self.channel_mappings = {}
        for mapping in mappings:
            self.channel_mappings[mapping['instrument_name']] = mapping
    
    def _build_ui(self):
        """Erstellt die Benutzeroberfläche mit Hintergrundbild"""
        # Hintergrundbild
        bg_path = PROJECT_ROOT / "gui" / "icons" / "Indicator.png"
        if bg_path.exists():
            self.bg_image_widget = Image(
                source=str(bg_path),
                allow_stretch=True,
                keep_ratio=True,
                size_hint=(1, 1),
                pos_hint={'x': 0, 'y': 0}
            )
            self.add_widget(self.bg_image_widget)
        
        # Instrument-Icons an konfigurierten Positionen
        self._place_instrument_icons()
    
    def _place_instrument_icons(self):
        """Platziert Instrument-Icons an den konfigurierten Positionen"""
        for inst_name, mapping in self.channel_mappings.items():
            # Hole Position aus Datenbank
            bg_x = mapping.get('bg_pos_x')
            bg_y = mapping.get('bg_pos_y')
            icon_w = mapping.get('icon_width')
            icon_h = mapping.get('icon_height')
            
            # Überspringe wenn keine Position konfiguriert
            if bg_x is None or bg_y is None:
                continue
            
            # Erstelle Icon-Widget
            icon = InstrumentIcon(
                instrument_name=inst_name,
                display_name=mapping['display_name'],
                base_color=mapping['color'],
                icon_path=mapping.get('icon_path')
            )
            
            # Position und Größe setzen (bindet auf Widget-Größe)
            def make_positioner(icon_widget, x, y, w, h):
                def update_pos_size(instance, value):
                    if instance.width > 0 and instance.height > 0:
                        # Berechne absolute Position
                        if x <= 1.0:  # Relativ (Prozent)
                            abs_x = instance.parent.width * x
                        else:  # Absolut (Pixel)
                            abs_x = x
                        
                        if y <= 1.0:  # Relativ (Prozent)
                            abs_y = instance.parent.height * (1.0 - y)  # Kivy y=0 ist unten
                        else:  # Absolut (Pixel)
                            abs_y = y
                        
                        # Berechne Größe
                        if w and w <= 1.0:  # Relativ
                            abs_w = instance.parent.width * w
                        elif w:  # Absolut
                            abs_w = w
                        else:
                            abs_w = 100
                        
                        if h and h <= 1.0:  # Relativ
                            abs_h = instance.parent.height * h
                        elif h:  # Absolut
                            abs_h = h
                        else:
                            abs_h = 100
                        
                        icon_widget.pos = (abs_x - abs_w/2, abs_y - abs_h/2)
                        icon_widget.size = (abs_w, abs_h)
                
                return update_pos_size
            
            # Initialisiere Position (sofort wenn möglich)
            def init_position():
                if self.width > 0 and self.height > 0:
                    positioner = make_positioner(icon, bg_x, bg_y, icon_w, icon_h)
                    positioner(self, self.size)
            
            # Binde auf Parent-Größe für zukünftige Updates
            positioner = make_positioner(icon, bg_x, bg_y, icon_w, icon_h)
            self.bind(size=positioner)
            
            self.add_widget(icon)
            self.instrument_widgets[inst_name] = icon
            
            # Initialisiere Position sofort
            init_position()
    
    def update_meters(self, meter_values: Dict[int, float]):
        """
        Aktualisiert die Anzeige basierend auf aktuellen Meter-Values
        
        Args:
            meter_values: Dict mit Kanal-Index -> Meter-Wert (0.0 bis 1.0)
        """
        for inst_name, mapping in self.channel_mappings.items():
            channel_idx = mapping['channel_index']
            if channel_idx in meter_values:
                level = meter_values[channel_idx]
                if inst_name in self.instrument_widgets:
                    self.instrument_widgets[inst_name].update_level(level)
    
    def _update_display(self, dt):
        """Periodisches Update"""
        pass
    
    def refresh(self):
        """Aktualisiert die Anzeige (z.B. nach Konfigurationsänderung)"""
        # Entferne alle Icons
        for widget in list(self.instrument_widgets.values()):
            self.remove_widget(widget)
        self.instrument_widgets.clear()
        
        # Lade neu und platziere
        self.load_channel_mappings()
        self._place_instrument_icons()
    
    def on_parent(self, widget, parent):
        """Wird aufgerufen wenn Widget zum Parent hinzugefügt wird"""
        if parent is None and self.update_event:
            Clock.unschedule(self.update_event)

