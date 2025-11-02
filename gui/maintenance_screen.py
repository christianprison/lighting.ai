"""
Wartungsbildschirm für Pflege der Referenzdaten
"""
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout

from gui.channel_mapping_dialog import ChannelMappingDialog


class MaintenanceScreen(Screen):
    """Wartungsbildschirm"""
    
    def __init__(self, database=None, **kwargs):
        super().__init__(**kwargs)
        self.name = "maintenance"
        self.database = database
        self._build_ui()
    
    def _build_ui(self):
        """Erstellt die Benutzeroberfläche"""
        layout = BoxLayout(orientation='vertical', padding=20, spacing=10)
        
        # Header
        header = BoxLayout(orientation='horizontal', size_hint_y=None, height=50)
        title = Label(text='Wartung', font_size='32sp')
        header.add_widget(title)
        
        btn_back = Button(text='Zurück', size_hint_x=None, width=120)
        btn_back.bind(on_press=self._go_back)
        header.add_widget(btn_back)
        layout.add_widget(header)
        
        # Buttons für verschiedene Funktionen
        btn_layout = BoxLayout(orientation='vertical', spacing=10, padding=20)
        
        btn_channel_mapping = Button(
            text='Kanalzuordnung konfigurieren',
            size_hint_y=None,
            height=60,
            font_size='20sp',
            background_color=(0.2, 0.6, 0.8, 1)
        )
        btn_channel_mapping.bind(on_press=self._open_channel_mapping)
        btn_layout.add_widget(btn_channel_mapping)
        
        # Content (Platzhalter für weitere Funktionen)
        content = BoxLayout(orientation='vertical', padding=20)
        
        info_label = Label(
            text='Wartungsmodus - Referenzdaten-Verwaltung\n\n'
                 'Hier können Sie:\n'
                 '- Kanalzuordnungen konfigurieren\n'
                 '- Songs verwalten\n'
                 '- Referenzdaten erfassen\n'
                 '- Licht-Programme erstellen\n'
                 '- Setlists zusammenstellen',
            font_size='18sp',
            halign='left',
            valign='top'
        )
        info_label.bind(texture_size=info_label.setter('size'))
        content.add_widget(info_label)
        
        btn_layout.add_widget(content)
        layout.add_widget(btn_layout)
        
        self.add_widget(layout)
    
    def _open_channel_mapping(self, instance):
        """Öffnet den Dialog zur Kanalzuordnung"""
        if not self.database:
            return
        
        def on_save():
            # Aktualisiere Input-Monitor falls vorhanden
            app = self.manager.parent if hasattr(self.manager, 'parent') else None
            if app and hasattr(app, 'input_monitor'):
                app.input_monitor.refresh()
        
        dialog = ChannelMappingDialog(
            database=self.database,
            on_save_callback=on_save
        )
        dialog.open()
    
    def _go_back(self, instance):
        """Zurück zum Hauptbildschirm"""
        self.manager.current = "main"

