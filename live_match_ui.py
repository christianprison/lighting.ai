"""
live_match_ui.py

Kivy-UI zum Live-Matching von Takten:

- Empfängt OSC-Meter-Values vom XR18 über `OSCListener`
- Nutzt `BeatDetector`, um Beats zu erkennen und Takte zu zählen
- Erzeugt pro Beat einen Feature-Vektor aus der Meter-History
- Fragt den Annoy-Index über `LiveBarMatcher` ab
- Zeigt den wahrscheinlichsten Song / Songteil im UI an
"""

from typing import Dict, List
import time

from kivy.app import App
from kivy.config import Config
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.clock import Clock

from database import Database
from osc_listener import OSCListener
from beat_detection import BeatDetector
from live_matcher import LiveBarMatcher


class LiveMatchRoot(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.padding = 20
        self.spacing = 20

        # Statuszeile
        self.status_label = Label(
            text="OSC/Beat: nicht gestartet",
            font_size="32sp",
            size_hint_y=None,
            height=60,
        )
        self.add_widget(self.status_label)

        # Aktueller Beat/Takt
        self.bar_label = Label(
            text="Takt: - | Beat: -",
            font_size="40sp",
            size_hint_y=None,
            height=80,
        )
        self.add_widget(self.bar_label)

        # Match-Ergebnis
        self.match_title_label = Label(
            text="Song: -",
            font_size="48sp",
            size_hint_y=None,
            height=90,
        )
        self.add_widget(self.match_title_label)

        self.match_part_label = Label(
            text="Teil: -",
            font_size="40sp",
            size_hint_y=None,
            height=80,
        )
        self.add_widget(self.match_part_label)

        self.match_meta_label = Label(
            text="Datum: - | Distanz: -",
            font_size="32sp",
            size_hint_y=None,
            height=70,
        )
        self.add_widget(self.match_meta_label)

        # Buttons
        btn_bar = BoxLayout(orientation="horizontal", size_hint_y=None, height=80, spacing=20)
        self.btn_start = Button(text="Start", font_size="32sp")
        self.btn_start.bind(on_press=lambda _: self.start_matching())
        btn_bar.add_widget(self.btn_start)

        self.btn_stop = Button(text="Stop", font_size="32sp")
        self.btn_stop.bind(on_press=lambda _: self.stop_matching())
        btn_bar.add_widget(self.btn_stop)

        self.add_widget(btn_bar)

        # Technik
        self.db = Database()
        self.feature_dim = 32
        self.matcher = LiveBarMatcher(feature_dim=self.feature_dim)

        self.osc: OSCListener | None = None
        self.beat_detector: BeatDetector | None = None
        self.meter_history: List[Dict[int, float]] = []
        self.current_bar = 1
        self.current_beat_in_bar = 0
        self.beats_per_bar = 4
        self.start_time = time.time()

    # ------------------------------------------------------------------ #
    # Start / Stop
    # ------------------------------------------------------------------ #

    def start_matching(self):
        if self.osc is not None and self.osc.is_running():
            return

        self.osc = OSCListener()
        self.beat_detector = BeatDetector()
        self.osc.set_meter_callback(self._on_meter_update)
        self.beat_detector.set_beat_callback(self._on_beat)

        self.meter_history.clear()
        self.current_bar = 1
        self.current_beat_in_bar = 0
        self.start_time = time.time()

        try:
            self.osc.start()
            self.status_label.text = "OSC/Beat: läuft"
        except Exception as e:
            self.status_label.text = f"Fehler beim Start: {e}"

    def stop_matching(self):
        if self.osc:
            self.osc.stop()
            self.osc = None
        self.status_label.text = "OSC/Beat: gestoppt"

    # ------------------------------------------------------------------ #
    # Callbacks
    # ------------------------------------------------------------------ #

    def _on_meter_update(self, meters: Dict[int, float]):
        """OSCListener-Callback."""
        if self.beat_detector:
            self.beat_detector.update_meters(meters)
        # für Feature-Vektor
        self.meter_history.append(meters)
        # History begrenzen
        if len(self.meter_history) > 100:
            self.meter_history = self.meter_history[-100:]

    def _on_beat(self, beat_time: float):
        """BeatDetector-Callback."""
        self.current_beat_in_bar += 1
        if self.current_beat_in_bar > self.beats_per_bar:
            self.current_beat_in_bar = 1
            self.current_bar += 1

        timestamp_sec = beat_time - self.start_time

        features = self._build_feature_vector()
        self.bar_label.text = f"Takt: {self.current_bar} | Beat: {self.current_beat_in_bar}"

        # Matching
        result = self.matcher.match_live_bar(
            features=features,
            bar=self.current_bar,
            beat_in_bar=self.current_beat_in_bar,
            timestamp_sec=timestamp_sec,
            top_k=10,
        )

        if result:
            self.match_title_label.text = f"Song: {result.song_title}"
            self.match_part_label.text = f"Teil: {result.song_part or '-'}"
            self.match_meta_label.text = (
                f"Datum: {result.recording_date or '-'} | Distanz: {result.distance:.4f}"
            )
        else:
            self.match_title_label.text = "Song: (kein Match)"
            self.match_part_label.text = "Teil: -"
            self.match_meta_label.text = "Datum: - | Distanz: -"

    # ------------------------------------------------------------------ #
    # Features
    # ------------------------------------------------------------------ #

    def _build_feature_vector(self) -> List[float]:
        """
        Erzeugt einen Feature-Vektor aus der aktuellen Meter-History.
        Hier: sehr einfache Mittelwert/Varianz-basierten Features.
        """
        window_size = 10
        if len(self.meter_history) < window_size:
            return [0.0] * self.feature_dim

        window = self.meter_history[-window_size:]
        all_channels = sorted({ch for snap in window for ch in snap.keys()})
        max_channels = min(len(all_channels), self.feature_dim)
        features: List[float] = []

        for ch in all_channels[:max_channels]:
            values = [snap.get(ch, 0.0) for snap in window]
            mean_val = sum(values) / len(values)
            var_val = sum((v - mean_val) ** 2 for v in values) / len(values)
            features.append(mean_val)
            if len(features) < self.feature_dim:
                features.append(var_val)

        while len(features) < self.feature_dim:
            features.append(0.0)

        return features[:self.feature_dim]


class LiveMatchApp(App):
    def build(self):
        self.title = "lighting.ai - Live Match"
        return LiveMatchRoot()

    def on_stop(self):
        # Aufräumen erledigt root via stop_matching / Database.close im GC
        pass


if __name__ == "__main__":
    # Fenstergröße anpassen
    Config.set("graphics", "width", "1920")
    Config.set("graphics", "height", "1080")
    Config.set("graphics", "resizable", "1")
    LiveMatchApp().run()


