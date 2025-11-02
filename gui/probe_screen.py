"""
Probe-Bildschirm für Songerkennung und Datenerfassung
"""
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label


class ProbeScreen(Screen):
    """Probe-Bildschirm"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "probe"
        self._build_ui()
    
    def _build_ui(self):
        """Erstellt die Benutzeroberfläche"""
        layout = BoxLayout(orientation='vertical', padding=20, spacing=10)
        
        # Header
        header = BoxLayout(orientation='horizontal', size_hint_y=None, height=50)
        title = Label(text='Probe', font_size='32sp')
        header.add_widget(title)
        
        btn_back = Button(text='Zurück', size_hint_x=None, width=120)
        btn_back.bind(on_press=self._go_back)
        header.add_widget(btn_back)
        layout.add_widget(header)
        
        # Content (Platzhalter)
        content = BoxLayout(orientation='vertical', padding=20)
        
        info_label = Label(
            text='Probe-Modus - Songerkennung\n\n'
                 'Hier können Sie:\n'
                 '- Live-Songs erkennen\n'
                 '- Referenzdaten aufzeichnen\n'
                 '- Beat-Detection testen\n'
                 '- Song-Teile markieren',
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

