"""
Wartungsbildschirm für Pflege der Referenzdaten
"""
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout


class MaintenanceScreen(Screen):
    """Wartungsbildschirm"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "maintenance"
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
        
        # Content (Platzhalter)
        content = BoxLayout(orientation='vertical', padding=20)
        
        info_label = Label(
            text='Wartungsmodus - Referenzdaten-Verwaltung\n\n'
                 'Hier können Sie:\n'
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
        
        layout.add_widget(content)
        
        self.add_widget(layout)
    
    def _go_back(self, instance):
        """Zurück zum Hauptbildschirm"""
        self.manager.current = "main"

