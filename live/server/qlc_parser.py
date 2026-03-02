"""Parse QLC+ 4 QXW workspace file and extract song chasers, collections, accents."""

from __future__ import annotations

import logging
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("live.qlc_parser")

INFINITE_HOLD = 4294967294  # 0xFFFFFFFE — manual advance in QLC+
STOP_FUNCTION_ID = 82       # "11 Stop" — title/end marker in song chasers

# Known accent / utility function IDs
ACCENT_FUNCTIONS = {
    "blind": 212,
    "blackout": 36,
    "strobe": 81,
    "alarm": 80,
    "fog_on": 38,
    "fog_off": 39,
    "fog_5s": 40,
    "fog_10s": 37,
}

# Base mood collections (numbered lighting programs)
BASE_COLLECTIONS = {
    70: "02 slow blue",
    71: "01 statisch bunt",
    74: "03 walking",
    75: "04 up'n'down",
    76: "05 left'n'right",
    77: "06 blinking",
    78: "07 round'n'round",
    79: "08 swimming",
    80: "09 Alarm",
    81: "10 Strobe",
    82: "11 Stop",
    83: "16 Searchlight",
    181: "20 white Fan up",
    182: "21 white fan down",
}

SPOT_COLLECTIONS = {
    224: "Spot auf Axel",
    226: "Spot auf Axel hot",
    227: "Spot auf Bibo",
    228: "Spot auf Pete",
    229: "Spot auf Tim",
}


@dataclass
class ChaserStep:
    index: int
    function_id: int
    function_name: str
    note: str  # Part name / description from the Note attribute
    hold_ms: int  # Duration in ms, or INFINITE_HOLD for manual advance
    fade_in: int = 0
    fade_out: int = 0
    is_title: bool = False  # True for the first/last "song name" steps
    is_manual: bool = False  # True if hold == INFINITE_HOLD


@dataclass
class SongChaser:
    chaser_id: int
    chaser_name: str
    steps: list[ChaserStep] = field(default_factory=list)
    song_id: str | None = None  # Matched DB song ID
    song_name: str | None = None  # Matched DB song name


@dataclass
class QlcFunction:
    id: int
    type: str
    name: str
    path: str = ""


@dataclass
class QlcData:
    """Complete parsed QLC+ data."""
    functions: dict[int, QlcFunction] = field(default_factory=dict)
    song_chasers: dict[int, SongChaser] = field(default_factory=dict)
    base_collections: dict[int, str] = field(default_factory=dict)
    spot_collections: dict[int, str] = field(default_factory=dict)
    accent_functions: dict[str, int] = field(default_factory=dict)
    song_mapping: dict[str, SongChaser] = field(default_factory=dict)  # song_id -> SongChaser


def _normalize(text: str) -> str:
    """Normalize a string for fuzzy matching: lowercase, strip emojis/symbols, normalize quotes."""
    # Remove emoji and special chars
    cleaned = "".join(
        c for c in text
        if unicodedata.category(c)[0] not in ("So", "Sk", "Cn")
    )
    # Normalize all quote variants to ASCII apostrophe
    cleaned = re.sub(r"[\u2018\u2019\u201A\u201B\u0060\u00B4]", "'", cleaned)
    # Lowercase, strip, collapse whitespace
    return re.sub(r"\s+", " ", cleaned.lower().strip())


def _match_songs(chasers: dict[int, SongChaser], db_songs: dict) -> dict[str, SongChaser]:
    """Match QLC+ song chasers to DB songs by name (fuzzy)."""
    mapping: dict[str, SongChaser] = {}

    # Build normalized name -> song_id lookup
    db_lookup: dict[str, tuple[str, str]] = {}  # normalized_name -> (song_id, original_name)
    for song_id, song in db_songs.items():
        norm = _normalize(song["name"])
        db_lookup[norm] = (song_id, song["name"])

    for chaser in chasers.values():
        norm_chaser = _normalize(chaser.chaser_name)

        # Direct match
        if norm_chaser in db_lookup:
            sid, sname = db_lookup[norm_chaser]
            chaser.song_id = sid
            chaser.song_name = sname
            mapping[sid] = chaser
            log.info("Matched: '%s' -> '%s' (%s)", chaser.chaser_name, sname, sid)
            continue

        # Substring match: chaser name contains DB song name or vice versa
        best_match = None
        best_len = 0
        for norm_db, (sid, sname) in db_lookup.items():
            if norm_db in norm_chaser or norm_chaser in norm_db:
                if len(norm_db) > best_len:
                    best_match = (sid, sname)
                    best_len = len(norm_db)

        if best_match and best_match[0] not in mapping:
            sid, sname = best_match
            chaser.song_id = sid
            chaser.song_name = sname
            mapping[sid] = chaser
            log.info("Fuzzy matched: '%s' -> '%s' (%s)", chaser.chaser_name, sname, sid)
        else:
            log.warning("No DB match for chaser: '%s' (ID %d)", chaser.chaser_name, chaser.chaser_id)

    return mapping


def parse(qxw_path: Path, db_songs: dict | None = None) -> QlcData:
    """Parse a QXW file and return structured QLC+ data."""
    tree = ET.parse(qxw_path)
    root = tree.getroot()

    # Handle QLC+ namespace
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    engine = root.find(f"{ns}Engine")
    if engine is None:
        raise ValueError("No <Engine> element found in QXW")

    data = QlcData()
    data.accent_functions = dict(ACCENT_FUNCTIONS)

    # Pass 1: Extract all functions
    for func_el in engine.findall(f"{ns}Function"):
        fid = int(func_el.get("ID", -1))
        ftype = func_el.get("Type", "")
        fname = func_el.get("Name", "")
        fpath = func_el.get("Path", "")

        data.functions[fid] = QlcFunction(id=fid, type=ftype, name=fname, path=fpath)

        # Identify base collections
        if fid in BASE_COLLECTIONS:
            data.base_collections[fid] = fname
        if fid in SPOT_COLLECTIONS:
            data.spot_collections[fid] = fname

        # Identify song chasers (Path="Pact Songs" and Type="Chaser")
        if ftype == "Chaser" and fpath == "Pact Songs":
            chaser = SongChaser(chaser_id=fid, chaser_name=fname)

            for step_el in func_el.findall(f"{ns}Step"):
                step_num = int(step_el.get("Number", 0))
                hold = int(step_el.get("Hold", 0))
                fade_in = int(step_el.get("FadeIn", 0))
                fade_out = int(step_el.get("FadeOut", 0))
                note = step_el.get("Note", "")
                func_id = int(step_el.text.strip()) if step_el.text else 0

                # Look up the referenced function name
                func_name = ""
                if func_id in data.functions:
                    func_name = data.functions[func_id].name
                elif func_id in BASE_COLLECTIONS:
                    func_name = BASE_COLLECTIONS[func_id]
                elif func_id in SPOT_COLLECTIONS:
                    func_name = SPOT_COLLECTIONS[func_id]

                is_title = (func_id == STOP_FUNCTION_ID and hold == INFINITE_HOLD)

                step = ChaserStep(
                    index=step_num,
                    function_id=func_id,
                    function_name=func_name,
                    note=note,
                    hold_ms=hold,
                    fade_in=fade_in,
                    fade_out=fade_out,
                    is_title=is_title,
                    is_manual=(hold == INFINITE_HOLD),
                )
                chaser.steps.append(step)

            # Skip empty chasers (deprecated songs with no steps)
            if chaser.steps:
                data.song_chasers[fid] = chaser
                log.info("Parsed chaser: '%s' (ID %d, %d steps)", fname, fid, len(chaser.steps))
            else:
                log.info("Skipped empty chaser: '%s' (ID %d)", fname, fid)

    # Resolve function names for steps that weren't yet in the lookup
    for chaser in data.song_chasers.values():
        for step in chaser.steps:
            if not step.function_name and step.function_id in data.functions:
                step.function_name = data.functions[step.function_id].name

    # Pass 2: Match songs to DB
    if db_songs:
        data.song_mapping = _match_songs(data.song_chasers, db_songs)

    log.info(
        "QXW parsed: %d functions, %d song chasers, %d matched to DB",
        len(data.functions),
        len(data.song_chasers),
        len(data.song_mapping),
    )

    return data


def chaser_to_dict(chaser: SongChaser) -> dict:
    """Serialize a SongChaser to a JSON-friendly dict."""
    return {
        "chaser_id": chaser.chaser_id,
        "chaser_name": chaser.chaser_name,
        "song_id": chaser.song_id,
        "song_name": chaser.song_name,
        "steps": [
            {
                "index": s.index,
                "function_id": s.function_id,
                "function_name": s.function_name,
                "note": s.note,
                "hold_ms": s.hold_ms,
                "hold_sec": round(s.hold_ms / 1000, 1) if s.hold_ms < INFINITE_HOLD else None,
                "fade_in": s.fade_in,
                "fade_out": s.fade_out,
                "is_title": s.is_title,
                "is_manual": s.is_manual,
            }
            for s in chaser.steps
        ],
    }


def qlc_data_to_dict(data: QlcData) -> dict:
    """Serialize full QLC data for the API / WebSocket."""
    return {
        "song_chasers": {
            str(k): chaser_to_dict(v) for k, v in data.song_chasers.items()
        },
        "song_mapping": {
            sid: chaser_to_dict(ch) for sid, ch in data.song_mapping.items()
        },
        "base_collections": data.base_collections,
        "spot_collections": data.spot_collections,
        "accent_functions": data.accent_functions,
    }
