"""
Hauptansicht mit permanentem Input-Monitor oben und TabbedPanel unten
"""
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.scrollview import ScrollView

from gui.input_monitor_bg import BackgroundInputMonitor
from gui.maintenance_screen import MaintenanceScreen
from gui.probe_screen import ProbeScreen
from gui.show_screen import ShowScreen
from gui.osc_test_screen import OSCTestScreen

from database import Database


class MainView(BoxLayout):
    """Hauptansicht mit permanentem Signal-Monitor"""
    
    def __init__(self, database: Database, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.database = database
        self.input_monitor = None
        
        self._build_ui()
    
    def _build_ui(self):
        """Erstellt die Benutzeroberfläche"""
        # Oben: Permanenter Input-Monitor
        monitor_container = BoxLayout(
            orientation='vertical',
            size_hint_y=None,
            height=600  # Höhe des Monitors (verdoppelt)
        )
        
        # Verwende BackgroundInputMonitor statt GridLayout
        self.input_monitor = BackgroundInputMonitor(database=self.database)
        monitor_container.add_widget(self.input_monitor)
        
        self.add_widget(monitor_container)
        
        # Unten: TabbedPanel für Modi
        self.tabs = TabbedPanel(do_default_tab=False)
        
        # Wartungs-Tab
        tab_maintenance = TabbedPanelItem(text='Wartung')
        # Erstelle Maintenance-Content direkt (ohne Screen-Wrapper)
        from kivy.uix.boxlayout import BoxLayout as BL
        from kivy.uix.button import Button
        from kivy.uix.label import Label
        from gui.channel_mapping_dialog import ChannelMappingDialog
        
        maintenance_layout = BL(orientation='vertical', padding=40, spacing=20)
        
        btn_channel = Button(
            text='Kanalzuordnung konfigurieren',
            size_hint_y=None,
            height=120,
            font_size='40sp',
            background_color=(0.2, 0.6, 0.8, 1)
        )
        def open_mapping(instance):
            dialog = ChannelMappingDialog(database=self.database, on_save_callback=self._refresh_monitor)
            dialog.open()
        btn_channel.bind(on_press=open_mapping)
        maintenance_layout.add_widget(btn_channel)
        
        info_label = Label(
            text='Wartungsmodus - Referenzdaten-Verwaltung\n\n'
                 'Hier können Sie:\n'
                 '- Kanalzuordnungen konfigurieren\n'
                 '- Songs verwalten\n'
                 '- Referenzdaten erfassen\n'
                 '- Licht-Programme erstellen\n'
                 '- Setlists zusammenstellen',
            font_size='36sp',
            halign='left',
            valign='top'
        )
        info_label.bind(texture_size=info_label.setter('size'))
        maintenance_layout.add_widget(info_label)
        tab_maintenance.add_widget(maintenance_layout)
        self.tabs.add_widget(tab_maintenance)
        
        # Probe-Tab
        tab_probe = TabbedPanelItem(text='Probe')
        probe_layout = BL(orientation='vertical', padding=40)
        probe_label = Label(
            text='Probe-Modus - Songerkennung\n\n'
                 'Hier können Sie:\n'
                 '- Live-Songs erkennen\n'
                 '- Referenzdaten aufzeichnen\n'
                 '- Beat-Detection testen\n'
                 '- Song-Teile markieren',
            font_size='36sp',
            halign='left',
            valign='top'
        )
        probe_label.bind(texture_size=probe_label.setter('size'))
        probe_layout.add_widget(probe_label)
        tab_probe.add_widget(probe_layout)
        self.tabs.add_widget(tab_probe)
        
        # OSC-Test-Tab (für Proberaum-Tests)
        tab_osc_test = TabbedPanelItem(text='OSC-Test')
        osc_test_content = OSCTestScreen(database=self.database)
        tab_osc_test.add_widget(osc_test_content)
        self.tabs.add_widget(tab_osc_test)
        
        # Show-Tab
        tab_show = TabbedPanelItem(text='Show')
        show_layout = BL(orientation='vertical', padding=40)
        show_label = Label(
            text='Show-Modus - Live-Auftritt\n\n'
                 'Robuster Modus für:\n'
                 '- Automatische Songerkennung\n'
                 '- Lichtsteuerung nach Setlist\n'
                 '- Manuelle Akzente (Strobe, Fog, etc.)\n'
                 '- Offline-Betrieb',
            font_size='36sp',
            halign='left',
            valign='top'
        )
        show_label.bind(texture_size=show_label.setter('size'))
        show_layout.add_widget(show_label)
        tab_show.add_widget(show_layout)
        self.tabs.add_widget(tab_show)
        
        self.add_widget(self.tabs)
    
    def update_meters(self, meter_values):
        """Aktualisiert die Meter-Values im Input-Monitor"""
        if self.input_monitor:
            self.input_monitor.update_meters(meter_values)
    
    def _refresh_monitor(self):
        """Aktualisiert den Input-Monitor (z.B. nach Konfigurationsänderung)"""
        if self.input_monitor:
            self.input_monitor.refresh()

