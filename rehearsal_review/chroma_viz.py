"""chroma_viz.py — Chroma-Feature-Visualisierung für den Timeline-Widget.

Extrahiert Chroma-Vektoren (12-dim) auf Beat-Positionen und liefert
Farb- und Form-Mapping für die Darstellung im Lead-Guitar-Track.
"""
from __future__ import annotations

import colorsys
import math

import numpy as np

PITCH_CLASSES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def extract_chroma_at_beats(
    wav_path,
    beat_times_abs: list[float],
    channel: int,
    sample_rate: int,
    window_sec: float = 0.28,
) -> list[dict]:
    """Extrahiert Chroma-Vektoren an Beat-Positionen aus einem WAV-Kanal.

    Liest die WAV-Datei mit soundfile, extrahiert für jeden Beat-Zeitpunkt
    ein Fenster der Länge window_sec (zentriert auf beat_time), berechnet
    librosa.feature.chroma_stft und gibt eine Liste von Dicts zurück:
    [{'t': float, 'chroma': list[float] (12-dim)}, ...]

    Skips beats where audio is unavailable.
    """
    try:
        import librosa
    except ImportError:
        raise ImportError("librosa nicht verfügbar — Chroma-Extraktion nicht möglich")

    import soundfile as sf

    half_win = window_sec / 2.0
    results: list[dict] = []

    with sf.SoundFile(wav_path) as f:
        wav_sr = f.samplerate
        wav_frames = f.frames
        wav_ch = f.channels

        if channel >= wav_ch:
            return []

        for bt in beat_times_abs:
            start_sec = bt - half_win
            end_sec = bt + half_win
            start_frame = max(0, int(start_sec * wav_sr))
            end_frame = min(wav_frames, int(end_sec * wav_sr))
            if end_frame <= start_frame:
                continue

            f.seek(start_frame)
            block = f.read(end_frame - start_frame, dtype="float32", always_2d=True)
            if block.shape[0] == 0:
                continue

            audio = block[:, channel]

            # Chroma mit librosa berechnen
            chroma = librosa.feature.chroma_stft(
                y=audio,
                sr=wav_sr,
                n_chroma=12,
                hop_length=512,
            )
            # Mitteln über Zeit → 12-dim Vektor
            chroma_mean = chroma.mean(axis=1).tolist()
            results.append({"t": bt, "chroma": chroma_mean})

    return results


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
