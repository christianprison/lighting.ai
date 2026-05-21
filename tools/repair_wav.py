#!/usr/bin/env python3
"""Repariert WAV/RF64-Aufnahmen mit kaputtem Header.

Problem
-------
Die Live-App schreibt die Multitrack-Aufnahme als RF64-Datei. Die
finalen 64-Bit-Größenangaben im ``ds64``-Chunk werden erst beim
``close()`` der Datei geschrieben. Wird der Server abrupt beendet
(Terminal geschlossen, Laptop-Deckel zu, SIGKILL), bleibt der Header
inkonsistent. ``soundfile`` / ``libsndfile`` melden dann beim Öffnen
oder Seek "Internal psf_fseek() failed."

Was tut dieses Skript?
----------------------
Liest die Roh-Bytes der kaputten WAV, findet den ``data``-Chunk,
berechnet die tatsächliche Audio-Daten-Länge anhand der Dateigröße
und schreibt eine frische Datei mit korrekten Header-Größen.

Was kann es NICHT?
------------------
Wenn während der Aufnahme die XR18 zeitweise keine Blöcke geliefert hat
(USB-Hänger), ist die Audio-Spur einfach kürzer als die Wall-Clock-Zeit.
Diese fehlenden Samples kann kein Repair-Tool rekonstruieren — die
reparierte Datei spielt dann schneller ab, weil die Lücken fehlen.

Benutzung
---------
    python3 tools/repair_wav.py <broken.wav> [<output.wav>]

Wenn ``output`` weggelassen wird: ``<broken>_repaired.wav`` neben dem
Original. Beim Repair-Vorgang wird das Original nicht angerührt.

Mehrere Dateien auf einmal:
    python3 tools/repair_wav.py live/data/recordings/2026-05-20/*.wav

Annahmen
--------
- Format: RF64 oder WAV, 18 Kanäle (oder weniger), Float32 (Subtype FLOAT).
- Der ``fmt ``-Chunk muss intakt sein (das ist er normalerweise — kaputt
  ist nur der ``ds64`` mit der Größenangabe).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

# Standard-Chunk-IDs (Big-Endian gelesen als 4-Byte-Strings)
RIFF_ID   = b"RIFF"
RF64_ID   = b"RF64"
BW64_ID   = b"BW64"
WAVE_ID   = b"WAVE"
FMT_ID    = b"fmt "
DATA_ID   = b"data"
DS64_ID   = b"ds64"
JUNK_ID   = b"JUNK"

# WAVE_FORMAT-Tags
WAVE_FORMAT_PCM        = 0x0001
WAVE_FORMAT_IEEE_FLOAT = 0x0003
WAVE_FORMAT_EXTENSIBLE = 0xFFFE

# Maximal akzeptable Sondiertiefe für den data-Chunk
MAX_HEADER_SCAN = 4096


def _find_chunk(data: bytes, chunk_id: bytes, start: int = 12) -> int | None:
    """Sucht ein Chunk-Header ab Position ``start``. Gibt die Position
    des Chunk-Headers (also der 4-Byte-ID) zurück oder ``None``.

    Geht durch die Chunk-Kette: nach jedem Chunk-Header (8 Bytes) folgt
    ``size`` Bytes Inhalt, dann der nächste Chunk.
    """
    pos = start
    n = len(data)
    while pos + 8 <= n:
        cid = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if cid == chunk_id:
            return pos
        # RF64: ds64-Chunk enthält 64-Bit-Größen, der 32-Bit-Header-Wert
        # ist 0xFFFFFFFF und unbrauchbar. Wir scannen einfach nach den
        # bekannten IDs auf 2-Byte-Raster, falls die Chunk-Kette gebrochen ist.
        if size == 0xFFFFFFFF or size == 0:
            break
        # WAV-Chunks sind word-aligned (gerade Größe)
        next_pos = pos + 8 + size + (size & 1)
        if next_pos <= pos:
            break
        pos = next_pos
    # Fallback: lineare Suche nach der ID innerhalb der ersten paar KB.
    needle = chunk_id
    end = min(MAX_HEADER_SCAN, len(data) - 4)
    p = data.find(needle, 12, end)
    return p if p >= 0 else None


def _parse_fmt(fmt_chunk: bytes) -> dict:
    """Parst einen ``fmt ``-Chunk-Inhalt (ohne ID+Size-Prefix)."""
    if len(fmt_chunk) < 16:
        raise ValueError("fmt-Chunk zu klein")
    audio_format, num_channels, sample_rate, byte_rate, block_align, bits = \
        struct.unpack("<HHIIHH", fmt_chunk[:16])
    sub_format_tag = audio_format
    if audio_format == WAVE_FORMAT_EXTENSIBLE and len(fmt_chunk) >= 40:
        # Erste 2 Byte des SubFormat-GUID = eigentlicher Format-Tag
        sub_format_tag = struct.unpack("<H", fmt_chunk[24:26])[0]
    return {
        "format_tag":      audio_format,
        "sub_format_tag":  sub_format_tag,
        "channels":        num_channels,
        "sample_rate":     sample_rate,
        "byte_rate":       byte_rate,
        "block_align":     block_align,
        "bits_per_sample": bits,
        "fmt_chunk_bytes": fmt_chunk,
    }


def _build_rf64_header(fmt_info: dict, data_size_bytes: int) -> bytes:
    """Baut einen kompletten RF64-Header für die gegebene Audio-Konfiguration.

    Layout:
      RF64  0xFFFFFFFF  WAVE
      ds64  size=28
        riff_size   (uint64) = data_size + alle Header
        data_size   (uint64) = data_size_bytes
        sample_count(uint64) = data_size / block_align
        table_len   (uint32) = 0  (keine zusätzlichen Chunks)
      fmt   <original fmt chunk>
      data  0xFFFFFFFF
        <audio data folgt>
    """
    fmt_bytes = fmt_info["fmt_chunk_bytes"]
    fmt_size  = len(fmt_bytes)
    # Word-Align fmt
    fmt_pad = fmt_size & 1
    block_align = fmt_info["block_align"] or 1
    sample_count = data_size_bytes // block_align

    # Aufbau ohne riff_size, die kommt nachher
    parts = bytearray()
    # RF64 / 0xFFFFFFFF / WAVE
    parts += RF64_ID
    parts += b"\xFF\xFF\xFF\xFF"
    parts += WAVE_ID
    # ds64 chunk: id(4) size(4) + 28 bytes Inhalt
    parts += DS64_ID
    parts += struct.pack("<I", 28)
    # placeholder: riff_size (8) + data_size (8) + sample_count (8) + table_len (4)
    parts += struct.pack("<Q", 0)               # riff_size — wird gleich gepatcht
    parts += struct.pack("<Q", data_size_bytes)
    parts += struct.pack("<Q", sample_count)
    parts += struct.pack("<I", 0)               # table_len
    # fmt chunk
    parts += FMT_ID
    parts += struct.pack("<I", fmt_size)
    parts += fmt_bytes
    if fmt_pad:
        parts += b"\x00"
    # data chunk header
    parts += DATA_ID
    parts += b"\xFF\xFF\xFF\xFF"

    # Jetzt riff_size patchen = Gesamtgröße - 8 Bytes (RF64-ID+placeholder)
    total = len(parts) + data_size_bytes
    riff_size = total - 8
    # ds64.riff_size liegt bei Offset 4+4+4+4+4 = 20
    struct.pack_into("<Q", parts, 20, riff_size)
    return bytes(parts)


def repair_file(src: Path, dst: Path | None = None, *, verbose: bool = True) -> Path:
    """Repariert eine einzelne WAV/RF64-Datei.

    Returns
    -------
    Pfad der reparierten Datei.
    """
    src = Path(src).resolve()
    if dst is None:
        dst = src.with_name(src.stem + "_repaired" + src.suffix)
    dst = Path(dst)
    if dst.exists():
        raise FileExistsError(f"Zieldatei existiert schon: {dst}")

    file_size = src.stat().st_size
    if file_size < 44:
        raise ValueError(f"Datei zu klein für WAV ({file_size} B): {src}")

    with src.open("rb") as fp:
        # Erste paar KB reichen, um Header zu parsen.
        header_probe = fp.read(min(MAX_HEADER_SCAN, file_size))

        riff_id = header_probe[0:4]
        if riff_id not in (RIFF_ID, RF64_ID, BW64_ID):
            raise ValueError(
                f"Unbekannte Datei-ID {riff_id!r} — keine WAV/RF64-Datei: {src}"
            )
        wave_id = header_probe[8:12]
        if wave_id != WAVE_ID:
            raise ValueError(f"WAVE-Marker fehlt (gefunden: {wave_id!r}): {src}")

        # fmt-Chunk lokalisieren
        fmt_pos = _find_chunk(header_probe, FMT_ID)
        if fmt_pos is None:
            raise ValueError(f"fmt-Chunk nicht gefunden in: {src}")
        fmt_size = struct.unpack("<I", header_probe[fmt_pos + 4:fmt_pos + 8])[0]
        fmt_bytes = header_probe[fmt_pos + 8:fmt_pos + 8 + fmt_size]
        fmt_info = _parse_fmt(fmt_bytes)

        # data-Chunk-Position bestimmen
        data_pos = _find_chunk(header_probe, DATA_ID)
        if data_pos is None:
            raise ValueError(
                f"data-Chunk nicht im ersten {MAX_HEADER_SCAN}-Byte-Fenster — "
                f"unerwartet großer Header in: {src}"
            )
        data_start = data_pos + 8  # ID(4) + size(4)
        actual_data_size = file_size - data_start
        block_align = fmt_info["block_align"] or 1
        # Auf vollen Frame abrunden (falls Datei nicht auf Block-Grenze endet)
        actual_data_size -= actual_data_size % block_align

        if actual_data_size <= 0:
            raise ValueError(f"Keine Audio-Daten in: {src} (size={file_size})")

        # Neuen Header bauen + Datei schreiben
        new_header = _build_rf64_header(fmt_info, actual_data_size)

        if verbose:
            sec = actual_data_size / (fmt_info["sample_rate"] * block_align)
            print(
                f"  {src.name}: "
                f"{fmt_info['channels']} ch × {fmt_info['sample_rate']} Hz × "
                f"{fmt_info['bits_per_sample']} bit, "
                f"{actual_data_size:,} B Audio = {sec:.1f} s",
                file=sys.stderr,
            )

        # Audio-Daten kopieren
        with dst.open("wb") as out:
            out.write(new_header)
            fp.seek(data_start)
            remaining = actual_data_size
            buf_size = 4 * 1024 * 1024  # 4 MB
            while remaining > 0:
                chunk = fp.read(min(buf_size, remaining))
                if not chunk:
                    break
                out.write(chunk)
                remaining -= len(chunk)

    return dst


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__, file=sys.stderr)
        return 1

    inputs = [Path(a) for a in argv[1:]]
    explicit_output: Path | None = None
    if len(inputs) == 2 and inputs[1].suffix.lower() == ".wav" and not inputs[1].exists():
        # Form: repair_wav.py broken.wav fixed.wav
        explicit_output = inputs[1]
        inputs = inputs[:1]

    failures = 0
    for src in inputs:
        if not src.exists():
            print(f"FEHLT: {src}", file=sys.stderr)
            failures += 1
            continue
        if src.stem.endswith("_repaired") or src.stem.endswith("_mixdown"):
            print(f"SKIP (schon repariert oder mixdown): {src.name}", file=sys.stderr)
            continue
        try:
            dst = repair_file(src, explicit_output)
            print(f"OK  → {dst}", file=sys.stderr)
        except Exception as exc:
            print(f"FEHLER bei {src}: {exc}", file=sys.stderr)
            failures += 1

    return 0 if failures == 0 else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
