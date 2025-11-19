"""
Hauptansicht mit permanentem Input-Monitor oben und TabbedPanel unten
"""
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.clock import Clock

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
        # Tab-Breite: 1/5 der Bildschirmbreite (1920px / 5 = 384px)
        self.tabs.tab_width = 384
        self.tabs.tab_height = 60  # Höhere Tabs für 24pt Schrift
        self.tabs.tab_padding = [10, 10]  # Padding
        
        # Wartungs-Tab
        tab_maintenance = TabbedPanelItem(text='Wartung')
        tab_maintenance.font_size = '24sp'
        tab_maintenance.bold = True
        # Erstelle Maintenance-Content direkt (ohne Screen-Wrapper)
        from kivy.uix.boxlayout import BoxLayout as BL
        from kivy.uix.label import Label
        from gui.admin_db_panel import AdminDbPanel

        maintenance_layout = BL(orientation='vertical', padding=40, spacing=20)

        # Inneres TabbedPanel innerhalb des Wartungs-Tabs
        inner_tabs = TabbedPanel(do_default_tab=False)
        inner_tabs.font_size = '24sp'
        inner_tabs.tab_width = None  # Automatische Breite basierend auf Text
        inner_tabs.tab_height = 60  # Höhere Tabs für 24pt Schrift
        inner_tabs.tab_padding = [80, 10]  # Horizontal-Padding verdoppelt

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
        
        # Hauptcontainer für 4 Spalten
        from kivy.uix.gridlayout import GridLayout as GL
        chan_layout = GL(cols=4, spacing=10, padding=10)
        
        import json
        from pathlib import Path
        import logging
        import re
        logger = logging.getLogger(__name__)
        
        # Funktion für natürliche Sortierung (berücksichtigt Nummern wie 01, 02, etc.)
        def natural_sort_key(name):
            if not name:
                return []
            parts = re.split(r'(\d+)', name.lower())
            result = []
            for part in parts:
                if part.isdigit():
                    result.append(int(part))
                else:
                    result.append(part)
            return result
        
        # Container 1: Fixtures
        fixtures_container = BL(orientation='vertical', spacing=5, padding=5)
        fixtures_title = Label(
            text='Fixtures',
            font_size='24sp',
            size_hint_y=None,
            height=40,
            bold=True,
            halign='left',
            text_size=(None, None)
        )
        fixtures_container.add_widget(fixtures_title)
        
        fixtures_scroll = ScrollView()
        fixtures_list = BL(orientation='vertical', spacing=5, padding=5, size_hint_y=None)
        fixtures_list.bind(minimum_height=fixtures_list.setter('height'))
        
        fixtures_json_path = Path.home() / 'Downloads' / 'fixtures_universe_output_with_channel_names.json'
        
        try:
            with open(fixtures_json_path, 'r', encoding='utf-8') as f:
                fixtures_data = json.load(f)
            
            logger.info(f'Lade {len(fixtures_data)} Fixtures aus JSON')
            
            # Sortiere Fixtures mit natürlicher Sortierung
            sorted_fixtures = sorted(fixtures_data, key=lambda x: natural_sort_key(x.get('fixture_name', '')))
            
            # Filtere Duplikate: Nur eindeutige Fixture-Namen anzeigen
            seen_names = set()
            unique_fixtures = []
            for fixture in sorted_fixtures:
                fixture_name = fixture.get('fixture_name', '')
                if fixture_name and fixture_name not in seen_names:
                    seen_names.add(fixture_name)
                    unique_fixtures.append(fixture)
            
            logger.info(f'{len(sorted_fixtures)} Fixtures geladen, {len(unique_fixtures)} eindeutige Namen')
            
            # Erstelle Label für jeden Fixture-Namen (eine Zeile pro Fixture)
            for fixture in unique_fixtures:
                fixture_name = fixture.get('fixture_name', '')
                name_label = Label(
                    text=fixture_name,
                    font_size='19.2sp',
                    size_hint_y=None,
                    height=32,
                    text_size=(None, None),
                    halign='left',
                    valign='middle'
                )
                fixtures_list.add_widget(name_label)
            
            logger.info(f'{len(unique_fixtures)} Fixtures zur Liste hinzugefügt')
                
        except FileNotFoundError:
            error_label = Label(
                text=f'Fehler: Fixtures-JSON nicht gefunden unter\n{fixtures_json_path}',
                font_size='20sp',
                color=(1, 0, 0, 1),
                size_hint_y=None,
                height=100
            )
            fixtures_list.add_widget(error_label)
        except Exception as e:
            logger.error(f'Fehler beim Laden der Fixtures: {e}', exc_info=True)
            error_label = Label(
                text=f'Fehler beim Laden der Fixtures: {str(e)}',
                font_size='20sp',
                color=(1, 0, 0, 1),
                size_hint_y=None,
                height=100
            )
            fixtures_list.add_widget(error_label)
        
        fixtures_scroll.add_widget(fixtures_list)
        fixtures_container.add_widget(fixtures_scroll)
        chan_layout.add_widget(fixtures_container)
        
        # Container 2: Narratives
        narratives_container = BL(orientation='vertical', spacing=5, padding=5)
        narratives_title = Label(
            text='Narratives',
            font_size='24sp',
            size_hint_y=None,
            height=40,
            bold=True,
            halign='left',
            text_size=(None, None)
        )
        narratives_container.add_widget(narratives_title)
        
        narratives_scroll = ScrollView()
        narratives_list = BL(orientation='vertical', spacing=5, padding=5, size_hint_y=None)
        narratives_list.bind(minimum_height=narratives_list.setter('height'))
        
        # Lade Narratives aus Datenbank
        try:
            if hasattr(self, 'database') and self.database:
                all_narratives = self.database.get_all_narratives()
                if all_narratives:
                    # Sortiere alphabetisch mit natürlicher Sortierung
                    sorted_narratives = sorted(all_narratives, key=lambda x: natural_sort_key(x.get('name', '')))
                    
                    # Erstelle Label für jede Narrative (eine Zeile pro Narrative)
                    for narrative in sorted_narratives:
                        narrative_name = narrative.get('name', '')
                        if narrative_name:
                            narrative_label = Label(
                                text=narrative_name,
                                font_size='19.2sp',
                                size_hint_y=None,
                                height=32,
                                text_size=(None, None),
                                halign='left',
                                valign='middle'
                            )
                            narratives_list.add_widget(narrative_label)
                    
                    logger.info(f'{len(sorted_narratives)} Narratives zur Liste hinzugefügt')
                else:
                    logger.info('Keine Narratives in Datenbank gefunden')
            else:
                logger.warning('Database nicht verfügbar')
        except Exception as e:
            logger.error(f'Fehler beim Laden der Narratives: {e}', exc_info=True)
            error_label = Label(
                text=f'Fehler beim Laden der Narratives: {str(e)}',
                font_size='20sp',
                color=(1, 0, 0, 1),
                size_hint_y=None,
                height=100
            )
            narratives_list.add_widget(error_label)
        
        narratives_scroll.add_widget(narratives_list)
        narratives_container.add_widget(narratives_scroll)
        chan_layout.add_widget(narratives_container)
        
        # Container 3: Moods
        moods_container = BL(orientation='vertical', spacing=5, padding=5)
        moods_title = Label(
            text='Moods',
            font_size='24sp',
            size_hint_y=None,
            height=40,
            bold=True,
            halign='left',
            text_size=(None, None)
        )
        moods_container.add_widget(moods_title)
        
        moods_scroll = ScrollView()
        moods_list = BL(orientation='vertical', spacing=5, padding=5, size_hint_y=None)
        moods_list.bind(minimum_height=moods_list.setter('height'))
        
        # Lade Moods aus Datenbank
        try:
            if hasattr(self, 'database') and self.database:
                all_moods = self.database.get_all_moods()
                if all_moods:
                    # Sortiere alphabetisch mit natürlicher Sortierung
                    sorted_moods = sorted(all_moods, key=lambda x: natural_sort_key(x.get('name', '')))
                    
                    # Erstelle Label für jeden Mood (eine Zeile pro Mood)
                    for mood in sorted_moods:
                        mood_name = mood.get('name', '')
                        if mood_name:
                            mood_label = Label(
                                text=mood_name,
                                font_size='19.2sp',
                                size_hint_y=None,
                                height=32,
                                text_size=(None, None),
                                halign='left',
                                valign='middle'
                            )
                            moods_list.add_widget(mood_label)
                    
                    logger.info(f'{len(sorted_moods)} Moods zur Liste hinzugefügt')
                else:
                    logger.info('Keine Moods in Datenbank gefunden')
            else:
                logger.warning('Database nicht verfügbar')
        except Exception as e:
            logger.error(f'Fehler beim Laden der Moods: {e}', exc_info=True)
            error_label = Label(
                text=f'Fehler beim Laden der Moods: {str(e)}',
                font_size='20sp',
                color=(1, 0, 0, 1),
                size_hint_y=None,
                height=100
            )
            moods_list.add_widget(error_label)
        
        moods_scroll.add_widget(moods_list)
        moods_container.add_widget(moods_scroll)
        chan_layout.add_widget(moods_container)
        
        # Container 4: Reserve
        reserve_container = BL(orientation='vertical', spacing=5, padding=5)
        reserve_title = Label(
            text='Reserve',
            font_size='24sp',
            size_hint_y=None,
            height=40,
            bold=True,
            halign='left',
            text_size=(None, None)
        )
        reserve_container.add_widget(reserve_title)
        
        reserve_scroll = ScrollView()
        reserve_list = BL(orientation='vertical', spacing=5, padding=5, size_hint_y=None)
        reserve_list.bind(minimum_height=reserve_list.setter('height'))
        
        placeholder_label2 = Label(
            text='(Reserve)',
            font_size='16sp',
            size_hint_y=None,
            height=32,
            halign='left',
            text_size=(None, None)
        )
        reserve_list.add_widget(placeholder_label2)
        
        reserve_scroll.add_widget(reserve_list)
        reserve_container.add_widget(reserve_scroll)
        chan_layout.add_widget(reserve_container)
        
        # Stelle sicher, dass die ScrollViews nach dem Layout-Update am oberen Rand starten
        def scroll_to_top(dt):
            fixtures_scroll.scroll_y = 1.0
            narratives_scroll.scroll_y = 1.0
            moods_scroll.scroll_y = 1.0
            reserve_scroll.scroll_y = 1.0
        
        Clock.schedule_once(scroll_to_top, 0.1)
        
        tab_channels_inner.add_widget(chan_layout)
        inner_tabs.add_widget(tab_channels_inner)
        
        # Wenn der Tab aktiviert wird, scroll nach oben
        def on_tab_state(tab, value):
            if value == 'down':  # Tab ist aktiv
                def scroll_after_layout(dt):
                    fixtures_scroll.scroll_y = 1.0
                    narratives_scroll.scroll_y = 1.0
                    moods_scroll.scroll_y = 1.0
                    reserve_scroll.scroll_y = 1.0
                Clock.schedule_once(scroll_after_layout, 0.1)
        
        tab_channels_inner.bind(state=on_tab_state)

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
    
    def set_fixture_narratives(self, fixture_name: str, narratives: str):
        """Setzt die Narratives für ein bestimmtes Fixture"""
        if hasattr(self, 'fixture_narratives_data') and fixture_name in self.fixture_narratives_data:
            self.fixture_narratives_data[fixture_name].text = narratives
    
    def set_all_fixture_narratives(self, narratives_data: dict):
        """Setzt die Narratives für alle Fixtures (narratives_data: {fixture_name: narratives_text})"""
        if hasattr(self, 'fixture_narratives_data'):
            for fixture_name, narratives_text in narratives_data.items():
                if fixture_name in self.fixture_narratives_data:
                    self.fixture_narratives_data[fixture_name].text = narratives_text or ''
    
    def _load_fixture_narratives(self):
        """Lädt Narratives-Daten aus Datenbank und zeigt sie in der entsprechenden Spalte an"""
        import logging
        import re
        
        logger = logging.getLogger(__name__)
        
        if not hasattr(self, 'fixture_narratives_data'):
            logger.warning('fixture_narratives_data noch nicht initialisiert')
            return
        
        if not hasattr(self, 'database') or not self.database:
            logger.warning('Database nicht verfügbar')
            return
        
        try:
            # Hole alle Narratives aus der Datenbank
            all_narratives = self.database.get_all_narratives()
            logger.info(f'Gefunden: {len(all_narratives)} Narratives in Datenbank')
            
            if all_narratives:
                # Funktion für natürliche Sortierung (berücksichtigt Nummern wie 01, 02, etc.)
                def natural_sort_key(name):
                    if not name:
                        return []
                    parts = re.split(r'(\d+)', name.lower())
                    result = []
                    for part in parts:
                        if part.isdigit():
                            result.append(int(part))
                        else:
                            result.append(part)
                    return result
                
                # Sortiere alphabetisch mit natürlicher Sortierung
                sorted_narratives = sorted(all_narratives, key=lambda x: natural_sort_key(x.get('name', '')))
                
                # Extrahiere nur die Namen
                narrative_names = [n['name'] for n in sorted_narratives if n.get('name')]
                narratives_text = ', '.join(narrative_names)
                
                logger.info(f'{len(narrative_names)} Narrative-Namen extrahiert: {narrative_names[:3]}...')
                
                # Zeige alle Narratives für alle Fixtures an
                for fixture_name in self.fixture_narratives_data:
                    if fixture_name in self.fixture_narratives_data:
                        self.fixture_narratives_data[fixture_name].text = narratives_text
                        logger.debug(f'Narratives für {fixture_name} gesetzt')
                
                logger.info(f'{len(sorted_narratives)} Narratives in Spalte angezeigt')
            else:
                logger.warning('Keine Narratives in Datenbank gefunden')
                
        except Exception as e:
            logger.error(f'Fehler beim Laden der Narratives aus Datenbank: {e}', exc_info=True)

