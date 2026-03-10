"""FastAPI application for lighting.ai Live Controller."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import load_config, Config
from .db_cache import sync, load_db, load_qxw_path
from .qlc_parser import parse, qlc_data_to_dict, QlcData, ACCENT_FUNCTIONS
from .qlc_osc import QlcOsc
from .ws_handler import WsHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-20s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("live.main")

# --- Global state ---
cfg: Config = load_config()
db: dict = {}
qlc_data: QlcData | None = None
osc: QlcOsc | None = None
ws_handler = WsHandler()

app = FastAPI(title="lighting.ai Live Controller", version="1.0.0")

# CORS — allow the GitHub Pages frontend and local dev to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class OscSendRequest(BaseModel):
    host: str = "127.0.0.1"
    port: int = 7700
    universe: int = 2
    collection_id: int


# --- Startup ---

@app.on_event("startup")
async def startup():
    global db, qlc_data, osc

    # 1) Sync DB from GitHub / local repo
    log.info("=== lighting.ai Live Controller ===")
    sync_result = sync(cfg)
    log.info("DB sync: %s", sync_result)

    # 2) Load DB
    try:
        db = load_db(cfg)
        log.info("DB loaded: %d songs", len(db.get("songs", {})))
    except FileNotFoundError as exc:
        log.error("DB load failed: %s", exc)
        db = {"songs": {}, "setlist": {"items": []}}

    # 3) Parse QXW
    try:
        qxw_path = load_qxw_path(cfg)
        qlc_data = parse(qxw_path, db.get("songs", {}))
        log.info(
            "QXW parsed: %d song chasers, %d matched",
            len(qlc_data.song_chasers),
            len(qlc_data.song_mapping),
        )
    except FileNotFoundError as exc:
        log.error("QXW load failed: %s", exc)

    # 4) Connect OSC
    osc = QlcOsc(cfg.qlc)
    osc_ok = osc.connect()

    # 5) Set initial WS state
    await ws_handler.update_state(
        db_synced=sync_result["ok"],
        db_sync_time=sync_result.get("time"),
        db_sync_method=sync_result.get("method", ""),
        qlc_connected=osc_ok,
    )

    log.info("Ready — http://%s:%d", cfg.server.host, cfg.server.port)


# --- Static files ---

_ui_dir = Path(__file__).resolve().parent.parent / "ui"
if _ui_dir.exists():
    app.mount("/ui", StaticFiles(directory=str(_ui_dir)), name="ui")


@app.get("/")
async def index():
    idx = _ui_dir / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return JSONResponse({"error": "UI not found"}, status_code=404)


# --- REST API ---

@app.get("/api/songs")
async def get_songs():
    """Return all songs from the DB."""
    songs = db.get("songs", {})
    return {
        sid: {
            "name": s.get("name", ""),
            "artist": s.get("artist", ""),
            "bpm": s.get("bpm", 0),
            "key": s.get("key", ""),
            "duration": s.get("duration", ""),
            "duration_sec": s.get("duration_sec", 0),
            "parts": {
                pid: {
                    "pos": p.get("pos", 0),
                    "name": p.get("name", ""),
                    "bars": p.get("bars", 0),
                    "duration_sec": p.get("duration_sec", 0),
                    "light_template": p.get("light_template", ""),
                }
                for pid, p in s.get("parts", {}).items()
            },
        }
        for sid, s in songs.items()
    }


@app.get("/api/songs/{song_id}/bars")
async def get_song_bars(song_id: str):
    """Return bars grouped by part for a song, including lyrics."""
    song = db.get("songs", {}).get(song_id)
    if not song:
        return JSONResponse({"error": "Song not found"}, status_code=404)
    all_bars = db.get("bars", {})
    # Group bars by part_id
    bars_by_part: dict[str, list] = {}
    for bid, b in all_bars.items():
        pid = b.get("part_id", "")
        if pid not in bars_by_part:
            bars_by_part[pid] = []
        bars_by_part[pid].append({"id": bid, **b})
    # Build ordered result: parts with their bars
    parts = song.get("parts", {})
    result = []
    for pid, p in sorted(parts.items(), key=lambda x: x[1].get("pos", 0)):
        part_bars = sorted(bars_by_part.get(pid, []), key=lambda x: x.get("bar_num", 0))
        result.append({
            "part_id": pid,
            "part_name": p.get("name", ""),
            "part_pos": p.get("pos", 0),
            "bar_count": p.get("bars", 0),
            "bars": [
                {"bar_num": b.get("bar_num", 0), "lyrics": b.get("lyrics", "")}
                for b in part_bars
            ],
        })
    return result


@app.get("/api/setlist")
async def get_setlist():
    """Return the active setlist."""
    sl = db.get("setlist", {})
    songs = db.get("songs", {})
    items = []
    for item in sl.get("items", []):
        if item.get("type") == "song":
            sid = item.get("song_id", "")
            song = songs.get(sid, {})
            items.append({
                "type": "song",
                "pos": item.get("pos"),
                "song_id": sid,
                "name": song.get("name", "?"),
                "artist": song.get("artist", ""),
                "bpm": song.get("bpm", 0),
                "has_chaser": sid in (qlc_data.song_mapping if qlc_data else {}),
            })
        elif item.get("type") == "pause":
            items.append({"type": "pause"})
    return {"name": sl.get("name", ""), "items": items}


@app.get("/api/qlc/mapping")
async def get_qlc_mapping():
    """Return the QLC+ song-to-chaser mapping."""
    if not qlc_data:
        return {"error": "QXW not loaded"}
    return qlc_data_to_dict(qlc_data)


@app.get("/api/qlc/status")
async def get_qlc_status():
    """Return QLC+ connection status."""
    return {
        "connected": osc.connected if osc else False,
        "host": cfg.qlc.osc_host,
        "port": cfg.qlc.osc_port,
    }


@app.post("/api/sync")
async def manual_sync():
    """Manually trigger a DB sync."""
    global db, qlc_data
    result = sync(cfg)

    if result["ok"]:
        db = load_db(cfg)
        try:
            qxw_path = load_qxw_path(cfg)
            qlc_data = parse(qxw_path, db.get("songs", {}))
        except FileNotFoundError:
            pass

    await ws_handler.update_state(
        db_synced=result["ok"],
        db_sync_time=result.get("time"),
        db_sync_method=result.get("method", ""),
    )
    return result


@app.post("/api/qlc/function/{func_id}/trigger")
async def trigger_function(func_id: int):
    """Trigger a QLC+ function's collection via OSC."""
    if osc:
        ok = osc.trigger_function(func_id)
        if ok:
            return {"ok": True, "function_id": func_id}
        return JSONResponse({"error": f"No collection mapping for function {func_id}"}, status_code=404)
    return JSONResponse({"error": "OSC not connected"}, status_code=503)


@app.post("/api/qlc/accent/{accent_type}")
async def trigger_accent(accent_type: str):
    """Trigger an accent (blind, blackout, strobe, fog_5s, etc.)."""
    if accent_type not in ACCENT_FUNCTIONS:
        return JSONResponse({"error": f"Unknown accent: {accent_type}"}, status_code=400)
    if osc:
        osc.trigger_accent(accent_type)
        return {"ok": True, "accent": accent_type}
    return JSONResponse({"error": "OSC not connected"}, status_code=503)


@app.post("/api/qlc/tap")
async def qlc_tap():
    """Send a tap tempo pulse to QLC+."""
    if osc:
        osc.tap_tempo()
        return {"ok": True}
    return JSONResponse({"error": "OSC not connected"}, status_code=503)


@app.post("/api/osc/send")
async def osc_send(req: OscSendRequest):
    """Send a raw OSC trigger from the QLC+ config tab (collection button test).

    Uses a one-shot UDP client so the host/port/universe from the request are honored
    (they may differ from the server's own QLC config).
    """
    from pythonosc.udp_client import SimpleUDPClient
    import time as _time

    try:
        client = SimpleUDPClient(req.host, req.port)
        path = f"/{req.universe}/dmx/{req.collection_id}"
        client.send_message(path, 255.0)
        _time.sleep(0.05)
        client.send_message(path, 0.0)
        log.info("OSC sent: %s = 255→0 (%s:%d)", path, req.host, req.port)
        return {"ok": True, "path": path}
    except Exception as exc:
        log.error("OSC send failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# --- WebSocket ---

async def _handle_ws_action(action: str, msg: dict) -> dict | None:
    """Process WebSocket commands from the UI."""
    songs = db.get("songs", {})

    if action == "select_song":
        song_id = msg.get("song_id", "")
        song = songs.get(song_id)
        if not song:
            return {"error": f"Song not found: {song_id}"}

        # Find the chaser for this song
        chaser = qlc_data.song_mapping.get(song_id) if qlc_data else None

        await ws_handler.update_state(
            current_song_id=song_id,
            current_song_name=song.get("name", ""),
            current_artist=song.get("artist", ""),
            current_bpm=song.get("bpm", 0),
            chaser_id=chaser.chaser_id if chaser else None,
            current_step=0,
            total_steps=len(chaser.steps) if chaser else 0,
            current_part_name=chaser.steps[0].note if chaser and chaser.steps else "",
            current_function_name=chaser.steps[0].function_name if chaser and chaser.steps else "",
            is_playing=False,
        )

        # Trigger the first step's collection (pre-song Stopp)
        if osc and chaser and chaser.steps:
            osc.trigger_function(chaser.steps[0].function_id)

        return {"ok": True, "song_id": song_id, "has_chaser": chaser is not None}

    elif action == "next":
        chaser = None
        if qlc_data and ws_handler.state.current_song_id:
            chaser = qlc_data.song_mapping.get(ws_handler.state.current_song_id)

        new_step = ws_handler.state.current_step + 1
        if chaser and new_step < len(chaser.steps):
            step = chaser.steps[new_step]
            await ws_handler.update_state(
                current_step=new_step,
                current_part_name=step.note,
                current_function_name=step.function_name,
                is_playing=True,
            )
            if osc:
                osc.trigger_function(step.function_id)
        return {"ok": True, "step": new_step}

    elif action == "prev":
        chaser = None
        if qlc_data and ws_handler.state.current_song_id:
            chaser = qlc_data.song_mapping.get(ws_handler.state.current_song_id)

        new_step = max(0, ws_handler.state.current_step - 1)
        if chaser and new_step < len(chaser.steps):
            step = chaser.steps[new_step]
            await ws_handler.update_state(
                current_step=new_step,
                current_part_name=step.note,
                current_function_name=step.function_name,
            )
            if osc:
                osc.trigger_function(step.function_id)
        return {"ok": True, "step": new_step}

    elif action == "goto":
        step_index = msg.get("step", 0)
        chaser = None
        if qlc_data and ws_handler.state.current_song_id:
            chaser = qlc_data.song_mapping.get(ws_handler.state.current_song_id)

        if chaser and 0 <= step_index < len(chaser.steps):
            step = chaser.steps[step_index]
            # Direct collection trigger — no need to step through
            if osc:
                osc.trigger_function(step.function_id)

            await ws_handler.update_state(
                current_step=step_index,
                current_part_name=step.note,
                current_function_name=step.function_name,
            )
        return {"ok": True, "step": step_index}

    elif action == "accent":
        accent_type = msg.get("type", "")
        if osc and accent_type in ACCENT_FUNCTIONS:
            osc.trigger_accent(accent_type)
            return {"ok": True, "accent": accent_type}
        return {"error": f"Unknown accent or OSC not connected: {accent_type}"}

    elif action == "tap":
        if osc:
            osc.tap_tempo()
        return {"ok": True}

    elif action == "get_state":
        return ws_handler.state.to_dict()

    else:
        return {"error": f"Unknown action: {action}"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_handler.connect(ws)
    try:
        while True:
            raw = await ws.receive_text()
            await ws_handler.handle_message(ws, raw, _handle_ws_action)
    except WebSocketDisconnect:
        await ws_handler.disconnect(ws)
    except Exception as exc:
        log.error("WS error: %s", exc)
        await ws_handler.disconnect(ws)
