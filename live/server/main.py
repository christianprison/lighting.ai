"""FastAPI application for lighting.ai Live Controller."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import load_config, Config
from .db_cache import sync, load_db, load_qxw_path, push_probe_log
from .qlc_parser import parse, qlc_data_to_dict, QlcData, ACCENT_FUNCTIONS, BASE_COLLECTIONS
from .qlc_osc import QlcOsc, FUNCTION_TO_COLLECTION
from .ws_handler import WsHandler
from .audio.reference_db import ReferenceDB, DEFAULT_DB_PATH
from .audio.audio_process import AudioProcess, PositionUpdate, BeatUpdate, AudioStatus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-20s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("live.main")


class _EventLogHandler(logging.Handler):
    """Leitet WARNING/ERROR/CRITICAL ins aktive Session-Logfile um."""

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.WARNING:
            return
        if audio_process is None:
            return
        el = audio_process.recorder.event_logger
        if el is None:
            return
        try:
            el.log(
                "server_log",
                level=record.levelname,
                logger=record.name,
                msg=record.getMessage(),
            )
        except Exception:
            pass

# --- Global state ---
cfg: Config = load_config()
db: dict = {}
qlc_data: QlcData | None = None
osc: QlcOsc | None = None
ws_handler = WsHandler()

# Audio engine
ref_db: ReferenceDB | None = None
audio_process: AudioProcess | None = None
_audio_queue: asyncio.Queue = asyncio.Queue()

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


class RehearsalSongRequest(BaseModel):
    song_id: str | None = None  # None = Live Mode (alle Songs)


class RecordingStartRequest(BaseModel):
    label: str = ""      # Frei wählbar, z.B. Song-Name
    song_id: str = ""    # Song-ID für spätere Zuordnung


# --- Startup / Shutdown ---

@app.on_event("startup")
async def startup():
    global db, qlc_data, osc, ref_db, audio_process, _audio_queue

    # 1) Sync DB from GitHub / local repo
    log.info("=== lighting.ai Live Controller ===")
    sync_result = sync(cfg)
    log.info("DB sync: %s", sync_result)

    # Ausstehende lokale Probe-Logs nach GitHub pushen (Offline-Fallback)
    asyncio.create_task(_push_pending_probe_logs())

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

    # 6) Referenz-DB + AudioProcess initialisieren
    _audio_queue = asyncio.Queue()
    ref_db = ReferenceDB(DEFAULT_DB_PATH)
    stats = ref_db.stats()
    log.info(
        "Referenz-DB: %d Songs, %d Bars, %d Feature-Vektoren",
        stats["songs"], stats["bars"], stats["feature_vectors"],
    )

    loop = asyncio.get_event_loop()
    audio_device = getattr(cfg, "audio_device", None)
    audio_process = AudioProcess(ref_db, _audio_queue, loop, device=audio_device)
    audio_process.start()

    # Logging-Handler registrieren: WARNING/ERROR → aktives Event-Logfile
    logging.getLogger().addHandler(_EventLogHandler())

    # Background-Task: Audio-Queue → WebSocket broadcast
    asyncio.create_task(_consume_audio_queue())

    log.info("Ready — http://%s:%d", cfg.server.host, cfg.server.port)


@app.on_event("shutdown")
async def shutdown():
    if audio_process:
        # Aufnahme stoppen und Session-ID ermitteln
        rec_info = audio_process.recorder._info
        session_id = rec_info.session_id if rec_info else None
        audio_process.stop()

        # Probe-Events exportieren und nach GitHub pushen
        if session_id and ref_db:
            await _export_and_push_probe_log(session_id)


async def _export_and_push_probe_log(session_id: str) -> None:
    """Exportiert Probe-Events als JSON und pusht nach GitHub."""
    import json as _json
    try:
        data = ref_db.export_probe_session(session_id)
        if data["event_count"] == 0:
            log.info("Keine Probe-Events für Session %s — kein Push", session_id)
            return

        content = _json.dumps(data, ensure_ascii=False, indent=2)
        log.info(
            "Exportiere %d Probe-Events für Session %s ...",
            data["event_count"], session_id,
        )
        ok = push_probe_log(cfg, session_id, content)
        if ok:
            log.info("Probe-Log erfolgreich nach GitHub gepusht: %s", session_id)
        else:
            # Offline oder kein Token — lokal speichern als Fallback
            local_dir = cfg.base_dir / "data" / "probe_logs"
            local_dir.mkdir(parents=True, exist_ok=True)
            local_path = local_dir / f"{session_id}.json"
            local_path.write_text(content, encoding="utf-8")
            log.info(
                "Offline — Probe-Log lokal gespeichert: %s (wird beim nächsten Start gepusht)",
                local_path,
            )
    except Exception as exc:
        log.error("Probe-Log Export/Push fehlgeschlagen: %s", exc)


async def _push_pending_probe_logs() -> None:
    """Pusht lokal gespeicherte Probe-Logs die beim letzten Shutdown offline waren."""
    import json as _json
    local_dir = cfg.base_dir / "data" / "probe_logs"
    if not local_dir.exists():
        return
    pending = list(local_dir.glob("*.json"))
    if not pending:
        return
    log.info("%d ausstehende Probe-Logs gefunden — pushe nach GitHub ...", len(pending))
    for path in pending:
        session_id = path.stem
        try:
            content = path.read_text(encoding="utf-8")
            ok = push_probe_log(cfg, session_id, content)
            if ok:
                path.unlink()
                log.info("Ausstehender Probe-Log gepusht und gelöscht: %s", session_id)
        except Exception as exc:
            log.warning("Push für %s fehlgeschlagen: %s", session_id, exc)


# --- Audio Queue Consumer ---

async def _consume_audio_queue() -> None:
    """Liest Ereignisse vom AudioProcess und broadcast sie per WebSocket."""
    while True:
        try:
            event = await _audio_queue.get()
        except asyncio.CancelledError:
            break

        if isinstance(event, PositionUpdate):
            await ws_handler.broadcast(event.to_dict())
        elif isinstance(event, BeatUpdate):
            await ws_handler.broadcast(event.to_dict())
        elif isinstance(event, AudioStatus):
            await ws_handler.broadcast(event.to_dict())


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
    """Return bars for a song, grouped by parts if available.

    Supports two DB schemas:
    - Legacy: bars have part_id, songs have parts dict
    - Current (v1.7.0+): bars have song_id directly, parts derived from bar positions
    """
    song = db.get("songs", {}).get(song_id)
    if not song:
        return JSONResponse({"error": "Song not found"}, status_code=404)
    all_bars = db.get("bars", {})

    # Collect all bars for this song (current schema: bars have song_id)
    song_bars = sorted(
        [b for b in all_bars.values() if b.get("song_id") == song_id],
        key=lambda x: x.get("bar_num", 0),
    )

    # If no bars found via song_id, try legacy schema (part_id)
    if not song_bars:
        parts = song.get("parts", {})
        if parts:
            bars_by_part: dict[str, list] = {}
            for b in all_bars.values():
                pid = b.get("part_id", "")
                bars_by_part.setdefault(pid, []).append(b)
            result = []
            for pid, p in sorted(parts.items(), key=lambda x: x[1].get("pos", 0)):
                part_bars = sorted(bars_by_part.get(pid, []), key=lambda x: x.get("bar_num", 0))
                result.append({
                    "part_id": pid,
                    "part_name": p.get("name", ""),
                    "bar_count": p.get("bars", 0),
                    "bars": [{"bar_num": b.get("bar_num", 0), "lyrics": b.get("lyrics", "").strip()}
                             for b in part_bars],
                })
            return result
        return []

    # Current schema: return as single part (parts not yet in DB)
    return [{
        "part_id": song_id,
        "part_name": "",
        "bar_count": len(song_bars),
        "bars": [{"bar_num": b.get("bar_num", 0), "lyrics": b.get("lyrics", "").strip()}
                 for b in song_bars],
    }]


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
        ok = await osc.trigger_function_async(func_id)
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
        await osc.trigger_accent_async(accent_type)
        return {"ok": True, "accent": accent_type}
    return JSONResponse({"error": "OSC not connected"}, status_code=503)


@app.post("/api/qlc/tap")
async def qlc_tap():
    """Send a tap tempo pulse to QLC+."""
    if osc:
        await osc.tap_tempo_async()
        return {"ok": True}
    return JSONResponse({"error": "OSC not connected"}, status_code=503)


@app.post("/api/osc/send")
async def osc_send(req: OscSendRequest):
    """Send a raw OSC trigger from the QLC+ config tab (collection button test).

    Uses a one-shot UDP client so the host/port/universe from the request are honored
    (they may differ from the server's own QLC config).
    """
    from pythonosc.udp_client import SimpleUDPClient

    try:
        client = SimpleUDPClient(req.host, req.port)
        path = f"/{req.universe}/dmx/{req.collection_id}"
        client.send_message(path, 255.0)
        await asyncio.sleep(0.05)  # non-blocking (ersetzt time.sleep)
        client.send_message(path, 0.0)
        log.info("OSC sent: %s = 255→0 (%s:%d)", path, req.host, req.port)
        return {"ok": True, "path": path}
    except Exception as exc:
        log.error("OSC send failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


class OscSendTemplateRequest(BaseModel):
    template: str  # light_template name, e.g. "03 walking"


@app.post("/api/osc/send_template")
async def osc_send_template(req: OscSendTemplateRequest):
    """Trigger QLC+ by light_template name (from DB part).

    Looks up the function_id in BASE_COLLECTIONS, then the collection_id
    in FUNCTION_TO_COLLECTION, and fires the OSC trigger via the active QLC client.
    """
    # Find function_id for this template name
    function_id: int | None = None
    for fid, tname in BASE_COLLECTIONS.items():
        if tname == req.template:
            function_id = fid
            break

    if function_id is None:
        log.warning("send_template: unknown template '%s'", req.template)
        return JSONResponse({"error": f"Unknown template: {req.template}"}, status_code=404)

    if qlc is None or not qlc.connected:
        return JSONResponse({"error": "QLC+ OSC not connected"}, status_code=503)

    ok = await qlc.trigger_function_async(function_id)
    if ok:
        log.info("send_template '%s' → function %d triggered", req.template, function_id)
        return {"ok": True, "template": req.template, "function_id": function_id}
    else:
        return JSONResponse({"error": f"No collection mapping for function {function_id}"}, status_code=500)


# --- Audio Engine API ---

@app.get("/api/audio/devices")
async def get_audio_devices():
    """Listet alle verfügbaren Audio-Input-Geräte.

    Damit lässt sich prüfen ob der XR18 als Device sichtbar ist
    und unter welchem Index/Namen er erscheint.
    """
    from .audio.audio_process import AudioProcess
    devices = AudioProcess.list_devices()
    # XR18 nur per Name erkennen — Kanalzahl allein reicht nicht (andere Geräte/JACK haben auch 18+)
    xr18_candidates = [d for d in devices if "xr18" in d.get("name", "").lower()
                       or "behringer" in d.get("name", "").lower()]
    other_18ch = [d for d in devices if d.get("channels_in", 0) >= 18
                  and "xr18" not in d.get("name", "").lower()
                  and "behringer" not in d.get("name", "").lower()]
    return {
        "devices": devices,
        "xr18_detected": len(xr18_candidates) > 0,
        "xr18_candidates": xr18_candidates,
        "other_18ch_devices": other_18ch,
    }


@app.get("/api/audio/levels")
async def get_audio_levels():
    """Aktuelle RMS-Pegel pro Kanal (0.0–1.0).

    Gibt 0.0 zurück wenn kein Audio-Stream aktiv ist.
    Kanal-Indizes sind 0-basiert (CH1 = Index 0, CH18 = Index 17).
    """
    if not audio_process:
        return JSONResponse({"error": "AudioProcess not initialised"}, status_code=503)
    levels = audio_process.channel_levels()
    # dBFS für bessere Lesbarkeit
    import math
    def to_dbfs(rms: float) -> float | None:
        if rms <= 0:
            return None
        return round(20 * math.log10(rms), 1)
    return {
        "channels": [
            {"ch": i + 1, "rms": levels[i], "dbfs": to_dbfs(levels[i])}
            for i in range(len(levels))
        ],
        "stream_active": audio_process.is_running(),
    }


@app.get("/api/audio/status")
async def get_audio_status():
    """Status des AudioProcess (läuft, Gerätename, Fehler)."""
    if audio_process:
        return audio_process.status()
    return {"running": False, "device": "", "error": "AudioProcess not initialised"}


@app.get("/api/audio/refdb/stats")
async def get_refdb_stats():
    """Statistiken der SQLite-Referenz-DB."""
    if ref_db:
        return ref_db.stats()
    return {"songs": 0, "bars": 0, "feature_vectors": 0}


@app.post("/api/audio/rehearsal/song")
async def set_rehearsal_song(req: RehearsalSongRequest):
    """Rehearsal Mode: aktiven Song setzen oder aufheben.

    song_id=null → Live Mode (alle Songs im Suchraum).
    song_id='5iZfKj' → Rehearsal Mode (nur dieser Song).
    """
    if not audio_process:
        return JSONResponse({"error": "AudioProcess not initialised"}, status_code=503)

    song_id = req.song_id
    audio_process.set_active_song(song_id)

    if song_id:
        song = db.get("songs", {}).get(song_id, {})
        bpm = float(song.get("bpm", 120))
        audio_process.set_bpm(bpm)

    mode = "rehearsal" if song_id else "live"
    return {"ok": True, "mode": mode, "song_id": song_id}


@app.post("/api/audio/reload")
async def reload_audio_engine():
    """Lädt alle Feature-Vektoren aus der Referenz-DB neu in den HMM."""
    if not audio_process:
        return JSONResponse({"error": "AudioProcess not initialised"}, status_code=503)
    n = audio_process.hmm.load_all_states()
    return {"ok": True, "states_loaded": n}


# --- Recording API ---

@app.post("/api/recording/start")
async def recording_start(req: RecordingStartRequest):
    """Startet eine neue Multitrack-Aufnahme (alle 18 XR18-Kanäle).

    Falls kein label angegeben: Zeitstempel wird als Name verwendet.
    Falls song_id angegeben: wird in der Datei-Metadaten vermerkt.
    """
    if not audio_process:
        return JSONResponse({"error": "AudioProcess not initialised"}, status_code=503)

    label = req.label
    if not label and req.song_id:
        song = db.get("songs", {}).get(req.song_id, {})
        label = song.get("name", req.song_id)

    try:
        info = audio_process.recorder.start(label=label, song_id=req.song_id)
        return {"ok": True, **audio_process.recorder.status()}
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/recording/stop")
async def recording_stop():
    """Beendet die laufende Aufnahme und schließt die Datei."""
    if not audio_process:
        return JSONResponse({"error": "AudioProcess not initialised"}, status_code=503)

    info = audio_process.recorder.stop()
    if info is None:
        return {"ok": False, "message": "Keine Aufnahme aktiv"}

    duration = round(info.blocks_written * 2048 / info.sample_rate, 1)
    return {
        "ok": True,
        "path": info.path,
        "duration_sec": duration,
        "blocks_written": info.blocks_written,
    }


@app.get("/api/recording/status")
async def recording_status():
    """Status der aktuellen Aufnahme."""
    if not audio_process:
        return JSONResponse({"error": "AudioProcess not initialised"}, status_code=503)
    return audio_process.recorder.status()


@app.get("/api/recording/list")
async def recording_list():
    """Listet alle vorhandenen WAV-Dateien im Recordings-Verzeichnis."""
    if not audio_process:
        return JSONResponse({"error": "AudioProcess not initialised"}, status_code=503)
    return {"recordings": audio_process.recorder.list_recordings()}


@app.post("/api/recording/mixdown")
async def recording_mixdown(body: dict):
    """Erstellt einen Stereo-Mixdown einer 18-Kanal-Aufnahme.

    Body: ``{"filename": "2026-03-24_200000_Animal.wav"}``
    Gibt Pfad + Metadaten der erzeugten Stereo-WAV zurück.
    """
    if not audio_process:
        return JSONResponse({"error": "AudioProcess not initialised"}, status_code=503)
    filename = body.get("filename", "")
    if not filename:
        return JSONResponse({"error": "filename fehlt"}, status_code=400)
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, audio_process.recorder.mixdown, filename
        )
        return result
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# --- WebSocket ---

def _log_user_action(action: str, data: dict) -> None:
    """Schreibt eine User-Interaktion ins aktive Event-Logfile."""
    if audio_process is None:
        return
    el = audio_process.recorder.event_logger
    if el is None:
        return
    el.log("user", action=action, data=data)


async def _handle_ws_action(action: str, msg: dict) -> dict | None:
    """Process WebSocket commands from the UI."""
    songs = db.get("songs", {})

    if action == "select_song":
        song_id = msg.get("song_id", "")
        song = songs.get(song_id)
        if not song:
            return {"error": f"Song not found: {song_id}"}
        _log_user_action("select_song", {"song_id": song_id, "name": song.get("name", "")})

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

        if osc and chaser and chaser.steps:
            await osc.trigger_function_async(chaser.steps[0].function_id)

        if audio_process:
            audio_process.set_bpm(float(song.get("bpm", 120)))

        return {"ok": True, "song_id": song_id, "has_chaser": chaser is not None}

    elif action == "next":
        _log_user_action("next", {"from_step": ws_handler.state.current_step})
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
                await osc.trigger_function_async(step.function_id)
        return {"ok": True, "step": new_step}

    elif action == "prev":
        _log_user_action("prev", {"from_step": ws_handler.state.current_step})
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
                await osc.trigger_function_async(step.function_id)
        return {"ok": True, "step": new_step}

    elif action == "goto":
        step_index = msg.get("step", 0)
        _log_user_action("goto", {"step": step_index, "from_step": ws_handler.state.current_step})
        chaser = None
        if qlc_data and ws_handler.state.current_song_id:
            chaser = qlc_data.song_mapping.get(ws_handler.state.current_song_id)

        if chaser and 0 <= step_index < len(chaser.steps):
            step = chaser.steps[step_index]
            if osc:
                await osc.trigger_function_async(step.function_id)
            await ws_handler.update_state(
                current_step=step_index,
                current_part_name=step.note,
                current_function_name=step.function_name,
            )
        return {"ok": True, "step": step_index}

    elif action == "accent":
        accent_type = msg.get("type", "")
        _log_user_action("accent", {"accent": accent_type})
        if osc and accent_type in ACCENT_FUNCTIONS:
            await osc.trigger_accent_async(accent_type)
            return {"ok": True, "accent": accent_type}
        return {"error": f"Unknown accent or OSC not connected: {accent_type}"}

    elif action == "tap":
        _log_user_action("tap", {"bpm_current": ws_handler.state.current_bpm})
        if osc:
            await osc.tap_tempo_async()
        return {"ok": True}

    elif action == "set_rehearsal_song":
        song_id = msg.get("song_id")  # None = Live Mode
        if audio_process:
            audio_process.set_active_song(song_id)
            if song_id:
                song = songs.get(song_id, {})
                audio_process.set_bpm(float(song.get("bpm", 120)))
        return {"ok": True, "mode": "rehearsal" if song_id else "live", "song_id": song_id}

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
