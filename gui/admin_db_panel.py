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

# Audio-Wiedergabe mit pygame
try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
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
        
        # Audio-Wiedergabe
        self.audio_playing = False
        self.audio_file_path: Optional[Path] = None
        self.temp_audio_file: Optional[Path] = None

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
        self.part_list_grid = GridLayout(cols=4, spacing=10, size_hint_y=None)
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
        
        # Header mit Play/Pause-Button
        timeline_header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=50,
            spacing=15
        )
        
        # Play/Pause-Button (links)
        self.play_pause_button = Button(
            text="▶ Abspielen",
            font_size="24sp",
            size_hint_x=None,
            width=200,
            size_hint_y=None,
            height=50,
            background_color=(0.2, 0.8, 0.2, 1) if PYGAME_AVAILABLE else (0.5, 0.5, 0.5, 1)
        )
        self.play_pause_button.bind(on_press=self._toggle_audio_playback)
        if not PYGAME_AVAILABLE:
            self.play_pause_button.disabled = True
            self.play_pause_button.text = "Audio nicht verfügbar"
        timeline_header.add_widget(self.play_pause_button)
        
        timeline_label = Label(
            text="Zeitstrahl (Songteile über Zeit)",
            font_size="20sp",
            size_hint_x=1.0,
            halign='left',
            bold=True
        )
        timeline_header.add_widget(timeline_label)
        
        timeline_container.add_widget(timeline_header)
        
        # Platzhalter für den Zeitstrahl (später zu implementieren)
        self.timeline_widget = Label(
            text="Zeitstrahl wird hier angezeigt",
            font_size="16sp",
            halign='left',
            valign='top'
        )
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
            # BPM als Ganzzahl (Integer) darstellen
            if bpm_val is None:
                bpm_text = ""
            else:
                bpm_text = str(int(round(bpm_val)))
            
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
            self.song_list_grid.add_widget(
                Label(
                    text=bpm_text,
                    font_size="22sp",
                    size_hint_y=None,
                    height=40,
                    halign='left',
                    text_size=(None, None),
                )
            )

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

            # Songteil-Name als Label (nicht farblich hinterlegt)
            self.part_list_grid.add_widget(
                Label(
                    text=part_name,
                    font_size="20sp",
                    size_hint_y=None,
                    height=40,
                    halign='left',
                    text_size=(None, None),
                )
            )

            # Startzeit
            self.part_list_grid.add_widget(
                Label(
                    text=start_time_str,
                    font_size="20sp",
                    size_hint_y=None,
                    height=40,
                    halign='left',
                    text_size=(None, None),
                )
            )

            # Dauer
            self.part_list_grid.add_widget(
                Label(
                    text=duration_str,
                    font_size="20sp",
                    size_hint_y=None,
                    height=40,
                    halign='left',
                    text_size=(None, None),
                )
            )

            # Takte
            self.part_list_grid.add_widget(
                Label(
                    text=bars_str,
                    font_size="20sp",
                    size_hint_y=None,
                    height=40,
                    halign='left',
                    text_size=(None, None),
                )
            )

            self._part_rows.append(
                {
                    "id": part["id"],
                    "part_name": part_name,
                }
            )
    
    # ------------------------------------------------------------------ #
    # Audio-Wiedergabe
    # ------------------------------------------------------------------ #
    
    def _toggle_audio_playback(self, instance):
        """Schaltet Audio-Wiedergabe ein/aus."""
        if not PYGAME_AVAILABLE:
            return
        
        if not self.current_song_id:
            return
        
        if self.audio_playing:
            self._stop_audio()
        else:
            self._start_audio()
    
    def _start_audio(self):
        """Startet die Audio-Wiedergabe für den aktuellen Song."""
        if not PYGAME_AVAILABLE or not self.current_song_id:
            return
        
        # Hole Audiofiles für den Song
        audio_files = self.db.get_audio_files_for_song(self.current_song_id)
        if not audio_files:
            print("Keine Audiodatei für diesen Song gefunden")
            return
        
        # Verwende die erste/neueste Audiodatei
        audio_file = audio_files[0]  # Oder sortiere nach recording_date
        
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
            
            self.audio_playing = True
            self.play_pause_button.text = "⏸ Pausieren"
            self.play_pause_button.background_color = (0.8, 0.2, 0.2, 1)
            
            # Überwache Wiedergabe-Ende
            Clock.schedule_interval(self._check_audio_status, 0.1)
            
        except Exception as e:
            print(f"Fehler beim Abspielen: {e}")
            self._stop_audio()
    
    def _stop_audio(self):
        """Stoppt die Audio-Wiedergabe."""
        if not PYGAME_AVAILABLE:
            return
        
        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
                pygame.mixer.quit()
        except:
            pass
        
        self.audio_playing = False
        self.play_pause_button.text = "▶ Abspielen"
        self.play_pause_button.background_color = (0.2, 0.8, 0.2, 1)
        
        Clock.unschedule(self._check_audio_status)
        
        # Lösche temporäre Datei
        if self.temp_audio_file and self.temp_audio_file.exists():
            try:
                self.temp_audio_file.unlink()
            except:
                pass
            self.temp_audio_file = None
    
    def _check_audio_status(self, dt):
        """Prüft ob Audio noch läuft."""
        if not PYGAME_AVAILABLE:
            return False
        
        try:
            if not pygame.mixer.music.get_busy():
                # Wiedergabe beendet
                self._stop_audio()
                return False
        except:
            self._stop_audio()
            return False
        
        return True



