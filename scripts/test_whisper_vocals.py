#!/usr/bin/env python3
"""Test Whisper speech recognition on a vocal channel from a multitrack WAV.

Usage:
    python test_whisper_vocals.py <session.wav> [options]

Options:
    --channel N     WAV channel index (0-based). Default: 0 (Pete Vox)
                    0=Pete, 1=Axel, 2=Bibo
    --start S       Start time in seconds (default: 0)
    --end E         End time in seconds (default: 60 — only first minute)
    --model M       Whisper model: tiny, base, small, medium, large-v3
                    Default: medium. large-v3 ist langsamer, aber besser.
    --language L    Sprachhinweis: 'de', 'en', oder leer lassen für Autodetect.
    --mix           Statt einzelnem Kanal: Main L+R (CH 16+17) als Stereo-Mix.

Beispiel (erste 90 Sekunden eines Songs, Pete Vox, Autodetect):
    python test_whisper_vocals.py 2025-11-01_203000_probe.wav --end 90

Beispiel (kompletter Song-Abschnitt, Axel, Modell large-v3):
    python test_whisper_vocals.py probe.wav --channel 1 --start 120 --end 240 --model large-v3

Setup (einmalig im venv):
    pip install openai-whisper
    # ffmpeg muss installiert sein: sudo apt install ffmpeg
"""

import argparse
import sys
from pathlib import Path

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("wav", help="Pfad zur 18-Kanal WAV-Datei")
    parser.add_argument("--channel", type=int, default=0,
                        help="Kanal-Index (0-basiert). 0=Pete, 1=Axel, 2=Bibo (default: 0)")
    parser.add_argument("--start",   type=float, default=0.0,
                        help="Startzeit in Sekunden (default: 0)")
    parser.add_argument("--end",     type=float, default=60.0,
                        help="Endzeit in Sekunden (default: 60)")
    parser.add_argument("--model",   default="medium",
                        choices=["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"],
                        help="Whisper-Modell (default: medium)")
    parser.add_argument("--language", default=None,
                        help="Sprachcode, z.B. 'de' oder 'en' (default: Autodetect)")
    parser.add_argument("--mix",     action="store_true",
                        help="Main L+R Mix (CH 16+17) statt einzelnem Kanal")
    args = parser.parse_args()

    wav_path = Path(args.wav)
    if not wav_path.exists():
        sys.exit(f"Datei nicht gefunden: {wav_path}")

    # --- soundfile laden ---
    try:
        import soundfile as sf
    except ImportError:
        sys.exit("soundfile nicht installiert: pip install soundfile")

    print(f"Lade {wav_path.name} …")
    info = sf.info(str(wav_path))
    sr = info.samplerate
    total_ch = info.channels
    total_sec = info.frames / sr
    print(f"  {total_ch} Kanäle, {sr} Hz, {total_sec:.1f} s gesamt")

    start_frame = int(args.start * sr)
    end_frame   = min(int(args.end * sr), info.frames)
    dur = (end_frame - start_frame) / sr
    print(f"  Lade [{args.start:.1f} s – {args.end:.1f} s] = {dur:.1f} s")

    data, _ = sf.read(str(wav_path), start=start_frame, stop=end_frame, dtype="float32")
    # data shape: (frames, channels)

    if args.mix:
        if total_ch < 18:
            sys.exit(f"Erwartet 18 Kanäle für Main L+R, hat nur {total_ch}")
        mono = (data[:, 16] + data[:, 17]) * 0.5
        label = "Main L+R Mix"
    else:
        if args.channel >= total_ch:
            sys.exit(f"Kanal {args.channel} nicht vorhanden (WAV hat {total_ch} Kanäle)")
        mono = data[:, args.channel]
        ch_names = {0: "Pete Vox", 1: "Axel Vox", 2: "Bibo Vox",
                    3: "Rhythm Guitar", 4: "Lead Guitar", 5: "Bass"}
        label = ch_names.get(args.channel, f"CH {args.channel}")

    print(f"  Kanal: {label}")

    # Peak-RMS als Plausibilitätscheck
    rms = float(np.sqrt(np.mean(mono ** 2)))
    peak = float(np.max(np.abs(mono)))
    print(f"  RMS={rms:.4f}  Peak={peak:.4f}", end="")
    if rms < 0.001:
        print("  ⚠ sehr leise — Kanal evtl. stumm oder falsch?", end="")
    print()

    # --- Whisper ---
    try:
        import whisper
    except ImportError:
        sys.exit("\nWhisper nicht installiert.\n"
                 "Bitte im venv ausführen:\n"
                 "  source /opt/lighting-venv/bin/activate\n"
                 "  pip install openai-whisper")

    print(f"\nLade Whisper-Modell '{args.model}' …")
    model = whisper.load_model(args.model)

    # Whisper erwartet float32 mono bei 16 kHz
    if sr != 16_000:
        print(f"  Resampling {sr} Hz → 16000 Hz …")
        try:
            import librosa
            mono = librosa.resample(mono, orig_sr=sr, target_sr=16_000)
        except ImportError:
            # Fallback: einfaches Decimation (grob, reicht zum Testen)
            ratio = sr // 16_000
            if ratio > 1:
                mono = mono[::ratio]
            print("  (librosa nicht gefunden, einfaches Decimation)")

    print(f"Transkribiere {dur:.1f} s …\n")
    result = model.transcribe(
        mono,
        language=args.language,
        verbose=False,          # keine Block-für-Block Ausgabe
        word_timestamps=False,
    )

    detected_lang = result.get("language", "?")
    print(f"{'='*60}")
    print(f"Erkannte Sprache: {detected_lang}")
    print(f"{'='*60}")
    print(result["text"].strip())
    print(f"{'='*60}\n")

    print("Segmente:")
    for seg in result["segments"]:
        # Zeitangaben relativ zur WAV-Datei (nicht zum Ausschnitt) ausgeben
        t0 = args.start + seg["start"]
        t1 = args.start + seg["end"]
        print(f"  [{t0:6.1f}s – {t1:6.1f}s]  {seg['text'].strip()}")


if __name__ == "__main__":
    main()
