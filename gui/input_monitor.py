"""
Input-Monitor Widget zur Anzeige der OSC-Meter-Values vom XR18
Arrangiert nach Bandmitgliedern (v.l.n.r.: Axel, Pete, Tim, Bibo)
"""
from kivy.uix.widget import Widget
from kivy.uix.gridlayout import GridLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.clock import Clock
from typing import Dict, Optional

from database import Database
from gui.instrument_icon import InstrumentIcon


class MusicianColumn(BoxLayout):
    """Spalte für einen Musiker mit allen seinen Instrumenten"""
    
    def __init__(self, musician_name: str, instruments: list, database: Database, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.musician_name = musician_name
        self.spacing = 10
        self.padding = 10
        
        # Musiker-Name
        name_label = Label(
            text=musician_name,
            font_size='40sp',
            size_hint_y=None,
            height=60,
            bold=True
        )
        self.add_widget(name_label)
        
        # Instrument-Icons
        self.instrument_widgets: Dict[str, InstrumentIcon] = {}
        for inst_data in instruments:
            icon = InstrumentIcon(
                instrument_name=inst_data['instrument_name'],
                display_name=inst_data['display_name'],
                base_color=inst_data['color'],
                icon_path=inst_data.get('icon_path'),
                size_hint_y=None,
                height=200
            )
            
            # Container mit Label
            container = BoxLayout(orientation='vertical', spacing=4, size_hint_y=None, height=260)
            container.add_widget(icon)
            
            label = Label(
                text=inst_data['display_name'],
                size_hint_y=None,
                height=50,
                font_size='24sp',
                text_size=(None, None),
                halign='center'
            )
            container.add_widget(label)
            
            self.add_widget(container)
            self.instrument_widgets[inst_data['instrument_name']] = icon
    
    def update_meters(self, meter_values: Dict[int, float]):
        """Aktualisiert Meter-Values für alle Instrumente in dieser Spalte"""
        for inst_name, icon_widget in self.instrument_widgets.items():
            # Finde Kanal-Index für dieses Instrument
            for inst_data in self.instrument_widgets.values():
                # Wir benötigen die Mapping-Daten - diese kommen von außen
                pass


class InputMonitor(GridLayout):
    """Input-Monitor zur Anzeige aller Instrument-Meter-Values nach Musiker gruppiert"""
    
    def __init__(self, database: Database, **kwargs):
        super().__init__(**kwargs)
        self.database = database
        self.cols = 4  # 4 Spalten für die 4 Musiker (Axel, Pete, Tim, Bibo)
        self.spacing = 20
        self.padding = 20
        
        self.musician_columns: Dict[str, MusicianColumn] = {}
        self.channel_mappings: Dict[str, Dict] = {}
        self.instrument_to_channel: Dict[str, int] = {}  # Instrument -> Channel-Index
        
        # Lade Kanalzuordnungen
        self.load_channel_mappings()
        
        # Erstelle Spalten nach Musiker
        self._build_musician_columns()
        
        # Update-Timer (30 FPS)
        self.update_event = Clock.schedule_interval(self._update_display, 1.0 / 30.0)
    
    def load_channel_mappings(self):
        """Lädt die Kanalzuordnungen aus der Datenbank"""
        mappings = self.database.get_all_channel_mappings()
        self.channel_mappings = {}
        self.instrument_to_channel = {}
        for mapping in mappings:
            self.channel_mappings[mapping['instrument_name']] = mapping
            self.instrument_to_channel[mapping['instrument_name']] = mapping['channel_index']
    
    def _build_musician_columns(self):
        """Erstellt Spalten für jeden Musiker, sortiert nach Position"""
        self.clear_widgets()
        self.musician_columns.clear()
        
        # Gruppiere Instrumente nach Musiker und Position
        musicians = {}  # position -> {musician_name: [instruments]}
        all_mappings = self.database.get_all_channel_mappings()
        
        for mapping in all_mappings:
            musician = mapping.get('musician_name') or 'Unknown'
            position = mapping.get('position') or 99
            
            if position not in musicians:
                musicians[position] = {}
            if musician not in musicians[position]:
                musicians[position][musician] = []
            
            musicians[position][musician].append(mapping)
        
        # Sortiere nach Position und erstelle Spalten
        for position in sorted(musicians.keys()):
            for musician_name, instruments in musicians[position].items():
                if not musician_name or musician_name == 'None':
                    musician_name = 'Unknown'
                column = MusicianColumn(
                    musician_name=musician_name,
                    instruments=instruments,
                    database=self.database,
                    size_hint_x=1.0
                )
                self.add_widget(column)
                self.musician_columns[musician_name] = column
    
    def update_meters(self, meter_values: Dict[int, float]):
        """
        Aktualisiert die Anzeige basierend auf aktuellen Meter-Values
        
        Args:
            meter_values: Dict mit Kanal-Index -> Meter-Wert (0.0 bis 1.0)
        """
        # Update alle Instrumente in allen Spalten
        for inst_name, mapping in self.channel_mappings.items():
            channel_idx = mapping['channel_index']
            if channel_idx in meter_values:
                level = meter_values[channel_idx]
                musician = mapping.get('musician_name', 'Unknown')
                
                # Finde die richtige Spalte und das Icon
                if musician in self.musician_columns:
                    column = self.musician_columns[musician]
                    if inst_name in column.instrument_widgets:
                        column.instrument_widgets[inst_name].update_level(level)
    
    def _update_display(self, dt):
        """Periodisches Update (wird vom Timer aufgerufen)"""
        pass
    
    def refresh(self):
        """Aktualisiert die Anzeige (z.B. nach Konfigurationsänderung)"""
        self.load_channel_mappings()
        self._build_musician_columns()
    
    def on_parent(self, widget, parent):
        """Wird aufgerufen wenn Widget zum Parent hinzugefügt wird"""
        if parent is None and self.update_event:
            # Stoppe Timer wenn Widget entfernt wird
            Clock.unschedule(self.update_event)
