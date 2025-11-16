"""
Blinkender Beat-Indikator zur Visualisierung der Beat-Detection-Ergebnisse
"""
from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse
from kivy.clock import Clock
from typing import Optional


class BeatIndicator(Widget):
    """Blinkender Punkt zur Visualisierung erkannt er Beats."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (None, None)
        self.size = (20, 20)  # Mindestens 10 Pixel Durchmesser (hier 20)
        self.beat_active = False
        self.blink_animation = None
        
        # Farben
        self.color_active = (1.0, 0.2, 0.2, 1.0)  # Rot wenn Beat erkannt
        self.color_inactive = (0.3, 0.3, 0.3, 0.5)  # Grau wenn kein Beat
        
        self.bind(size=self._update_canvas, pos=self._update_canvas)
        self._update_canvas()
    
    def _update_canvas(self, *args):
        """Aktualisiert die Canvas-Zeichnung."""
        self.canvas.clear()
        
        if self.width == 0 or self.height == 0:
            return
        
        with self.canvas:
            # Zeichne Kreis
            if self.beat_active:
                Color(*self.color_active)
            else:
                Color(*self.color_inactive)
            
            # Zentriere den Kreis
            center_x = self.x + self.width / 2
            center_y = self.y + self.height / 2
            radius = min(self.width, self.height) / 2
            
            Ellipse(
                pos=(center_x - radius, center_y - radius),
                size=(radius * 2, radius * 2)
            )
    
    def trigger_beat(self):
        """Wird aufgerufen wenn ein Beat erkannt wurde."""
        self.beat_active = True
        self._update_canvas()
        
        # Starte Blink-Animation: nach 100ms wieder aus
        if self.blink_animation:
            Clock.unschedule(self.blink_animation)
        
        self.blink_animation = Clock.schedule_once(
            lambda dt: self._reset_beat(),
            0.1  # 100ms blinken
        )
    
    def _reset_beat(self):
        """Setzt den Beat-Indikator zurück."""
        self.beat_active = False
        self._update_canvas()
        self.blink_animation = None

