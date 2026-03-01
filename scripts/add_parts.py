#!/usr/bin/env python3
"""Add researched song parts to the lighting-ai database."""
import json
import math

DB_PATH = "/home/user/lighting.ai/db/lighting-ai-db.json"

def calc_duration(bars, bpm):
    """Calculate duration in seconds from bars and BPM."""
    if bpm == 0 or bars == 0:
        return 0
    return round(bars * 240 / bpm)

def make_parts(song_id, parts_list, bpm):
    """Create parts dict from a list of (name, bars, light_template) tuples."""
    parts = {}
    for i, (name, bars, template) in enumerate(parts_list, 1):
        part_id = f"{song_id}_P{i:03d}"
        parts[part_id] = {
            "pos": i,
            "name": name,
            "bars": bars,
            "duration_sec": calc_duration(bars, bpm),
            "light_template": template,
            "notes": ""
        }
    return parts

def main():
    with open(DB_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)

    songs = db["songs"]

    # 1. Bitter End - Placebo (dgSleW) - BPM correction: 201 -> 186
    sid = "dgSleW"
    songs[sid]["bpm"] = 186
    songs[sid]["duration"] = "3:12"
    songs[sid]["duration_sec"] = 192
    songs[sid]["parts"] = make_parts(sid, [
        ("Intro",       4,  "intro_buildup"),
        ("Verse 1",    16,  "verse_driving"),
        ("Chorus 1",    8,  "chorus_full"),
        ("Verse 2",    16,  "verse_driving"),
        ("Chorus 2",   16,  "chorus_full"),
        ("Bridge",     16,  "bridge_atmospheric"),
        ("Chorus 3",   16,  "chorus_full"),
        ("Outro",      20,  "outro_fadeout"),
        ("Ending",      4,  "outro_cut"),
    ], 186)

    # 2. Black Chandelier - Biffy Clyro (F71u8Z) - BPM stays 112
    sid = "F71u8Z"
    songs[sid]["duration"] = "4:05"
    songs[sid]["duration_sec"] = 245
    songs[sid]["parts"] = make_parts(sid, [
        ("Intro",           8,  "intro_buildup"),
        ("Verse 1",        16,  "verse_driving"),
        ("Pre-Chorus 1",    8,  "prechorus_rise"),
        ("Chorus 1",        8,  "chorus_full"),
        ("Interlude",       2,  "generic_bpm"),
        ("Verse 2",        16,  "verse_driving"),
        ("Pre-Chorus 2",    8,  "prechorus_rise"),
        ("Chorus 2",        8,  "chorus_full"),
        ("Bridge / Solo",   8,  "solo_spotlight"),
        ("Pre-Chorus 3",    8,  "prechorus_rise"),
        ("Chorus 3",        8,  "chorus_full"),
        ("Chorus 4 / Outro",15, "outro_fadeout"),
    ], 112)

    # 3. Enjoy The Silence - Depeche Mode (QeOWYg) - BPM: 0 -> 113
    sid = "QeOWYg"
    songs[sid]["bpm"] = 113
    songs[sid]["duration"] = "4:18"
    songs[sid]["duration_sec"] = 258
    songs[sid]["parts"] = make_parts(sid, [
        ("Intro",           16, "intro_buildup"),
        ("Verse 1",          8, "verse_minimal"),
        ("Chorus 1",         8, "chorus_full"),
        ("Instrumental 1",  10, "generic_bpm"),
        ("Verse 2",          8, "verse_minimal"),
        ("Chorus 2",         8, "chorus_full"),
        ("Instrumental 2",  12, "generic_bpm"),
        ("Chorus 3",         8, "chorus_full"),
        ("Bridge",           8, "bridge_atmospheric"),
        ("Chorus 4",        16, "chorus_full"),
        ("Outro",           20, "outro_fadeout"),
    ], 113)

    # 4. Last Resort - Papa Roach (gRbHPO) - BPM: 0 -> 91
    sid = "gRbHPO"
    songs[sid]["bpm"] = 91
    songs[sid]["duration"] = "3:20"
    songs[sid]["duration_sec"] = 200
    songs[sid]["parts"] = make_parts(sid, [
        ("Intro (Clean)",    4, "intro_buildup"),
        ("Intro (Full)",     4, "intro_hit"),
        ("Verse 1",          8, "verse_driving"),
        ("Pre-Chorus 1",     4, "prechorus_rise"),
        ("Chorus 1",         8, "chorus_full"),
        ("Post-Chorus",      4, "generic_bpm"),
        ("Verse 2",          8, "verse_driving"),
        ("Pre-Chorus 2",     4, "prechorus_rise"),
        ("Chorus 2",         8, "chorus_full"),
        ("Bridge",           8, "bridge_breakdown"),
        ("Chorus 3",         8, "chorus_full"),
        ("Outro",            8, "outro_cut"),
    ], 91)

    # 5. Lights Out - Royal Blood (XJ5YzI) - BPM correction: 80 -> 90
    sid = "XJ5YzI"
    songs[sid]["bpm"] = 90
    songs[sid]["duration"] = "3:57"
    songs[sid]["duration_sec"] = 237
    songs[sid]["parts"] = make_parts(sid, [
        ("Intro",            4, "intro_buildup"),
        ("Verse 1",          8, "verse_driving"),
        ("Pre-Chorus 1",     4, "prechorus_rise"),
        ("Chorus 1",         8, "chorus_full"),
        ("Verse 2",          8, "verse_driving"),
        ("Pre-Chorus 2",     4, "prechorus_rise"),
        ("Chorus 2",         8, "chorus_full"),
        ("Breakdown",        4, "breakdown_minimal"),
        ("Bridge",           8, "bridge_atmospheric"),
        ("Solo",            16, "solo_intense"),
        ("Chorus 3",         8, "chorus_full"),
        ("Outro",            9, "outro_cut"),
    ], 90)

    # 6. Moon over Bourbon Street - Sting (rK4O7W) - BPM stays 108 (band tempo)
    sid = "rK4O7W"
    songs[sid]["duration"] = "3:59"
    songs[sid]["duration_sec"] = 239
    songs[sid]["parts"] = make_parts(sid, [
        ("Intro",            4, "intro_buildup"),
        ("Verse 1",         16, "verse_minimal"),
        ("Chorus 1",         4, "chorus_half"),
        ("Instrumental 1",   8, "generic_bpm"),
        ("Verse 2",         16, "verse_minimal"),
        ("Chorus 2",         4, "chorus_half"),
        ("Instrumental 2",  12, "solo_spotlight"),
        ("Verse 3",         16, "verse_driving"),
        ("Chorus 3",         4, "chorus_full"),
        ("Outro",           16, "outro_fadeout"),
    ], 108)

    # 7. Should I Stay Or Should I Go - The Clash (rNOnoq) - BPM: 0 -> 113
    sid = "rNOnoq"
    songs[sid]["bpm"] = 113
    songs[sid]["parts"] = make_parts(sid, [
        ("Intro",            4, "intro_hit"),
        ("Verse 1",          8, "verse_driving"),
        ("Chorus 1",         8, "chorus_full"),
        ("Verse 2",          8, "verse_driving"),
        ("Chorus 2",         8, "chorus_full"),
        ("Bridge",           8, "bridge_atmospheric"),
        ("Guitar Solo",      8, "solo_intense"),
        ("Chorus 3",         8, "chorus_full"),
        ("Outro",            8, "outro_cut"),
    ], 113)

    # 8. Supergirl - Reamonn (SaUgTX) - BPM: 0 -> 116
    sid = "SaUgTX"
    songs[sid]["bpm"] = 116
    songs[sid]["duration"] = "4:06"
    songs[sid]["duration_sec"] = 246
    songs[sid]["parts"] = make_parts(sid, [
        ("Intro",            8, "intro_buildup"),
        ("Verse 1",          8, "verse_minimal"),
        ("Chorus 1",         8, "chorus_half"),
        ("Interlude",        4, "generic_bpm"),
        ("Verse 2",          8, "verse_driving"),
        ("Chorus 2",         8, "chorus_full"),
        ("Chorus 3",         8, "chorus_full"),
        ("Bridge",           8, "bridge_atmospheric"),
        ("Interlude 2",      8, "solo_spotlight"),
        ("Verse 3",          8, "verse_driving"),
        ("Chorus 4",        16, "chorus_anthem"),
        ("Outro",           16, "outro_fadeout"),
    ], 116)

    # 9. You're all I have - Snow Patrol (HDX1IN) - BPM stays 136
    sid = "HDX1IN"
    songs[sid]["parts"] = make_parts(sid, [
        ("Intro",            4, "intro_buildup"),
        ("Verse 1",         16, "verse_driving"),
        ("Pre-Chorus 1",     8, "prechorus_rise"),
        ("Chorus 1",        16, "chorus_full"),
        ("Verse 2",         16, "verse_driving"),
        ("Pre-Chorus 2",     8, "prechorus_rise"),
        ("Chorus 2",        16, "chorus_full"),
        ("Bridge",           8, "bridge_atmospheric"),
        ("Chorus 3",        16, "chorus_full"),
        ("Outro",            8, "outro_fadeout"),
    ], 136)

    # 10. Fluorescent Adolescent - Arctic Monkeys (NEW SONG)
    # Generate a short ID similar to existing ones
    new_id = "FaAM01"
    songs[new_id] = {
        "name": "Fluorescent Adolescent",
        "artist": "Arctic Monkeys",
        "bpm": 112,
        "key": "E dur",
        "year": "2007",
        "pick": "",
        "gema_nr": "",
        "duration": "3:04",
        "duration_sec": 184,
        "notes": "",
        "parts": make_parts(new_id, [
            ("Intro",        8, "intro_buildup"),
            ("Verse 1",     16, "verse_driving"),
            ("Chorus 1",     8, "chorus_full"),
            ("Verse 2",     16, "verse_driving"),
            ("Chorus 2",    10, "chorus_full"),
            ("Middle 8",     8, "bridge_atmospheric"),
            ("Interlude",    4, "generic_bpm"),
            ("Outro",       16, "outro_fadeout"),
        ], 112)
    }

    # Add Fluorescent Adolescent to setlist
    setlist_items = db["setlist"]["items"]
    next_pos = max(item.get("pos", 0) for item in setlist_items if item.get("type") == "song") + 1
    setlist_items.append({
        "type": "song",
        "pos": next_pos,
        "song_id": new_id
    })

    # Write back
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    print("Done! Updated songs:")
    updated = ["dgSleW", "F71u8Z", "QeOWYg", "gRbHPO", "XJ5YzI", "rK4O7W", "rNOnoq", "SaUgTX", "HDX1IN", new_id]
    for sid in updated:
        s = songs[sid]
        part_count = len(s["parts"])
        total_bars = sum(p["bars"] for p in s["parts"].values())
        print(f"  {s['name']} ({s['artist']}) - {part_count} parts, {total_bars} bars, {s['bpm']} BPM")

if __name__ == "__main__":
    main()
