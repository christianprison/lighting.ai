"""
Timeline-Widget zur Darstellung von Songteilen als Balken mit Zeiger.
"""

from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle, Line
from kivy.graphics.texture import Texture
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
        self.pixels_per_second = 20  # 20 Pixel pro Sekunde (halbiert)
        self.bpm: Optional[int] = None  # BPM des Songs für Skala
        
        # Farben
        self.color_pointer = (1.0, 0.2, 0.2, 1.0)  # Rot für Zeiger
        self.color_border = (1.0, 1.0, 1.0, 1.0)  # Weiß für Rahmen
        self.color_scale = (0.8, 0.8, 0.8, 1.0)  # Grau für Skala
        # Farben werden basierend auf Songteil-Typ bestimmt
        
        self.bind(size=self._update_canvas, pos=self._update_canvas)
    
    def set_song_parts(self, parts: List[Dict], bpm: Optional[int] = None):
        """Setzt die Songteile für die Anzeige."""
        self.song_parts = sorted(parts, key=lambda p: p.get("start_ms", 0) or 0)
        self.bpm = bpm
        
        # Berechne Gesamtdauer
        if self.song_parts:
            last_part = max(self.song_parts, key=lambda p: p.get("end_ms", 0) or 0)
            self.total_duration_ms = last_part.get("end_ms", 0) or 0
        else:
            self.total_duration_ms = 0
        
        # Berechne Widget-Breite basierend auf Song-Länge für Scrollbarkeit
        if self.bpm and self.bpm > 0 and self.song_parts:
            ms_per_bar = 4 * (60000.0 / self.bpm)
            total_bars = 0
            for part in self.song_parts:
                bars = part.get("bars")
                if bars and bars > 0:
                    total_bars += bars
                else:
                    start_ms = part.get("start_ms", 0) or 0
                    end_ms = part.get("end_ms", 0) or 0
                    if end_ms > start_ms:
                        total_bars += int((end_ms - start_ms) / ms_per_bar)
            
            # Berechne benötigte Breite in Pixeln
            total_width_pixels = (total_bars * ms_per_bar / 1000.0) * self.pixels_per_second
            # Setze Widget-Breite (mindestens verfügbare Breite)
            if hasattr(self, 'parent') and self.parent:
                min_width = self.parent.width if hasattr(self.parent, 'width') else 800
            else:
                min_width = 800
            
            self.size_hint_x = None
            self.width = max(min_width, total_width_pixels)
        else:
            # Fallback: Zeit-basiert
            if self.total_duration_ms > 0:
                total_width_pixels = (self.total_duration_ms / 1000.0) * self.pixels_per_second
                if hasattr(self, 'parent') and self.parent:
                    min_width = self.parent.width if hasattr(self.parent, 'width') else 800
                else:
                    min_width = 800
                self.size_hint_x = None
                self.width = max(min_width, total_width_pixels)
            else:
                self.size_hint_x = 1.0
        
        self._update_canvas()
    
    def set_position(self, position_ms: int, active_part_id: Optional[int] = None):
        """Setzt die aktuelle Position im Zeitstrahl.
        
        Args:
            position_ms: Position in Millisekunden
            active_part_id: Optional: ID des aktiven Songteils (wird gesetzt, wenn nicht None)
        """
        self.current_position_ms = position_ms
        
        # Wenn active_part_id explizit gesetzt wurde, verwende diesen
        if active_part_id is not None:
            self.active_part_id = active_part_id
        else:
            # Bestimme aktiven Songteil automatisch basierend auf Position
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
            # Berechne Skalierung basierend auf Takten, wenn BPM vorhanden
            if self.bpm and self.bpm > 0:
                ms_per_bar = 4 * (60000.0 / self.bpm)
                # Berechne Gesamtzahl der Takte
                total_bars = 0
                for part in self.song_parts:
                    bars = part.get("bars")
                    if bars and bars > 0:
                        total_bars += bars
                    else:
                        # Fallback: Berechne aus Zeit
                        start_ms = part.get("start_ms", 0) or 0
                        end_ms = part.get("end_ms", 0) or 0
                        if end_ms > start_ms:
                            total_bars += int((end_ms - start_ms) / ms_per_bar)
                
                # Berechne Gesamtbreite basierend auf Takten
                total_width_pixels = (total_bars * ms_per_bar / 1000.0) * self.pixels_per_second
            else:
                # Fallback: Zeit-basiert
                total_width_pixels = (self.total_duration_ms / 1000.0) * self.pixels_per_second
            
            # Skaliere so, dass alles sichtbar ist, aber mindestens 40px/sec
            if total_width_pixels > self.width:
                scale = self.width / total_width_pixels
            else:
                scale = 1.0
            
            # Zeichne Skala über den Balken (wenn BPM vorhanden)
            # Skala wird unten bündig gezeichnet, über den Balken
            scale_y_bottom = self.y + self.height * 0.1 + self.height * 0.3 + 2  # Untere Kante der Skala (über den Balken)
            scale_y_normal_top = scale_y_bottom + 6  # Normale Markierung: 6px hoch
            scale_y_tall_top = scale_y_bottom + 12  # Hohe Markierung: 12px hoch
            
            if self.bpm and self.bpm > 0:
                # Berechne Dauer einer Viertelnote in Millisekunden
                quarter_note_ms = 60000.0 / self.bpm
                ms_per_bar = 4 * quarter_note_ms  # Ein Takt = 4 Viertelnoten
                
                # Berechne kumulative Taktnummer über alle Songteile
                cumulative_bar = 0
                
                # Zeichne Skala für jeden Songteil
                for part in self.song_parts:
                    start_ms = part.get("start_ms", 0) or 0
                    end_ms = part.get("end_ms", 0) or 0
                    bars = part.get("bars")
                    
                    if end_ms <= start_ms:
                        continue
                    
                    # Startposition des Songteils in Pixeln (basierend auf kumulativer Taktposition)
                    # Berechne Position basierend auf Takten statt Zeit
                    part_x_start = self.x + (cumulative_bar * ms_per_bar / 1000.0) * self.pixels_per_second * scale
                    
                    # Zeichne Viertelnoten-Markierungen für diesen Songteil
                    current_bar_in_part = 0
                    bars_in_part = bars if bars and bars > 0 else int((end_ms - start_ms) / ms_per_bar)
                    
                    # Zeichne Taktnummer am Anfang jedes Songteils (nur beim ersten Takt)
                    if bars_in_part > 0:
                        first_bar_x_pos = self.x + (cumulative_bar * ms_per_bar / 1000.0) * self.pixels_per_second * scale
                        # Zeichne Taktnummer (16pt Schriftgröße) über der Skala
                        from kivy.core.text import Label as TextLabel
                        text_label = TextLabel(
                            text=str(cumulative_bar + 1),
                            font_size=16,
                            color=(0.8, 0.8, 0.8, 1.0)
                        )
                        text_label.refresh()
                        text_texture = text_label.texture
                        if text_texture:
                            Color(0.8, 0.8, 0.8, 1.0)
                            Rectangle(
                                texture=text_texture,
                                pos=(first_bar_x_pos - text_texture.width / 2, scale_y_tall_top + 2),
                                size=(text_texture.width, text_texture.height)
                            )
                    
                    for bar_in_part in range(bars_in_part):
                        # Position basierend auf Taktnummer
                        bar_x_pos = self.x + ((cumulative_bar + bar_in_part) * ms_per_bar / 1000.0) * self.pixels_per_second * scale
                        
                        # Zeichne Taktmarkierung (hoch) - unten bündig
                        Color(*self.color_scale)
                        Rectangle(pos=(bar_x_pos - 1, scale_y_bottom), size=(3, 12))
                        
                        # Zeichne Viertelnoten-Markierungen innerhalb des Takts
                        for quarter in range(4):
                            if quarter > 0:  # Erste Viertelnote ist bereits durch Taktmarkierung abgedeckt
                                quarter_x_pos = bar_x_pos + (quarter * quarter_note_ms / 1000.0) * self.pixels_per_second * scale
                                Color(*self.color_scale)
                                Rectangle(pos=(quarter_x_pos - 1, scale_y_bottom), size=(3, 6))
                    
                    # Aktualisiere kumulative Taktnummer
                    cumulative_bar += bars_in_part
            
            # Zeichne Songteile als Balken (Höhe halbiert)
            # Skala ist oben, dann kommen die Balken darunter
            scale_height = 20  # Platz für Skala oben
            y_start = self.y + self.height * 0.1
            bar_height = self.height * 0.3  # Halbiert von 0.6 auf 0.3
            
            # Berechne kumulative Taktnummer für Positionierung
            cumulative_bar = 0
            ms_per_bar = 4 * (60000.0 / self.bpm) if self.bpm and self.bpm > 0 else 1000.0
            
            for part in self.song_parts:
                start_ms = part.get("start_ms", 0) or 0
                end_ms = part.get("end_ms", 0) or 0
                bars = part.get("bars")
                
                if end_ms <= start_ms:
                    continue
                
                # Berechne Breite basierend auf Taktzahl statt Zeit
                if bars and bars > 0 and self.bpm and self.bpm > 0:
                    # Breite basierend auf Taktzahl
                    width = (bars * ms_per_bar / 1000.0) * self.pixels_per_second * scale
                    # Position basierend auf kumulativer Taktnummer
                    x_pos = self.x + (cumulative_bar * ms_per_bar / 1000.0) * self.pixels_per_second * scale
                    cumulative_bar += bars
                else:
                    # Fallback: Zeit-basiert wenn keine Takte vorhanden
                    duration_ms = end_ms - start_ms
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
                        bg_color = (1.0, 0.0, 1.0, 1.0)  # Magenta wenn aktiv (einheitlich)
                elif "strophe" in part_name or "verse" in part_name:
                    # Schwarz mit weißer Schrift
                    bg_color = (0.0, 0.0, 0.0, 1.0)  # Schwarz
                    if is_active:
                        bg_color = (1.0, 0.0, 1.0, 1.0)  # Magenta wenn aktiv (einheitlich)
                else:
                    # Standard: Grau
                    bg_color = (0.5, 0.5, 0.5, 0.7)  # Grau
                    if is_active:
                        bg_color = (1.0, 0.0, 1.0, 1.0)  # Magenta wenn aktiv (einheitlich)
                
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
            
            # Zeichne Zeiger (immer wenn Position gesetzt ist, auch bei 0)
            if self.current_position_ms >= 0:
                # Berechne Pointer-Position basierend auf Takten, wenn BPM vorhanden
                if self.bpm and self.bpm > 0:
                    ms_per_bar = 4 * (60000.0 / self.bpm)
                    # Finde den Songteil, in dem sich die Position befindet
                    cumulative_bar = 0
                    pointer_bar = 0
                    for part in self.song_parts:
                        start_ms = part.get("start_ms", 0) or 0
                        end_ms = part.get("end_ms", 0) or 0
                        bars = part.get("bars")
                        
                        if start_ms <= self.current_position_ms <= end_ms:
                            # Position ist in diesem Teil
                            relative_ms = self.current_position_ms - start_ms
                            bars_in_part = bars if bars and bars > 0 else int((end_ms - start_ms) / ms_per_bar)
                            relative_bars = relative_ms / ms_per_bar
                            pointer_bar = cumulative_bar + relative_bars
                            break
                        elif self.current_position_ms > end_ms:
                            # Position ist nach diesem Teil
                            bars_in_part = bars if bars and bars > 0 else int((end_ms - start_ms) / ms_per_bar)
                            cumulative_bar += bars_in_part
                        else:
                            # Position ist vor diesem Teil
                            break
                    
                    # Berechne X-Position basierend auf Taktnummer
                    pointer_x = self.x + (pointer_bar * ms_per_bar / 1000.0) * self.pixels_per_second * scale
                else:
                    # Fallback: Zeit-basiert
                    pointer_x = self.x + (self.current_position_ms / 1000.0) * self.pixels_per_second * scale
                
                Color(*self.color_pointer)
                Line(points=[pointer_x, self.y, pointer_x, self.y + self.height], width=2)
    
    def get_active_part_id(self) -> Optional[int]:
        """Gibt die ID des aktiven Songteils zurück."""
        return self.active_part_id
    
    def get_part_x_position(self, part_id: int) -> Optional[float]:
        """Gibt die X-Position (linker Rand) eines Songteils zurück.
        
        Args:
            part_id: ID des Songteils
            
        Returns:
            X-Position in Pixeln relativ zum Widget, oder None wenn nicht gefunden
        """
        if not self.song_parts or self.width == 0:
            return None
        
        # Berechne Skalierung (gleiche Logik wie in _update_canvas)
        if self.bpm and self.bpm > 0:
            ms_per_bar = 4 * (60000.0 / self.bpm)
            total_bars = 0
            for part in self.song_parts:
                bars = part.get("bars")
                if bars and bars > 0:
                    total_bars += bars
                else:
                    start_ms = part.get("start_ms", 0) or 0
                    end_ms = part.get("end_ms", 0) or 0
                    if end_ms > start_ms:
                        total_bars += int((end_ms - start_ms) / ms_per_bar)
            
            total_width_pixels = (total_bars * ms_per_bar / 1000.0) * self.pixels_per_second
        else:
            total_width_pixels = (self.total_duration_ms / 1000.0) * self.pixels_per_second
        
        if total_width_pixels > self.width:
            scale = self.width / total_width_pixels
        else:
            scale = 1.0
        
        # Finde den Songteil und berechne seine Position
        cumulative_bar = 0
        ms_per_bar = 4 * (60000.0 / self.bpm) if self.bpm and self.bpm > 0 else 1000.0
        
        for part in self.song_parts:
            if part.get("id") == part_id:
                start_ms = part.get("start_ms", 0) or 0
                bars = part.get("bars")
                
                if bars and bars > 0 and self.bpm and self.bpm > 0:
                    # Position basierend auf kumulativer Taktnummer
                    x_pos = self.x + (cumulative_bar * ms_per_bar / 1000.0) * self.pixels_per_second * scale
                    return x_pos
                else:
                    # Fallback: Zeit-basiert
                    x_pos = self.x + (start_ms / 1000.0) * self.pixels_per_second * scale
                    return x_pos
            
            # Aktualisiere kumulative Taktnummer für nächsten Teil
            if bars and bars > 0:
                cumulative_bar += bars
        
        return None

