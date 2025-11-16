"""
Timeline-Widget zur Darstellung von Songteilen als Balken mit Zeiger.
"""

from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle, Line
from kivy.clock import Clock
from typing import List, Dict, Optional
import time


class TimelineWidget(Widget):
    """Zeitstrahl-Widget, das Songteile als Balken darstellt."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.song_parts: List[Dict] = []
        self.current_position_ms: int = 0  # Aktuelle Position in Millisekunden
        self.total_duration_ms: int = 0  # Gesamtdauer des Songs
        self.active_part_id: Optional[int] = None
        self.pixels_per_second = 10  # 10 Pixel pro Sekunde
        
        # Farben
        self.color_pointer = (1.0, 0.2, 0.2, 1.0)  # Rot für Zeiger
        self.color_border = (1.0, 1.0, 1.0, 1.0)  # Weiß für Rahmen
        # Farben werden basierend auf Songteil-Typ bestimmt
        
        self.bind(size=self._update_canvas, pos=self._update_canvas)
    
    def set_song_parts(self, parts: List[Dict]):
        """Setzt die Songteile für die Anzeige."""
        self.song_parts = sorted(parts, key=lambda p: p.get("start_ms", 0) or 0)
        
        # Berechne Gesamtdauer
        if self.song_parts:
            last_part = max(self.song_parts, key=lambda p: p.get("end_ms", 0) or 0)
            self.total_duration_ms = last_part.get("end_ms", 0) or 0
        else:
            self.total_duration_ms = 0
        
        self._update_canvas()
    
    def set_position(self, position_ms: int):
        """Setzt die aktuelle Position im Zeitstrahl."""
        self.current_position_ms = position_ms
        
        # Bestimme aktiven Songteil
        self.active_part_id = None
        for part in self.song_parts:
            start_ms = part.get("start_ms", 0) or 0
            end_ms = part.get("end_ms", 0) or 0
            
            if start_ms <= position_ms <= end_ms:
                self.active_part_id = part.get("id")
                break
        
        self._update_canvas()
    
    def _update_canvas(self, *args):
        """Aktualisiert die Canvas-Zeichnung."""
        self.canvas.clear()
        
        if not self.song_parts or self.total_duration_ms == 0 or self.width == 0:
            return
        
        with self.canvas:
            # Berechne Skalierung: 10 Pixel pro Sekunde
            total_width_pixels = (self.total_duration_ms / 1000.0) * self.pixels_per_second
            # Skaliere so, dass alles sichtbar ist, aber mindestens 10px/sec
            if total_width_pixels > self.width:
                scale = self.width / total_width_pixels
            else:
                scale = 1.0
            
            # Zeichne Songteile als Balken
            y_start = self.y + self.height * 0.2
            bar_height = self.height * 0.6
            
            for part in self.song_parts:
                start_ms = part.get("start_ms", 0) or 0
                end_ms = part.get("end_ms", 0) or 0
                duration_ms = end_ms - start_ms
                
                if duration_ms <= 0:
                    continue
                
                # Position und Breite in Pixeln
                x_pos = self.x + (start_ms / 1000.0) * self.pixels_per_second * scale
                width = (duration_ms / 1000.0) * self.pixels_per_second * scale
                
                # Bestimme Farbe basierend auf Songteil-Typ
                part_name = (part.get("part_name") or "").lower()
                is_active = part.get("id") == self.active_part_id
                
                # Refrain/Chorus = weiß, Verse/Strophe = schwarz
                if "refrain" in part_name or "chorus" in part_name:
                    # Weiß mit schwarzer Schrift (für später)
                    bg_color = (1.0, 1.0, 1.0, 1.0)  # Weiß
                    if is_active:
                        bg_color = (0.9, 0.9, 0.9, 1.0)  # Leicht grau wenn aktiv
                elif "strophe" in part_name or "verse" in part_name:
                    # Schwarz mit weißer Schrift
                    bg_color = (0.0, 0.0, 0.0, 1.0)  # Schwarz
                    if is_active:
                        bg_color = (0.2, 0.2, 0.2, 1.0)  # Leicht grau wenn aktiv
                else:
                    # Standard: Grau
                    bg_color = (0.5, 0.5, 0.5, 0.7)  # Grau
                    if is_active:
                        bg_color = (0.2, 0.6, 0.9, 0.7)  # Blau wenn aktiv
                
                # Zeichne Balken
                Color(*bg_color)
                Rectangle(pos=(x_pos, y_start), size=(width, bar_height))
                
                # Zeichne weißen Rahmen
                Color(*self.color_border)
                # Oben
                Line(points=[x_pos, y_start + bar_height, x_pos + width, y_start + bar_height], width=1)
                # Unten
                Line(points=[x_pos, y_start, x_pos + width, y_start], width=1)
                # Links
                Line(points=[x_pos, y_start, x_pos, y_start + bar_height], width=1)
                # Rechts
                Line(points=[x_pos + width, y_start, x_pos + width, y_start + bar_height], width=1)
            
            # Zeichne Zeiger
            if self.current_position_ms > 0:
                pointer_x = self.x + (self.current_position_ms / 1000.0) * self.pixels_per_second * scale
                Color(*self.color_pointer)
                Line(points=[pointer_x, self.y, pointer_x, self.y + self.height], width=2)
    
    def get_active_part_id(self) -> Optional[int]:
        """Gibt die ID des aktiven Songteils zurück."""
        return self.active_part_id

