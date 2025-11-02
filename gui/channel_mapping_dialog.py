"""
Modaler Dialog zur Konfiguration der Kanalzuordnungen
"""
from kivy.uix.modalview import ModalView
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView

from database import Database


class ChannelMappingDialog(ModalView):
    """Dialog zur Bearbeitung der Kanalzuordnungen"""
    
    def __init__(self, database: Database, on_save_callback=None, **kwargs):
        super().__init__(**kwargs)
        self.database = database
        self.on_save_callback = on_save_callback
        
        self.size_hint = (0.9, 0.9)
        self.auto_dismiss = False
        
        self.mapping_widgets = {}
        self._build_ui()
    
    def _build_ui(self):
        """Erstellt die Benutzeroberfläche"""
        layout = BoxLayout(orientation='vertical', padding=40, spacing=20)
        
        # Titel
        title = Label(
            text='Kanalzuordnung konfigurieren',
            font_size='56sp',
            size_hint_y=None,
            height=100
        )
        layout.add_widget(title)
        
        # ScrollView für die Zuordnungen
        scroll = ScrollView()
        content = GridLayout(cols=4, spacing=20, size_hint_y=None)
        content.bind(minimum_height=content.setter('height'))
        
        # Header
        content.add_widget(Label(text='Instrument', font_size='32sp', size_hint_y=None, height=80))
        content.add_widget(Label(text='Anzeigename', font_size='32sp', size_hint_y=None, height=80))
        content.add_widget(Label(text='OSC-Kanal', font_size='32sp', size_hint_y=None, height=80))
        content.add_widget(Label(text='', size_hint_y=None, height=80))
        
        # Lade Zuordnungen
        mappings = self.database.get_all_channel_mappings()
        
        for mapping in mappings:
            inst_name = mapping['instrument_name']
            
            # Instrument-Name
            label_inst = Label(
                text=inst_name,
                size_hint_y=None,
                height=100,
                font_size='32sp',
                text_size=(None, None)
            )
            content.add_widget(label_inst)
            
            # Anzeigename (editierbar)
            text_display = TextInput(
                text=mapping['display_name'],
                multiline=False,
                size_hint_y=None,
                height=100,
                font_size='32sp'
            )
            self.mapping_widgets[f"{inst_name}_display"] = text_display
            content.add_widget(text_display)
            
            # Kanal-Auswahl (Spinner mit 0-17 für XR18)
            spinner_channel = Spinner(
                text=str(mapping['channel_index']),
                values=[str(i) for i in range(18)],  # XR18 hat 18 Kanäle (0-17)
                size_hint_y=None,
                height=100,
                font_size='32sp'
            )
            self.mapping_widgets[f"{inst_name}_channel"] = spinner_channel
            content.add_widget(spinner_channel)
            
            # Platzhalter
            content.add_widget(Widget(size_hint_y=None, height=100))
        
        scroll.add_widget(content)
        layout.add_widget(scroll)
        
        # Buttons
        btn_layout = BoxLayout(size_hint_y=None, height=100, spacing=20)
        
        btn_cancel = Button(text='Abbrechen', size_hint_x=0.3, font_size='40sp')
        btn_cancel.bind(on_press=lambda x: self.dismiss())
        btn_layout.add_widget(btn_cancel)
        
        btn_save = Button(text='Speichern', size_hint_x=0.7, font_size='40sp', background_color=(0.2, 0.8, 0.2, 1))
        btn_save.bind(on_press=self._save_mappings)
        btn_layout.add_widget(btn_save)
        
        layout.add_widget(btn_layout)
        
        self.add_widget(layout)
    
    def _save_mappings(self, instance):
        """Speichert die Kanalzuordnungen"""
        mappings = self.database.get_all_channel_mappings()
        
        for mapping in mappings:
            inst_name = mapping['instrument_name']
            
            # Hole neue Werte
            display_widget = self.mapping_widgets.get(f"{inst_name}_display")
            channel_widget = self.mapping_widgets.get(f"{inst_name}_channel")
            
            if display_widget and channel_widget:
                new_display = display_widget.text
                new_channel = int(channel_widget.text)
                
                # Aktualisiere in Datenbank
                self.database.update_channel_mapping(
                    instrument_name=inst_name,
                    channel_index=new_channel,
                    display_name=new_display
                )
        
        # Informiere Callback
        if self.on_save_callback:
            self.on_save_callback()
        
        self.dismiss()

