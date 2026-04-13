"""chroma_viz.py — Chroma-Feature-Visualisierung für den Timeline-Widget.

Extrahiert Chroma-Vektoren (12-dim) auf Beat-Positionen und liefert
Farb- und Form-Mapping für die Darstellung im Lead-Guitar-Track.
"""
from __future__ import annotations

import colorsys
import math

import numpy as np

PITCH_CLASSES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# XR18-Kanal-Indizes (0-basiert) für Audio-Feature-Extraktion
CH_LEAD_VOCAL  = 0   # CH01 = Lead Vocal (Pete)
CH_LEAD_GUITAR = 4   # CH05 = Lead Guitar L
CH_BASS        = 5   # CH06 = Bass

# Tonartenname → MIDI-Pitch-Class (0=C … 11=H)
_ROOT_TO_PC: dict[str, int] = {
    'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3,
    'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8,
    'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11, 'H': 11,
}
_MAJOR_STEPS = [0, 2, 4, 5, 7, 9, 11]   # Dur-Tonleiter (7 Töne)
_MINOR_STEPS = [0, 2, 3, 5, 7, 8, 10]   # Natürliches Moll (7 Töne)


def key_pitch_classes(key_str: str) -> list[int]:
    """Parst eine Tonart-Zeichenkette und gibt die 7 Pitch-Classes zurück.

    Format: "{Grundton} {Modus}"  —  z.B. "D dur", "E moll", "Bb dur".
    Gibt [] zurück wenn nicht parsbar.
    """
    parts = key_str.strip().split()
    if len(parts) < 2:
        return []
    root = _ROOT_TO_PC.get(parts[0])
    if root is None:
        return []
    steps = _MAJOR_STEPS if parts[1].lower() == "dur" else _MINOR_STEPS
    return [(root + s) % 12 for s in steps]


def apply_key_weight(
    chroma: list[float],
    key_pcs: list[int],
    weight: float = 2.0,
) -> list[float]:
    """Gewichtet Töne der Tonart stärker und normiert auf max=1.

    Tonarteigene Pitch-Classes werden mit `weight` multipliziert,
    danach wird der Vektor auf max=1 normiert.
    """
    arr = [v * (weight if i in key_pcs else 1.0) for i, v in enumerate(chroma)]
    m = max(arr) if arr else 0.0
    if m > 0:
        arr = [v / m for v in arr]
    return arr




def chroma_to_rgb(chroma: list[float]) -> tuple[int, int, int]:
    """Mappt einen 12-dim Chroma-Vektor auf RGB via zirkulären Mittelwert.

    Pitch-Klasse k → Winkel = k * 2π/12.
    Der zirkuläre Mittelwert gibt den Farbton (0–1).
    Sättigung = min(1, 2 * sqrt(sin² + cos²)) — Maß der harmonischen Konzentration.
    Helligkeit = 0.88 (fest, hell aber nicht grell).
    """
    chroma_arr = np.array(chroma, dtype=float)
    total = chroma_arr.sum()
    if total <= 0:
        return (128, 128, 128)

    weights = chroma_arr / total
    angles = [k * 2.0 * math.pi / 12 for k in range(12)]

    sin_sum = sum(weights[k] * math.sin(angles[k]) for k in range(12))
    cos_sum = sum(weights[k] * math.cos(angles[k]) for k in range(12))

    hue = (math.atan2(sin_sum, cos_sum) / (2.0 * math.pi)) % 1.0
    saturation = min(1.0, 2.0 * math.sqrt(sin_sum ** 2 + cos_sum ** 2))
    value = 0.88

    r, g, b = colorsys.hsv_to_rgb(hue, saturation, value)
    return (int(r * 255), int(g * 255), int(b * 255))


def chroma_shape_type(chroma: list[float], threshold: float = 0.5) -> str:
    """Bestimmt den Form-Typ anhand der Anzahl dominanter Pitch-Klassen.

    Zählt Pitch-Klassen mit chroma[i] >= threshold * max(chroma).
    Gibt zurück: 'line' (1–2), 'triangle' (3), 'diamond' (4), 'circle' (5+).
    """
    if not chroma:
        return "circle"
    max_val = max(chroma)
    if max_val <= 0:
        return "circle"
    cutoff = threshold * max_val
    count = sum(1 for v in chroma if v >= cutoff)
    if count <= 2:
        return "line"
    if count == 3:
        return "triangle"
    if count == 4:
        return "diamond"
    if count == 5:
        return "pentagon"
    return "circle"


def chroma_tooltip(chroma: list[float]) -> str:
    """Gibt eine mehrzeilige Darstellung der stärksten Pitch-Klassen zurück.

    Sortiert nach Stärke (absteigend), nur Klassen mit Wert >= 0.15 * max.
    Format: "G: 0.92\\nD: 0.71\\nB: 0.44"
    """
    if not chroma:
        return ""
    max_val = max(chroma)
    if max_val <= 0:
        return ""
    cutoff = 0.15 * max_val
    ranked = sorted(
        [(PITCH_CLASSES[i], v) for i, v in enumerate(chroma) if v >= cutoff],
        key=lambda x: x[1],
        reverse=True,
    )
    return "\n".join(f"{name}: {val:.2f}" for name, val in ranked)


def compute_beat_times(bar_times: list[float], bpm: float) -> list[float]:
    """Berechnet alle Viertelnoten-Positionen aus Takt-Zeitstempeln und BPM.

    Für jedes Paar aufeinanderfolgender Takte werden 4 Beats erzeugt.
    Für den letzten Takt werden ebenfalls 4 Beats erzeugt.
    Gibt eine sortierte, deduplizierte Liste zurück.
    """
    if not bar_times or bpm <= 0:
        return []

    beat_sec = 60.0 / bpm
    beats: set[float] = set()

    for i in range(len(bar_times) - 1):
        bar_start = bar_times[i]
        for k in range(4):
            beats.add(round(bar_start + k * beat_sec, 6))

    # Letzter Takt: 4 Beats hinzufügen
    last_bar = bar_times[-1]
    for k in range(4):
        beats.add(round(last_bar + k * beat_sec, 6))

    return sorted(beats)


def extract_vocal_activity(
    vocal_buf: "np.ndarray",
    sample_rate: int,
    seg_start_t: float = 0.0,
    window_sec: float = 0.05,
    rms_threshold: "float | None" = None,
) -> list[dict]:
    """Extrahiert Vokal-Aktivität (VAD) aus dem Lead-Vocal-Kanal.

    Algorithmus: Bandpass 200–4000 Hz (verwirft Kick/Bass), RMS pro 50ms-Fenster,
    adaptiver Schwellwert (40 % des 75. Perzentils; Minimum 2 mV).

    Args:
        vocal_buf:      Mono-Puffer float32 des Lead-Vocal-Kanals.
        sample_rate:    Abtastrate in Hz.
        seg_start_t:    Absoluter WAV-Zeitstempel des ersten Samples.
        window_sec:     Fenstergröße für RMS-Berechnung (Standard: 50 ms).
        rms_threshold:  Fester RMS-Schwellwert; None = auto-adaptiv.

    Returns:
        list[dict] mit {"t": float, "active": bool, "rms": float} pro Fenster.
        Erweiterbar um "f0", "voiced", "chroma" für spätere pyin-Integration.
    """
    if len(vocal_buf) == 0:
        return []

    try:
        from scipy.signal import butter, sosfilt
        nyq = sample_rate / 2.0
        # Bandpass 200–4000 Hz: Gesangsstimme, verwirft Kick/Bass und HF-Rauschen
        _sos = butter(4, [200.0 / nyq, 4000.0 / nyq], btype="band", output="sos")
        filtered = sosfilt(_sos, vocal_buf.astype(np.float64)).astype(np.float32)
    except Exception:
        filtered = vocal_buf.astype(np.float32)

    win_samples = max(1, int(window_sec * sample_rate))
    n_windows   = len(filtered) // win_samples
    if n_windows == 0:
        return []

    # RMS pro Fenster (vektorisiert)
    frames = filtered[: n_windows * win_samples].reshape(n_windows, win_samples)
    rms_arr = np.sqrt(np.mean(frames ** 2, axis=1))   # shape (n_windows,)

    # Adaptiver Schwellwert: 40 % des 75. Perzentils, mindestens 2 mV
    if rms_threshold is None:
        p75 = float(np.percentile(rms_arr, 75))
        rms_threshold = max(2e-3, p75 * 0.4)

    result: list[dict] = []
    for i, rms in enumerate(rms_arr):
        result.append({
            "t":      round(seg_start_t + i * window_sec, 4),
            "active": bool(float(rms) >= rms_threshold),
            "rms":    round(float(rms), 6),
        })
    return result


