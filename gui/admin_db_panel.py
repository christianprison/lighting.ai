"""
Admin-Panel für die Wartung der SQLite-Datenbank.

Version 1: Fokus auf Song-Stammdaten (Tabelle `songs`):
- Liste aller Songs
- Hinzufügen / Bearbeiten von Name, Artist, BPM, Dauer, Notizen
"""

from typing import Optional, List, Dict
import io
import tempfile
from pathlib import Path

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

    def _build_ui(self):
        # Hauptlayout: Oben Tabellen (4/5), unten Zeitstrahl (1/5)
        main_layout = BoxLayout(orientation="vertical", spacing=10)
        
        # Obere Hälfte: Tabellen (4/5 der Höhe)
        tables_container = BoxLayout(orientation="horizontal", spacing=20, size_hint_y=0.8)
        
        # Linke Seite: Songliste (1/4 der Breite)
        list_container = BoxLayout(orientation="vertical", size_hint_x=0.25)

        scroll = ScrollView()
        # Spalten: Titel | BPM (ohne Songteile-Spalte)
        self.song_list_grid = GridLayout(
            cols=2, spacing=10, size_hint_y=None
        )
        self.song_list_grid.bind(
            minimum_height=self.song_list_grid.setter("height")
        )
        scroll.add_widget(self.song_list_grid)
        list_container.add_widget(scroll)

        tables_container.add_widget(list_container)

        # Rechte Seite: Songteile (3/4 der Breite)
        part_container = BoxLayout(orientation="vertical", size_hint_x=0.75)

        part_scroll = ScrollView()
        # Spalten: Songteil | Startzeit (mm:ss) | Dauer (mm:ss) | Takte
        self.part_list_grid = GridLayout(cols=5, spacing=10, size_hint_y=None)
        self.part_list_grid.bind(
            minimum_height=self.part_list_grid.setter("height")
        )
        part_scroll.add_widget(self.part_list_grid)
        part_container.add_widget(part_scroll)

        tables_container.add_widget(part_container)
        main_layout.add_widget(tables_container)
        
        # Unteres Fünftel: Zeitstrahl-Bereich (1/5 der Höhe)
        timeline_container = BoxLayout(
            orientation="vertical",
            size_hint_y=0.2,
            padding=10,
            spacing=10
        )
        
        # Header mit Play/Pause-Button und Offset-Anzeige
        timeline_header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=50,
            spacing=15
        )
        
        # Linke Seite: Play-Button, Beat-Indikator und Offset
        left_side = BoxLayout(
            orientation="vertical",
            size_hint_x=None,
            width=200,
            spacing=5
        )
        
        # Play/Pause-Button
        # Prüfe pygame zur Laufzeit
        pygame_available = _check_pygame_available()
        self.play_pause_button = Button(
            text="▶ Abspielen",
            font_size="24sp",
            size_hint_y=None,
            height=40,
            background_color=(0.2, 0.8, 0.2, 1) if pygame_available else (0.5, 0.5, 0.5, 1)
        )
        self.play_pause_button.bind(on_press=self._toggle_audio_playback)
        if not pygame_available:
            self.play_pause_button.disabled = True
            self.play_pause_button.text = "Audio nicht verfügbar"
        left_side.add_widget(self.play_pause_button)
        
        # Beat-Indikator mit Label
        beat_container = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=50,
            spacing=2
        )
        
        # Label "beat"
        beat_label = Label(
            text="beat",
            font_size="14sp",
            size_hint_y=None,
            height=20,
            halign='center'
        )
        beat_label.bind(texture_size=beat_label.setter('size'))
        beat_container.add_widget(beat_label)
        
        # Beat-Indikator (blinkender Punkt)
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
        beat_indicator_container.add_widget(Label(size_hint_x=1.0))  # Spacer links
        beat_indicator_container.add_widget(self.beat_indicator)
        beat_indicator_container.add_widget(Label(size_hint_x=1.0))  # Spacer rechts
        beat_container.add_widget(beat_indicator_container)
        
        left_side.add_widget(beat_container)
        
        # Offset-Anzeige (editierbar)
        offset_layout = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=30,
            spacing=5
        )
        offset_label = Label(
            text="Offset:",
            font_size="14sp",
            size_hint_x=None,
            width=50
        )
        offset_layout.add_widget(offset_label)
        
        self.offset_input = TextInput(
            text="0.000",
            font_size="14sp",
            multiline=False,
            size_hint_x=1.0,
            size_hint_y=None,
            height=30,
            padding=[5, 5],
            hint_text="Sek.Millisek (z.B. 5.250)"
        )
        self.offset_input.bind(on_text_validate=self._save_offset)
        self.offset_input.bind(focus=self._on_offset_focus_lost)
        offset_layout.add_widget(self.offset_input)
        left_side.add_widget(offset_layout)
        
        timeline_header.add_widget(left_side)
        
        timeline_label = Label(
            text="Zeitstrahl (Songteile über Zeit)",
            font_size="20sp",
            size_hint_x=1.0,
            halign='left',
            bold=True
        )
        timeline_header.add_widget(timeline_label)
        
        timeline_container.add_widget(timeline_header)
        
        # Timeline-Widget
        self.timeline_widget = TimelineWidget()
        timeline_container.add_widget(self.timeline_widget)
        
        main_layout.add_widget(timeline_container)
        
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

        # Header (nur Titel und BPM, keine Songteile-Spalte)
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
                halign='left',
                text_size=(None, None),
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
            
            # Titel (editierbar per Doppelklick)
            item = SongListItem(
                admin_panel=self,
                song_id=song_id,
                text=name,
                font_size="22sp",
                size_hint_y=None,
                height=40,
            )
            self.song_list_grid.add_widget(item)
            self.song_items[song_id] = item
            
            # BPM (editierbar per Doppelklick)
            bpm_label = Label(
                text=bpm_text,
                font_size="22sp",
                size_hint_y=None,
                height=40,
                halign='left',
                text_size=(None, None),
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

        # Header: Songteil | Startzeit | Dauer | Takte
        self.part_list_grid.add_widget(
            Label(
                text="Songteil",
                font_size="22sp",
                bold=True,
                size_hint_y=None,
                height=40,
                halign='left',
                text_size=(None, None),
            )
        )
        self.part_list_grid.add_widget(
            Label(
                text="Startzeit",
                font_size="22sp",
                bold=True,
                size_hint_y=None,
                height=40,
                halign='left',
                text_size=(None, None),
            )
        )
        self.part_list_grid.add_widget(
            Label(
                text="Dauer",
                font_size="22sp",
                bold=True,
                size_hint_y=None,
                height=40,
                halign='left',
                text_size=(None, None),
            )
        )
        self.part_list_grid.add_widget(
            Label(
                text="Takte",
                font_size="22sp",
                bold=True,
                size_hint_y=None,
                height=40,
                halign='left',
                text_size=(None, None),
            )
        )
        self.part_list_grid.add_widget(
            Label(
                text="Aktion",
                font_size="22sp",
                bold=True,
                size_hint_y=None,
                height=40,
                halign='left',
                text_size=(None, None),
            )
        )

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
            
            # Songteil-Name
            part_name_label = create_label_with_bg(part_name, bg_color, text_color)
            part_name_label._field_name = "part_name"
            part_name_label.bind(on_touch_down=on_label_double_click)
            self.part_list_grid.add_widget(part_name_label)

            # Startzeit
            start_time_label = create_label_with_bg(start_time_str, bg_color, text_color)
            start_time_label._field_name = "start_ms"
            start_time_label.bind(on_touch_down=on_label_double_click)
            self.part_list_grid.add_widget(start_time_label)

            # Dauer
            duration_label = create_label_with_bg(duration_str, bg_color, text_color)
            duration_label._field_name = "duration_ms"
            duration_label.bind(on_touch_down=on_label_double_click)
            self.part_list_grid.add_widget(duration_label)

            # Takte
            bars_label = create_label_with_bg(bars_str, bg_color, text_color)
            bars_label._field_name = "bars"
            bars_label.bind(on_touch_down=on_label_double_click)
            self.part_list_grid.add_widget(bars_label)

            # Löschen-Button
            from kivy.uix.button import Button
            delete_button = Button(
                text="🗑",
                font_size="20sp",
                size_hint_y=None,
                height=40,
                size_hint_x=None,
                width=60,
                background_color=(0.8, 0.2, 0.2, 1.0)
            )
            delete_button._part_id = part["id"]
            delete_button._part_name = part_name
            delete_button._admin_panel = self
            delete_button.bind(on_press=self._on_delete_part_click)
            self.part_list_grid.add_widget(delete_button)

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
    
    def _on_delete_part_click(self, instance):
        """Wird aufgerufen, wenn der Löschen-Button geklickt wird."""
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
            
            # Setze Position auf Offset (funktioniert nur mit OGG, bei MP3 wird es ignoriert)
            # Für MP3 müssen wir die Position manuell tracken
            if self.audio_offset_sec > 0:
                try:
                    pygame.mixer.music.set_pos(self.audio_offset_sec)
                except:
                    # set_pos funktioniert nicht mit MP3, wir tracken die Position manuell
                    pass
            
            # Startzeit für Position-Tracking
            # Bei Offset: Startzeit wird um Offset reduziert, damit Songteile bei 0 beginnen
            import time
            self.audio_start_time = time.time() - self.audio_offset_sec
            self.audio_paused_position_ms = 0
            
            # Beat-Detection für Audio-Datei (asynchron starten)
            self.quarter_notes: List[float] = []  # Viertelnoten-Zeitpunkte in Sekunden
            self.current_quarter_index: int = 0
            # Starte Beat-Detection im Hintergrund (kann etwas dauern)
            Clock.schedule_once(lambda dt: self._analyze_audio_beats(audio_file, song), 0.1)
            
            self.audio_playing = True
            self.play_pause_button.text = "⏸ Pausieren"
            self.play_pause_button.background_color = (0.8, 0.2, 0.2, 1)
            
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
        self.play_pause_button.text = "▶ Abspielen"
        self.play_pause_button.background_color = (0.2, 0.8, 0.2, 1)
        
        Clock.unschedule(self._check_audio_status)
        Clock.unschedule(self._update_timeline_position)
        
        # Setze Beat-Detection-Variablen zurück
        self.quarter_notes = []
        self.current_quarter_index = 0
        
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
    
    def _analyze_audio_beats(self, audio_file: Dict, song: Dict):
        """Analysiert die Audio-Datei auf Beats/Viertelnoten."""
        if not self.temp_audio_file or not self.temp_audio_file.exists():
            return
        
        try:
            from audio_beat_detection import detect_beats_from_audio, get_quarter_notes_from_beats
            
            bpm = song.get("bpm")
            offset_sec = audio_file.get('offset_sec', 0.0) or 0.0
            
            # Erkenne Beats aus Audio-Datei
            beat_times, detected_bpm = detect_beats_from_audio(
                self.temp_audio_file,
                bpm_hint=bpm,
                offset_sec=offset_sec
            )
            
            if beat_times:
                # Konvertiere zu Viertelnoten
                self.quarter_notes = get_quarter_notes_from_beats(beat_times, detected_bpm or bpm)
                self.current_quarter_index = 0
                print(f"Beat-Detection: {len(self.quarter_notes)} Viertelnoten erkannt")
            else:
                print("Keine Beats erkannt, verwende Zeit-basierte Position")
                self.quarter_notes = []
        except ImportError:
            print("librosa nicht verfügbar, verwende Zeit-basierte Position")
            self.quarter_notes = []
        except Exception as e:
            print(f"Fehler bei Beat-Detection: {e}")
            import traceback
            traceback.print_exc()
            self.quarter_notes = []
    
    def _update_timeline_position(self, dt):
        """Aktualisiert die Position im Zeitstrahl basierend auf der Audio-Wiedergabe und Beat-Detection."""
        if not self.audio_playing or not self.audio_start_time:
            return
        
        try:
            import time
            
            # Berechne verstrichene Zeit seit Start (ohne Offset, da Songteile bei 0 beginnen)
            elapsed_seconds = time.time() - self.audio_start_time
            
            # Wenn Beat-Detection verfügbar ist, verwende erkannte Viertelnoten
            if self.quarter_notes:
                # Finde die nächste Viertelnote basierend auf verstrichener Zeit
                prev_index = self.current_quarter_index
                new_beats_detected = False
                
                while (self.current_quarter_index < len(self.quarter_notes) and
                       self.quarter_notes[self.current_quarter_index] <= elapsed_seconds):
                    # Beat erkannt
                    new_beats_detected = True
                    self.current_quarter_index += 1
                
                # Trigger Beat-Indikator wenn neuer Beat erkannt wurde
                if new_beats_detected and hasattr(self, 'beat_indicator') and self.beat_indicator:
                    self.beat_indicator.trigger_beat()
                
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
                # Fallback: Zeit-basierte Position
                current_position_ms = int((self.audio_paused_position_ms / 1000.0 + elapsed_seconds) * 1000)
            
            # Aktualisiere Timeline (Songteile beginnen bei 0, Offset wird nicht berücksichtigt)
            if self.timeline_widget:
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



