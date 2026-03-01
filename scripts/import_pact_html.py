#!/usr/bin/env python3
"""
Import-Script: Pact Repertoire HTML → lighting-ai-db.json

Parst die BandHelper-HTML-Repertoire-Liste von THE PACT und erzeugt
die lighting-ai-db.json mit korrekten Song-Daten und Part-Strukturen.
"""

import json
import re
import string
import random
from html.parser import HTMLParser
from pathlib import Path


def generate_id(length=6):
    """Erzeugt eine zufällige ID aus Buchstaben und Ziffern."""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


class RepertoireParser(HTMLParser):
    """Parst die BandHelper-HTML-Tabelle."""

    def __init__(self):
        super().__init__()
        self.songs = []
        self.current_row = []
        self.current_cell = ""
        self.in_td = False
        self.in_heading = False
        self.in_label_row = False
        self.current_class = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")

        if tag == "td":
            self.in_td = True
            self.current_cell = ""
            self.current_class = cls

            if "heading" in cls:
                self.in_heading = True
            elif "label" in cls:
                self.in_label_row = True

        if tag == "tr":
            self.current_row = []
            self.in_label_row = False

    def handle_endtag(self, tag):
        if tag == "td":
            self.in_td = False
            if not self.in_heading and not self.in_label_row:
                self.current_row.append(self.current_cell.strip())
            self.in_heading = False

        if tag == "tr":
            if len(self.current_row) == 9 and not self.in_label_row:
                self.songs.append({
                    "name": self.current_row[0],
                    "tempo": self.current_row[1],
                    "artist": self.current_row[2],
                    "gema_nr": self.current_row[3].strip(),
                    "year": self.current_row[4],
                    "pick": self.current_row[5],
                    "key": self.current_row[6],
                    "duration": self.current_row[7],
                    "notes_raw": self.current_row[8],
                })
            self.in_label_row = False

    def handle_data(self, data):
        if self.in_td:
            self.current_cell += data

    def handle_entityref(self, name):
        if self.in_td:
            self.current_cell += f"&{name};"


def parse_duration_sec(duration_str: str) -> int:
    """'3:30' → 210"""
    if not duration_str or ":" not in duration_str:
        return 0
    parts = duration_str.split(":")
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return 0


def is_part_name(text: str) -> bool:
    """Prüft ob ein Text ein Part-Name ist (vs. Kommentar/Akkordfolge)."""
    t = text.strip()
    if not t:
        return False
    # Zu lang → wahrscheinlich ein Kommentar
    if len(t) > 60:
        return False
    # Einzel-Buchstaben oder kurze Akkordnamen (C, d, G, e,d, Am, F#, etc.)
    if len(t) <= 3 and re.match(r'^[A-Ga-g#,]+$', t):
        return False
    # Reine Akkordfolgen erkennen (z.B. "CGFF CGFF", "C|C|d|G|", "dFaa dFCG")
    chord_only = t.replace("|", "").replace(",", "").strip()
    if re.match(r'^[A-Ga-g#b\d\s/]+$', chord_only) and len(chord_only) > 3:
        # Aber nicht wenn es klar ein Part-Keyword enthält
        part_keywords_quick = ["intro", "verse", "chorus", "bridge", "solo",
                               "ref", "str", "end", "outro", "thema"]
        if not any(kw in chord_only.lower() for kw in part_keywords_quick):
            return False
    # Kommentare/Anweisungen filtern (fangen mit Präpositionen/Bindewörtern an)
    comment_starters = [
        "in der ", "in die ", "über ", "nach ", "vor dem ", "vor der ",
        "vor bass", "vor git", "statt ", "dann ", "wenn ", "weil ", "wie im ",
        "ref immer", "immer ",
    ]
    tl = t.lower()
    if any(tl.startswith(cs) for cs in comment_starters):
        return False

    # Klar ein Part-Name wenn bekannte Begriffe enthalten
    part_keywords = [
        "intro", "verse", "str", "strophe", "chorus", "ref", "refrain",
        "bridge", "solo", "interlude", "outro", "end", "ausklang",
        "thema", "theme", "coda", "pre-chorus", "prechorus", "pre-verse",
        "drums", "guitar", "gitarre", "bass", "piano", "vox", "vocal",
        "abschlag", "finish", "fade", "breakdown", "buildup", "break",
        "zwischenteil", "rage", "la la", "post-chorus", "power",
        "toms", "alle", "stopp", "stop",
    ]
    if any(kw in tl for kw in part_keywords):
        return True
    # Kurze Einträge (< 25 Zeichen) ohne Pipe/Gleich/reine Chords
    if len(t) < 25 and not re.search(r'[=|]', t):
        # Aber nicht wenn es wie ein einzelner Akkord aussieht
        if not re.match(r'^[A-Ga-g#bm\d\s]+$', t):
            return True
        # Mindestens ein Wort mit >2 Buchstaben (nicht nur Akkord-Notation)
        if any(len(w) > 2 and not re.match(r'^[A-Ga-g#bm\d]+$', w) for w in t.split()):
            return True
    return False


def parse_notes_to_parts(notes_raw: str, bpm: int) -> list[dict]:
    """
    Versucht die Notizen-Feld in eine Part-Liste zu parsen.

    Erkennt Muster wie:
    - "Intro; Verse 1; Chorus; ..." → einfache Part-Namen
    - "8T Intro; 16T Verse; ..." → Part-Namen mit Taktanzahl
    - "8 Intro; 16 verse; ..." → Kurzform mit Taktanzahl

    Behandelt "|"-Separator als Alternativ-Arrangement (nur erste Hälfte nutzen).
    """
    if not notes_raw:
        return []

    # Pipe-Separator: " | " (mit Leerzeichen) trennt oft zwei Versionen
    # des Arrangements. Pipes OHNE Leerzeichen sind Akkordnotation (C|d|G|).
    if " | " in notes_raw:
        pipe_parts = notes_raw.split(" | ")
        part_keywords = ["intro", "verse", "chorus", "bridge", "solo", "ref",
                         "strophe", "interlude", "outro", "end", "thema"]
        def keyword_count(text):
            tl = text.lower()
            return sum(1 for kw in part_keywords if kw in tl)
        # Den Teil mit den meisten Part-Keywords nehmen
        best = max(pipe_parts, key=keyword_count)
        notes_raw = best

    # Aufspaltung nach Semikolon
    raw_parts = [p.strip() for p in notes_raw.split(";")]
    # Leere und reine Whitespace-Einträge raus
    raw_parts = [p for p in raw_parts if p]

    parts = []
    # Regex für Taktanzahl am Anfang: "8T Intro" oder "16 verse" oder "4t nur Git"
    bars_prefix_pattern = re.compile(r'^(\d+)\s*[Tt]?\s+(.+)$')
    # Regex für Taktanzahl in Klammern: "Verse (16T)" oder "Chorus (8T)"
    bars_paren_pattern = re.compile(r'\((\d+)\s*[Tt]\)')

    for raw in raw_parts:
        bars = 0
        name = raw

        # Erst Taktanzahl am Anfang prüfen
        m = bars_prefix_pattern.match(raw)
        if m:
            bars = int(m.group(1))
            name = m.group(2).strip()

        # Dann Taktanzahl in Klammern prüfen (z.B. "Verse (16T)")
        if bars == 0:
            m2 = bars_paren_pattern.search(name)
            if m2:
                bars = int(m2.group(1))

        # Namen normalisieren/bereinigen — Klammer-Taktangaben entfernen
        name = bars_paren_pattern.sub('', name).strip()
        # Timestamps entfernen (z.B. "0:00 Verse1a" → "Verse1a", "2:34 Chorus 3b" → "Chorus 3b")
        name = re.sub(r'^\d+:\d+\s+', '', name).strip()
        # Inline-Akkordnotation mit Pipes entfernen (z.B. "ref C|C|d|G|e,d|" → "Ref")
        name = re.sub(r'\s+[A-Ga-g#|,\d]+\|[A-Ga-g#|,\d]*', '', name).strip()
        # Akkordfolgen nach Part-Name entfernen (z.B. "Intro CGFF CGFF CGaF CGFF" → "Intro")
        name = re.sub(r'\s+[A-G][A-Ga-g#\d]+(\s+[A-G][A-Ga-g#\d]+){2,}', '', name).strip()
        # Trailing Kommas, Punkte, Pipes entfernen
        name = name.rstrip(",.|; ")

        # Part-Name-Filterung
        if not is_part_name(name):
            continue

        parts.append({
            "name": name,
            "bars": bars,
        })

    return parts


def classify_part_template(name: str) -> str:
    """Weist einem Part-Namen ein Light-Template zu."""
    nl = name.lower()

    if any(w in nl for w in ["intro", "thema"]):
        return "intro_buildup"
    if any(w in nl for w in ["verse", "str", "strophe"]):
        if any(w in nl for w in ["power", "alle", "full"]):
            return "verse_driving"
        if any(w in nl for w in ["leise", "quiet", "ohne", "only", "nur"]):
            return "verse_minimal"
        return "verse_driving"
    if any(w in nl for w in ["bridge", "pre-chorus", "prechorus"]):
        return "prechorus_rise"
    if any(w in nl for w in ["chorus", "ref", "refrain"]):
        if any(w in nl for w in ["stop", "halb", "half"]):
            return "chorus_half"
        return "chorus_full"
    if "solo" in nl:
        if "bass" in nl:
            return "solo_intense"
        return "solo_spotlight"
    if "interlude" in nl:
        return "bridge_atmospheric"
    if any(w in nl for w in ["outro", "end", "ausklang", "fade", "abschlag", "finish", "coda"]):
        return "outro_fadeout"
    if any(w in nl for w in ["breakdown", "break"]):
        return "breakdown_minimal"
    if any(w in nl for w in ["buildup", "steigerung"]):
        return "buildup_8bars"

    return "generic_bpm"


def calc_part_duration(bars: int, bpm: int) -> int:
    """Berechnet Part-Dauer in Sekunden aus Bars und BPM."""
    if bars <= 0 or bpm <= 0:
        return 0
    # 4/4 Takt: 1 Takt = 4 Beats
    return round((bars * 4 * 60) / bpm)


def build_db(songs_raw: list[dict]) -> dict:
    """Baut die komplette DB-Struktur."""
    used_ids = set()

    def unique_id():
        while True:
            sid = generate_id(6)
            if sid not in used_ids:
                used_ids.add(sid)
                return sid

    songs = {}

    for s in songs_raw:
        song_id = unique_id()

        bpm = 0
        if s["tempo"]:
            try:
                bpm = int(s["tempo"])
            except ValueError:
                pass

        duration_sec = parse_duration_sec(s["duration"])

        # Pick-Feld: 🔻 steht für ein Plektrum/Pick, Inhalt 1:1 übernehmen
        pick = s["pick"].strip()

        # GEMA bereinigen
        gema = s["gema_nr"].strip()
        if gema.lower().startswith("keine"):
            gema = ""

        # Parts aus Notizen parsen
        raw_parts = parse_notes_to_parts(s["notes_raw"], bpm)

        parts = {}
        notes = s["notes_raw"]  # Original-Notizen als Backup

        if raw_parts:
            for i, rp in enumerate(raw_parts, 1):
                part_id = f"{song_id}_P{i:03d}"
                dur = calc_part_duration(rp["bars"], bpm) if rp["bars"] > 0 else 0
                template = classify_part_template(rp["name"])

                parts[part_id] = {
                    "pos": i,
                    "name": rp["name"],
                    "bars": rp["bars"],
                    "duration_sec": dur,
                    "light_template": template,
                    "notes": "",
                }

        songs[song_id] = {
            "name": s["name"],
            "artist": s["artist"],
            "bpm": bpm,
            "key": s["key"],
            "year": s["year"],
            "pick": pick,
            "gema_nr": gema,
            "duration": s["duration"],
            "duration_sec": duration_sec,
            "notes": notes,
            "parts": parts,
        }

    # Setlist: alle Songs in alphabetischer Reihenfolge
    sorted_songs = sorted(songs.items(), key=lambda x: x[1]["name"].lower())
    setlist_items = []
    for i, (sid, _) in enumerate(sorted_songs, 1):
        setlist_items.append({"type": "song", "pos": i, "song_id": sid})

    db = {
        "version": "1.0",
        "band": "The Pact",
        "setlist": {
            "name": "Repertoire",
            "items": setlist_items,
        },
        "songs": songs,
        "bars": {},
        "accents": {},
        "meta": {
            "accent_types": {
                "bl": "Blinder",
                "bo": "Blackout",
                "hl": "Highlight",
                "st": "Strobe",
                "fg": "Fog",
            },
            "pos_16th_map": "1=eins,2=e,3=und,4=e,5=zwei,6=e,7=und,8=e,9=drei,10=e,11=und,12=e,13=vier,14=e,15=und,16=e",
            "storage": "github",
            "audio_path": "audio/{song_id}/{part_id}/",
        },
    }

    return db


def main():
    repo_root = Path(__file__).resolve().parent.parent
    html_path = repo_root / "db" / "Pact Repertoire.html"
    output_path = repo_root / "db" / "lighting-ai-db.json"

    print(f"Lese HTML: {html_path}")
    html_content = html_path.read_text(encoding="utf-8")

    parser = RepertoireParser()
    parser.feed(html_content)

    print(f"Gefunden: {len(parser.songs)} Songs")

    for s in parser.songs:
        tempo = s["tempo"] or "?"
        parts = parse_notes_to_parts(s["notes_raw"], int(s["tempo"]) if s["tempo"] else 0)
        parts_info = f"{len(parts)} parts" if parts else "no parts"
        print(f"  {s['name']:40s} {s['artist']:30s} {tempo:>4s} BPM  {s['key']:12s} {s['gema_nr']:16s} {parts_info}")

    db = build_db(parser.songs)

    print(f"\nSchreibe DB: {output_path}")
    print(f"  Songs: {len(db['songs'])}")

    total_parts = sum(len(s["parts"]) for s in db["songs"].values())
    songs_with_parts = sum(1 for s in db["songs"].values() if s["parts"])
    print(f"  Parts gesamt: {total_parts}")
    print(f"  Songs mit Parts: {songs_with_parts}")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

    print("\nDone!")


if __name__ == "__main__":
    main()
