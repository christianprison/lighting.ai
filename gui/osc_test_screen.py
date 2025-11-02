"""
OSC-Test-Screen zum Testen des OSC-Empfangs im Proberaum
"""
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.clock import Clock
from collections import deque
from typing import Dict, List
from datetime import datetime

from database import Database
from osc_listener import OSCListener
from config import OSC_LISTEN_PORT


class OSCTestScreen(BoxLayout):
    """Test-Screen für OSC-Signal-Empfang"""
    
    def __init__(self, database: Database, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.database = database
        self.spacing = 10
        self.padding = 20
        
        # OSC-Listener (wird später gestartet)
        self.osc_listener: OSCListener = None
        
        # Aktuelle Meter-Values
        self.current_meters: Dict[int, float] = {}
        
        # Message-Log (letzte 100 Nachrichten)
        self.message_log: deque = deque(maxlen=100)
        
        # Channel-Mappings für Anzeige
        self.channel_mappings = {}
        
        # UI-Elemente
        self.status_label = None
        self.meter_grid = None
        self.log_scroll = None
        
        self._build_ui()
        
        # Starte OSC-Listener wenn Screen aktiviert wird
        self._start_osc_listener()
    
    def _build_ui(self):
        """Erstellt die Benutzeroberfläche"""
        # Header mit Status
        header = BoxLayout(orientation='horizontal', size_hint_y=None, height=80, spacing=20)
        
        self.status_label = Label(
            text='OSC-Listener: Wird gestartet...',
            font_size='36sp',
            size_hint_x=0.7,
            halign='left'
        )
        header.add_widget(self.status_label)
        
        btn_refresh = Button(
            text='Aktualisieren',
            size_hint_x=0.15,
            font_size='24sp',
            background_color=(0.2, 0.6, 0.8, 1)
        )
        btn_refresh.bind(on_press=lambda x: self._refresh_display())
        header.add_widget(btn_refresh)
        
        btn_clear_log = Button(
            text='Log löschen',
            size_hint_x=0.15,
            font_size='24sp',
            background_color=(0.6, 0.2, 0.2, 1)
        )
        btn_clear_log.bind(on_press=lambda x: self._clear_log())
        header.add_widget(btn_clear_log)
        
        self.add_widget(header)
        
        # Zwei-Spalten-Layout: Meter-Anzeige und Log
        content = BoxLayout(orientation='horizontal', spacing=20)
        
        # Linke Spalte: Meter-Values
        left_panel = BoxLayout(orientation='vertical', size_hint_x=0.5)
        
        meter_label = Label(
            text='Aktuelle Meter-Values',
            font_size='32sp',
            size_hint_y=None,
            height=60,
            bold=True
        )
        left_panel.add_widget(meter_label)
        
        # ScrollView für Meter-Grid
        meter_scroll = ScrollView()
        self.meter_grid = GridLayout(cols=3, spacing=10, size_hint_y=None)
        self.meter_grid.bind(minimum_height=self.meter_grid.setter('height'))
        meter_scroll.add_widget(self.meter_grid)
        left_panel.add_widget(meter_scroll)
        
        content.add_widget(left_panel)
        
        # Rechte Spalte: OSC-Message-Log
        right_panel = BoxLayout(orientation='vertical', size_hint_x=0.5)
        
        log_label = Label(
            text='OSC-Message-Log (letzte 100 Nachrichten)',
            font_size='32sp',
            size_hint_y=None,
            height=60,
            bold=True
        )
        right_panel.add_widget(log_label)
        
        self.log_scroll = ScrollView()
        self.log_content = BoxLayout(orientation='vertical', spacing=5, size_hint_y=None)
        self.log_content.bind(minimum_height=self.log_content.setter('height'))
        self.log_scroll.add_widget(self.log_content)
        right_panel.add_widget(self.log_scroll)
        
        content.add_widget(right_panel)
        
        self.add_widget(content)
        
        # Update-Timer (10x pro Sekunde)
        self.update_timer = Clock.schedule_interval(self._update_display, 0.1)
        
        # Lade Channel-Mappings
        self._load_channel_mappings()
        self._build_meter_display()
    
    def _load_channel_mappings(self):
        """Lädt Channel-Mappings aus Datenbank"""
        mappings = self.database.get_all_channel_mappings()
        self.channel_mappings = {}
        for mapping in mappings:
            self.channel_mappings[mapping['channel_index']] = mapping
    
    def _build_meter_display(self):
        """Baut die Meter-Anzeige auf"""
        self.meter_grid.clear_widgets()
        
        # Header
        self.meter_grid.add_widget(Label(text='Kanal', font_size='24sp', bold=True, size_hint_y=None, height=50))
        self.meter_grid.add_widget(Label(text='Instrument', font_size='24sp', bold=True, size_hint_y=None, height=50))
        self.meter_grid.add_widget(Label(text='Wert', font_size='24sp', bold=True, size_hint_y=None, height=50))
        
        # Zeilen für alle möglichen Kanäle (0-17 für XR18)
        for ch in range(18):
            # Kanal-Nummer
            ch_label = Label(
                text=f'Kanal {ch}',
                font_size='20sp',
                size_hint_y=None,
                height=50
            )
            self.meter_grid.add_widget(ch_label)
            
            # Instrument-Name
            inst_label = Label(
                text=self.channel_mappings.get(ch, {}).get('display_name', 'Nicht zugeordnet'),
                font_size='20sp',
                size_hint_y=None,
                height=50
            )
            self.meter_grid.add_widget(inst_label)
            
            # Meter-Wert
            meter_value_label = Label(
                text='0.00',
                font_size='20sp',
                size_hint_y=None,
                height=50
            )
            meter_value_label.channel_index = ch  # Für Update-Zugriff
            self.meter_grid.add_widget(meter_value_label)
    
    def _start_osc_listener(self):
        """Startet den OSC-Listener"""
        try:
            if self.osc_listener is None:
                from config import OSC_LISTEN_PORT
                self.osc_listener = OSCListener(port=OSC_LISTEN_PORT)
                self.osc_listener.set_meter_callback(self._on_meter_update)
                self.osc_listener.start()
                
                if self.osc_listener.is_running():
                    self.status_label.text = f'OSC-Listener: Läuft auf Port {OSC_LISTEN_PORT}'
                    self.status_label.color = (0, 1, 0, 1)  # Grün
                else:
                    self.status_label.text = 'OSC-Listener: Fehler beim Starten'
                    self.status_label.color = (1, 0, 0, 1)  # Rot
        except Exception as e:
            self.status_label.text = f'OSC-Listener Fehler: {str(e)}'
            self.status_label.color = (1, 0, 0, 1)
    
    def _on_meter_update(self, meter_values: Dict[int, float]):
        """Callback für Meter-Value-Updates"""
        self.current_meters.update(meter_values)
        
        # Logge Nachricht
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        for ch, val in meter_values.items():
            inst_name = self.channel_mappings.get(ch, {}).get('display_name', f'Kanal {ch}')
            self.message_log.append(f"[{timestamp}] /meters/{ch} = {val:.3f} ({inst_name})")
    
    def _update_display(self, dt):
        """Aktualisiert die Anzeige"""
        # Update Meter-Values in Grid
        for widget in self.meter_grid.children:
            if hasattr(widget, 'channel_index'):
                ch = widget.channel_index
                value = self.current_meters.get(ch, 0.0)
                widget.text = f'{value:.3f}'
                
                # Farbkodierung: Grün bei hohem Wert, Rot bei niedrigem
                if value > 0.7:
                    widget.color = (0, 1, 0, 1)  # Grün
                elif value > 0.3:
                    widget.color = (1, 1, 0, 1)  # Gelb
                elif value > 0.0:
                    widget.color = (1, 0.5, 0, 1)  # Orange
                else:
                    widget.color = (0.7, 0.7, 0.7, 1)  # Grau
        
        # Update Log-Anzeige (nur wenn neue Nachrichten)
        if len(self.message_log) > len(self.log_content.children):
            self._update_log_display()
        
        # Update Status
        if self.osc_listener and self.osc_listener.is_running():
            num_active = len([v for v in self.current_meters.values() if v > 0.01])
            self.status_label.text = f'OSC-Listener: Läuft | Aktive Kanäle: {num_active}/18'
    
    def _update_log_display(self):
        """Aktualisiert den Log-Bereich"""
        # Entferne alte Einträge (behalte nur die letzten 50 sichtbar)
        current_count = len(self.log_content.children)
        while current_count >= 50:
            self.log_content.remove_widget(self.log_content.children[0])
            current_count -= 1
        
        # Füge neue Einträge hinzu
        logged_count = len([w for w in self.log_content.children if hasattr(w, 'is_log_entry')])
        new_messages = list(self.message_log)[logged_count:]
        
        for msg in new_messages:
            log_entry = Label(
                text=msg,
                font_size='18sp',
                size_hint_y=None,
                height=40,
                text_size=(None, None),
                halign='left',
                valign='middle'
            )
            log_entry.is_log_entry = True
            log_entry.bind(texture_size=log_entry.setter('size'))
            self.log_content.add_widget(log_entry)
        
        # Scrolle nach unten
        if self.log_scroll:
            Clock.schedule_once(lambda dt: setattr(self.log_scroll, 'scroll_y', 0), 0.1)
    
    def _refresh_display(self):
        """Aktualisiert die Anzeige manuell"""
        self._load_channel_mappings()
        self._build_meter_display()
    
    def _clear_log(self):
        """Löscht den Log"""
        self.message_log.clear()
        self.log_content.clear_widgets()
    
    def on_parent(self, widget, parent):
        """Wird aufgerufen wenn Widget entfernt wird"""
        if parent is None:
            if self.update_timer:
                Clock.unschedule(self.update_timer)
            if self.osc_listener:
                self.osc_listener.stop()

