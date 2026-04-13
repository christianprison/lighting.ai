"""chroma_extractor.py — Streaming Chroma-Extraktion (Prime Directive: identisch live und Simulation).

Kein HPSS (Harmonic-Percussive Source Separation): erfordert den vollen Puffer
im Voraus und kann nicht kausal/streaming betrieben werden.

Stattdessen: Rolling-Buffer bei reduzierter Abtastrate, STFT-Chroma (Gitarre)
oder CQT-Chroma (Bass, fmin=C1 ≈ 32,7 Hz) auf kurzem Fenster pro Beat/Takt.

Verwendung:
    guitar = StreamingChromaExtractor(sr, window_sec=0.5)
    bass   = StreamingChromaExtractor(sr, window_sec=2.0,
                 target_sr=8_000, bp_low=30, bp_high=300, use_cqt=True)

    # im Audio-Loop (pro Block):
    guitar.push_block(block[:, CH_GUITAR])
    bass.push_block(block[:, CH_BASS])

    # beim Beat-Event:
    chroma_vec = guitar.get_chroma()   # 12 Werte, L2-normiert, oder None

    # beim Takt-Start:
    bass_chroma = bass.get_chroma()
    bass_rhythm = bass.get_rhythm_score(bpm)
"""
from __future__ import annotations

from math import gcd
from typing import Optional

import numpy as np


# ── Kanal-Konstanten (re-exportiert von beat_detector, hier für Bequemlichkeit) ──
from detection.beat_detector import CH_GUITAR, CH_BASS, CH_LEAD_VOCAL  # noqa: F401


class StreamingChromaExtractor:
    """Rolling-Buffer Chroma-Extraktion für einen Mono-Audiokanal.

    Puffert die letzten `window_sec` Sekunden Audio.  Auf Abruf gibt
    `get_chroma()` einen 12-dim power-normierten Chroma-Vektor zurück —
    dieselbe Berechnung, die auch im Live-Betrieb auf dem gleich großen
    Rolling-Buffer ausgeführt wird.

    Optionen:
    - `target_sr`: Audio wird vor dem Einschreiben auf diese Abtastrate
      dezimiert (spart Rechenzeit bei CQT auf tiefe Frequenzen).
    - `bp_low`/`bp_high`: Bandpass-Filter wird bei der Original-Abtastrate
      angewendet (bessere Filterqualität vor dem Dezimieren).
    - `use_cqt`: CQT statt STFT — bessere Frequenzauflösung bei tiefen
      Tönen (Bass), dafür etwas langsamer.
    - `fmin_hz`: Unterste CQT-Frequenz (Standard: C1 ≈ 32,7 Hz).
    """

    def __init__(
        self,
        sample_rate: int,
        window_sec: float,
        target_sr: Optional[int] = None,
        bp_low: Optional[float] = None,
        bp_high: Optional[float] = None,
        use_cqt: bool = False,
        fmin_hz: Optional[float] = None,
    ) -> None:
        self._in_sr  = sample_rate
        self._out_sr = target_sr if target_sr is not None else sample_rate
        self._use_cqt = use_cqt
        self._fmin    = fmin_hz if fmin_hz is not None else 32.703   # C1

        self._window = int(window_sec * self._out_sr)
        self._buf    = np.zeros(self._window, dtype=np.float32)

        # Optionaler Bandpass-Filter (bei Original-Abtastrate)
        self._bp_sos: Optional[np.ndarray] = None
        self._bp_zi:  Optional[np.ndarray] = None
        if bp_low is not None and bp_high is not None:
            try:
                from scipy.signal import butter
                nyq = sample_rate / 2.0
                self._bp_sos = butter(
                    4, [bp_low / nyq, bp_high / nyq], btype="band", output="sos"
                )
                self._bp_zi = np.zeros((self._bp_sos.shape[0], 2))
            except Exception:
                pass

        # Dezimierungs-Verhältnis (resample_poly: up/down, vereinfacht mit GCD)
        if self._out_sr != sample_rate:
            g = gcd(int(self._out_sr), int(sample_rate))
            self._up   = int(self._out_sr) // g
            self._down = int(sample_rate)  // g
            self._resample = True
        else:
            self._up = self._down = 1
            self._resample = False

    # ── Samples einschreiben ──────────────────────────────────────────────────

    def push_block(self, samples: np.ndarray) -> None:
        """Mono-Block in Rolling-Buffer einschreiben.

        Reihenfolge: Bandpass (Original-Abtastrate) → Dezimierung → Buffer.
        Identisch mit dem, was im Live-Betrieb pro Sounddevice-Block passiert.
        """
        x = samples.astype(np.float32)

        # Bandpass (optional, z.B. 30–300 Hz für Bass)
        if self._bp_sos is not None:
            from scipy.signal import sosfilt
            x, self._bp_zi = sosfilt(self._bp_sos, x.astype(np.float64),
                                     zi=self._bp_zi)
            x = x.astype(np.float32)

        # Dezimierung auf Ziel-Abtastrate
        if self._resample:
            from scipy.signal import resample_poly
            x = resample_poly(x, self._up, self._down).astype(np.float32)

        # Rolling-Buffer: älteste Samples herausschieben, neue hinten einschreiben
        n = len(x)
        if n >= self._window:
            self._buf[:] = x[-self._window:]
        else:
            self._buf[:-n] = self._buf[n:]
            self._buf[-n:] = x

    # ── Chroma abrufen ────────────────────────────────────────────────────────

    def get_chroma(self) -> Optional[list[float]]:
        """12-dim power-normierter Chroma-Vektor aus aktuellem Rolling-Buffer.

        Gibt None zurück bei Stille (max < 1e-5) oder fehlendem librosa.
        Kein HPSS — Prime Directive: dieselbe Berechnung auch im Live-Betrieb.
        """
        if float(np.max(np.abs(self._buf))) < 1e-5:
            return None
        try:
            import librosa
        except ImportError:
            return None

        y = self._buf.copy()

        if self._use_cqt:
            # CQT: bessere Auflösung bei tiefen Frequenzen (Bass-Grundtöne ab C1)
            chroma = librosa.feature.chroma_cqt(
                y=y, sr=self._out_sr, hop_length=128,
                fmin=self._fmin, n_chroma=12,
            )
        else:
            # STFT-Chroma: schneller, ausreichend für Gitarre (mittlere/hohe Töne)
            chroma = librosa.feature.chroma_stft(
                y=y, sr=self._out_sr, hop_length=256, n_fft=2048, n_chroma=12,
            )

        c = chroma.mean(axis=1).astype(np.float64)
        c = c ** 2                          # Power-Normalisierung: schärfere Peaks
        norm = float(np.linalg.norm(c))
        if norm < 1e-8:
            return None
        return (c / norm).tolist()

    # ── Rhythmus-Score abrufen ────────────────────────────────────────────────

    def get_rhythm_score(self, bpm: float) -> float:
        """Rhythmus-Score: 1,0 = perfekte Achtelnoten, 0,0 = unregelmäßig.

        Misst wie nah die Abstände zwischen Einsätzen (Inter-Onset-Intervalle)
        an einem Vielfachen einer Achtelnote liegen.
        Gibt 0,5 zurück wenn zu wenig Einsätze vorhanden oder bpm=0.
        """
        if bpm <= 0 or float(np.max(np.abs(self._buf))) < 1e-5:
            return 0.5
        try:
            import librosa
        except ImportError:
            return 0.5

        hop = 128
        try:
            env = librosa.onset.onset_strength(
                y=self._buf.copy(), sr=self._out_sr, hop_length=hop,
            )
            onset_frames = librosa.onset.onset_detect(
                onset_envelope=env, sr=self._out_sr, hop_length=hop, backtrack=True,
            )
        except Exception:
            return 0.5

        if len(onset_frames) < 2:
            return 0.5

        onset_times  = librosa.frames_to_time(onset_frames, sr=self._out_sr, hop_length=hop)
        eighth_sec   = 60.0 / bpm / 2.0
        max_ioi      = 4.0 * 4.0 * (60.0 / bpm)   # maximal 4 Takte

        iois = [float(d) for d in np.diff(onset_times) if 0.05 <= d <= max_ioi]
        if not iois:
            return 0.5

        scores = []
        for ioi in iois:
            n = max(1, round(ioi / eighth_sec))
            dev = abs(ioi - n * eighth_sec) / eighth_sec
            scores.append(max(0.0, 1.0 - 2.0 * dev))
        return float(np.mean(scores))

    # ── Hilfsmethoden ─────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Setzt Buffer und Filter-Zustand zurück (z.B. bei Songwechsel)."""
        self._buf[:] = 0.0
        if self._bp_zi is not None:
            self._bp_zi[:] = 0.0
