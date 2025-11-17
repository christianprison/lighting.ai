"""
Admin-Panel für die Wartung der SQLite-Datenbank.

Version 1: Fokus auf Song-Stammdaten (Tabelle `songs`):
- Liste aller Songs
- Hinzufügen / Bearbeiten von Name, Artist, BPM, Dauer, Notizen
"""

import logging
from typing import Optional, List, Dict
import io
import tempfile
from pathlib import Path
from config import LOG_DIR

# Logger für Beat-Detection
beat_logger = logging.getLogger('beat_detection')
beat_logger.setLevel(logging.DEBUG)
# Erstelle FileHandler für Beat-Detection-Logs
beat_log_file = LOG_DIR / "beat_detection.log"

# Lösche alte Logdatei beim App-Start (nur wenn sie existiert)
# Dies sorgt dafür, dass nur die aktuelle Session geloggt wird
if beat_log_file.exists():
    try:
        beat_log_file.unlink()
    except Exception:
        pass  # Ignoriere Fehler beim Löschen (z.B. wenn Datei gerade verwendet wird)

beat_file_handler = logging.FileHandler(beat_log_file)
beat_file_handler.setLevel(logging.DEBUG)
beat_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
beat_file_handler.setFormatter(beat_formatter)
beat_logger.addHandler(beat_file_handler)
beat_logger.propagate = False  # Verhindere doppelte Logs
beat_logger.info("=" * 80)
beat_logger.info("Neue Beat-Detection-Session gestartet")
beat_logger.info("=" * 80)

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.modalview import ModalView
from kivy.clock import Clock

from database import Database
from gui.timeline_widget import TimelineWidget
from gui.beat_indicator import BeatIndicator


class SongPartEditDialog(ModalView):
    """Dialog zum Bearbeiten eines Songteil-Feldes."""
    
    def __init__(self, field_name: str, current_value: str, part_id: int, 
                 admin_panel: "AdminDbPanel", part_dict: Dict, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.4, 0.25)
        self.field_name = field_name
        self.current_value = current_value
        self.part_id = part_id
        self.admin_panel = admin_panel
        self.part_dict = part_dict
        
        self._build_ui()
    
    def _build_ui(self):
        layout = BoxLayout(orientation='vertical', padding=15, spacing=10)
        
        # Titel
        field_labels = {
            "part_name": "Songteil-Name",
            "start_ms": "Startzeit",
            "duration_ms": "Dauer",
            "bars": "Takte"
        }
        title = Label(
            text=f"{field_labels.get(self.field_name, self.field_name)} bearbeiten",
            font_size="24sp",
            bold=True,
            size_hint_y=None,
            height=40
        )
        layout.add_widget(title)
        
        # Eingabefeld
        if self.field_name in ["start_ms", "duration_ms"]:
            # Zeit-Eingabe (mm:ss)
            input_label = Label(
                text="Format: mm:ss",
                font_size="24sp",
                size_hint_y=None,
                height=35
            )
            layout.add_widget(input_label)
            self.text_input = TextInput(
                text=self.current_value,
                font_size="24sp",
                multiline=False,
                size_hint_y=None,
                height=50,
                padding=[8, 8]
            )
        elif self.field_name == "bars":
            # Taktzahl-Eingabe (nur Zahlen)
            input_label = Label(
                text="Anzahl der Takte (Zahl)",
                font_size="24sp",
                size_hint_y=None,
                height=35
            )
            layout.add_widget(input_label)
            self.text_input = TextInput(
                text=self.current_value,
                font_size="24sp",
                multiline=False,
                size_hint_y=None,
                height=50,
                padding=[8, 8],
                input_filter='int'  # Nur Zahlen
            )
        else:
            # Text-Eingabe (ohne Label)
            self.text_input = TextInput(
                text=self.current_value,
                font_size="24sp",
                multiline=False,
                size_hint_y=None,
                height=50,
                padding=[8, 8]
            )
        
        # Enter-Taste im TextInput binden
        self.text_input.bind(on_text_validate=self._on_save)
        layout.add_widget(self.text_input)
        
        # Buttons
        button_layout = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height=50)
        
        btn_save = Button(
            text="Speichern",
            font_size="24sp",
            background_color=(0.2, 0.8, 0.2, 1.0)
        )
        btn_save.bind(on_press=self._on_save)
        button_layout.add_widget(btn_save)
        
        btn_cancel = Button(
            text="Abbrechen",
            font_size="24sp",
            background_color=(0.8, 0.2, 0.2, 1.0)
        )
        btn_cancel.bind(on_press=self._on_cancel)
        button_layout.add_widget(btn_cancel)
        
        layout.add_widget(button_layout)
        
        self.add_widget(layout)
        
        # Fokus auf Eingabefeld und Keyboard-Handler
        Clock.schedule_once(lambda dt: setattr(self.text_input, 'focus', True), 0.1)
        
        # Keyboard-Handler für Enter und ESC
        from kivy.core.window import Window
        self._keyboard = Window.request_keyboard(self._keyboard_closed, self)
        self._keyboard.bind(on_key_down=self._on_keyboard_down)
    
    def _on_save(self, instance):
        """Speichert die Änderung."""
        new_value = self.text_input.text
        self.admin_panel._save_song_part_field(self.part_id, self.field_name, new_value, self.part_dict)
        self._keyboard_closed()
        self.dismiss()
    
    def _on_cancel(self, instance):
        """Verwirft die Änderung."""
        self._keyboard_closed()
        self.dismiss()
    
    def _keyboard_closed(self):
        """Wird aufgerufen, wenn die Tastatur geschlossen wird."""
        if self._keyboard:
            self._keyboard.unbind(on_key_down=self._on_keyboard_down)
            self._keyboard.release()
            self._keyboard = None
    
    def _on_keyboard_down(self, keyboard, keycode, text, modifiers):
        """Behandelt Tastendrücke."""
        # Enter-Taste (keycode[1] ist der Tastencode)
        if keycode[1] == 'enter' or keycode[1] == 'return':
            self._on_save(None)
            return True
        # ESC-Taste
        elif keycode[1] == 'escape':
            self._on_cancel(None)
            return True
        return False


class SongFieldEditDialog(ModalView):
    """Dialog zum Bearbeiten eines Song-Feldes."""
    
    def __init__(self, field_name: str, current_value: str, song_id: int, 
                 admin_panel: "AdminDbPanel", song_dict: Dict, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.4, 0.25)
        self.field_name = field_name
        self.current_value = current_value
        self.song_id = song_id
        self.admin_panel = admin_panel
        self.song_dict = song_dict
        
        self._build_ui()
    
    def _build_ui(self):
        layout = BoxLayout(orientation='vertical', padding=15, spacing=10)
        
        # Titel
        field_labels = {
            "name": "Songtitel",
            "bpm": "BPM",
            "duration": "Dauer"
        }
        title = Label(
            text=f"{field_labels.get(self.field_name, self.field_name)} bearbeiten",
            font_size="24sp",
            bold=True,
            size_hint_y=None,
            height=40
        )
        layout.add_widget(title)
        
        # Eingabefeld
        if self.field_name == "duration":
            # Zeit-Eingabe (mm:ss)
            input_label = Label(
                text="Format: mm:ss",
                font_size="24sp",
                size_hint_y=None,
                height=35
            )
            layout.add_widget(input_label)
            self.text_input = TextInput(
                text=self.current_value,
                font_size="24sp",
                multiline=False,
                size_hint_y=None,
                height=50,
                padding=[8, 8]
            )
        elif self.field_name == "bpm":
            # BPM-Eingabe (nur Zahlen)
            input_label = Label(
                text="Beats per Minute (Zahl)",
                font_size="24sp",
                size_hint_y=None,
                height=35
            )
            layout.add_widget(input_label)
            self.text_input = TextInput(
                text=self.current_value,
                font_size="24sp",
                multiline=False,
                size_hint_y=None,
                height=50,
                padding=[8, 8],
                input_filter='int'  # Nur Zahlen
            )
        else:
            # Text-Eingabe (Songtitel)
            self.text_input = TextInput(
                text=self.current_value,
                font_size="24sp",
                multiline=False,
                size_hint_y=None,
                height=50,
                padding=[8, 8]
            )
        
        # Enter-Taste im TextInput binden
        self.text_input.bind(on_text_validate=self._on_save)
        layout.add_widget(self.text_input)
        
        # Buttons
        button_layout = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height=50)
        
        btn_save = Button(
            text="Speichern",
            font_size="24sp",
            background_color=(0.2, 0.8, 0.2, 1.0)
        )
        btn_save.bind(on_press=self._on_save)
        button_layout.add_widget(btn_save)
        
        btn_cancel = Button(
            text="Abbrechen",
            font_size="24sp",
            background_color=(0.8, 0.2, 0.2, 1.0)
        )
        btn_cancel.bind(on_press=self._on_cancel)
        button_layout.add_widget(btn_cancel)
        
        layout.add_widget(button_layout)
        
        self.add_widget(layout)
        
        # Fokus auf Eingabefeld und Keyboard-Handler
        Clock.schedule_once(lambda dt: setattr(self.text_input, 'focus', True), 0.1)
        
        # Keyboard-Handler für Enter und ESC
        from kivy.core.window import Window
        self._keyboard = Window.request_keyboard(self._keyboard_closed, self)
        self._keyboard.bind(on_key_down=self._on_keyboard_down)
    
    def _on_save(self, instance):
        """Speichert die Änderung."""
        new_value = self.text_input.text
        self.admin_panel._save_song_field(self.song_id, self.field_name, new_value, self.song_dict)
        self._keyboard_closed()
        self.dismiss()
    
    def _on_cancel(self, instance):
        """Verwirft die Änderung."""
        self._keyboard_closed()
        self.dismiss()
    
    def _keyboard_closed(self):
        """Wird aufgerufen, wenn die Tastatur geschlossen wird."""
        if self._keyboard:
            self._keyboard.unbind(on_key_down=self._on_keyboard_down)
            self._keyboard.release()
            self._keyboard = None
    
    def _on_keyboard_down(self, keyboard, keycode, text, modifiers):
        """Behandelt Tastendrücke."""
        # Enter-Taste (keycode[1] ist der Tastencode)
        if keycode[1] == 'enter' or keycode[1] == 'return':
            self._on_save(None)
            return True
        # ESC-Taste
        elif keycode[1] == 'escape':
            self._on_cancel(None)
            return True
        return False

# Audio-Wiedergabe mit pygame
def _check_pygame_available():
    """Prüft zur Laufzeit, ob pygame verfügbar ist."""
    try:
        import pygame
        # Initialisiere nur, wenn noch nicht initialisiert
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        return True
    except:
        return False

# Initiale Prüfung beim Import
PYGAME_AVAILABLE = _check_pygame_available()
if not PYGAME_AVAILABLE:
    print("Warnung: pygame nicht verfügbar, Audio-Wiedergabe nicht möglich")


class SongListItem(Button):
    """Listeneintrag für einen Song, unterstützt Links- und Rechtsklick."""

    def __init__(self, admin_panel: "AdminDbPanel", song_id: int, **kwargs):
        super().__init__(**kwargs)
        self.admin_panel = admin_panel
        self.song_id = song_id
        # Hintergrund transparent, wird bei Auswahl gesetzt
        self.background_normal = ""
        self.background_color = (0, 0, 0, 0)
        # Text linksbündig ausrichten
        self.halign = 'left'
        # Binde text_size an size, damit halign funktioniert
        self.bind(size=self._update_text_size)
        self._update_text_size()
    
    def _update_text_size(self, *args):
        """Aktualisiert text_size basierend auf der aktuellen Größe"""
        self.text_size = (self.width, None)

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        # Rechtsklick: Kontext-Dialog zum Bearbeiten
        if hasattr(touch, "button") and touch.button == "right":
            self.admin_panel.open_song_dialog(self.song_id)
            return True
        # Linksklick: Song auswählen und Songteile anzeigen
        if hasattr(touch, "button") and touch.button == "left":
            self.admin_panel.select_song(self.song_id)
            return True
        return super().on_touch_down(touch)


class SongEditDialog(ModalView):
    """Modaler Dialog zum Anlegen/Bearbeiten eines Songs."""

    def __init__(self, admin_panel: "AdminDbPanel", song: Optional[Dict] = None, **kwargs):
        super().__init__(**kwargs)
        self.admin_panel = admin_panel
        self.song = song

        self.size_hint = (0.7, 0.7)
        self.auto_dismiss = False

        root = BoxLayout(orientation="vertical", padding=20, spacing=10)

        title_text = "Neuer Song" if song is None else f"Song bearbeiten (ID {song['id']})"
        title = Label(text=title_text, font_size="36sp", size_hint_y=None, height=60)
        root.add_widget(title)

        form = GridLayout(cols=2, spacing=10, size_hint_y=0.8)

        form.add_widget(Label(text="Titel:", font_size="28sp"))
        self.txt_name = TextInput(font_size="28sp", multiline=False)
        form.add_widget(self.txt_name)

        form.add_widget(Label(text="BPM:", font_size="28sp"))
        self.txt_bpm = TextInput(font_size="28sp", multiline=False)
        form.add_widget(self.txt_bpm)

        form.add_widget(Label(text="Dauer (Sekunden):", font_size="28sp"))
        self.txt_duration = TextInput(font_size="28sp", multiline=False)
        form.add_widget(self.txt_duration)

        form.add_widget(Label(text="Notizen:", font_size="28sp"))
        self.txt_notes = TextInput(font_size="24sp", multiline=True)
        form.add_widget(self.txt_notes)

        root.add_widget(form)

        btn_bar = BoxLayout(orientation="horizontal", size_hint_y=None, height=80, spacing=20)
        btn_cancel = Button(text="Abbrechen", font_size="28sp")
        btn_cancel.bind(on_press=lambda _: self.dismiss())
        btn_bar.add_widget(btn_cancel)

        btn_save = Button(text="Speichern", font_size="28sp", background_color=(0.2, 0.8, 0.2, 1))
        btn_save.bind(on_press=lambda _: self._save())
        btn_bar.add_widget(btn_save)

        root.add_widget(btn_bar)
        self.add_widget(root)

        if song:
            self._load_song(song)

    def _load_song(self, song: Dict):
        self.txt_name.text = song.get("name") or ""
        bpm = song.get("bpm")
        self.txt_bpm.text = "" if bpm is None else str(bpm)
        duration = song.get("duration")
        self.txt_duration.text = "" if duration is None else str(duration)
        self.txt_notes.text = song.get("notes") or ""

    def _save(self):
        self.admin_panel.save_song_from_dialog(self.song, self.txt_name.text,
                                              self.txt_bpm.text, self.txt_duration.text,
                                              self.txt_notes.text)
        self.dismiss()


class AdminDbPanel(BoxLayout):
    def __init__(self, database: Database, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.spacing = 20
        self.padding = 20

        self.db = database

        self.song_list_grid: Optional[GridLayout] = None
        self.part_list_grid: Optional[GridLayout] = None
        self.songs: List[Dict] = []
        self.current_song_id: Optional[int] = None
        self.song_items: Dict[int, SongListItem] = {}
        self._part_labels: Dict[int, List[Label]] = {}  # Speichert Labels für Hervorhebung
        
        # Audio-Wiedergabe
        self.audio_playing = False
        self.audio_file_path: Optional[Path] = None
        self.temp_audio_file: Optional[Path] = None
        self.audio_start_time: Optional[float] = None  # Startzeit der Wiedergabe
        self.audio_paused_position_ms: int = 0  # Position beim Pausieren
        self.audio_offset_sec: float = 0.0  # Offset der aktuellen Audiodatei

        self._build_ui()
        self._load_songs()
        
        # Keyboard-Handler für Space-Taste (Play/Pause)
        from kivy.core.window import Window
        Window.bind(on_key_down=self._on_keyboard_down)

    def _build_ui(self):
        # Hauptlayout: Oben Tabellen (4/5), unten Zeitstrahl/Steuerung (1/5)
        main_layout = BoxLayout(orientation="vertical", spacing=10)
        
        # Obere Hälfte: Tabellen (4/5 der Höhe)
        top_container = BoxLayout(orientation="horizontal", spacing=20, size_hint_y=0.8)
        
        # Linke Seite oben: Songliste (25% Breite)
        list_container = BoxLayout(orientation="vertical", size_hint_x=0.25)

        scroll = ScrollView()
        # Spalten: Titel | BPM (ohne Löschbutton, wird ins Kontextmenü verschoben)
        self.song_list_grid = GridLayout(
            cols=2, spacing=10, size_hint_y=None
        )
        self.song_list_grid.bind(
            minimum_height=self.song_list_grid.setter("height")
        )
        scroll.add_widget(self.song_list_grid)
        list_container.add_widget(scroll)
        
        top_container.add_widget(list_container)

        # Rechte Seite oben: Songteile (75% Breite)
        part_container = BoxLayout(orientation="vertical", size_hint_x=0.75)

        part_scroll = ScrollView()
        # Spalten: Songteil | Startzeit (mm:ss) | Dauer (mm:ss) | Takte | Aktion
        self.part_list_grid = GridLayout(cols=5, spacing=10, size_hint_y=None)  # 5 statt 6 (ohne Löschbutton)
        self.part_list_grid.bind(
            minimum_height=self.part_list_grid.setter("height")
        )
        part_scroll.add_widget(self.part_list_grid)
        part_container.add_widget(part_scroll)

        top_container.add_widget(part_container)
        main_layout.add_widget(top_container)
        
        # Unteres Fünftel: Steuerung links, Zeitstrahl rechts
        bottom_container = BoxLayout(orientation="horizontal", spacing=20, size_hint_y=0.2)
        
        # Steuerungseinheit (links unten)
        controls_container = BoxLayout(
            orientation="vertical",
            padding=5,
            spacing=5,
            size_hint_x=0.2
        )
        
        pygame_available = _check_pygame_available()
        self.play_pause_button = Button(
            text="Abspielen",
            font_size="24sp",
            size_hint_y=None,
            height=40,
            background_color=(0.2, 0.8, 0.2, 1) if pygame_available else (0.5, 0.5, 0.5, 1)
        )
        self.play_pause_button.bind(on_press=self._toggle_audio_playback)
        if not pygame_available:
            self.play_pause_button.disabled = True
            self.play_pause_button.text = "Audio nicht verfügbar"
        controls_container.add_widget(self.play_pause_button)
        
        beat_container = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=100,
            spacing=2
        )
        
        beat_label = Label(
            text="beat",
            font_size="16sp",
            size_hint_y=None,
            height=20,
            halign='center'
        )
        beat_label.bind(texture_size=beat_label.setter('size'))
        beat_container.add_widget(beat_label)
        
        beat_indicator_container = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=20
        )
        self.beat_indicator = BeatIndicator(
            size_hint_x=None,
            size_hint_y=None,
            width=20,
            height=20
        )
        beat_indicator_container.add_widget(Label(size_hint_x=1.0))
        beat_indicator_container.add_widget(self.beat_indicator)
        beat_indicator_container.add_widget(Label(size_hint_x=1.0))
        beat_container.add_widget(beat_indicator_container)
        
        self.beat_status_label = Label(
            text="Status: Warte auf Audio",
            font_size="12sp",
            size_hint_y=None,
            height=20,
            halign='center'
        )
        beat_container.add_widget(self.beat_status_label)
        
        from kivy.uix.progressbar import ProgressBar
        self.beat_confidence_gauge = ProgressBar(
            max=100,
            value=0,
            size_hint_y=None,
            height=15
        )
        self.beat_confidence_label = Label(
            text="Präzision: 0%",
            font_size="12sp",
            size_hint_y=None,
            height=15,
            halign='center'
        )
        beat_container.add_widget(self.beat_confidence_gauge)
        beat_container.add_widget(self.beat_confidence_label)
        controls_container.add_widget(beat_container)
        
        offset_layout = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=45,
            spacing=15
        )
        offset_label = Label(
            text="Offset:",
            font_size="24sp",
            size_hint_x=None,
            width=50
        )
        offset_layout.add_widget(offset_label)
        
        self.offset_input = TextInput(
            text="0.000",
            font_size="24sp",
            multiline=False,
            size_hint_x=1.0,
            size_hint_y=None,
            height=45,
            padding=[5, 5],
            hint_text="Sek.Millisek (z.B. 5.250)"
        )
        self.offset_input.bind(on_text_validate=self._save_offset)
        self.offset_input.bind(focus=self._on_offset_focus_lost)
        offset_layout.add_widget(self.offset_input)
        controls_container.add_widget(offset_layout)
        
        bottom_container.add_widget(controls_container)
        
        # Zeitstrahl (rechts unten)
        timeline_container = BoxLayout(
            orientation="vertical",
            size_hint_x=0.8
        )
        
        self.timeline_scroll = ScrollView(
            do_scroll_x=True,
            do_scroll_y=False,
            size_hint=(1.0, 1.0)
        )
        
        self.timeline_widget = TimelineWidget()
        self.timeline_scroll.add_widget(self.timeline_widget)
        timeline_container.add_widget(self.timeline_scroll)
        
        bottom_container.add_widget(timeline_container)
        main_layout.add_widget(bottom_container)
        
        self.add_widget(main_layout)

    # ------------------------------------------------------------------ #
    # Datenladen / Liste
    # ------------------------------------------------------------------ #

    def _load_songs(self):
        """Lädt alle Songs aus der DB und füllt die Liste."""
        self.songs = self.db.get_all_songs()
        self._populate_song_list()

    def _populate_song_list(self):
        assert self.song_list_grid is not None
        self.song_list_grid.clear_widgets()
        self.song_items.clear()

        # Header (Titel, BPM, Aktion)
        self.song_list_grid.add_widget(
            Label(
                text="Titel",
                font_size="24sp",
                bold=True,
                size_hint_y=None,
                height=40,
                halign='left',
                text_size=(None, None),
            )
        )
        self.song_list_grid.add_widget(
            Label(
                text="BPM",
                font_size="24sp",
                bold=True,
                size_hint_y=None,
                height=40,
                size_hint_x=None,
                width=60,  # Schmaler gemacht
                halign='left',
                text_size=(60, None),
            )
        )

        for song in self.songs:
            song_id = song["id"]
            name = song["name"]
            bpm_val = song.get("bpm")
            duration_val = song.get("duration")
            
            # BPM als Ganzzahl (Integer) darstellen
            if bpm_val is None:
                bpm_text = ""
            else:
                bpm_text = str(int(round(bpm_val)))
            
            # Dauer formatieren (mm:ss)
            if duration_val is None:
                duration_text = ""
            else:
                total_sec = int(duration_val)
                minutes = total_sec // 60
                seconds = total_sec % 60
                duration_text = f"{minutes:02d}:{seconds:02d}"
            
            # Titel (editierbar per Doppelklick) - breiter gemacht für einzeilige Darstellung
            item = SongListItem(
                admin_panel=self,
                song_id=song_id,
                text=name,
                font_size="22sp",
                size_hint_y=None,
                height=40,
                size_hint_x=None,
                width=400,  # Breiter für einzeilige Darstellung
                halign='left',
                text_size=(400, None),
            )
            # Kontextmenü für rechten Mausklick hinzufügen
            item.bind(on_touch_down=self._on_song_right_click)
            self.song_list_grid.add_widget(item)
            self.song_items[song_id] = item
            
            # BPM (editierbar per Doppelklick) - schmaler gemacht
            bpm_label = Label(
                text=bpm_text,
                font_size="22sp",
                size_hint_y=None,
                height=40,
                size_hint_x=None,
                width=60,  # Schmaler gemacht
                halign='left',
                text_size=(60, None),
            )
            bpm_label._song_id = song_id
            bpm_label._field_name = "bpm"
            bpm_label._admin_panel = self
            bpm_label._song_dict = song
            bpm_label._last_click_time = 0
            bpm_label._last_click_pos = None
            
            def on_bpm_double_click(label_instance, touch):
                """Öffnet Edit-Dialog bei Doppelklick auf BPM."""
                if label_instance.collide_point(*touch.pos):
                    current_time = touch.time_start
                    if (hasattr(label_instance, '_last_click_time') and
                        label_instance._last_click_time and 
                        current_time - label_instance._last_click_time < 0.3 and
                        hasattr(label_instance, '_last_click_pos') and
                        label_instance._last_click_pos and
                        abs(touch.pos[0] - label_instance._last_click_pos[0]) < 10 and
                        abs(touch.pos[1] - label_instance._last_click_pos[1]) < 10):
                        dialog = SongFieldEditDialog(
                            field_name="bpm",
                            current_value=label_instance.text,
                            song_id=label_instance._song_id,
                            admin_panel=label_instance._admin_panel,
                            song_dict=label_instance._song_dict
                        )
                        dialog.open()
                        return True
                    label_instance._last_click_time = current_time
                    label_instance._last_click_pos = touch.pos
                return False
            
            bpm_label.bind(on_touch_down=on_bpm_double_click)
            # Kontextmenü für rechten Mausklick hinzufügen
            bpm_label.bind(on_touch_down=self._on_song_right_click)
            self.song_list_grid.add_widget(bpm_label)

        # Selektion optisch aktualisieren
        self._update_selection_highlight()

    # ------------------------------------------------------------------ #
    # Song-Auswahl und Dialog
    # ------------------------------------------------------------------ #

    def select_song(self, song_id: int):
        """Wird bei Linksklick auf einen Songtitel aufgerufen."""
        self.current_song_id = song_id
        self._update_selection_highlight()
        self._load_song_parts(song_id)
        # Stoppe laufende Wiedergabe wenn Song gewechselt wird
        self._stop_audio()
        
        # Setze Beat-Indikator zurück wenn kein Song ausgewählt
        if hasattr(self, 'beat_indicator') and self.beat_indicator:
            self.beat_indicator.beat_active = False
            self.beat_indicator._update_canvas()
            if hasattr(self.beat_indicator, 'blink_animation') and self.beat_indicator.blink_animation:
                Clock.unschedule(self.beat_indicator.blink_animation)
                self.beat_indicator.blink_animation = None

    def open_song_dialog(self, song_id: Optional[int]):
        """Wird bei Rechtsklick auf einen Songtitel aufgerufen."""
        song = self.db.get_song(song_id) if song_id is not None else None
        dialog = SongEditDialog(self, song)
        dialog.open()

    def _update_selection_highlight(self):
        """Aktualisiert die Hintergrundfarbe der Songliste basierend auf der Auswahl."""
        for sid, widget in self.song_items.items():
            if sid == self.current_song_id:
                # hellgrau markieren
                widget.background_color = (0.7, 0.7, 0.7, 1)
            else:
                # transparent
                widget.background_color = (0, 0, 0, 0)

    def save_song_from_dialog(
        self,
        song: Optional[Dict],
        name_text: str,
        bpm_text: str,
        duration_text: str,
        notes_text: str,
    ):
        name = name_text.strip()
        if not name:
            return

        bpm = None
        if bpm_text.strip():
            try:
                bpm = float(bpm_text.strip())
            except ValueError:
                bpm = None

        duration = None
        if duration_text.strip():
            try:
                duration = float(duration_text.strip())
            except ValueError:
                duration = None

        notes = notes_text.strip() or None

        if song is None:
            # Neu
            song_id = self.db.add_song(
                name=name,
                artist=None,
                duration=duration,
                bpm=bpm,
                notes=notes,
            )
            self.current_song_id = song_id
        else:
            # Update
            self.db.update_song(
                song["id"],
                name=name,
                artist=None,
                duration=duration,
                bpm=bpm,
                notes=notes,
            )
            self.current_song_id = song["id"]

        self._load_songs()
        if self.current_song_id:
            self._load_song_parts(self.current_song_id)

    # ------------------------------------------------------------------ #
    # Songteile
    # ------------------------------------------------------------------ #

    def _load_song_parts(self, song_id: int):
        """Lädt die Songteile eines Songs in die rechte Liste."""
        if not self.part_list_grid:
            return
        parts = self.db.get_song_parts(song_id)
        # nach start_segment sortieren
        parts = sorted(parts, key=lambda p: p.get("start_segment", 0))

        self.part_list_grid.clear_widgets()
        self._part_rows: List[Dict] = []
        self._part_labels: Dict[int, List[Label]] = {}  # Speichert Labels für Hervorhebung

        # Header: Songteil | Startzeit | Dauer | Takte | Abspielen | Aktion
        songteil_header = Label(
            text="Songteil",
            font_size="22sp",
            bold=True,
            size_hint_y=None,
            height=40,
            size_hint_x=None,
            width=200,  # Feste Breite für Songteil
            halign='left',
            text_size=(200, None),
        )
        self.part_list_grid.add_widget(songteil_header)
        
        # Startzeit-Überschrift (klickbar)
        startzeit_header = Label(
            text="Startzeit",
            font_size="22sp",
            bold=True,
            size_hint_y=None,
            height=40,
            size_hint_x=None,
            width=80,  # Halbe Breite
            halign='left',
            text_size=(80, None),
        )
        startzeit_header._admin_panel = self
        startzeit_header._field_name = "start_ms"
        startzeit_header.bind(on_touch_down=self._on_header_click)
        self.part_list_grid.add_widget(startzeit_header)
        
        # Dauer-Überschrift (klickbar)
        dauer_header = Label(
            text="Dauer",
            font_size="22sp",
            bold=True,
            size_hint_y=None,
            height=40,
            size_hint_x=None,
            width=80,  # Halbe Breite
            halign='left',
            text_size=(80, None),
        )
        dauer_header._admin_panel = self
        dauer_header._field_name = "duration_ms"
        dauer_header.bind(on_touch_down=self._on_header_click)
        self.part_list_grid.add_widget(dauer_header)
        
        # Takte-Überschrift (klickbar)
        takte_header = Label(
            text="Takte",
            font_size="22sp",
            bold=True,
            size_hint_y=None,
            height=40,
            size_hint_x=None,
            width=80,  # Feste Breite
            halign='left',
            text_size=(80, None),
        )
        takte_header._admin_panel = self
        takte_header._field_name = "bars"
        takte_header.bind(on_touch_down=self._on_header_click)
        self.part_list_grid.add_widget(takte_header)
        
        # Abspielen-Überschrift
        abspielen_header = Label(
            text="Abspielen",
            font_size="22sp",
            bold=True,
            size_hint_y=None,
            height=40,
            size_hint_x=None,
            width=100,  # Feste Breite
            halign='left',
            text_size=(100, None),
        )
        self.part_list_grid.add_widget(abspielen_header)
        
        # Aktion-Überschrift
        aktion_header = Label(
            text="Aktion",
            font_size="22sp",
            bold=True,
            size_hint_y=None,
            height=40,
            size_hint_x=None,
            width=100,  # Feste Breite
            halign='left',
            text_size=(100, None),
        )
        self.part_list_grid.add_widget(aktion_header)

        for part in parts:
            part_name = part.get("part_name") or ""
            start_ms = part.get("start_ms")
            duration_ms = part.get("duration_ms")
            bars = part.get("bars")

            # Formatierung: mm:ss
            def format_ms_to_mmss(ms):
                if ms is None:
                    return "--:--"
                total_sec = ms // 1000
                minutes = total_sec // 60
                seconds = total_sec % 60
                return f"{minutes:02d}:{seconds:02d}"

            start_time_str = format_ms_to_mmss(start_ms)
            duration_str = format_ms_to_mmss(duration_ms)
            bars_str = str(bars) if bars is not None else "--"

            # Bestimme Text- und Hintergrundfarbe basierend auf Songteil-Typ
            part_name_lower = part_name.lower()
            if "refrain" in part_name_lower or "chorus" in part_name_lower:
                # Weiß mit schwarzer Schrift
                text_color = (0.0, 0.0, 0.0, 1.0)  # Schwarz
                bg_color = (1.0, 1.0, 1.0, 1.0)  # Weiß
            elif "strophe" in part_name_lower or "verse" in part_name_lower:
                # Schwarz mit weißer Schrift
                text_color = (1.0, 1.0, 1.0, 1.0)  # Weiß
                bg_color = (0.0, 0.0, 0.0, 1.0)  # Schwarz
            else:
                # Standard: Weiß
                text_color = (1.0, 1.0, 1.0, 1.0)  # Weiß
                bg_color = (0.3, 0.3, 0.3, 1.0)  # Dunkelgrau

            def create_label_with_bg(text, bg_color, text_color):
                """Erstellt ein Label mit Hintergrundfarbe."""
                from kivy.graphics import Color as GColor, Rectangle
                label = Label(
                    text=text,
                    font_size="20sp",
                    size_hint_y=None,
                    height=40,
                    halign='left',
                    text_size=(None, None),
                    color=text_color,
                )
                # Füge Hintergrund hinzu
                with label.canvas.before:
                    GColor(*bg_color)
                    bg_rect = Rectangle(pos=label.pos, size=label.size)
                
                # Aktualisiere Hintergrund bei Größenänderung
                def update_bg(instance, value):
                    if hasattr(instance, '_bg_rect'):
                        instance._bg_rect.pos = instance.pos
                        instance._bg_rect.size = instance.size
                
                label._bg_rect = bg_rect
                label.bind(pos=update_bg, size=update_bg)
                
                # Doppelklick-Handler
                label._last_click_time = 0
                label._last_click_pos = None
                label._part_id = part["id"]
                label._field_name = None
                label._admin_panel = self
                label._part_dict = part
                
                return label
            
            # Callback für Doppelklick
            def on_label_double_click(label_instance, touch):
                """Öffnet Edit-Dialog bei Doppelklick."""
                if label_instance.collide_point(*touch.pos):
                    current_time = touch.time_start
                    # Prüfe ob Doppelklick (innerhalb von 300ms und ähnliche Position)
                    if (hasattr(label_instance, '_last_click_time') and
                        label_instance._last_click_time and 
                        current_time - label_instance._last_click_time < 0.3 and
                        hasattr(label_instance, '_last_click_pos') and
                        label_instance._last_click_pos and
                        abs(touch.pos[0] - label_instance._last_click_pos[0]) < 10 and
                        abs(touch.pos[1] - label_instance._last_click_pos[1]) < 10):
                        # Öffne Dialog
                        dialog = SongPartEditDialog(
                            field_name=label_instance._field_name,
                            current_value=label_instance.text,
                            part_id=label_instance._part_id,
                            admin_panel=label_instance._admin_panel,
                            part_dict=label_instance._part_dict
                        )
                        dialog.open()
                        return True
                    label_instance._last_click_time = current_time
                    label_instance._last_click_pos = touch.pos
                return False
            
            # Songteil-Name (feste Breite wie Header)
            part_name_label = create_label_with_bg(part_name, bg_color, text_color)
            part_name_label._field_name = "part_name"
            part_name_label.size_hint_x = None
            part_name_label.width = 200  # Gleiche Breite wie Header
            part_name_label.text_size = (200, None)
            part_name_label.bind(on_touch_down=on_label_double_click)
            self.part_list_grid.add_widget(part_name_label)

            # Startzeit (halbe Breite)
            start_time_label = create_label_with_bg(start_time_str, bg_color, text_color)
            start_time_label._field_name = "start_ms"
            start_time_label.size_hint_x = None
            start_time_label.width = 80  # Halbe Breite
            start_time_label.text_size = (80, None)
            start_time_label.bind(on_touch_down=on_label_double_click)
            self.part_list_grid.add_widget(start_time_label)

            # Dauer (halbe Breite)
            duration_label = create_label_with_bg(duration_str, bg_color, text_color)
            duration_label._field_name = "duration_ms"
            duration_label.size_hint_x = None
            duration_label.width = 80  # Halbe Breite
            duration_label.text_size = (80, None)
            duration_label.bind(on_touch_down=on_label_double_click)
            self.part_list_grid.add_widget(duration_label)

            # Takte (feste Breite wie Header)
            bars_label = create_label_with_bg(bars_str, bg_color, text_color)
            bars_label._field_name = "bars"
            bars_label.size_hint_x = None
            bars_label.width = 80  # Gleiche Breite wie Header
            bars_label.text_size = (80, None)
            bars_label.bind(on_touch_down=on_label_double_click)
            self.part_list_grid.add_widget(bars_label)

            # "Ab hier" Button (feste Breite wie Header)
            from kivy.uix.button import Button
            play_from_button = Button(
                text="Ab hier",
                font_size="18sp",
                size_hint_y=None,
                height=40,
                size_hint_x=None,
                width=100,  # Gleiche Breite wie "Abspielen" Header
                background_color=(0.2, 0.6, 0.8, 1.0)
            )
            play_from_button._part_id = part["id"]
            play_from_button._start_ms = start_ms
            play_from_button._admin_panel = self
            play_from_button.bind(on_press=self._on_play_from_part_click)
            # Kontextmenü für rechten Mausklick hinzufügen
            play_from_button.bind(on_touch_down=self._on_part_right_click)
            self.part_list_grid.add_widget(play_from_button)

            # Speichere Labels für Hervorhebung
            part_labels = [
                part_name_label,  # Songteil-Name
                start_time_label,  # Startzeit
                duration_label,  # Dauer
                bars_label,  # Takte
            ]
            self._part_labels[part["id"]] = part_labels
            
            self._part_rows.append(
                {
                    "id": part["id"],
                    "part_name": part_name,
                }
            )
        
        # Button zum Erstellen eines neuen Songteils am Ende der Tabelle
        from kivy.uix.button import Button
        add_part_button = Button(
            text="+ Neuer Songteil",
            font_size="20sp",
            size_hint_y=None,
            height=50,
            background_color=(0.2, 0.8, 0.2, 1.0)
        )
        add_part_button.bind(on_press=self._on_add_part_click)
        self.part_list_grid.add_widget(add_part_button)
        
        # Leere Zellen für die restlichen Spalten
        for _ in range(4):  # 4 leere Zellen (Songteil, Startzeit, Dauer, Takte)
            self.part_list_grid.add_widget(Label(text="", size_hint_y=None, height=50))
        
        # Setze Songteile im Timeline-Widget (mit BPM)
        if self.timeline_widget:
            song = self.db.get_song(self.current_song_id)
            bpm = song.get("bpm") if song else None
            self.timeline_widget.set_song_parts(parts, bpm=bpm)
        
        # Lade und zeige Offset der Audiodatei
        self._load_audio_offset()
        
        # Setze Beat-Indikator zurück wenn keine Songteile vorhanden
        if not parts and hasattr(self, 'beat_indicator') and self.beat_indicator:
            self.beat_indicator.beat_active = False
            self.beat_indicator._update_canvas()
            if hasattr(self.beat_indicator, 'blink_animation') and self.beat_indicator.blink_animation:
                Clock.unschedule(self.beat_indicator.blink_animation)
                self.beat_indicator.blink_animation = None
    
    def _on_header_click(self, instance, touch):
        """Wird aufgerufen, wenn auf eine Überschrift geklickt wird. Berechnet Werte aus BPM + anderen Spalten."""
        if not instance.collide_point(*touch.pos):
            return False
        
        if not self.current_song_id:
            return False
        
        # Hole Song für BPM
        song = self.db.get_song(self.current_song_id)
        bpm = song.get("bpm") if song else None
        
        if not bpm or bpm <= 0:
            print("BPM nicht verfügbar, kann Werte nicht berechnen")
            return False
        
        field_name = instance._field_name
        parts = self.db.get_song_parts(self.current_song_id)
        parts = sorted(parts, key=lambda p: p.get("start_segment", 0))
        
        updated_count = 0
        
        for part in parts:
            part_id = part["id"]
            bars = part.get("bars")
            duration_ms = part.get("duration_ms")
            start_ms = part.get("start_ms")
            
            if field_name == "bars":
                # Berechne Takte aus Dauer und BPM
                if duration_ms and duration_ms > 0:
                    ms_per_bar = 4 * (60000.0 / bpm)
                    calculated_bars = round(duration_ms / ms_per_bar)
                    if bars != calculated_bars:
                        self.db.update_song_part(part_id, bars=calculated_bars)
                        updated_count += 1
            
            elif field_name == "duration_ms":
                # Berechne Dauer aus Takte und BPM
                if bars and bars > 0:
                    ms_per_bar = 4 * (60000.0 / bpm)
                    calculated_duration_ms = round(bars * ms_per_bar)
                    if duration_ms != calculated_duration_ms:
                        # Berechne end_ms neu
                        start_ms = part.get("start_ms") or 0
                        end_ms = start_ms + calculated_duration_ms
                        self.db.update_song_part(part_id, duration_ms=calculated_duration_ms, end_ms=end_ms)
                        updated_count += 1
                        # Berechne nachfolgende Teile neu
                        self._recalculate_following_parts(part_id, end_ms)
            
            elif field_name == "start_ms":
                # Berechne Startzeit kumulativ aus vorherigen Songteilen
                # Sortiere nach start_segment
                current_index = parts.index(part)
                if current_index == 0:
                    # Erster Teil: Startzeit = 0
                    if start_ms != 0:
                        duration_ms = part.get("duration_ms") or 0
                        end_ms = 0 + duration_ms
                        self.db.update_song_part(part_id, start_ms=0, end_ms=end_ms)
                        updated_count += 1
                        self._recalculate_following_parts(part_id, end_ms)
                else:
                    # Startzeit = Endzeit des vorherigen Teils
                    prev_part = parts[current_index - 1]
                    prev_end_ms = prev_part.get("end_ms") or 0
                    if start_ms != prev_end_ms:
                        duration_ms = part.get("duration_ms") or 0
                        end_ms = prev_end_ms + duration_ms
                        self.db.update_song_part(part_id, start_ms=prev_end_ms, end_ms=end_ms)
                        updated_count += 1
                        self._recalculate_following_parts(part_id, end_ms)
        
        if updated_count > 0:
            print(f"{updated_count} Songteile basierend auf {field_name} neu berechnet (BPM: {bpm})")
            # Lade Songteile neu
            self._load_song_parts(self.current_song_id)
        
        return True
    
    def _save_song_part_field(self, part_id: int, field_name: str, new_value: str, part_dict: Dict):
        """Speichert ein Feld eines Songteils in der Datenbank."""
        try:
            if field_name == "part_name":
                # Direkt speichern
                self.db.update_song_part(part_id, part_name=new_value)
                print(f"Songteil '{part_dict.get('part_name')}' umbenannt zu '{new_value}'")
            
            elif field_name == "start_ms":
                # Konvertiere mm:ss zu Millisekunden
                try:
                    parts = new_value.split(":")
                    if len(parts) == 2:
                        minutes = int(parts[0])
                        seconds = int(parts[1])
                        start_ms = (minutes * 60 + seconds) * 1000
                        
                        # Berechne end_ms neu basierend auf duration_ms
                        duration_ms = part_dict.get("duration_ms") or 0
                        end_ms = start_ms + duration_ms
                        
                        self.db.update_song_part(part_id, start_ms=start_ms, end_ms=end_ms)
                        print(f"Startzeit aktualisiert: {new_value} ({start_ms}ms)")
                        
                        # Berechne alle nachfolgenden Songteile neu
                        self._recalculate_following_parts(part_id, end_ms)
                    else:
                        print(f"Ungültiges Format für Startzeit: {new_value} (erwartet: mm:ss)")
                        return
                except ValueError as e:
                    print(f"Fehler beim Parsen der Startzeit: {e}")
                    return
            
            elif field_name == "duration_ms":
                # Konvertiere mm:ss zu Millisekunden
                try:
                    parts = new_value.split(":")
                    if len(parts) == 2:
                        minutes = int(parts[0])
                        seconds = int(parts[1])
                        duration_ms = (minutes * 60 + seconds) * 1000
                        
                        # Berechne end_ms neu basierend auf start_ms
                        start_ms = part_dict.get("start_ms") or 0
                        end_ms = start_ms + duration_ms
                        
                        # Berechne bars neu basierend auf BPM
                        song = self.db.get_song(self.current_song_id)
                        bpm = song.get("bpm") if song else None
                        bars = None
                        if bpm and duration_ms and bpm > 0:
                            ms_per_bar = 4 * (60000.0 / bpm)
                            bars = round(duration_ms / ms_per_bar)
                        
                        self.db.update_song_part(part_id, duration_ms=duration_ms, end_ms=end_ms, bars=bars)
                        print(f"Dauer aktualisiert: {new_value} ({duration_ms}ms, {bars} Takte)")
                        
                        # Berechne alle nachfolgenden Songteile neu
                        self._recalculate_following_parts(part_id, end_ms)
                    else:
                        print(f"Ungültiges Format für Dauer: {new_value} (erwartet: mm:ss)")
                        return
                except ValueError as e:
                    print(f"Fehler beim Parsen der Dauer: {e}")
                    return
            
            elif field_name == "bars":
                # Direkt speichern
                try:
                    bars = int(new_value) if new_value and new_value != "--" else None
                    self.db.update_song_part(part_id, bars=bars)
                    print(f"Takte aktualisiert: {bars}")
                except ValueError:
                    print(f"Ungültiger Wert für Takte: {new_value}")
                    return
            
            # Aktualisiere das Label direkt, wenn es existiert
            if self.current_song_id and part_id in self._part_labels:
                labels = self._part_labels[part_id]
                if field_name == "part_name" and len(labels) > 0:
                    labels[0].text = new_value
                elif field_name == "start_ms" and len(labels) > 1:
                    # Konvertiere zurück zu mm:ss
                    try:
                        parts = new_value.split(":")
                        if len(parts) == 2:
                            labels[1].text = new_value
                    except:
                        pass
                elif field_name == "duration_ms" and len(labels) > 2:
                    # Konvertiere zurück zu mm:ss
                    try:
                        parts = new_value.split(":")
                        if len(parts) == 2:
                            labels[2].text = new_value
                    except:
                        pass
                elif field_name == "bars" and len(labels) > 3:
                    labels[3].text = new_value
            
            # Lade Songteile neu, um Timeline zu aktualisieren
            if self.current_song_id:
                self._load_song_parts(self.current_song_id)
            
        except Exception as e:
            print(f"Fehler beim Speichern: {e}")
            import traceback
            traceback.print_exc()
    
    def _save_song_field(self, song_id: int, field_name: str, new_value: str, song_dict: Dict):
        """Speichert ein Feld eines Songs in der Datenbank."""
        try:
            if field_name == "name":
                # Direkt speichern
                self.db.update_song(song_id, name=new_value)
                print(f"Songtitel aktualisiert: {new_value}")
            
            elif field_name == "bpm":
                # BPM als Integer speichern
                try:
                    bpm = int(new_value) if new_value and new_value.strip() else None
                    self.db.update_song(song_id, bpm=bpm)
                    print(f"BPM aktualisiert: {bpm}")
                    
                    # Berechne Takte für alle Songteile neu
                    if bpm and bpm > 0:
                        self._recalculate_bars_for_all_parts(song_id, bpm)
                except ValueError:
                    print(f"Ungültiger Wert für BPM: {new_value}")
                    return
            
            elif field_name == "duration":
                # Konvertiere mm:ss zu Sekunden
                try:
                    parts = new_value.split(":")
                    if len(parts) == 2:
                        minutes = int(parts[0])
                        seconds = int(parts[1])
                        duration_sec = minutes * 60 + seconds
                        self.db.update_song(song_id, duration=duration_sec)
                        print(f"Dauer aktualisiert: {new_value} ({duration_sec}s)")
                    else:
                        print(f"Ungültiges Format für Dauer: {new_value} (erwartet: mm:ss)")
                        return
                except ValueError as e:
                    print(f"Fehler beim Parsen der Dauer: {e}")
                    return
            
            # Lade Songs neu, um Anzeige zu aktualisieren
            self._load_songs()
            
            # Wenn aktueller Song geändert wurde, aktualisiere auch die Songteile
            if song_id == self.current_song_id:
                self._load_song_parts(song_id)
            
        except Exception as e:
            print(f"Fehler beim Speichern: {e}")
            import traceback
            traceback.print_exc()
    
    def _recalculate_following_parts(self, changed_part_id: int, new_end_ms: int):
        """Berechnet alle nachfolgenden Songteile neu, ausgehend von der Endzeit des geänderten Songteils."""
        if not self.current_song_id:
            return
        
        # Hole alle Songteile des Songs, sortiert nach start_segment
        all_parts = self.db.get_song_parts(self.current_song_id)
        all_parts = sorted(all_parts, key=lambda p: p.get("start_segment", 0))
        
        # Finde den geänderten Songteil und alle nachfolgenden
        changed_part = None
        following_parts = []
        found_changed = False
        
        for part in all_parts:
            if part["id"] == changed_part_id:
                changed_part = part
                found_changed = True
                continue
            if found_changed:
                following_parts.append(part)
        
        if not changed_part or not following_parts:
            return
        
        # Berechne neue Startzeiten für alle nachfolgenden Songteile
        current_start_ms = new_end_ms
        
        for part in following_parts:
            old_start_ms = part.get("start_ms") or 0
            old_duration_ms = part.get("duration_ms") or 0
            
            # Neue Startzeit = Endzeit des vorherigen Songteils
            new_start_ms = current_start_ms
            new_end_ms = new_start_ms + old_duration_ms
            
            # Berechne bars neu basierend auf BPM
            song = self.db.get_song(self.current_song_id)
            bpm = song.get("bpm") if song else None
            bars = None
            if bpm and old_duration_ms and bpm > 0:
                ms_per_bar = 4 * (60000.0 / bpm)
                bars = round(old_duration_ms / ms_per_bar)
            
            # Aktualisiere Songteil
            self.db.update_song_part(
                part["id"],
                start_ms=new_start_ms,
                end_ms=new_end_ms,
                bars=bars
            )
            
            # Nächste Startzeit = Endzeit dieses Songteils
            current_start_ms = new_end_ms
        
        print(f"Nachfolgende Songteile neu berechnet: {len(following_parts)} Teile")
    
    def _recalculate_bars_for_all_parts(self, song_id: int, bpm: float):
        """Berechnet die Taktanzahl für alle Songteile eines Songs neu basierend auf BPM."""
        if not bpm or bpm <= 0:
            return
        
        # Hole alle Songteile des Songs
        parts = self.db.get_song_parts(song_id)
        
        updated_count = 0
        for part in parts:
            part_id = part["id"]
            duration_ms = part.get("duration_ms")
            
            if duration_ms and duration_ms > 0:
                # Berechne Takte basierend auf BPM
                # Dauer einer Viertelnote in ms
                quarter_note_ms = 60000.0 / bpm
                # Anzahl der Viertelnoten
                quarter_notes = duration_ms / quarter_note_ms
                # Anzahl der Takte (4/4-Takt: 4 Viertelnoten pro Takt)
                calculated_bars = round(quarter_notes / 4.0)
                
                # Aktualisiere nur wenn bars fehlt oder abweicht
                current_bars = part.get("bars")
                if current_bars is None or abs(current_bars - calculated_bars) > 0.5:
                    self.db.update_song_part(part_id, bars=calculated_bars)
                    updated_count += 1
                    part_name = part.get("part_name", "")
                    print(f"  ✓ {part_name}: Takte von {current_bars} auf {calculated_bars} aktualisiert")
        
        if updated_count > 0:
            print(f"Taktanzahl für {updated_count} Songteile neu berechnet (BPM: {bpm})")
            # Lade Songteile neu, um Anzeige zu aktualisieren
            if song_id == self.current_song_id:
                self._load_song_parts(song_id)
    
    def _on_play_from_part_click(self, instance):
        """Wird aufgerufen, wenn der 'Ab hier' Button geklickt wird."""
        start_ms = instance._start_ms or 0
        
        # Stoppe aktuelle Wiedergabe falls aktiv
        if self.audio_playing:
            self._stop_audio()
        
        # Starte Audio-Wiedergabe ab dieser Position
        if not self.current_song_id:
            return
        
        # Setze Startposition (Startzeit des Songteils + Offset)
        # Der Offset wird in _start_audio berücksichtigt
        self.audio_paused_position_ms = start_ms
        
        # Starte Wiedergabe
        self._start_audio()
    
    def _on_part_right_click(self, widget, touch):
        """Wird aufgerufen, wenn mit der rechten Maustaste auf einen Songteil geklickt wird."""
        if touch.button == 'right' and widget.collide_point(*touch.pos):
            part_id = widget._part_id
            part_name = widget._part_name
            
            # Kontextmenü anzeigen
            from kivy.uix.popup import Popup
            from kivy.uix.boxlayout import BoxLayout
            from kivy.uix.button import Button
            
            content = BoxLayout(orientation='vertical', spacing=10, padding=10)
            
            btn_delete = Button(
                text="Löschen",
                font_size="20sp",
                size_hint_y=None,
                height=50,
                background_color=(0.8, 0.2, 0.2, 1.0)
            )
            btn_delete.bind(on_press=lambda b: self._on_delete_part_click(widget))
            
            btn_cancel = Button(
                text="Abbrechen",
                font_size="20sp",
                size_hint_y=None,
                height=50
            )
            
            popup = Popup(
                title=f"Songteil: {part_name}",
                content=content,
                size_hint=(0.4, 0.3),
                auto_dismiss=True
            )
            
            btn_cancel.bind(on_press=lambda b: popup.dismiss())
            content.add_widget(btn_delete)
            content.add_widget(btn_cancel)
            popup.open()
            return True
        return False
    
    def _on_song_right_click(self, widget, touch):
        """Wird aufgerufen, wenn mit der rechten Maustaste auf einen Song geklickt wird."""
        if touch.button == 'right' and widget.collide_point(*touch.pos):
            song_id = widget._song_id if hasattr(widget, '_song_id') else None
            song_name = widget._song_name if hasattr(widget, '_song_name') else None
            
            if not song_id:
                # Versuche song_id aus dem SongListItem zu bekommen
                for sid, item in self.song_items.items():
                    if item == widget:
                        song_id = sid
                        break
            
            if song_id:
                song = self.db.get_song(song_id)
                if song:
                    song_name = song.get("name")
                # Kontextmenü anzeigen
                from kivy.uix.popup import Popup
                from kivy.uix.boxlayout import BoxLayout
                from kivy.uix.button import Button
                
                content = BoxLayout(orientation='vertical', spacing=10, padding=10)
                
                btn_delete = Button(
                    text="Löschen",
                    font_size="20sp",
                    size_hint_y=None,
                    height=50,
                    background_color=(0.8, 0.2, 0.2, 1.0)
                )
                # Erstelle temporäres Objekt für _on_delete_song_click
                class TempInstance:
                    def __init__(self, sid, sname):
                        self._song_id = sid
                        self._song_name = sname
                btn_delete.bind(on_press=lambda b: self._on_delete_song_click(TempInstance(song_id, song_name)))
                
                btn_cancel = Button(
                    text="Abbrechen",
                    font_size="20sp",
                    size_hint_y=None,
                    height=50
                )
                
                popup = Popup(
                    title=f"Song: {song_name}",
                    content=content,
                    size_hint=(0.4, 0.3),
                    auto_dismiss=True
                )
                
                btn_cancel.bind(on_press=lambda b: popup.dismiss())
                content.add_widget(btn_delete)
                content.add_widget(btn_cancel)
                popup.open()
                return True
        return False
    
    def _on_delete_part_click(self, instance):
        """Wird aufgerufen, wenn der Löschen-Button im Kontextmenü geklickt wird."""
        part_id = instance._part_id
        part_name = instance._part_name
        
        # Bestätigungsdialog
        from kivy.uix.modalview import ModalView
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        
        confirm_dialog = ModalView(size_hint=(0.5, 0.3))
        layout = BoxLayout(orientation='vertical', padding=20, spacing=15)
        
        label = Label(
            text=f"Songteil '{part_name}' wirklich löschen?",
            font_size="24sp",
            text_size=(None, None),
            halign='center'
        )
        label.bind(texture_size=label.setter('size'))
        layout.add_widget(label)
        
        button_layout = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height=50)
        
        btn_confirm = Button(
            text="Löschen",
            font_size="24sp",
            background_color=(0.8, 0.2, 0.2, 1.0)
        )
        def on_confirm(btn):
            self.db.delete_song_part(part_id)
            confirm_dialog.dismiss()
            # Lade Songteile neu
            if self.current_song_id:
                self._load_song_parts(self.current_song_id)
        btn_confirm.bind(on_press=on_confirm)
        button_layout.add_widget(btn_confirm)
        
        btn_cancel = Button(
            text="Abbrechen",
            font_size="24sp",
            background_color=(0.5, 0.5, 0.5, 1.0)
        )
        btn_cancel.bind(on_press=lambda btn: confirm_dialog.dismiss())
        button_layout.add_widget(btn_cancel)
        
        layout.add_widget(button_layout)
        confirm_dialog.add_widget(layout)
        confirm_dialog.open()
    
    def _on_delete_song_click(self, instance):
        """Wird aufgerufen, wenn der Löschen-Button für einen Song geklickt wird."""
        song_id = instance._song_id
        song_name = instance._song_name
        
        # Bestätigungsdialog
        from kivy.uix.modalview import ModalView
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        
        confirm_dialog = ModalView(size_hint=(0.5, 0.3))
        layout = BoxLayout(orientation='vertical', padding=20, spacing=15)
        
        label = Label(
            text=f"Song '{song_name}' wirklich löschen?\n(Alle Songteile werden ebenfalls gelöscht)",
            font_size="24sp",
            text_size=(None, None),
            halign='center'
        )
        label.bind(texture_size=label.setter('size'))
        layout.add_widget(label)
        
        button_layout = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height=50)
        
        btn_confirm = Button(
            text="Löschen",
            font_size="24sp",
            background_color=(0.8, 0.2, 0.2, 1.0)
        )
        def on_confirm(btn):
            self.db.delete_song(song_id)
            confirm_dialog.dismiss()
            # Wenn der gelöschte Song gerade ausgewählt war, setze Auswahl zurück
            if self.current_song_id == song_id:
                self.current_song_id = None
                # Leere Songteile-Liste
                if self.part_list_grid:
                    self.part_list_grid.clear_widgets()
                # Leere Timeline
                if self.timeline_widget:
                    self.timeline_widget.set_song_parts([], bpm=None)
            # Lade Songs neu
            self._load_songs()
        btn_confirm.bind(on_press=on_confirm)
        button_layout.add_widget(btn_confirm)
        
        btn_cancel = Button(
            text="Abbrechen",
            font_size="24sp",
            background_color=(0.5, 0.5, 0.5, 1.0)
        )
        btn_cancel.bind(on_press=lambda btn: confirm_dialog.dismiss())
        button_layout.add_widget(btn_cancel)
        
        layout.add_widget(button_layout)
        confirm_dialog.add_widget(layout)
        confirm_dialog.open()
    
    def _on_add_part_click(self, instance):
        """Wird aufgerufen, wenn der Button zum Erstellen eines neuen Songteils geklickt wird."""
        if not self.current_song_id:
            return
        
        # Hole den letzten Songteil, um die nächste Segment-Nummer zu bestimmen
        parts = self.db.get_song_parts(self.current_song_id)
        if parts:
            last_segment = max(p.get("start_segment", 0) for p in parts)
            next_segment = last_segment + 1
        else:
            next_segment = 1
        
        # Hole die letzte Endzeit, um die Startzeit zu bestimmen
        if parts:
            last_end_ms = max(p.get("end_ms", 0) or 0 for p in parts)
            start_ms = last_end_ms
        else:
            start_ms = 0
        
        # Erstelle neuen Songteil
        part_id = self.db.add_song_part(
            song_id=self.current_song_id,
            part_name="Neuer Songteil",
            start_segment=next_segment,
            end_segment=next_segment,
            start_ms=start_ms,
            end_ms=start_ms + 10000,  # Standard: 10 Sekunden
            duration_ms=10000,
            bars=None
        )
        
        # Lade Songteile neu
        self._load_song_parts(self.current_song_id)
    
    # ------------------------------------------------------------------ #
    # Audio-Wiedergabe
    # ------------------------------------------------------------------ #
    
    def _on_keyboard_down(self, window, key, scancode, codepoint, modifier):
        """Behandelt Tastendrücke - Space für Play/Pause."""
        # Space-Taste (keycode 32 oder 'spacebar')
        if key == 32 or codepoint == ' ':
            if self.current_song_id:
                self._toggle_audio_playback(None)
            return True
        return False
    
    def _toggle_audio_playback(self, instance):
        """Schaltet Audio-Wiedergabe ein/aus."""
        if not _check_pygame_available():
            return
        
        if not self.current_song_id:
            return
        
        if self.audio_playing:
            self._stop_audio()
        else:
            self._start_audio()
    
    def _start_audio(self):
        """Startet die Audio-Wiedergabe für den aktuellen Song."""
        if not _check_pygame_available() or not self.current_song_id:
            return
        
        # Import pygame hier, da es zur Laufzeit verfügbar sein könnte
        import pygame
        
        # Hole Audiofiles für den Song
        audio_files = self.db.get_audio_files_for_song(self.current_song_id)
        if not audio_files:
            print("Keine Audiodatei für diesen Song gefunden")
            return
        
        # Verwende die erste/neueste Audiodatei
        audio_file = audio_files[0]  # Oder sortiere nach recording_date
        
        # Hole Song-Daten für Beat-Detection
        song = self.db.get_song(self.current_song_id)
        
        # Hole Offset
        self.audio_offset_sec = audio_file.get('offset_sec', 0.0) or 0.0
        
        # Speichere BLOB in temporärer Datei
        audio_data = audio_file.get('audio_data')
        if not audio_data:
            print("Keine Audio-Daten gefunden")
            return
        
        try:
            # Erstelle temporäre Datei
            temp_dir = Path(tempfile.gettempdir())
            file_name = audio_file.get('file_name', 'audio.mp3')
            self.temp_audio_file = temp_dir / f"lighting_ai_{self.current_song_id}_{file_name}"
            self.temp_audio_file.write_bytes(audio_data)
            
            # Initialisiere pygame mixer
            pygame.mixer.init()
            pygame.mixer.music.load(str(self.temp_audio_file))
            pygame.mixer.music.play()
            
            # Berechne tatsächliche Startposition in der Audiodatei
            # Wenn "Ab hier" verwendet wurde: start_ms + offset
            # Sonst: nur offset
            import time
            start_position_ms = self.audio_paused_position_ms if hasattr(self, 'audio_paused_position_ms') and self.audio_paused_position_ms > 0 else 0
            audio_start_position_sec = (start_position_ms / 1000.0) + self.audio_offset_sec
            
            # Setze Position auf Offset + Startposition (funktioniert nur mit OGG, bei MP3 wird es ignoriert)
            # Für MP3 müssen wir die Position manuell tracken
            if audio_start_position_sec > 0:
                try:
                    pygame.mixer.music.set_pos(audio_start_position_sec)
                except:
                    # set_pos funktioniert nicht mit MP3, wir tracken die Position manuell
                    pass
            
            # Startzeit für Position-Tracking
            # Wichtig: Pointer startet bei der Startposition des Songteils (start_position_ms)
            # Der Offset wird nur für die Audio-Wiedergabe verwendet, nicht für die Pointer-Position
            # audio_start_time wird so gesetzt, dass elapsed_seconds bei start_position_ms beginnt
            self.audio_start_time = time.time() - (start_position_ms / 1000.0)
            # Setze Position zurück wenn nicht von "Ab hier" gesetzt
            if not hasattr(self, 'audio_paused_position_ms') or self.audio_paused_position_ms == 0:
                self.audio_paused_position_ms = 0
            
            # Beat-Detection für Audio-Datei
            # WICHTIG: Setze current_quarter_index zurück
            self.current_quarter_index = 0
            beat_logger.info(f"Wiedergabe gestartet, current_quarter_index auf 0 zurückgesetzt")
            
            # Wenn BPM vorhanden ist, generiere SOFORT gleichmäßige Viertelnoten
            # Die Beat-Detection kann im Hintergrund laufen und das BPM verfeinern
            bpm = song.get("bpm")
            offset_sec = audio_file.get('offset_sec', 0.0) or 0.0
            
            if bpm and bpm > 0:
                # Bestimme Audio-Dauer schnell
                try:
                    import soundfile as sf
                    # Verwende soundfile für schnelle Dauer-Bestimmung (lädt nicht die gesamte Datei)
                    with sf.SoundFile(str(self.temp_audio_file)) as f:
                        audio_duration = len(f) / f.samplerate
                    beat_logger.info(f"Audio-Dauer schnell bestimmt: {audio_duration:.2f}s")
                except Exception as e:
                    # Fallback: konservative Schätzung
                    audio_duration = 300.0  # 5 Minuten als Fallback
                    beat_logger.warning(f"Konnte Audio-Dauer nicht bestimmen, verwende Schätzung: {audio_duration}s ({e})")
                
                # Generiere gleichmäßige Viertelnoten ab Offset
                quarter_note_interval = 60.0 / bpm
                quarter_notes = []
                current_time = offset_sec
                # Generiere Beats für die gesamte Audio-Dauer + etwas Puffer
                while current_time <= audio_duration + 10.0:  # 10 Sekunden Puffer
                    quarter_notes.append(current_time)
                    current_time += quarter_note_interval
                
                self.quarter_notes = quarter_notes
                beat_logger.info(f"Sofortige Beat-Generierung: {len(quarter_notes)} gleichmäßige Viertelnoten (BPM: {bpm:.1f}, Interval: {quarter_note_interval:.3f}s, Dauer: {audio_duration:.2f}s)")
                
                # Update Status
                if hasattr(self, 'beat_status_label'):
                    self.beat_status_label.text = f"Status: {len(quarter_notes)} Viertelnoten (BPM: {bpm:.1f}, wird verfeinert...)"
            else:
                # Kein BPM vorhanden, warte auf Beat-Detection
                self.quarter_notes: List[float] = []
                beat_logger.info(f"Kein BPM vorhanden, Beat-Detection wird gestartet")
            
            # Starte Beat-Detection im Hintergrund-Thread (verfeinert BPM und Beats)
            # Dies läuft parallel zur Wiedergabe und kann das BPM verfeinern
            import threading
            beat_thread = threading.Thread(
                target=self._analyze_audio_beats_thread,
                args=(audio_file, song),
                daemon=True
            )
            beat_thread.start()
            
            self.audio_playing = True
            self.play_pause_button.text = "Pausieren"
            self.play_pause_button.background_color = (0.8, 0.2, 0.2, 1)
            
            # Setze Pointer auf Position 0 (ganz links, beim ersten Songteil)
            if self.timeline_widget:
                self.timeline_widget.set_position(0)
            
            # Überwache Wiedergabe-Ende und Position
            Clock.schedule_interval(self._check_audio_status, 0.1)
            Clock.schedule_interval(self._update_timeline_position, 0.05)  # 20 FPS für flüssige Animation
            
        except Exception as e:
            print(f"Fehler beim Abspielen: {e}")
            self._stop_audio()
    
    def _stop_audio(self):
        """Stoppt die Audio-Wiedergabe."""
        if not _check_pygame_available():
            return
        
        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
                pygame.mixer.quit()
        except:
            pass
        
        self.audio_playing = False
        self.play_pause_button.text = "Abspielen"
        self.play_pause_button.background_color = (0.2, 0.8, 0.2, 1)
        
        Clock.unschedule(self._check_audio_status)
        Clock.unschedule(self._update_timeline_position)
        
        # Setze Beat-Detection-Variablen zurück
        self.quarter_notes = []
        self.current_quarter_index = 0
        beat_logger.info(f"Wiedergabe gestoppt, current_quarter_index auf 0 zurückgesetzt")
        
        # Setze Beat-Indikator zurück
        if hasattr(self, 'beat_indicator') and self.beat_indicator:
            self.beat_indicator.beat_active = False
            self.beat_indicator._update_canvas()
            if hasattr(self.beat_indicator, 'blink_animation') and self.beat_indicator.blink_animation:
                Clock.unschedule(self.beat_indicator.blink_animation)
                self.beat_indicator.blink_animation = None
        
        # Setze Position zurück
        if self.timeline_widget:
            self.timeline_widget.set_position(0)
        self._highlight_active_part(None)
        
        # Lösche temporäre Datei
        if self.temp_audio_file and self.temp_audio_file.exists():
            try:
                self.temp_audio_file.unlink()
            except:
                pass
            self.temp_audio_file = None
    
    def _check_audio_status(self, dt):
        """Prüft ob Audio noch läuft."""
        if not _check_pygame_available():
            return False
        
        try:
            import pygame
            if not pygame.mixer.music.get_busy():
                # Wiedergabe beendet
                self._stop_audio()
                return False
        except:
            self._stop_audio()
            return False
        
        return True
    
    def _analyze_audio_beats_thread(self, audio_file: Dict, song: Dict):
        """Analysiert die Audio-Datei auf Beats/Viertelnoten in einem separaten Thread."""
        beat_logger.debug("_analyze_audio_beats_thread aufgerufen")
        beat_logger.debug(f"temp_audio_file: {self.temp_audio_file}")
        beat_logger.debug(f"temp_audio_file exists: {self.temp_audio_file.exists() if self.temp_audio_file else False}")
        
        # UI-Updates müssen im Hauptthread passieren
        def update_status(text):
            if hasattr(self, 'beat_status_label'):
                self.beat_status_label.text = text
        
        def update_result(quarter_notes_list, status_text):
            self.quarter_notes = quarter_notes_list
            # WICHTIG: Wenn die Wiedergabe bereits läuft, setze current_quarter_index auf die aktuelle Position
            # basierend auf der bereits verstrichenen Zeit, damit nicht alle vergangenen Beats auf einmal getriggert werden
            if self.audio_playing and hasattr(self, 'audio_start_time') and self.audio_start_time:
                import time
                elapsed_seconds = time.time() - self.audio_start_time
                if elapsed_seconds < 0:
                    elapsed_seconds = 0
                
                # Finde den ersten Beat-Index, der noch nicht erreicht wurde
                current_index = 0
                if quarter_notes_list:
                    for i, beat_time in enumerate(quarter_notes_list):
                        if beat_time > elapsed_seconds:
                            current_index = i
                            break
                    else:
                        # Alle Beats sind bereits vergangen
                        current_index = len(quarter_notes_list)
                
                self.current_quarter_index = current_index
                beat_logger.info(f"quarter_notes gesetzt: {len(quarter_notes_list)} Viertelnoten, current_quarter_index={current_index} (elapsed: {elapsed_seconds:.3f}s)")
            else:
                self.current_quarter_index = 0
                beat_logger.info(f"quarter_notes gesetzt: {len(quarter_notes_list)} Viertelnoten, current_quarter_index=0 (Wiedergabe nicht aktiv)")
            
            if len(quarter_notes_list) > 0:
                beat_logger.info(f"Erste Viertelnote: {quarter_notes_list[0]:.3f}s, Letzte: {quarter_notes_list[-1]:.3f}s")
            if hasattr(self, 'beat_status_label'):
                self.beat_status_label.text = status_text
        
        # Update Status im Hauptthread
        Clock.schedule_once(lambda dt: update_status("Status: Prüfe Audio-Datei..."), 0)
        
        if not self.temp_audio_file:
            error_msg = "temp_audio_file ist None"
            beat_logger.error(error_msg)
            Clock.schedule_once(lambda dt: update_status(f"Status: {error_msg}"), 0)
            return
        
        if not self.temp_audio_file.exists():
            error_msg = f"Audio-Datei nicht gefunden: {self.temp_audio_file}"
            beat_logger.error(error_msg)
            Clock.schedule_once(lambda dt: update_status(f"Status: {error_msg}"), 0)
            return
        
        try:
            # Prüfe ob madmom verfügbar ist
            try:
                from madmom.features.beats import RNNBeatProcessor, DBNBeatTrackingProcessor
                import soundfile as sf
                madmom_available = True
                beat_logger.info(f"madmom verfügbar")
            except ImportError as ie:
                error_msg = f"madmom nicht verfügbar: {ie}"
                beat_logger.error(error_msg)
                Clock.schedule_once(lambda dt: update_result([], f"Status: {error_msg}"), 0)
                return
            
            from audio_beat_detection import detect_beats_from_audio, get_quarter_notes_from_beats
            
            bpm = song.get("bpm")
            offset_sec = audio_file.get('offset_sec', 0.0) or 0.0
            
            beat_logger.info(f"BPM: {bpm}, Offset: {offset_sec}s")
            beat_logger.info("Starte Beat-Detection...")
            
            # Update Status während Analyse (im Hauptthread)
            Clock.schedule_once(lambda dt: update_status("Status: Initialisiere madmom..."), 0)
            Clock.schedule_once(lambda dt: update_status("Status: RNNBeatProcessor läuft (kann 30-60s dauern)..."), 1)
            
            # Erkenne Beats aus Audio-Datei (blockiert, daher im Thread)
            beat_times, detected_bpm, audio_duration = detect_beats_from_audio(
                self.temp_audio_file,
                bpm_hint=bpm,
                offset_sec=offset_sec
            )
            
            beat_logger.info(f"Beat-Detection Ergebnis: {len(beat_times) if beat_times else 0} Beats, BPM: {detected_bpm}, Dauer: {audio_duration:.2f}s" if audio_duration else f"Beat-Detection Ergebnis: {len(beat_times) if beat_times else 0} Beats, BPM: {detected_bpm}")
            
            if beat_times and len(beat_times) > 0:
                # Konvertiere Beats zu gleichmäßigen Viertelnoten
                # Verwende detected_bpm oder bpm für gleichmäßige Generierung
                final_bpm = detected_bpm or bpm
                quarter_notes_list = get_quarter_notes_from_beats(
                    beat_times, 
                    final_bpm,
                    audio_duration=audio_duration
                )
                status_text = f"Status: {len(quarter_notes_list)} gleichmäßige Viertelnoten (BPM: {final_bpm:.1f})"
                beat_logger.info(f"Beat-Detection erfolgreich: {len(quarter_notes_list)} gleichmäßige Viertelnoten erkannt")
                # Update Ergebnis im Hauptthread
                Clock.schedule_once(lambda dt: update_result(quarter_notes_list, status_text), 0)
            else:
                error_msg = f"Keine Beats erkannt (detected_bpm: {detected_bpm})"
                beat_logger.warning(error_msg)
                Clock.schedule_once(lambda dt: update_result([], f"Status: {error_msg}"), 0)
        except ImportError as ie:
            error_msg = f"Import-Fehler: {ie}"
            beat_logger.error(error_msg, exc_info=True)
            Clock.schedule_once(lambda dt: update_result([], f"Status: {error_msg}"), 0)
        except Exception as e:
            error_msg = f"Fehler bei Beat-Detection: {type(e).__name__}: {str(e)}"
            beat_logger.error(error_msg, exc_info=True)
            Clock.schedule_once(lambda dt: update_result([], f"Status: {error_msg[:60]}"), 0)
    
    def _update_timeline_position(self, dt):
        """Aktualisiert die Position im Zeitstrahl basierend auf der Audio-Wiedergabe und Beat-Detection."""
        # Debug: Log alle 5 Sekunden, ob die Funktion aufgerufen wird
        if not hasattr(self, '_last_position_debug_time'):
            self._last_position_debug_time = 0
        import time
        current_time = time.time()
        if current_time - self._last_position_debug_time > 5.0:
            beat_logger.debug(f"_update_timeline_position aufgerufen: audio_playing={self.audio_playing}, audio_start_time={self.audio_start_time}, quarter_notes={len(self.quarter_notes) if self.quarter_notes else 0}")
            self._last_position_debug_time = current_time
        
        if not self.audio_playing or not self.audio_start_time:
            if current_time - self._last_position_debug_time > 5.0:
                beat_logger.debug(f"_update_timeline_position: Bedingung nicht erfüllt - audio_playing={self.audio_playing}, audio_start_time={self.audio_start_time}")
            return
        
        try:
            # Stelle sicher, dass current_quarter_index initialisiert ist
            if not hasattr(self, 'current_quarter_index'):
                self.current_quarter_index = 0
                beat_logger.debug("current_quarter_index initialisiert auf 0")
            
            # Berechne verstrichene Zeit seit Start
            # Wichtig: elapsed_seconds beginnt bei 0, unabhängig vom Offset
            # Der Offset wird nur für die Audio-Wiedergabe verwendet, nicht für die Pointer-Position
            elapsed_seconds = time.time() - self.audio_start_time
            # Stelle sicher, dass elapsed_seconds nicht negativ wird und bei 0 startet
            if elapsed_seconds < 0:
                elapsed_seconds = 0
            
            # Wenn Beat-Detection verfügbar ist, verwende erkannte Viertelnoten
            if self.quarter_notes and len(self.quarter_notes) > 0:
                # Update Status
                if hasattr(self, 'beat_status_label'):
                    self.beat_status_label.text = f"Status: Beat Detection aktiv ({len(self.quarter_notes)} Viertelnoten)"
                
                # Finde die nächste Viertelnote basierend auf verstrichener Zeit
                # Trigger Beat-Indikator bei jeder Viertelnote
                beats_detected_count = 0
                # Stelle sicher, dass current_quarter_index initialisiert ist
                if not hasattr(self, 'current_quarter_index'):
                    self.current_quarter_index = 0
                
                # Debug-Logging alle 2 Sekunden
                if not hasattr(self, '_last_beat_debug_time'):
                    self._last_beat_debug_time = 0
                if elapsed_seconds - self._last_beat_debug_time > 2.0:
                    beat_logger.debug(f"elapsed_seconds={elapsed_seconds:.3f}, current_quarter_index={self.current_quarter_index}, quarter_notes length={len(self.quarter_notes)}")
                    if self.current_quarter_index < len(self.quarter_notes):
                        beat_logger.debug(f"Nächste Viertelnote bei: {self.quarter_notes[self.current_quarter_index]:.3f}s")
                    beat_logger.debug(f"beat_indicator vorhanden: {hasattr(self, 'beat_indicator')}, beat_indicator ist None: {not hasattr(self, 'beat_indicator') or self.beat_indicator is None}")
                    self._last_beat_debug_time = elapsed_seconds
                
                while (self.current_quarter_index < len(self.quarter_notes) and
                       self.quarter_notes[self.current_quarter_index] <= elapsed_seconds):
                    # Beat erkannt - trigger bei jeder Viertelnote
                    beat_time = self.quarter_notes[self.current_quarter_index]
                    beat_logger.debug(f"Beat erkannt bei {beat_time:.3f}s (elapsed: {elapsed_seconds:.3f}s)")
                    if hasattr(self, 'beat_indicator') and self.beat_indicator:
                        beat_logger.debug(f"Rufe beat_indicator.trigger_beat() auf")
                        self.beat_indicator.trigger_beat()
                    else:
                        beat_logger.warning(f"beat_indicator nicht verfügbar oder None!")
                    beats_detected_count += 1
                    self.current_quarter_index += 1
                
                if beats_detected_count > 0:
                    beat_logger.debug(f"{beats_detected_count} Beats getriggert, neuer current_quarter_index={self.current_quarter_index}")
                
                # Update Präzision (basierend auf erkannten Beats vs. erwartete Beats)
                if hasattr(self, 'beat_confidence_gauge') and hasattr(self, 'beat_confidence_label'):
                    if len(self.quarter_notes) > 0:
                        # Berechne Präzision basierend auf erwarteter vs. tatsächlicher Anzahl
                        song = self.db.get_song(self.current_song_id) if self.current_song_id else None
                        bpm = song.get("bpm") if song else None
                        if bpm and bpm > 0:
                            # Erwartete Anzahl von Viertelnoten basierend auf verstrichener Zeit
                            expected_beats = elapsed_seconds * (bpm / 60.0) * 4
                            if expected_beats > 0:
                                # Präzision: Wie viele Beats wurden erkannt vs. erwartet
                                # Wenn mehr erkannt als erwartet, ist das 100%
                                confidence = min(100, (self.current_quarter_index / expected_beats) * 100)
                            else:
                                confidence = 100 if self.current_quarter_index > 0 else 0
                        else:
                            # Kein BPM: Präzision basierend auf erkannten Beats
                            confidence = 100 if self.current_quarter_index > 0 else 0
                        self.beat_confidence_gauge.value = confidence
                        self.beat_confidence_label.text = f"Präzision: {confidence:.0f}%"
                    else:
                        # Keine Viertelnoten erkannt
                        self.beat_confidence_gauge.value = 0
                        self.beat_confidence_label.text = "Präzision: 0%"
                
                # Verwende die Position der aktuellen Viertelnote
                if self.current_quarter_index > 0:
                    # Position zwischen vorheriger und aktueller Viertelnote interpolieren
                    if self.current_quarter_index < len(self.quarter_notes):
                        prev_quarter = self.quarter_notes[self.current_quarter_index - 1]
                        next_quarter = self.quarter_notes[self.current_quarter_index]
                        # Lineare Interpolation
                        if next_quarter > prev_quarter:
                            t = (elapsed_seconds - prev_quarter) / (next_quarter - prev_quarter)
                            position_sec = prev_quarter + t * (next_quarter - prev_quarter)
                        else:
                            position_sec = prev_quarter
                    else:
                        # Nach der letzten Viertelnote: verwende letzte Position + verstrichene Zeit
                        last_quarter = self.quarter_notes[-1]
                        position_sec = last_quarter + (elapsed_seconds - last_quarter)
                else:
                    # Vor der ersten Viertelnote
                    position_sec = elapsed_seconds
                
                current_position_ms = int(position_sec * 1000)
            else:
                # Keine Beat-Detection verfügbar
                if hasattr(self, 'beat_status_label'):
                    self.beat_status_label.text = "Status: Beat Detection nicht verfügbar"
                if hasattr(self, 'beat_confidence_gauge') and hasattr(self, 'beat_confidence_label'):
                    self.beat_confidence_gauge.value = 0
                    self.beat_confidence_label.text = "Präzision: 0%"
                
                # Fallback: Zeit-basierte Position
                start_offset = self.audio_paused_position_ms / 1000.0 if hasattr(self, 'audio_paused_position_ms') and self.audio_paused_position_ms > 0 else 0.0
                current_position_ms = int((start_offset + elapsed_seconds) * 1000)
            
            # Aktualisiere Timeline (Songteile beginnen bei 0, Offset wird nicht berücksichtigt)
            if self.timeline_widget and hasattr(self, 'timeline_scroll'):
                # Berechne Pointer-X-Position relativ zum Timeline-Widget
                pointer_x_relative = None
                if self.timeline_widget.bpm and self.timeline_widget.bpm > 0:
                    # Takt-basiert
                    ms_per_bar = 4 * (60000.0 / self.timeline_widget.bpm)
                    cumulative_bar = 0
                    pointer_bar = 0
                    for part in self.timeline_widget.song_parts:
                        start_ms = part.get("start_ms", 0) or 0
                        end_ms = part.get("end_ms", 0) or 0
                        bars = part.get("bars")
                        
                        if start_ms <= current_position_ms <= end_ms:
                            relative_ms = current_position_ms - start_ms
                            bars_in_part = bars if bars and bars > 0 else int((end_ms - start_ms) / ms_per_bar)
                            relative_bars = relative_ms / ms_per_bar
                            pointer_bar = cumulative_bar + relative_bars
                            break
                        elif current_position_ms > end_ms:
                            bars_in_part = bars if bars and bars > 0 else int((end_ms - start_ms) / ms_per_bar)
                            cumulative_bar += bars_in_part
                    
                    pointer_x_relative = (pointer_bar * ms_per_bar / 1000.0) * self.timeline_widget.pixels_per_second
                else:
                    # Zeit-basiert
                    pointer_x_relative = (current_position_ms / 1000.0) * self.timeline_widget.pixels_per_second
                
                # Prüfe ob Pointer die Mitte des sichtbaren Bereichs erreicht hat
                if pointer_x_relative is not None:
                    scroll_view_width = self.timeline_scroll.width
                    if scroll_view_width > 0 and self.timeline_widget.width > scroll_view_width:
                        scroll_view_x = self.timeline_scroll.scroll_x
                        visible_left = scroll_view_x * (self.timeline_widget.width - scroll_view_width)
                        visible_right = visible_left + scroll_view_width
                        center_x = visible_left + (scroll_view_width / 2.0)
                        
                        # Wenn Pointer die Mitte erreicht hat und noch nicht ganz rechts gescrollt ist
                        if pointer_x_relative >= center_x and scroll_view_x < 0.99:
                            # Scrolle weiter nach rechts (5% pro Frame)
                            max_scroll = max(0, 1.0 - (scroll_view_width / self.timeline_widget.width))
                            new_scroll_x = min(max_scroll, scroll_view_x + 0.05)
                            self.timeline_scroll.scroll_x = new_scroll_x
                        elif pointer_x_relative < center_x and scroll_view_x > 0.01:
                            # Pointer ist noch links von der Mitte, scrolle zurück
                            optimal_scroll = (pointer_x_relative - scroll_view_width / 2.0) / (self.timeline_widget.width - scroll_view_width)
                            optimal_scroll = max(0.0, min(1.0, optimal_scroll))
                            self.timeline_scroll.scroll_x = optimal_scroll
                
                self.timeline_widget.set_position(current_position_ms)
            elif self.timeline_widget:
                self.timeline_widget.set_position(current_position_ms)
                
                # Hervorhebe aktiven Songteil
                active_part_id = self.timeline_widget.get_active_part_id()
                self._highlight_active_part(active_part_id)
        except Exception as e:
            print(f"Fehler beim Aktualisieren der Timeline-Position: {e}")
            import traceback
            traceback.print_exc()
    
    def _load_audio_offset(self):
        """Lädt den Offset der aktuellen Audiodatei und zeigt ihn an."""
        if not self.current_song_id:
            self.offset_input.text = "0.000"
            return
        
        audio_files = self.db.get_audio_files_for_song(self.current_song_id)
        if not audio_files:
            self.offset_input.text = "0.000"
            return
        
        # Verwende die erste/neueste Audiodatei
        audio_file = audio_files[0]
        offset_sec = audio_file.get('offset_sec', 0.0) or 0.0
        
        # Formatiere als Sekunden.Millisekunden (z.B. 5.250)
        seconds = int(offset_sec)
        milliseconds = int((offset_sec - seconds) * 1000)
        self.offset_input.text = f"{seconds}.{milliseconds:03d}"
        self.audio_offset_sec = offset_sec
    
    def _save_offset(self, instance):
        """Speichert den Offset in der Datenbank."""
        if not self.current_song_id:
            return
        
        try:
            # Parse Sekunden.Millisekunden Format (z.B. 5.250)
            offset_text = self.offset_input.text.strip()
            if "." in offset_text:
                parts = offset_text.split(".")
                if len(parts) == 2:
                    seconds = int(parts[0])
                    milliseconds = int(parts[1])
                    offset_sec = seconds + (milliseconds / 1000.0)
                else:
                    raise ValueError("Ungültiges Format")
            else:
                # Versuche als Sekunden zu parsen
                offset_sec = float(offset_text)
        except ValueError:
            print(f"Ungültiges Format für Offset: {offset_text} (erwartet: Sekunden.Millisekunden, z.B. 5.250)")
            self._load_audio_offset()  # Stelle ursprünglichen Wert wieder her
            return
        
        # Hole aktuelle Audiodatei
        audio_files = self.db.get_audio_files_for_song(self.current_song_id)
        if not audio_files:
            return
        
        audio_file = audio_files[0]
        audio_file_id = audio_file.get('id')
        
        # Aktualisiere Offset in der Datenbank
        # Da es keine update_audio_file Methode gibt, müssen wir direkt SQL verwenden
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE audio_files
            SET offset_sec = ?
            WHERE id = ?
        """, (offset_sec, audio_file_id))
        conn.commit()
        
        self.audio_offset_sec = offset_sec
        print(f"Offset aktualisiert: {offset_sec}s ({offset_text})")
    
    def _on_offset_focus_lost(self, instance, value):
        """Wird aufgerufen, wenn der Offset-Input den Fokus verliert."""
        if not value:  # Fokus verloren
            self._save_offset(instance)
    
    def _highlight_active_part(self, active_part_id: Optional[int]):
        """Hervorhebt den aktiven Songteil in der Liste."""
        if not hasattr(self, '_part_labels') or not self._part_labels:
            return
        
        # Setze alle Labels zurück (stelle ursprüngliche Farben wieder her)
        for part_id, labels in self._part_labels.items():
            if not labels:
                continue
            part_name = labels[0].text if labels else ""
            part_name_lower = part_name.lower()
            
            # Bestimme ursprüngliche Farben
            if "refrain" in part_name_lower or "chorus" in part_name_lower:
                text_color = (0.0, 0.0, 0.0, 1.0)  # Schwarz
                bg_color = (1.0, 1.0, 1.0, 1.0)  # Weiß
            elif "strophe" in part_name_lower or "verse" in part_name_lower:
                text_color = (1.0, 1.0, 1.0, 1.0)  # Weiß
                bg_color = (0.0, 0.0, 0.0, 1.0)  # Schwarz
            else:
                text_color = (1.0, 1.0, 1.0, 1.0)  # Weiß
                bg_color = (0.3, 0.3, 0.3, 1.0)  # Dunkelgrau
            
            for label in labels:
                # Stelle ursprünglichen Hintergrund wieder her
                if hasattr(label, 'canvas') and hasattr(label.canvas, 'before'):
                    label.canvas.before.clear()
                    from kivy.graphics import Color as GColor, Rectangle
                    with label.canvas.before:
                        GColor(*bg_color)
                        bg_rect = Rectangle(pos=label.pos, size=label.size)
                    
                    def update_bg(instance, value):
                        if hasattr(instance, '_bg_rect'):
                            instance._bg_rect.pos = instance.pos
                            instance._bg_rect.size = instance.size
                    
                    label._bg_rect = bg_rect
                    label.bind(pos=update_bg, size=update_bg)
                label.color = text_color
        
        # Hervorhebe aktiven Teil mit hellblauem Hintergrund
        if active_part_id and active_part_id in self._part_labels:
            labels = self._part_labels[active_part_id]
            # Bestimme Textfarbe basierend auf Songteil-Typ
            part_name = labels[0].text if labels else ""
            part_name_lower = part_name.lower()
            if "refrain" in part_name_lower or "chorus" in part_name_lower:
                text_color = (0.0, 0.0, 0.0, 1.0)  # Schwarz
            elif "strophe" in part_name_lower or "verse" in part_name_lower:
                text_color = (1.0, 1.0, 1.0, 1.0)  # Weiß
            else:
                text_color = (0, 0, 0, 1)  # Schwarz für besseren Kontrast auf hellblauem Hintergrund
            
            for label in labels:
                # Überschreibe Hintergrund mit hellblau
                if hasattr(label, 'canvas') and hasattr(label.canvas, 'before'):
                    label.canvas.before.clear()
                    from kivy.graphics import Color as GColor, Rectangle
                    with label.canvas.before:
                        GColor(0.2, 0.6, 0.9, 0.5)  # Hellblau
                        bg_rect = Rectangle(pos=label.pos, size=label.size)
                    
                    def update_bg(instance, value):
                        if hasattr(instance, '_bg_rect'):
                            instance._bg_rect.pos = instance.pos
                            instance._bg_rect.size = instance.size
                    
                    label._bg_rect = bg_rect
                    label.bind(pos=update_bg, size=update_bg)
                label.color = text_color



