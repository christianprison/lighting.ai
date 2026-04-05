"""Audio-Fingerprinting — Feature-Extraktion pro Takt.

Erzeugt einen 48-dimensionalen Feature-Vektor aus einem Audio-Snippet:
  - chroma_cqt mean  (12 Werte) — harmonischer Inhalt / Akkordfarbe
  - MFCC mean        (20 Werte) — Klangfarbe / Timbre
  - onset_strength   (16 Werte) — Rhythmusmuster auf 16tel-Raster
  - rms              (1 Wert)   — Energie-Level (gespeichert separat)

Der Vektor ist normiert (L2) und damit unabhängig von der Lautstärke,
was den Fingerprint robust gegen Pegelunterschiede zwischen Studio-
und Live-Aufnahme macht.

Abhängigkeit: librosa (und damit numpy/scipy/soundfile)
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

log = logging.getLogger("live.audio.fingerprint")

# Dimensionen der Teilfeaturen
CHROMA_DIM = 12
MFCC_DIM = 20
ONSET_BINS = 16
VECTOR_DIM = CHROMA_DIM + MFCC_DIM + ONSET_BINS  # 48


def _import_librosa():
    """Lazy import von librosa (ca. 1s Import-Zeit)."""
    try:
        import librosa  # type: ignore
        return librosa
    except ImportError as exc:
        raise ImportError(
            "librosa ist nicht installiert. "
            "Bitte 'pip install librosa' ausführen."
        ) from exc


# ---------------------------------------------------------------------------
# Feature-Extraktion
# ---------------------------------------------------------------------------

def extract_features(
    audio_path: str | Path,
    bpm: float = 120.0,
    sr: int = 22050,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Extrahiert Feature-Vektor aus einem Audio-Snippet.

    Parameters
    ----------
    audio_path:
        Pfad zur Audio-Datei (MP3, WAV, …)
    bpm:
        Tempo des Songs — wird für die 16tel-Rasterung verwendet
    sr:
        Target-Sample-Rate (wird beim Laden konvertiert)

    Returns
    -------
    (chroma, mfcc, onset, rms) — alle als float32
        chroma  shape (12,)
        mfcc    shape (20,)
        onset   shape (16,)
        rms     scalar float
    """
    librosa = _import_librosa()
    path = Path(audio_path)

    if not path.exists():
        raise FileNotFoundError(f"Audio-Datei nicht gefunden: {path}")

    # Laden + Mono-Konvertierung
    y, sr_loaded = librosa.load(str(path), sr=sr, mono=True)

    if len(y) == 0:
        raise ValueError(f"Audio-Datei ist leer: {path}")

    # RMS-Energie (vor Normierung)
    rms = float(np.sqrt(np.mean(y ** 2)))

    # --- Chroma (CQT-basiert, stabiler bei Live-Aufnahmen) ---
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, bins_per_octave=36)
    chroma_mean = np.mean(chroma, axis=1).astype(np.float32)  # (12,)

    # --- MFCC ---
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=MFCC_DIM)
    mfcc_mean = np.mean(mfcc, axis=1).astype(np.float32)  # (20,)

    # --- Onset Strength auf 16tel-Raster ---
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onset_16th = _onset_to_16th_grid(onset_env, y, sr, bpm)  # (16,)

    return chroma_mean, mfcc_mean, onset_16th, rms


def _onset_to_16th_grid(
    onset_env: np.ndarray,
    y: np.ndarray,
    sr: int,
    bpm: float,
) -> np.ndarray:
    """Faltet die Onset-Kurve auf ein 16 Bins umfassendes 16tel-Raster.

    Ein Takt bei `bpm` BPM hat eine Dauer von 60/bpm * 4 Sekunden.
    Diese wird in 16 gleichmäßige Bins unterteilt.
    Für jeden Bin wird die maximale Onset-Stärke genommen.
    """
    hop_length = 512  # librosa default
    frames_per_sec = sr / hop_length

    # Dauer eines Taktes in Frames
    bar_duration_sec = 60.0 / bpm * 4.0
    bar_frames = int(bar_duration_sec * frames_per_sec)

    # Nur so viele Frames wie der Takt lang ist (oder alle, falls kürzer)
    n_frames = min(len(onset_env), bar_frames)
    frames = onset_env[:n_frames]

    # Aufteilen in 16 Bins
    bins = np.array_split(frames, ONSET_BINS)
    grid = np.array([np.max(b) if len(b) > 0 else 0.0 for b in bins], dtype=np.float32)

    # Normieren auf [0, 1]
    max_val = grid.max()
    if max_val > 0:
        grid /= max_val

    return grid


# ---------------------------------------------------------------------------
# Ähnlichkeit
# ---------------------------------------------------------------------------

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Kosinus-Ähnlichkeit zwischen zwei Feature-Vektoren.

    Returns 0.0 … 1.0 (1.0 = identisch, 0.0 = orthogonal)
    """
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def weighted_similarity(
    query_chroma: np.ndarray,
    query_mfcc: np.ndarray,
    query_onset: np.ndarray,
    ref_chroma: np.ndarray,
    ref_mfcc: np.ndarray,
    ref_onset: np.ndarray,
    w_chroma: float = 0.5,
    w_mfcc: float = 0.3,
    w_onset: float = 0.2,
) -> float:
    """Gewichtete Ähnlichkeit aus drei Teil-Features.

    Standardgewichte: Chroma dominiert (harmonisch stabiler),
    MFCC sekundär (Klangfarbe), Onset tertiär (Rhythmus).
    Die Gewichte können nach der ersten Probe-Session empirisch angepasst
    werden (vgl. Architektur-Doku: Nachanalyse).
    """
    sim_chroma = cosine_similarity(query_chroma, ref_chroma)
    sim_mfcc = cosine_similarity(query_mfcc, ref_mfcc)
    sim_onset = cosine_similarity(query_onset, ref_onset)
    return w_chroma * sim_chroma + w_mfcc * sim_mfcc + w_onset * sim_onset


# ---------------------------------------------------------------------------
# Batch-Extraktion (für den Importer)
# ---------------------------------------------------------------------------

def extract_features_batch(
    audio_paths: list[str | Path],
    bpm: float,
    sr: int = 22050,
) -> list[tuple[np.ndarray, np.ndarray, np.ndarray, float] | None]:
    """Extrahiert Features für eine Liste von Audio-Dateien.

    Gibt None für Dateien zurück, die nicht geladen werden können.
    """
    results = []
    for path in audio_paths:
        try:
            results.append(extract_features(path, bpm=bpm, sr=sr))
        except (FileNotFoundError, ValueError) as exc:
            log.warning("Feature-Extraktion fehlgeschlagen: %s — %s", path, exc)
            results.append(None)
    return results


# ---------------------------------------------------------------------------
# Live-Snapshot aus rohem Audio-Buffer
# ---------------------------------------------------------------------------

def extract_features_from_array(
    samples: np.ndarray,
    sr: int,
    bpm: float = 120.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Wie extract_features(), aber direkt aus einem numpy-Array.

    Wird vom AudioProcess für Live-USB-Audio verwendet.
    Der Buffer sollte mindestens einen Takt lang sein.
    """
    librosa = _import_librosa()

    # Mono erzwingen
    if samples.ndim > 1:
        y = np.mean(samples, axis=1).astype(np.float32)
    else:
        y = samples.astype(np.float32)

    if len(y) == 0:
        raise ValueError("Audio-Buffer ist leer")

    rms = float(np.sqrt(np.mean(y ** 2)))

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, bins_per_octave=36)
    chroma_mean = np.mean(chroma, axis=1).astype(np.float32)

    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=MFCC_DIM)
    mfcc_mean = np.mean(mfcc, axis=1).astype(np.float32)

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onset_16th = _onset_to_16th_grid(onset_env, y, sr, bpm)

    return chroma_mean, mfcc_mean, onset_16th, rms
