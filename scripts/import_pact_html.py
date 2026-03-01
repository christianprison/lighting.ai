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


class LyricsStripper(HTMLParser):
    """Entfernt HTML-Tags aus BandHelper-Lyrics und gibt Plaintext zurück."""

    def __init__(self):
        super().__init__()
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "p"):
            self.text.append("\n")

    def handle_data(self, data):
        self.text.append(data)

    def get_text(self):
        return "".join(self.text)


def strip_html_lyrics(html: str) -> str:
    """HTML-Lyrics → Plaintext."""
    s = LyricsStripper()
    s.feed(html)
    return s.get_text()


def parse_lyrics_sections(html_lyrics: str) -> list[dict]:
    """
    Parst HTML-Lyrics aus BandHelper in Sektionen mit Lyrics-Zeilen.

    Rückgabe: [{"section": "VERSE 1", "lines": ["Line 1", "Line 2", ...]}, ...]
    """
    text = strip_html_lyrics(html_lyrics)
    lines = text.split("\n")

    # Akkorde und Tab-Notation entfernen
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Tab-Notation (|——— Muster)
        if re.match(r'^[|\-—\d\s]+$', stripped):
            continue
        # Reine Akkordzeilen (H5  E5 F#5 etc.)
        if re.match(r'^[\s|:]*([A-H][#b♯♭]?\d?\s*)+[|:\s]*$', stripped):
            continue
        # Akkord-Patterns wie "||: H5   E5 F♯5 :||"
        if re.match(r'^\|{0,2}:?\s*[A-H]', stripped) and re.search(r'[|:]', stripped):
            continue
        # Reine Akkordnamen ohne Lyrics (z.B. "Fm Fm6", "C/Fm Fm")
        if re.match(r'^[A-H][#b♯♭]?\d?m?\d?(/[A-H][#b♯♭]?\d?m?\d?)?\s+[A-H]', stripped) and len(stripped) < 20:
            continue
        # Inline-Akkorde entfernen (2+ Leerzeichen nach Akkord = Inline-Chord)
        cleaned = re.sub(r'[A-H][#b♯♭♮]?\d?m?\d?\s{2,}', '', stripped)
        cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
        if cleaned and len(cleaned) > 1:
            cleaned_lines.append(cleaned)

    # In Sektionen aufteilen
    section_pattern = re.compile(
        r'^(VERSE|CHORUS|THEME|BRIDGE|INTRO|OUTRO|INTERLUDE|SOLO|PRE-CHORUS|BREAKDOWN|CODA)'
        r'[\s\d:]*',
        re.IGNORECASE
    )

    sections = []
    current_section = {"section": "Intro", "lines": []}

    for line in cleaned_lines:
        # Songtitel-Zeile überspringen
        if line.isupper() and len(line.split()) <= 5 and not section_pattern.match(line):
            continue

        m = section_pattern.match(line)
        if m:
            # Neue Sektion starten
            if current_section["lines"]:
                sections.append(current_section)
            section_name = line.rstrip(":").strip()
            current_section = {"section": section_name, "lines": []}
        else:
            # Spielanweisungen filtern (z.B. "Chorus: Repeat 4x Clarinet Solo")
            if re.match(r'^(Chorus|Repeat|repeat):\s*(Repeat|repeat)', line):
                continue
            current_section["lines"].append(line)

    if current_section["lines"]:
        sections.append(current_section)

    return sections


def load_stringbreak_lyrics(stringbreak_path: Path) -> dict[str, list[dict]]:
    """
    Lädt Lyrics aus Stringbreak.json und gibt sie nach Song-Name indiziert zurück.

    Rückgabe: {"Along comes Mary": [{"section": "VERSE 1", "lines": [...]}, ...], ...}
    """
    if not stringbreak_path.exists():
        return {}

    with open(stringbreak_path, encoding="utf-8") as f:
        sb = json.load(f)

    lyrics_by_name = {}
    for sid, song in sb.get("song", {}).items():
        lyrics_html = song.get("lyrics", "")
        if not lyrics_html:
            continue
        name = song.get("name", "")
        sections = parse_lyrics_sections(lyrics_html)
        if sections:
            lyrics_by_name[name] = sections

    return lyrics_by_name


def match_section_to_part(section_name: str, part_name: str) -> bool:
    """Prüft ob eine Lyrics-Sektion zu einem Part passt (fuzzy)."""
    sn = section_name.lower().strip()
    pn = part_name.lower().strip()

    # Exakter Match
    if sn == pn:
        return True

    # Kernwort-Match (VERSE 1 ↔ Verse 1, CHORUS ↔ Chorus (lunch))
    section_keywords = {
        "verse": ["verse", "str", "strophe"],
        "chorus": ["chorus", "ref", "refrain"],
        "theme": ["theme", "thema", "intro", "interlude"],
        "bridge": ["bridge"],
        "intro": ["intro"],
        "outro": ["outro", "end", "ausklang", "coda"],
        "solo": ["solo"],
        "interlude": ["interlude"],
    }

    # Nummer extrahieren (Verse 1, Chorus 2, etc.)
    sn_num = re.search(r'\d+', sn)
    pn_num = re.search(r'\d+', pn)
    sn_base = re.sub(r'[\d:]+', '', sn).strip()
    pn_base = re.sub(r'[\d:]+', '', pn).strip()

    for key, aliases in section_keywords.items():
        if any(a in sn_base for a in [key] + aliases):
            if any(a in pn_base for a in [key] + aliases):
                # Basis-Typ matched — prüfe Nummer
                if sn_num and pn_num:
                    return sn_num.group() == pn_num.group()
                # Ohne Nummer: erstes Vorkommen matchen
                return True

    return False


def assign_lyrics_to_db(db: dict, lyrics_by_name: dict[str, list[dict]]) -> int:
    """
    Ordnet Lyrics aus Stringbreak den Songs in der DB zu.
    Erstellt Bar-Einträge mit Lyrics-Zeilen.

    Rückgabe: Anzahl Songs mit zugeordneten Lyrics.
    """
    bar_counter = 0
    songs_with_lyrics = 0

    for song_id, song in db["songs"].items():
        song_name = song["name"]
        if song_name not in lyrics_by_name:
            continue

        sections = lyrics_by_name[song_name]
        parts = song.get("parts", {})
        if not parts:
            continue

        # Parts nach Position sortieren
        sorted_parts = sorted(parts.items(), key=lambda x: x[1]["pos"])

        # Jede Sektion einem Part zuordnen
        used_parts = set()
        section_to_part = {}

        for section in sections:
            for part_id, part in sorted_parts:
                if part_id in used_parts:
                    continue
                if match_section_to_part(section["section"], part["name"]):
                    section_to_part[section["section"]] = part_id
                    used_parts.add(part_id)
                    break

        # Bars erstellen für zugeordnete Sektionen
        assigned = False
        for section in sections:
            part_id = section_to_part.get(section["section"])
            if not part_id or not section["lines"]:
                continue

            for i, lyric_line in enumerate(section["lines"], 1):
                bar_counter += 1
                bar_id = f"B{bar_counter:04d}"
                db["bars"][bar_id] = {
                    "part_id": part_id,
                    "bar_num": i,
                    "lyrics": lyric_line,
                    "audio": "",
                    "has_accents": False,
                }
                assigned = True

        if assigned:
            songs_with_lyrics += 1

    return songs_with_lyrics


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
    stringbreak_path = repo_root / "db" / "Stringbreak.json"
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

    # Lyrics aus Stringbreak.json extrahieren und zuordnen
    print(f"\nLese Lyrics: {stringbreak_path}")
    lyrics_by_name = load_stringbreak_lyrics(stringbreak_path)
    print(f"  Songs mit Lyrics in Stringbreak: {len(lyrics_by_name)}")

    # Matching Songs finden
    pact_names = {s["name"] for s in db["songs"].values()}
    matching = pact_names & set(lyrics_by_name.keys())
    print(f"  Davon im Pact-Repertoire: {len(matching)}")
    for name in sorted(matching):
        sections = lyrics_by_name[name]
        lines = sum(len(s["lines"]) for s in sections)
        print(f"    {name}: {len(sections)} Sektionen, {lines} Lyrics-Zeilen")

    songs_with_lyrics = assign_lyrics_to_db(db, lyrics_by_name)
    print(f"  Songs mit zugeordneten Lyrics: {songs_with_lyrics}")
    print(f"  Bars mit Lyrics: {len(db['bars'])}")

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
