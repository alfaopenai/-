from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .gg_reader.calibration import load_calibration, save_calibration
from .gg_reader.capture import ScreenCapture
from .gg_reader.history_store import append_event, read_history
from .gg_reader.models import GgReaderStartRequest, GgReaderStatus
from .gg_reader.parser import load_mock_snapshot, parse_frame


app = FastAPI(title="Alpha Poker GG Reader")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:7000", "http://localhost:7000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

reader_state = GgReaderStatus()
reader_config = GgReaderStartRequest()


@app.post("/api/gg-reader/start")
async def start_reader(request: GgReaderStartRequest) -> GgReaderStatus:
    global reader_config, reader_state
    reader_config = request
    reader_state = GgReaderStatus(
        running=True,
        monitorIndex=request.monitorIndex,
        fps=request.fps,
        profile=request.profile,
        message="running",
        lastSnapshotAt=None,
    )
    append_event({"time": int(time.time() * 1000), "type": "reader_started", "message": "GG reader started"})
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


@app.get("/api/gg-reader/history")
async def get_history(limit: int = 50) -> list[dict[str, Any]]:
    return read_history(limit)


@app.get("/api/gg-reader/calibration")
async def get_calibration() -> dict[str, Any]:
    return load_calibration()


@app.post("/api/gg-reader/calibration")
async def post_calibration(data: dict[str, Any]) -> dict[str, Any]:
    return save_calibration(data)


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
                            "clearTable": True,
                            "fatal": True,
                            "confidence": 0,
                        })
                    else:
                        if snapshot is None:
                            await websocket.send_json({
                                "type": "status",
                                "status": "waiting",
                                "message": "מחובר, אבל OCR/כיול GG עדיין לא הופעל. לא נקראו נתוני שולחן.",
                                "clearTable": True,
                                "calibrationVerified": bool(calibration.get("verified")),
                                "confidence": 0,
                            })
                        else:
                            reader_state.lastSnapshotAt = snapshot.timestamp
                            await websocket.send_json(snapshot.model_dump())
            await asyncio.sleep(max(0.1, 1 / max(reader_config.fps, 0.1)))
    except WebSocketDisconnect:
        return
