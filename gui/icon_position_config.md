# Konfiguration der Instrument-Positionen auf dem Hintergrundbild

Das Hintergrundbild `Indicator.png` hat eine Größe von **2048x512 Pixel**.

## Koordinatensystem

- **X-Achse**: 0 = links, 2048 = rechts (oder relativ 0.0 = links, 1.0 = rechts)
- **Y-Achse**: 0 = unten, 512 = oben (oder relativ 0.0 = unten, 1.0 = oben)
- **Mittelpunkt eines Icons**: Die angegebenen Koordinaten beziehen sich auf den Mittelpunkt des Icons

## Position-Format

Sie können Positionen auf zwei Arten angeben:

### 1. Relativ (Prozent, 0.0 bis 1.0)
- **bg_pos_x**: 0.0 = ganz links, 1.0 = ganz rechts
- **bg_pos_y**: 0.0 = ganz unten, 1.0 = ganz oben
- **icon_width/icon_height**: 0.0 bis 1.0 für Größe relativ zur Bildgröße

### 2. Absolut (Pixel)
- **bg_pos_x**: Pixel-Wert von links (0-2048)
- **bg_pos_y**: Pixel-Wert von unten (0-512)
- **icon_width/icon_height**: Pixel-Größe

## Beispiel-Konfiguration

Wenn ein Instrument "bassdrum" an Position (512, 256) mit Größe 100x100 Pixel platziert werden soll:

```python
db.update_channel_mapping(
    instrument_name="bassdrum",
    bg_pos_x=512,  # 512 Pixel von links
    bg_pos_y=256,  # 256 Pixel von unten
    icon_width=100,  # 100 Pixel breit
    icon_height=100  # 100 Pixel hoch
)
```

Oder relativ:

```python
db.update_channel_mapping(
    instrument_name="bassdrum",
    bg_pos_x=0.25,  # 25% von links = 512 Pixel
    bg_pos_y=0.5,   # 50% von unten = 256 Pixel
    icon_width=0.05,  # 5% der Breite = ~100 Pixel
    icon_height=0.2   # 20% der Höhe = ~100 Pixel
)
```

## Konfigurationsdialog

Ein Dialog zur visuellen Konfiguration der Positionen kann im Wartungsmodus hinzugefügt werden.

## Format für die Datenbank

Die Positionen werden in der Datenbank-Tabelle `channel_mapping` in folgenden Spalten gespeichert:
- `bg_pos_x`: X-Position
- `bg_pos_y`: Y-Position
- `icon_width`: Icon-Breite
- `icon_height`: Icon-Höhe

