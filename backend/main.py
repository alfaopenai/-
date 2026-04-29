from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .gg_reader.calibration import load_calibration, save_calibration
from .gg_reader.capture import ScreenCapture, list_monitors, resolve_monitor_index
from .gg_reader.history_store import append_event, read_history
from .gg_reader.models import GgReaderStartRequest, GgReaderStatus
from .gg_reader.parser import load_mock_snapshot, parse_frame


DATA_DIR = Path(__file__).resolve().parent / "data"
DEBUG_FRAME_PATH = DATA_DIR / "debug_last_frame.png"

app = FastAPI(title="Alpha Poker GG Reader")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:7000",
        "http://localhost:7000",
        "http://127.0.0.1:3001",
        "http://localhost:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

reader_state = GgReaderStatus()
reader_config = GgReaderStartRequest()


@app.post("/api/gg-reader/start")
async def start_reader(request: GgReaderStartRequest) -> GgReaderStatus:
    global reader_config, reader_state
    resolved_index, monitor_message = resolve_monitor_index(request.monitorIndex)
    reader_config = request.model_copy(update={"monitorIndex": resolved_index})
    reader_state = GgReaderStatus(
        running=True,
        monitorIndex=resolved_index,
        fps=request.fps,
        profile=request.profile,
        message=monitor_message or "running",
        lastSnapshotAt=None,
    )
    append_event({
        "time": int(time.time() * 1000),
        "type": "reader_started",
        "message": monitor_message or "GG reader started",
    })
    return reader_state


@app.post("/api/gg-reader/stop")
async def stop_reader() -> GgReaderStatus:
    reader_state.running = False
    reader_state.message = "stopped"
    append_event({"time": int(time.time() * 1000), "type": "reader_stopped", "message": "GG reader stopped"})
    return reader_state


@app.get("/api/gg-reader/status")
async def get_status() -> GgReaderStatus:
    return reader_state


@app.get("/api/gg-reader/monitors")
async def get_monitors() -> list[dict[str, int]]:
    return list_monitors()


@app.get("/api/gg-reader/history")
async def get_history(limit: int = 50) -> list[dict[str, Any]]:
    return read_history(limit)


@app.get("/api/gg-reader/calibration")
async def get_calibration() -> dict[str, Any]:
    return load_calibration()


@app.post("/api/gg-reader/calibration")
async def post_calibration(data: dict[str, Any]) -> dict[str, Any]:
    return save_calibration(data)


def save_debug_frame(monitor_index: int) -> dict[str, Any]:
    from PIL import Image

    capture = ScreenCapture(monitor_index=monitor_index)
    frame = capture.grab()
    resolved_index = capture.get_monitor_index()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if frame.ndim == 3 and frame.shape[2] >= 4:
        image = Image.fromarray(frame[:, :, [2, 1, 0, 3]], "RGBA")
    elif frame.ndim == 3 and frame.shape[2] == 3:
        image = Image.fromarray(frame[:, :, [2, 1, 0]], "RGB")
    else:
        image = Image.fromarray(frame)
    image.save(DEBUG_FRAME_PATH)

    height, width = frame.shape[:2]
    return {
        "path": str(DEBUG_FRAME_PATH),
        "width": int(width),
        "height": int(height),
        "monitorIndex": resolved_index,
    }


@app.get("/api/gg-reader/debug/frame")
async def get_debug_frame(monitorIndex: int | None = None) -> dict[str, Any]:
    try:
        metadata = save_debug_frame(monitorIndex or reader_config.monitorIndex)
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "path": str(DEBUG_FRAME_PATH),
            "monitorIndex": monitorIndex or reader_config.monitorIndex,
        }
    return {"ok": True, **metadata}


@app.get("/api/gg-reader/debug/frame-info")
async def get_debug_frame_info() -> dict[str, Any]:
    if not DEBUG_FRAME_PATH.exists():
        return {
            "exists": False,
            "path": str(DEBUG_FRAME_PATH),
            "monitorIndex": reader_config.monitorIndex,
        }
    return {
        "exists": True,
        "path": str(DEBUG_FRAME_PATH),
        "bytes": DEBUG_FRAME_PATH.stat().st_size,
        "monitorIndex": reader_config.monitorIndex,
    }


@app.websocket("/ws/gg-reader")
async def gg_reader_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    capture = ScreenCapture(monitor_index=reader_config.monitorIndex, debug=reader_config.debug)
    calibration = load_calibration()
    try:
        while True:
            if reader_state.running:
                if reader_config.profile == "mock":
                    snapshot = load_mock_snapshot()
                    reader_state.lastSnapshotAt = snapshot.timestamp
                    await websocket.send_json(snapshot.model_dump())
                else:
                    try:
                        frame = capture.grab()
                        snapshot = parse_frame(frame, calibration)
                    except Exception as exc:
                        await websocket.send_json({
                            "type": "status",
                            "status": "warning",
                            "message": f"לא ניתן לצלם את Monitor {reader_config.monitorIndex}: {exc}",
                            "clearTable": False,
                            "fatal": False,
                            "confidence": 0,
                        })
                    else:
                        if snapshot is None:
                            await websocket.send_json({
                                "type": "status",
                                "status": "waiting",
                                "message": "מחובר, ממתין לזיהוי שולחן GG",
                                "clearTable": False,
                                "calibrationVerified": bool(calibration.get("verified")),
                                "confidence": 0,
                            })
                        else:
                            reader_state.lastSnapshotAt = snapshot.timestamp
                            await websocket.send_json(snapshot.model_dump())
            await asyncio.sleep(max(0.1, 1 / max(reader_config.fps, 0.1)))
    except WebSocketDisconnect:
        return
