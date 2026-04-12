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


def extract_chroma_at_beats(
    wav_path,
    beat_times_abs: list[float],
    channel: int,
    sample_rate: int,
    window_sec: float = 0.28,
    song_key: str = "",
    progress_callback=None,
) -> list[dict]:
    """Extrahiert Chroma-Vektoren an Beat-Positionen aus einem WAV-Kanal.

    Verwendet chroma_cqt (Constant-Q-Transformation) statt STFT für bessere
    Frequenzauflösung bei tiefen Gitarrenfrequenzen. Zusätzlich werden
    harmonische Anteile per HPSS (Harmonic-Percussive Source Separation) isoliert,
    um Anschlags-Transienten zu unterdrücken.

    Falls song_key angegeben (z.B. "D dur"), werden tonarteigene Töne doppelt
    gewichtet (apply_key_weight), um tonartfremde Oberton-Artefakte zu dämpfen.

    Gibt zurück: [{'t': float, 'chroma': list[float] (12-dim)}, ...]
    """
    try:
        import librosa
    except ImportError:
        raise ImportError("librosa nicht verfügbar — Chroma-Extraktion nicht möglich")

    import soundfile as sf

    key_pcs = key_pitch_classes(song_key) if song_key else []
    half_win = window_sec / 2.0
    results: list[dict] = []

    with sf.SoundFile(wav_path) as f:
        wav_sr = f.samplerate
        wav_frames = f.frames
        wav_ch = f.channels

        if channel >= wav_ch:
            return []

        n_beats = max(1, len(beat_times_abs))
        for bi, bt in enumerate(beat_times_abs):
            start_frame = max(0, int((bt - half_win) * wav_sr))
            end_frame   = min(wav_frames, int((bt + half_win) * wav_sr))
            if end_frame <= start_frame:
                continue

            f.seek(start_frame)
            block = f.read(end_frame - start_frame, dtype="float32", always_2d=True)
            if block.shape[0] == 0:
                continue

            audio = block[:, channel]

            # HPSS: nur harmonische Anteile → unterdrückt Anschlags-Transienten
            y_harm = librosa.effects.harmonic(audio, margin=8)

            # CQT-basierte Chroma: logarithmisches Frequenzraster,
            # bessere Auflösung bei tiefen Gitarrenfrequenzen
            chroma = librosa.feature.chroma_cqt(
                y=y_harm,
                sr=wav_sr,
                n_chroma=12,
                hop_length=512,
            )
            chroma_mean = chroma.mean(axis=1).tolist()

            # Tonart-Gewichtung (tonarteigene Töne ×2, dann normiert)
            if key_pcs:
                chroma_mean = apply_key_weight(chroma_mean, key_pcs, weight=2.0)

            results.append({"t": bt, "chroma": chroma_mean})

            if progress_callback is not None:
                progress_callback((bi + 1) / n_beats)

    return results


def extract_chroma_at_beats_from_array(
    audio: "np.ndarray",
    seg_start_t: float,
    sample_rate: int,
    beat_times_abs: list[float],
    window_sec: float = 0.28,
    song_key: str = "",
    progress_callback=None,
) -> list[dict]:
    """Extrahiert Chroma-Vektoren pro Beat aus einem bereits eingelesenen Audio-Array.

    Optimierung: HPSS und CQT werden **einmalig auf dem vollen Puffer** berechnet
    und anschließend pro Beat nur in der fertigen Matrix gesliced.
    Kein wiederholter librosa-Aufruf pro Beat → 10–20× schneller als der
    vorherige Per-Clip-Ansatz.
    """
    try:
        import librosa
    except ImportError:
        raise ImportError("librosa nicht verfügbar — Chroma-Extraktion nicht möglich")

    if not beat_times_abs or len(audio) == 0:
        return []

    key_pcs = key_pitch_classes(song_key) if song_key else []

    # ── Einmalige Vorberechnung auf vollem Puffer ─────────────────────────────
    if progress_callback:
        progress_callback(0.05)

    # HPSS: harmonischen Anteil isolieren (einmalig, nicht pro Beat-Clip)
    y_harm = librosa.effects.harmonic(audio.astype(np.float32), margin=8)

    if progress_callback:
        progress_callback(0.35)

    # CQT-Chroma: Matrix (12 × n_frames) für den gesamten Puffer
    hop = 512
    chroma_full = librosa.feature.chroma_cqt(
        y=y_harm, sr=sample_rate, n_chroma=12, hop_length=hop,
    )   # shape: (12, n_frames)

    if progress_callback:
        progress_callback(0.70)

    n_frames = chroma_full.shape[1]
    hop_sec  = hop / sample_rate
    f_half   = max(1, round(window_sec / 2.0 / hop_sec))

    # ── Pro Beat: Slice aus der Matrix ───────────────────────────────────────
    results: list[dict] = []
    n_beats = max(1, len(beat_times_abs))

    for bi, bt in enumerate(beat_times_abs):
        f_center = int((bt - seg_start_t) / hop_sec)
        f_start  = max(0, f_center - f_half)
        f_end    = min(n_frames, f_center + f_half + 1)
        if f_end <= f_start:
            continue

        chroma_mean = chroma_full[:, f_start:f_end].mean(axis=1)

        # Power-Normalisierung: quadrieren → scharfe Pitch-Klassen-Peaks
        chroma_mean = chroma_mean ** 2
        norm = float(np.linalg.norm(chroma_mean))
        if norm < 1e-8:
            continue
        chroma_mean = (chroma_mean / norm).tolist()

        if key_pcs:
            chroma_mean = apply_key_weight(chroma_mean, key_pcs, weight=2.0)

        results.append({"t": bt, "chroma": chroma_mean})

        if progress_callback:
            progress_callback(0.70 + 0.30 * (bi + 1) / n_beats)

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


def bass_rhythm_score(
    audio_clip: "np.ndarray",
    sample_rate: int,
    bpm: float,
) -> float:
    """Berechnet Rhythmus-Score: 1.0 = perfekte 8tel-Noten, 0.0 = unregelmäßig.

    Misst wie nah die Inter-Onset-Intervalle an einem Vielfachen einer 8tel-Note
    liegen. Score 1.0: alle Onsets landen exakt auf 8tel-Positionen.
    Score 0.0: Onsets liegen genau zwischen zwei 8tel-Positionen.

    Verwendet librosa onset_strength + onset_detect. Gibt 0.5 zurück wenn
    zu wenig Onsets vorhanden (< 2), damit kein Rauschen entsteht.
    """
    try:
        import librosa
    except ImportError:
        return 0.5

    if len(audio_clip) < 512 or bpm <= 0:
        return 0.0

    eighth_sec = 60.0 / bpm / 2.0
    hop = 256

    try:
        env = librosa.onset.onset_strength(
            y=audio_clip.astype(np.float32),
            sr=sample_rate,
            hop_length=hop,
        )
        onset_frames = librosa.onset.onset_detect(
            onset_envelope=env,
            sr=sample_rate,
            hop_length=hop,
            backtrack=True,
        )
    except Exception:
        return 0.5

    if len(onset_frames) < 2:
        return 0.5   # zu wenig Onsets → neutral

    onset_times = librosa.frames_to_time(onset_frames, sr=sample_rate, hop_length=hop)

    # IOIs filtern: >50 ms (kein Glissando-Artefakt), < 4 Takte (kein Rauschen)
    max_ioi = 4.0 * 4.0 * (60.0 / bpm)
    iois = [float(d) for d in np.diff(onset_times) if 0.05 <= d <= max_ioi]
    if not iois:
        return 0.5

    scores = []
    for ioi in iois:
        n = max(1, round(ioi / eighth_sec))     # nächstes Vielfaches der 8tel-Note
        expected = n * eighth_sec
        dev = abs(ioi - expected) / eighth_sec  # Abweichung in 8tel-Note-Einheiten
        scores.append(max(0.0, 1.0 - 2.0 * dev))   # 0.5 Einheiten → Score 0

    return float(np.mean(scores))


def _rhythm_score_from_onset_slice(
    onset_env: "np.ndarray",
    hop_length: int,
    sample_rate: int,
    bpm: float,
) -> float:
    """Rhythmus-Score aus einem Slice der vorberechneten Onset-Stärke.

    Identische Logik wie bass_rhythm_score(), aber ohne erneutes
    onset_strength()-Call — arbeitet auf dem bereits berechneten Slice.
    """
    try:
        import librosa
    except ImportError:
        return 0.5

    if len(onset_env) < 4 or bpm <= 0:
        return 0.5

    try:
        onset_frames = librosa.onset.onset_detect(
            onset_envelope=onset_env,
            sr=sample_rate,
            hop_length=hop_length,
            backtrack=True,
        )
    except Exception:
        return 0.5

    if len(onset_frames) < 2:
        return 0.5

    onset_times = librosa.frames_to_time(onset_frames, sr=sample_rate, hop_length=hop_length)
    eighth_sec  = 60.0 / bpm / 2.0
    max_ioi     = 4.0 * 4.0 * (60.0 / bpm)
    iois = [float(d) for d in np.diff(onset_times) if 0.05 <= d <= max_ioi]
    if not iois:
        return 0.5

    scores = []
    for ioi in iois:
        n = max(1, round(ioi / eighth_sec))
        dev = abs(ioi - n * eighth_sec) / eighth_sec
        scores.append(max(0.0, 1.0 - 2.0 * dev))
    return float(np.mean(scores))


def extract_bass_at_bars_from_array(
    audio: "np.ndarray",
    seg_start_t: float,
    sample_rate: int,
    bar_times_abs: list[float],
    bpm: float,
    song_key: str = "",
    progress_callback=None,
) -> list[dict]:
    """Extrahiert Bass-Chroma und Rhythmus-Score pro Takt aus einem Audio-Array.

    Optimierung: Bandpass, HPSS, CQT und Onset-Stärke werden **einmalig auf
    dem vollen Puffer** berechnet. Pro Takt werden nur die entsprechenden
    Frame-Bereiche aus den vorberechneten Matrizen gelesen.

    Vorher: 180 Takte × (HPSS + CQT + onset_strength) ≈ 60–120 s
    Jetzt:  1× (Bandpass + HPSS + CQT + onset_strength) + 180× Slice ≈ 8–20 s
    """
    try:
        import librosa
        from scipy.signal import butter, sosfilt
    except ImportError:
        raise ImportError("librosa/scipy nicht verfügbar — Bass-Extraktion nicht möglich")

    if not bar_times_abs or bpm <= 0 or len(audio) == 0:
        return []

    key_pcs  = key_pitch_classes(song_key) if song_key else []
    beat_sec = 60.0 / bpm
    bar_sec  = 4.0 * beat_sec
    n_samples = len(audio)

    # ── Einmalige Vorberechnung auf vollem Puffer ─────────────────────────────
    if progress_callback:
        progress_callback(0.05)

    # Bandpass 30–300 Hz: isoliert Bass-Grundtöne, entfernt Gitarren/Drum-Bleed
    nyq = sample_rate / 2.0
    _sos = butter(4, [30.0 / nyq, 300.0 / nyq], btype="band", output="sos")
    audio_bp = sosfilt(_sos, audio.astype(np.float64)).astype(np.float32)

    if progress_callback:
        progress_callback(0.10)

    # HPSS: harmonischen Anteil isolieren (einmalig)
    y_harm = librosa.effects.harmonic(audio_bp, margin=8)

    if progress_callback:
        progress_callback(0.45)

    # CQT-Chroma: Matrix (12 × n_frames) für den gesamten Puffer
    hop = 256
    chroma_full = librosa.feature.chroma_cqt(
        y=y_harm, sr=sample_rate, n_chroma=12, hop_length=hop,
        fmin=librosa.note_to_hz("C1"),
    )   # shape: (12, n_frames)

    if progress_callback:
        progress_callback(0.75)

    # Onset-Stärke für Rhythmus-Scores (einmalig)
    onset_env_full = librosa.onset.onset_strength(
        y=audio_bp, sr=sample_rate, hop_length=hop,
    )

    if progress_callback:
        progress_callback(0.85)

    n_frames = chroma_full.shape[1]
    hop_sec  = hop / sample_rate

    # ── Pro Takt: Slice aus Matrizen ─────────────────────────────────────────
    results: list[dict] = []
    n_bars = max(1, len(bar_times_abs))

    for bi, bt in enumerate(bar_times_abs):
        bt_end = bar_times_abs[bi + 1] if bi + 1 < len(bar_times_abs) else bt + bar_sec

        f_start = max(0, int((bt     - seg_start_t) / hop_sec))
        f_end   = min(n_frames, int((bt_end - seg_start_t) / hop_sec) + 1)
        s_start = max(0, int((bt     - seg_start_t) * sample_rate))
        s_end   = min(n_samples, int((bt_end - seg_start_t) * sample_rate))

        if f_end <= f_start or s_end - s_start < 512:
            continue

        # Stille Takte überspringen (nach Bandpass)
        rms = float(np.sqrt(np.mean(audio_bp[s_start:s_end] ** 2)))
        if rms < 2e-4:
            continue

        # Chroma aus vorberechneter Matrix + Power-Normalisierung
        chroma_mean = chroma_full[:, f_start:f_end].mean(axis=1)
        chroma_mean = chroma_mean ** 2
        norm = float(np.linalg.norm(chroma_mean))
        if norm < 1e-8:
            continue
        chroma_mean = (chroma_mean / norm).tolist()

        if key_pcs:
            chroma_mean = apply_key_weight(chroma_mean, key_pcs, weight=2.0)

        # Rhythmus-Score aus vorberechneter Onset-Stärke (kein erneuter Aufruf)
        rhythm = _rhythm_score_from_onset_slice(
            onset_env_full[f_start:f_end], hop, sample_rate, bpm
        )

        results.append({"t": bt, "chroma": chroma_mean, "rhythm": rhythm})

        if progress_callback:
            progress_callback(0.85 + 0.15 * (bi + 1) / n_bars)

    return results
