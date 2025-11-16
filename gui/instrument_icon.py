"""
Instrument-Icon Widget mit Bild- und Canvas-Unterstützung
"""
from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.graphics import Color, Line, Rectangle, Ellipse
from kivy.core.image import Image as CoreImage
from pathlib import Path
from typing import Optional

from config import PROJECT_ROOT


class InstrumentIcon(Widget):
    """Einzelnes Instrument-Icon mit Bild oder Canvas-Fallback"""
    
    def __init__(self, instrument_name: str, display_name: str, 
                 base_color: tuple, icon_path: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.instrument_name = instrument_name
        self.display_name = display_name
        self.base_color = base_color  # (r, g, b)
        self.current_level = 0.0  # 0.0 bis 1.0
        self.icon_path = icon_path
        self.image_widget = None
        
        # Prüfe ob Icon-Bild existiert
        if icon_path:
            icon_full_path = PROJECT_ROOT / "gui" / "icons" / icon_path
            if icon_full_path.exists():
                self._setup_image_icon(icon_full_path)
                return
        
        # Fallback: Canvas-Zeichnung
        self._setup_canvas_icon()
    
    def _setup_image_icon(self, image_path: Path):
        """Setup mit Bild-Icon"""
        # Image-Widget für Icon
        self.image_widget = Image(
            source=str(image_path),
            allow_stretch=True,
            keep_ratio=True
        )
        self.add_widget(self.image_widget)
        
        # Canvas für Overlay (Farbfüllung basierend auf Level)
        self.bind(size=self._update_image_overlay, pos=self._update_image_overlay)
    
    def _setup_canvas_icon(self):
        """Setup mit Canvas-Zeichnung (Fallback)"""
        # Zeichne Icon erst wenn Widget eine Größe hat
        self.bind(size=self._draw_canvas_icon, pos=self._draw_canvas_icon)
    
    def _update_image_overlay(self, *args):
        """Aktualisiert Overlay für Bild-Icon basierend auf Level"""
        if not self.image_widget or self.width == 0 or self.height == 0:
            return
        
        # Tint-Overlay basierend auf Level
        level = self.current_level
        r = min(1.0, self.base_color[0] * (0.3 + level * 0.7))
        g = min(1.0, self.base_color[1] * (0.3 + level * 0.7))
        b = min(1.0, self.base_color[2] * (0.3 + level * 0.7))
        
        # Opacity basierend auf Level
        opacity = 0.3 + level * 0.7
        
        # Zeichne Overlay auf Canvas
        self.canvas.clear()
        with self.canvas:
            Color(r, g, b, opacity)
            Rectangle(pos=self.pos, size=self.size)
    
    def _draw_canvas_icon(self, *args):
        """Zeichnet das Instrument-Icon mit Canvas"""
        # Prüfe ob Widget bereits eine Größe hat
        if self.width == 0 or self.height == 0:
            return
        
        self.canvas.clear()
        
        # Hintergrundfarbe basierend auf Level
        level = self.current_level
        r = min(1.0, self.base_color[0] * (0.2 + level * 0.8))
        g = min(1.0, self.base_color[1] * (0.2 + level * 0.8))
        b = min(1.0, self.base_color[2] * (0.2 + level * 0.8))
        
        with self.canvas:
            # Zeichne Icon-Form mit Farbfüllung
            Color(r, g, b, 1.0)
            self._draw_instrument_shape()
            
            # Umriss (hell)
            Color(0.9, 0.9, 0.9, 1.0)
            # Zeichne Umriss direkt hier
            w, h = self.width, self.height
            if w > 0 and h > 0:
                # Rechteckiger Umriss
                Line(points=[2, 2, w-2, 2, w-2, h-2, 2, h-2, 2, 2], width=2)
    
    def _draw_instrument_shape(self):
        """Zeichnet die Form des Instruments"""
        w, h = self.width, self.height
        cx, cy = w / 2, h / 2
        
        if 'bassdrum' in self.instrument_name.lower():
            Ellipse(pos=(cx - min(w, h) * 0.4, cy - min(w, h) * 0.4),
                   size=(min(w, h) * 0.8, min(w, h) * 0.8))
        elif 'snare' in self.instrument_name.lower():
            Ellipse(pos=(cx - w * 0.4, cy - h * 0.15),
                   size=(w * 0.8, h * 0.3))
        elif 'tom' in self.instrument_name.lower():
            Ellipse(pos=(cx - min(w, h) * 0.35, cy - min(w, h) * 0.35),
                   size=(min(w, h) * 0.7, min(w, h) * 0.7))
        elif 'overhead' in self.instrument_name.lower():
            Ellipse(pos=(cx - w * 0.35, cy - h * 0.2),
                   size=(w * 0.7, h * 0.4))
        elif 'bass' in self.instrument_name.lower() and 'guitar' not in self.instrument_name.lower():
            Rectangle(pos=(cx - w * 0.35, cy - h * 0.4),
                     size=(w * 0.7, h * 0.8))
        elif 'guitar' in self.instrument_name.lower():
            Rectangle(pos=(cx - w * 0.35, cy - h * 0.35),
                     size=(w * 0.7, h * 0.7))
        elif 'vocals' in self.instrument_name.lower():
            Line(points=[cx, cy - h * 0.3, cx, cy + h * 0.2], width=2)
            Ellipse(pos=(cx - w * 0.15, cy + h * 0.2),
                   size=(w * 0.3, h * 0.3))
        elif 'synthesizer' in self.instrument_name.lower():
            Rectangle(pos=(cx - w * 0.4, cy - h * 0.3),
                     size=(w * 0.8, h * 0.6))
            for i in range(5):
                Line(points=[
                    cx - w * 0.4 + i * w * 0.2, cy - h * 0.3,
                    cx - w * 0.4 + i * w * 0.2, cy + h * 0.3
                ], width=1)
        else:
            Rectangle(pos=(cx - w * 0.35, cy - h * 0.35),
                     size=(w * 0.7, h * 0.7))
    
    def _draw_outline(self):
        """Zeichnet den Umriss des Icons"""
        w, h = self.width, self.height
        if w > 0 and h > 0:
            # Zeichne Rechteck als Umriss
            Color(0.9, 0.9, 0.9, 1.0)
            # Oben
            Line(points=[2, h-2, w-2, h-2], width=2)
            # Unten
            Line(points=[2, 2, w-2, 2], width=2)
            # Links
            Line(points=[2, 2, 2, h-2], width=2)
            # Rechts
            Line(points=[w-2, 2, w-2, h-2], width=2)
    
    def update_level(self, level: float):
        """Aktualisiert den Meter-Level (0.0 bis 1.0)"""
        self.current_level = max(0.0, min(1.0, level))
        if self.image_widget:
            self._update_image_overlay()
        elif self.width > 0 and self.height > 0:
            self._draw_canvas_icon()

