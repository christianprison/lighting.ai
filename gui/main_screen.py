"""
Hauptbildschirm mit Modus-Auswahl
"""
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.app import App

from mode_manager import OperationMode


class MainScreen(Screen):
    """Hauptbildschirm für Modus-Auswahl"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "main"
        self._build_ui()
    
    def _build_ui(self):
        """Erstellt die Benutzeroberfläche"""
        layout = BoxLayout(
            orientation='vertical',
            padding=40,
            spacing=30
        )
        
        # Titel
        title = Label(
            text='lighting.ai',
            font_size='48sp',
            size_hint_y=None,
            height=60
        )
        layout.add_widget(title)
        
        subtitle = Label(
            text='Bitte wählen Sie einen Betriebsmodus',
            font_size='24sp',
            size_hint_y=None,
            height=40
        )
        layout.add_widget(subtitle)
        
        # Modus-Buttons
        button_layout = BoxLayout(
            orientation='vertical',
            spacing=20,
            size_hint_y=None,
            height=300
        )
        
        # Wartung-Modus
        btn_maintenance = Button(
            text='Wartung',
            font_size='32sp',
            size_hint_y=None,
            height=80,
            background_color=(0.2, 0.6, 0.8, 1)
        )
        btn_maintenance.bind(on_press=lambda x: self._select_mode(OperationMode.MAINTENANCE))
        button_layout.add_widget(btn_maintenance)
        
        # Probe-Modus
        btn_probe = Button(
            text='Probe',
            font_size='32sp',
            size_hint_y=None,
            height=80,
            background_color=(0.2, 0.8, 0.4, 1)
        )
        btn_probe.bind(on_press=lambda x: self._select_mode(OperationMode.PROBE))
        button_layout.add_widget(btn_probe)
        
        # Show-Modus
        btn_show = Button(
            text='Show',
            font_size='32sp',
            size_hint_y=None,
            height=80,
            background_color=(0.8, 0.2, 0.2, 1)
        )
        btn_show.bind(on_press=lambda x: self._select_mode(OperationMode.SHOW))
        button_layout.add_widget(btn_show)
        
        layout.add_widget(button_layout)
        
        # Info-Text
        info = Label(
            text='Show-Modus läuft offline ohne Internetverbindung',
            font_size='16sp',
            size_hint_y=None,
            height=30
        )
        layout.add_widget(info)
        
        self.add_widget(layout)
    
    def _select_mode(self, mode: OperationMode):
        """Wechselt zum ausgewählten Modus"""
        app = App.get_running_app()
        if hasattr(app, 'mode_manager'):
            app.mode_manager.set_mode(mode)
            app.switch_to_mode_screen(mode)

