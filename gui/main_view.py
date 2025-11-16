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
        self.monitor_container = None
        
        self._build_ui()
    
    def _build_ui(self):
        """Erstellt die Benutzeroberfläche"""
        # TabbedPanel für Modi (ohne permanenten Monitor oben)
        self.tabs = TabbedPanel(do_default_tab=False)
        # Tab-Schriftgröße auf 24PT setzen, fett
        self.tabs.font_size = '24sp'
        # Tab-Breite verdoppeln: Mindestbreite basierend auf Text * 2
        # Da tab_width=None automatisch ist, erhöhen wir die Tab-Höhe und nutzen padding
        self.tabs.tab_height = 60  # Höhere Tabs für 24pt Schrift
        # Tab-Minimalbreite durch Padding erhöhen (visuell breiter)
        self.tabs.tab_padding = [40, 10]  # Horizontal-Padding verdoppelt
        
        # Wartungs-Tab
        tab_maintenance = TabbedPanelItem(text='Wartung')
        tab_maintenance.font_size = '24sp'
        tab_maintenance.bold = True
        # Erstelle Maintenance-Content direkt (ohne Screen-Wrapper)
        from kivy.uix.boxlayout import BoxLayout as BL
        from kivy.uix.button import Button
        from kivy.uix.label import Label
        from gui.channel_mapping_dialog import ChannelMappingDialog
        from gui.admin_db_panel import AdminDbPanel

        maintenance_layout = BL(orientation='vertical', padding=40, spacing=20)

        # Inneres TabbedPanel innerhalb des Wartungs-Tabs
        inner_tabs = TabbedPanel(do_default_tab=False)
        inner_tabs.font_size = '24sp'
        inner_tabs.tab_width = None  # Automatische Breite basierend auf Text
        inner_tabs.tab_height = 60  # Höhere Tabs für 24pt Schrift
        inner_tabs.tab_padding = [40, 10]  # Horizontal-Padding verdoppelt

        # Tab 1: Songs (Admin-UI)
        tab_songs_inner = TabbedPanelItem(text='Songs')
        tab_songs_inner.font_size = '24sp'
        tab_songs_inner.bold = True
        admin_panel = AdminDbPanel(database=self.database)
        tab_songs_inner.add_widget(admin_panel)
        inner_tabs.add_widget(tab_songs_inner)

        # Tab 2: Licht
        tab_channels_inner = TabbedPanelItem(text='Licht')
        tab_channels_inner.font_size = '24sp'
        tab_channels_inner.bold = True
        chan_layout = BL(orientation='vertical', padding=20, spacing=20)
        btn_channel = Button(
            text='Kanalzuordnung öffnen',
            size_hint_y=None,
            height=80,
            font_size='32sp',
            background_color=(0.2, 0.6, 0.8, 1)
        )
        def open_mapping(instance):
            dialog = ChannelMappingDialog(database=self.database, on_save_callback=self._refresh_monitor)
            dialog.open()
        btn_channel.bind(on_press=open_mapping)
        chan_layout.add_widget(btn_channel)
        tab_channels_inner.add_widget(chan_layout)
        inner_tabs.add_widget(tab_channels_inner)

        maintenance_layout.add_widget(inner_tabs)
        tab_maintenance.add_widget(maintenance_layout)
        self.tabs.add_widget(tab_maintenance)
        
        # Probe-Tab
        tab_probe = TabbedPanelItem(text='Probe')
        tab_probe.font_size = '24sp'
        tab_probe.bold = True
        probe_layout = BL(orientation='vertical', padding=40)
        # Monitor in diesem Tab
        self.input_monitor_probe = BackgroundInputMonitor(database=self.database)
        probe_layout.add_widget(self.input_monitor_probe)
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
        tab_osc_test.font_size = '24sp'
        tab_osc_test.bold = True
        osc_test_layout = BL(orientation='vertical', padding=40)
        # Monitor in diesem Tab
        self.input_monitor_osc = BackgroundInputMonitor(database=self.database)
        osc_test_layout.add_widget(self.input_monitor_osc)
        osc_test_content = OSCTestScreen(database=self.database)
        osc_test_layout.add_widget(osc_test_content)
        tab_osc_test.add_widget(osc_test_layout)
        self.tabs.add_widget(tab_osc_test)
        
        # Show-Tab
        tab_show = TabbedPanelItem(text='Show')
        tab_show.font_size = '24sp'
        tab_show.bold = True
        show_layout = BL(orientation='vertical', padding=40)
        # Monitor in diesem Tab
        self.input_monitor_show = BackgroundInputMonitor(database=self.database)
        show_layout.add_widget(self.input_monitor_show)
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
        # Aktualisiere alle Monitor-Instanzen
        if hasattr(self, 'input_monitor_probe') and self.input_monitor_probe:
            self.input_monitor_probe.update_meters(meter_values)
        if hasattr(self, 'input_monitor_osc') and self.input_monitor_osc:
            self.input_monitor_osc.update_meters(meter_values)
        if hasattr(self, 'input_monitor_show') and self.input_monitor_show:
            self.input_monitor_show.update_meters(meter_values)
    
    def _refresh_monitor(self):
        """Aktualisiert den Input-Monitor (z.B. nach Konfigurationsänderung)"""
        if hasattr(self, 'input_monitor_probe') and self.input_monitor_probe:
            self.input_monitor_probe.refresh()
        if hasattr(self, 'input_monitor_osc') and self.input_monitor_osc:
            self.input_monitor_osc.refresh()
        if hasattr(self, 'input_monitor_show') and self.input_monitor_show:
            self.input_monitor_show.refresh()

