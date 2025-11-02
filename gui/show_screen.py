"""
Show-Bildschirm für Live-Auftritte
"""
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView

from gui.input_monitor import InputMonitor


class ShowScreen(Screen):
    """Show-Bildschirm"""
    
    def __init__(self, database=None, **kwargs):
        super().__init__(**kwargs)
        self.name = "show"
        self.database = database
        self.input_monitor = None
        self._build_ui()
    
    def _build_ui(self):
        """Erstellt die Benutzeroberfläche"""
        layout = BoxLayout(orientation='vertical', padding=10, spacing=10)
        
        # Header
        header = BoxLayout(orientation='horizontal', size_hint_y=None, height=50)
        title = Label(text='Show', font_size='32sp')
        header.add_widget(title)
        
        btn_back = Button(text='Zurück', size_hint_x=None, width=120)
        btn_back.bind(on_press=self._go_back)
        header.add_widget(btn_back)
        layout.add_widget(header)
        
        # Input-Monitor
        if self.database:
            scroll = ScrollView()
            self.input_monitor = InputMonitor(database=self.database)
            scroll.add_widget(self.input_monitor)
            layout.add_widget(scroll)
        else:
            content = BoxLayout(orientation='vertical', padding=20)
            info_label = Label(
                text='Show-Modus - Live-Auftritt\n\n'
                     'Input-Monitor wird geladen...',
                font_size='18sp',
                halign='left',
                valign='top'
            )
            info_label.bind(texture_size=info_label.setter('size'))
            content.add_widget(info_label)
            layout.add_widget(content)
        
        self.add_widget(layout)
    
    def update_meters(self, meter_values):
        """Aktualisiert die Meter-Values im Input-Monitor"""
        if self.input_monitor:
            self.input_monitor.update_meters(meter_values)
    
    def _go_back(self, instance):
        """Zurück zum Hauptbildschirm"""
        self.manager.current = "main"

