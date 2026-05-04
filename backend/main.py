from __future__ import annotations

import asyncio
import logging
import time
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .gg_reader.calibration import load_calibration, save_calibration
from .gg_reader.capture import ScreenCapture, list_gg_windows, list_monitors, resolve_monitor_index
from .gg_reader.fast_reader import FastGgReader
from .gg_reader.history_store import append_event, read_hands, read_history, record_snapshot
from .gg_reader.models import GgReaderStartRequest, GgReaderStatus, GgTableSnapshot
from .gg_reader.parser import load_mock_snapshot, parse_frame
from .gg_reader.table_crop import detect_clubgg_table_crop


DATA_DIR = Path(__file__).resolve().parent / "data"
DEBUG_FRAME_PATH = DATA_DIR / "debug_last_frame.png"
DEBUG_CROPPED_FRAME_PATH = DATA_DIR / "debug_last_cropped_frame.png"
DEBUG_ROI_OVERLAY_PATH = DATA_DIR / "debug_roi_overlay.png"
DEBUG_FIELD_CROPS_DIR = DATA_DIR / "field_crops"

logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

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
last_snapshot = None
current_hand_id: str | None = None
FAST_GG_READER = FastGgReader()
last_crop_metrics: dict[str, Any] = {
    "inputFrameWidth": None,
    "inputFrameHeight": None,
    "croppedFrameWidth": None,
    "croppedFrameHeight": None,
    "cropSource": "none",
    "selectedWindowTitle": None,
    "selectedWindowRect": None,
    "cropRect": None,
    "innerTableRect": None,
    "cropConfidence": 0.0,
    "cropWarnings": [],
}
_last_cropped_frame_saved_at = 0.0
_cropped_frame_save_task: asyncio.Task[Any] | None = None
_CACHE_TTL_SECONDS = 1.0
_CALIBRATION_CACHE_TTL_SECONDS = 2.0
_cached_windows: tuple[float, list[dict[str, Any]]] = (0.0, [])
_cached_monitors: tuple[float, list[dict[str, Any]]] = (0.0, [])
_cached_calibration: tuple[float, dict[str, Any] | None] = (0.0, None)


POSITION_SEQUENCE = ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"]
HEADS_UP_POSITIONS = ["SB", "BB"]
STREET_ORDER = {"unknown": -1, "preflop": 0, "flop": 1, "turn": 2, "river": 3, "showdown": 4}


def enrich_snapshot(snapshot: GgTableSnapshot) -> tuple[GgTableSnapshot, list[dict[str, Any]]]:
    global current_hand_id, last_snapshot

    enriched = snapshot.model_copy(deep=True)
    active_indexes = sorted(
        {
            int(seat.physicalSeatIndex)
            for seat in enriched.seats
            if seat.active and 0 <= int(seat.physicalSeatIndex) < 9
        }
    )
    enriched.activePlayerCount = len(active_indexes)

    previous_for_history: GgTableSnapshot | None = last_snapshot
    if current_hand_id is None or is_new_hand(enriched, previous_for_history):
        current_hand_id = f"gg-{enriched.timestamp}"
        previous_for_history = None

    enriched.handId = current_hand_id
    assign_positions(enriched, active_indexes)
    infer_actions(enriched, previous_for_history)
    events = record_snapshot(enriched, previous_for_history)
    last_snapshot = enriched
    return enriched, events


def is_new_hand(snapshot: GgTableSnapshot, previous: GgTableSnapshot | None) -> bool:
    if previous is None:
        return True
    previous_street = STREET_ORDER.get(previous.street, -1)
    next_street = STREET_ORDER.get(snapshot.street, -1)
    previous_board_count = sum(1 for card in previous.board if card.visible and not card.hidden)
    next_board_count = sum(1 for card in snapshot.board if card.visible and not card.hidden)
    if next_street >= 0 and previous_street > next_street:
        return True
    if previous_board_count > 0 and next_board_count == 0 and snapshot.street == "preflop":
        return True
    if next_board_count == 0 and previous_board_count == 0 and previous.dealerSeatIndex != snapshot.dealerSeatIndex:
        previous_bets = sum(float(seat.currentBet or 0) for seat in previous.seats if seat.active)
        next_bets = sum(float(seat.currentBet or 0) for seat in snapshot.seats if seat.active)
        if previous_bets == 0 and next_bets == 0:
            return True
    return False


def assign_positions(snapshot: GgTableSnapshot, active_indexes: list[int]) -> None:
    if not active_indexes:
        return

    if snapshot.dealerSeatIndex not in active_indexes:
        snapshot.dealerSeatIndex = active_indexes[0]

    dealer_order_index = active_indexes.index(snapshot.dealerSeatIndex)
    positions = HEADS_UP_POSITIONS if len(active_indexes) == 2 else POSITION_SEQUENCE
    seat_by_index = {seat.physicalSeatIndex: seat for seat in snapshot.seats}

    for physical_index in range(9):
        seat = seat_by_index.get(physical_index)
        if seat is None:
            continue
        if not seat.active:
            seat.position = None
            seat.isDealer = False
            seat.status = "empty"
            continue
        order_index = active_indexes.index(physical_index)
        relative_index = (order_index - dealer_order_index + len(active_indexes)) % len(active_indexes)
        seat.position = positions[relative_index] if relative_index < len(positions) else f"P{relative_index + 1}"
        seat.isDealer = physical_index == snapshot.dealerSeatIndex
        if seat.status == "empty":
            seat.status = "active"


def infer_actions(snapshot: GgTableSnapshot, previous: GgTableSnapshot | None) -> None:
    previous_seats = {seat.physicalSeatIndex: seat for seat in previous.seats} if previous else {}
    previous_max_bet = max(
        [round(float(seat.currentBet or 0), 2) for seat in previous.seats if seat.active] or [0.0]
    ) if previous else 0.0
    current_max_bet = max(
        [round(float(seat.currentBet or 0), 2) for seat in snapshot.seats if seat.active] or [0.0]
    )
    now_ms = int(snapshot.timestamp or time.time() * 1000)

    for seat in snapshot.seats:
        if not seat.active:
            seat.action = "none"
            seat.actionAmount = 0
            seat.actionSource = "empty"
            seat.status = "empty"
            continue

        before = previous_seats.get(seat.physicalSeatIndex)
        current_bet = round(float(seat.currentBet or 0), 2)
        before_bet = round(float(before.currentBet or 0), 2) if before else 0.0
        had_cards = bool(before and before.holeCards)
        has_cards = bool(seat.holeCards)
        explicit_action = seat.action if seat.action in {"check", "call", "bet", "raise", "fold", "all-in", "waiting"} else "none"

        if explicit_action not in {"none"} and float(seat.actionConfidence or 0.0) >= 0.45:
            if not seat.actionSource:
                seat.actionSource = "label_ocr" if explicit_action != "bet" else "visible_bet"
            if explicit_action == "fold":
                seat.holeCards = []
                seat.status = "folded"
                seat.actionAmount = 0
                seat.actionSource = seat.actionSource or "label_ocr"
            elif explicit_action in {"call", "bet", "raise", "all-in"}:
                seat.actionAmount = current_bet or float(seat.actionAmount or 0)
            continue

        if before and before.active and had_cards and not has_cards:
            seat.action = "fold"
            seat.actionAmount = 0
            seat.actionConfidence = max(float(seat.actionConfidence or 0), 0.90)
            seat.actionSource = "cards_disappeared"
            seat.status = "folded"
            continue

        if float(seat.stack or 0.0) <= 0.05 and (current_bet > 0 or float(seat.committed or 0) > 0):
            seat.action = "all-in"
            seat.actionAmount = max(current_bet, float(seat.committed or 0))
            seat.actionConfidence = max(float(seat.actionConfidence or 0), 0.82)
            seat.actionSource = "stack_zero"
            continue

        if current_bet > before_bet + 0.01:
            if current_bet > max(previous_max_bet, before_bet) + 0.01 and previous_max_bet > 0:
                seat.action = "raise"
                seat.actionSource = "bet_delta"
            elif previous_max_bet > 0 and current_bet >= previous_max_bet - 0.01:
                seat.action = "call"
                seat.actionSource = "bet_delta"
            else:
                seat.action = "bet"
                seat.actionSource = "bet_delta"
            seat.actionAmount = current_bet
            seat.actionConfidence = max(float(seat.betConfidence or 0), 0.80)
            continue

        if current_bet > 0 and current_bet >= current_max_bet - 0.01 and previous_max_bet > 0 and before_bet < current_bet:
            seat.action = "call"
            seat.actionAmount = current_bet
            seat.actionConfidence = max(float(seat.betConfidence or 0), 0.72)
            seat.actionSource = "bet_delta"
            continue

        if current_bet > 0:
            if seat.action not in {"bet", "raise", "call", "all-in"}:
                seat.action = "bet"
            seat.actionAmount = current_bet
            seat.actionSource = seat.actionSource or "visible_bet"
            continue

        if before and before.action in {"check", "fold", "call", "bet", "raise", "all-in"}:
            age_ms = max(0, now_ms - int(previous.timestamp or now_ms))
            if age_ms <= 2000:
                seat.action = before.action
                seat.actionAmount = float(before.actionAmount or 0)
                seat.actionConfidence = min(float(before.actionConfidence or 0.0), 0.55)
                seat.actionSource = before.actionSource or "held"
                if before.status == "folded":
                    seat.status = "folded"
                continue

        if seat.action not in {"check", "fold", "waiting"}:
            seat.action = "none"
            seat.actionSource = "none"
        seat.actionAmount = 0


@app.post("/api/gg-reader/start")
async def start_reader(request: GgReaderStartRequest) -> GgReaderStatus:
    global reader_config, reader_state
    resolved_index, monitor_message = resolve_monitor_index(request.monitorIndex)
    reader_config = request.model_copy(update={"monitorIndex": resolved_index})
    message = monitor_message or "running"
    if request.captureMode == "browser":
        message = "browser capture ready"
    reader_state = GgReaderStatus(
        running=True,
        monitorIndex=resolved_index,
        fps=request.fps,
        profile=request.profile,
        message=message,
        lastSnapshotAt=None,
    )
    append_event({
        "time": int(time.time() * 1000),
        "type": "reader_started",
        "message": message if message != "running" else "GG reader started",
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


@app.get("/api/gg-reader/windows")
async def get_windows() -> list[dict[str, Any]]:
    return list_gg_windows()


def decode_browser_frame(body: bytes) -> Any:
    import cv2
    import numpy as np

    buffer = np.frombuffer(body, dtype=np.uint8)
    decoded = cv2.imdecode(buffer, cv2.IMREAD_UNCHANGED)
    if decoded is not None and decoded.size:
        if decoded.ndim == 2:
            return cv2.cvtColor(decoded, cv2.COLOR_GRAY2BGR)
        return decoded

    from PIL import Image
    image = Image.open(BytesIO(body)).convert("RGBA")
    rgba = np.array(image)
    return rgba[:, :, [2, 1, 0, 3]]


def get_cached_gg_windows() -> list[dict[str, Any]]:
    global _cached_windows

    now = time.monotonic()
    cached_at, cached_value = _cached_windows
    if now - cached_at <= _CACHE_TTL_SECONDS:
        return cached_value
    value = list_gg_windows()
    _cached_windows = (now, value)
    return value


def get_cached_monitors() -> list[dict[str, Any]]:
    global _cached_monitors

    now = time.monotonic()
    cached_at, cached_value = _cached_monitors
    if now - cached_at <= _CACHE_TTL_SECONDS:
        return cached_value
    value = list_monitors()
    _cached_monitors = (now, value)
    return value


def get_cached_calibration() -> dict[str, Any]:
    global _cached_calibration

    now = time.monotonic()
    cached_at, cached_value = _cached_calibration
    if cached_value is not None and now - cached_at <= _CALIBRATION_CACHE_TTL_SECONDS:
        return cached_value
    value = load_calibration()
    _cached_calibration = (now, value)
    return value


def save_cached_calibration(data: dict[str, Any]) -> dict[str, Any]:
    global _cached_calibration

    value = save_calibration(data)
    _cached_calibration = (time.monotonic(), value)
    return value


def crop_browser_frame_to_gg_window(frame: Any) -> Any:
    cropped, _metrics = crop_browser_frame_to_gg_window_with_metrics(frame)
    return cropped


def refine_gg_table_crop(frame: Any, metrics: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    crop_result = detect_clubgg_table_crop(frame, {"source": metrics.get("cropSource")})
    refined_metrics = dict(metrics)
    base_rect = metrics.get("cropRect") or {"left": 0, "top": 0, "width": frame.shape[1], "height": frame.shape[0]}
    local_rect = crop_result.crop_rect
    combined_rect = {
        "left": int(base_rect.get("left") or 0) + int(local_rect.get("left") or 0),
        "top": int(base_rect.get("top") or 0) + int(local_rect.get("top") or 0),
        "width": int(local_rect.get("width") or 0),
        "height": int(local_rect.get("height") or 0),
    }
    refined_metrics.update(crop_result.metrics())
    refined_metrics["cropSource"] = (
        str(metrics.get("cropSource") or "browser")
        if crop_result.source in {"window-client", "browser-window-direct"}
        else f"{metrics.get('cropSource') or 'browser'}+{crop_result.source}"
    )
    refined_metrics["cropRect"] = combined_rect
    refined_metrics["inputFrameWidth"] = int(metrics.get("inputFrameWidth") or frame.shape[1])
    refined_metrics["inputFrameHeight"] = int(metrics.get("inputFrameHeight") or frame.shape[0])
    return crop_result.cropped_frame, refined_metrics


def crop_browser_frame_to_gg_window_with_metrics(frame: Any) -> tuple[Any, dict[str, Any]]:
    frame_height, frame_width = frame.shape[:2]
    metrics: dict[str, Any] = {
        "inputFrameWidth": int(frame_width),
        "inputFrameHeight": int(frame_height),
        "croppedFrameWidth": int(frame_width),
        "croppedFrameHeight": int(frame_height),
        "cropSource": "browser-no-window",
        "selectedWindowTitle": None,
        "selectedWindowRect": None,
        "cropRect": {"left": 0, "top": 0, "width": int(frame_width), "height": int(frame_height)},
    }
    windows = get_cached_gg_windows()
    if not windows:
        return refine_gg_table_crop(frame, metrics)

    window = windows[0]
    metrics["selectedWindowTitle"] = str(window.get("title") or "")
    metrics["selectedWindowRect"] = {
        "left": int(window.get("left") or 0),
        "top": int(window.get("top") or 0),
        "width": int(window.get("width") or 0),
        "height": int(window.get("height") or 0),
    }
    window_width = int(window.get("width") or 0)
    window_height = int(window.get("height") or 0)
    if window_width <= 0 or window_height <= 0:
        metrics["cropSource"] = "browser-invalid-window"
        return refine_gg_table_crop(frame, metrics)

    # If the browser shared only the GG window, keep the frame as-is.
    if frame_width <= window_width * 1.35 and frame_height <= window_height * 1.35:
        metrics["cropSource"] = "browser-window-direct"
        return refine_gg_table_crop(frame, metrics)

    monitors = get_cached_monitors()
    monitor = next(
        (
            item for item in monitors
            if int(item["left"]) <= int(window["left"]) < int(item["left"]) + int(item["width"])
            and int(item["top"]) <= int(window["top"]) < int(item["top"]) + int(item["height"])
        ),
        monitors[0] if monitors else None,
    )
    if not monitor:
        metrics["cropSource"] = "browser-monitor-unavailable"
        return refine_gg_table_crop(frame, metrics)

    scale_x = frame_width / max(1, int(monitor["width"]))
    scale_y = frame_height / max(1, int(monitor["height"]))
    left = int(round((int(window["left"]) - int(monitor["left"])) * scale_x))
    top = int(round((int(window["top"]) - int(monitor["top"])) * scale_y))
    right = int(round(left + window_width * scale_x))
    bottom = int(round(top + window_height * scale_y))

    left = max(0, min(frame_width, left))
    top = max(0, min(frame_height, top))
    right = max(left, min(frame_width, right))
    bottom = max(top, min(frame_height, bottom))
    if right - left < 320 or bottom - top < 240:
        metrics["cropSource"] = "browser-crop-too-small"
        return refine_gg_table_crop(frame, metrics)
    cropped = frame[top:bottom, left:right]
    metrics["croppedFrameWidth"] = int(right - left)
    metrics["croppedFrameHeight"] = int(bottom - top)
    metrics["cropSource"] = "browser-fullscreen-window-crop"
    metrics["cropRect"] = {
        "left": int(left),
        "top": int(top),
        "width": int(right - left),
        "height": int(bottom - top),
    }
    return refine_gg_table_crop(cropped, metrics)


def save_debug_image(path: Path, frame: Any) -> None:
    from PIL import Image

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if frame.ndim == 3 and frame.shape[2] >= 4:
        image = Image.fromarray(frame[:, :, [2, 1, 0, 3]], "RGBA")
    elif frame.ndim == 3 and frame.shape[2] == 3:
        image = Image.fromarray(frame[:, :, [2, 1, 0]], "RGB")
    else:
        image = Image.fromarray(frame)
    image.save(path)


def save_cropped_debug_frame(frame: Any, *, force: bool = False) -> None:
    global _last_cropped_frame_saved_at

    now = time.monotonic()
    if not force and now - _last_cropped_frame_saved_at < 1.0:
        return
    save_debug_image(DEBUG_CROPPED_FRAME_PATH, frame)
    _last_cropped_frame_saved_at = now


def schedule_cropped_debug_frame_save(frame: Any) -> None:
    global _cropped_frame_save_task

    if _cropped_frame_save_task is not None and not _cropped_frame_save_task.done():
        return
    if time.monotonic() - _last_cropped_frame_saved_at < 1.0:
        return
    _cropped_frame_save_task = asyncio.create_task(asyncio.to_thread(save_cropped_debug_frame, frame))
    _cropped_frame_save_task.add_done_callback(_ignore_background_task_error)


def _ignore_background_task_error(task: asyncio.Task[Any]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


@app.post("/api/gg-reader/parse-frame")
async def parse_browser_frame(request: Request, seq: int | None = None) -> dict[str, Any]:
    loop_started_at = time.perf_counter()
    server_received_at = int(time.time() * 1000)
    body = await request.body()
    frame_bytes = len(body)
    if not body:
        return {
            "type": "status",
            "status": "warning",
            "message": "לא התקבל פריים מהדפדפן.",
            "clearTable": False,
            "confidence": 0,
            "captureSource": "browser",
            "frameSeq": seq,
            "serverReceivedAt": server_received_at,
            "frameBytes": frame_bytes,
        }

    try:
        decode_started_at = time.perf_counter()
        frame = await asyncio.to_thread(decode_browser_frame, body)
        decode_ms = round((time.perf_counter() - decode_started_at) * 1000, 2)
        crop_started_at = time.perf_counter()
        frame, crop_metrics = await asyncio.to_thread(crop_browser_frame_to_gg_window_with_metrics, frame)
        crop_ms = round((time.perf_counter() - crop_started_at) * 1000, 2)
        schedule_cropped_debug_frame_save(frame)
        parse_started_at = time.perf_counter()
        snapshot = await asyncio.to_thread(parse_frame, frame, get_cached_calibration(), FAST_GG_READER)
        backend_parse_ms = round((time.perf_counter() - parse_started_at) * 1000, 2)
    except Exception as exc:
        return {
            "type": "status",
            "status": "warning",
            "message": f"לא ניתן לנתח פריים GG: {exc}",
            "clearTable": False,
            "confidence": 0,
            "captureSource": "browser",
            "frameSeq": seq,
            "serverReceivedAt": server_received_at,
            "frameBytes": frame_bytes,
        }

    frame_ms = round((time.perf_counter() - loop_started_at) * 1000, 2)
    last_crop_metrics.clear()
    last_crop_metrics.update(crop_metrics)
    metrics = FAST_GG_READER.get_metrics()
    metrics.update(crop_metrics)
    metrics["readerParseMs"] = metrics.get("parseMs")
    metrics["parseMs"] = backend_parse_ms
    metrics["cropMs"] = crop_ms
    metrics["totalFrameMs"] = frame_ms
    metrics["frameBytes"] = frame_bytes
    metrics["frameSeq"] = seq
    metrics["serverReceivedAt"] = server_received_at
    reader_state.framesRead += 1
    reader_state.lastFrameMs = frame_ms
    reader_state.captureSource = "browser"

    if snapshot is None:
        return {
            "type": "status",
            "status": "waiting",
            "message": "מחובר, ממתין לזיהוי שולחן GG",
            "clearTable": False,
            "confidence": 0,
            "captureSource": "browser",
            "frameSeq": seq,
            "serverReceivedAt": server_received_at,
            "frameBytes": frame_bytes,
            "frameMs": frame_ms,
            "decodeMs": decode_ms,
            "cropMs": crop_ms,
            "parseMs": backend_parse_ms,
            **metrics,
        }

    snapshot, events = enrich_snapshot(snapshot)
    reader_state.lastSnapshotAt = snapshot.timestamp
    data = snapshot.model_dump()
    data["captureSource"] = "browser"
    data["frameSeq"] = seq
    data["serverReceivedAt"] = server_received_at
    data["frameBytes"] = frame_bytes
    data["frameMs"] = frame_ms
    data["decodeMs"] = decode_ms
    data["cropMs"] = crop_ms
    data["parseMs"] = backend_parse_ms
    data["totalFrameMs"] = frame_ms
    data.update(metrics)
    data["events"] = events
    return data


@app.get("/api/gg-reader/history")
async def get_history(limit: int = 50) -> list[dict[str, Any]]:
    return read_history(limit)


@app.get("/api/gg-reader/hands")
async def get_hands(limit: int = 25) -> list[dict[str, Any]]:
    return read_hands(limit)


@app.get("/api/gg-reader/calibration")
async def get_calibration() -> dict[str, Any]:
    return get_cached_calibration()


@app.post("/api/gg-reader/calibration")
async def post_calibration(data: dict[str, Any]) -> dict[str, Any]:
    return save_cached_calibration(data)


def save_debug_frame(monitor_index: int, capture_mode: str = "auto") -> dict[str, Any]:
    global last_crop_metrics

    capture = ScreenCapture(monitor_index=monitor_index, capture_mode=capture_mode)
    try:
        frame = capture.grab()
        resolved_index = capture.get_monitor_index()
        capture_source = capture.last_source
        captured_window = capture.last_window
    finally:
        capture.close()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    save_debug_image(DEBUG_FRAME_PATH, frame)
    cropped_frame, crop_metrics = refine_gg_table_crop(frame, {
        "inputFrameWidth": int(frame.shape[1]),
        "inputFrameHeight": int(frame.shape[0]),
        "croppedFrameWidth": int(frame.shape[1]),
        "croppedFrameHeight": int(frame.shape[0]),
        "cropSource": capture_source,
        "selectedWindowTitle": str((captured_window or {}).get("title") or "") if captured_window else None,
        "selectedWindowRect": {
            "left": int((captured_window or {}).get("left") or 0),
            "top": int((captured_window or {}).get("top") or 0),
            "width": int((captured_window or {}).get("width") or frame.shape[1]),
            "height": int((captured_window or {}).get("height") or frame.shape[0]),
        } if captured_window else None,
        "cropRect": {"left": 0, "top": 0, "width": int(frame.shape[1]), "height": int(frame.shape[0])},
    })
    save_cropped_debug_frame(cropped_frame, force=True)

    height, width = frame.shape[:2]
    last_crop_metrics = crop_metrics
    return {
        "path": str(DEBUG_FRAME_PATH),
        "croppedPath": str(DEBUG_CROPPED_FRAME_PATH),
        "width": int(width),
        "height": int(height),
        "croppedWidth": int(cropped_frame.shape[1]),
        "croppedHeight": int(cropped_frame.shape[0]),
        "monitorIndex": resolved_index,
        "captureSource": capture_source,
        "window": captured_window,
        **crop_metrics,
    }


@app.get("/api/gg-reader/debug/frame")
async def get_debug_frame(monitorIndex: int | None = None, source: str = "auto") -> dict[str, Any]:
    try:
        capture_mode = source if source in {"auto", "window", "monitor"} else "auto"
        metadata = save_debug_frame(monitorIndex or reader_config.monitorIndex, capture_mode)
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
            "croppedPath": str(DEBUG_CROPPED_FRAME_PATH),
            "croppedExists": DEBUG_CROPPED_FRAME_PATH.exists(),
            "monitorIndex": reader_config.monitorIndex,
        }
    return {
        "exists": True,
        "path": str(DEBUG_FRAME_PATH),
        "bytes": DEBUG_FRAME_PATH.stat().st_size,
        "croppedPath": str(DEBUG_CROPPED_FRAME_PATH),
        "croppedExists": DEBUG_CROPPED_FRAME_PATH.exists(),
        "croppedBytes": DEBUG_CROPPED_FRAME_PATH.stat().st_size if DEBUG_CROPPED_FRAME_PATH.exists() else 0,
        "monitorIndex": reader_config.monitorIndex,
    }


@app.get("/api/gg-reader/debug/metrics")
async def get_debug_metrics() -> dict[str, Any]:
    return {
        **FAST_GG_READER.get_metrics(),
        **last_crop_metrics,
        "running": reader_state.running,
        "framesRead": reader_state.framesRead,
        "lastFrameMs": reader_state.lastFrameMs,
        "captureSource": reader_state.captureSource,
        "lastSnapshotAt": reader_state.lastSnapshotAt,
    }


@app.get("/api/gg-reader/debug/roi-overlay")
async def get_debug_roi_overlay() -> dict[str, Any]:
    try:
        metadata = FAST_GG_READER.save_roi_overlay(DEBUG_ROI_OVERLAY_PATH)
    except Exception:
        source_path = DEBUG_CROPPED_FRAME_PATH if DEBUG_CROPPED_FRAME_PATH.exists() else DEBUG_FRAME_PATH
        if not source_path.exists():
            return {
                "ok": False,
                "error": "No parsed frame or debug_last_cropped_frame.png is available.",
                "path": str(DEBUG_ROI_OVERLAY_PATH),
            }
        import cv2

        frame = cv2.imread(str(source_path), cv2.IMREAD_UNCHANGED)
        if frame is None:
            return {
                "ok": False,
                "error": f"Could not load {source_path.name}.",
                "path": str(DEBUG_ROI_OVERLAY_PATH),
            }
        metadata = FAST_GG_READER.save_roi_overlay(DEBUG_ROI_OVERLAY_PATH, frame=frame)
    return {
        "ok": True,
        "croppedFramePath": str(DEBUG_CROPPED_FRAME_PATH),
        "croppedFrameWidth": last_crop_metrics.get("croppedFrameWidth") or metadata.get("width"),
        "croppedFrameHeight": last_crop_metrics.get("croppedFrameHeight") or metadata.get("height"),
        "profile": FAST_GG_READER.get_metrics().get("profile"),
        "cropSource": last_crop_metrics.get("cropSource"),
        **metadata,
    }


@app.get("/api/gg-reader/debug/field-crops")
async def get_debug_field_crops() -> dict[str, Any]:
    try:
        metadata = FAST_GG_READER.save_field_crops(DEBUG_FIELD_CROPS_DIR)
    except Exception:
        source_path = DEBUG_CROPPED_FRAME_PATH if DEBUG_CROPPED_FRAME_PATH.exists() else DEBUG_FRAME_PATH
        if not source_path.exists():
            return {
                "ok": False,
                "error": "No parsed frame or debug frame is available.",
                "path": str(DEBUG_FIELD_CROPS_DIR),
            }
        import cv2

        frame = cv2.imread(str(source_path), cv2.IMREAD_UNCHANGED)
        if frame is None:
            return {
                "ok": False,
                "error": f"Could not load {source_path.name}.",
                "path": str(DEBUG_FIELD_CROPS_DIR),
            }
        metadata = FAST_GG_READER.save_field_crops(DEBUG_FIELD_CROPS_DIR, frame=frame)
    return {
        "ok": True,
        "croppedFramePath": str(DEBUG_CROPPED_FRAME_PATH),
        "cropSource": last_crop_metrics.get("cropSource"),
        **metadata,
    }


@app.get("/api/gg-reader/debug/last-snapshot-detailed")
async def get_debug_last_snapshot_detailed() -> dict[str, Any]:
    if last_snapshot is None:
        return {
            "ok": False,
            "snapshot": None,
            "metrics": {
                **FAST_GG_READER.get_metrics(),
                **last_crop_metrics,
            },
        }
    return {
        "ok": True,
        "snapshot": last_snapshot.model_dump(),
        "metrics": {
            **FAST_GG_READER.get_metrics(),
            **last_crop_metrics,
        },
    }


@app.websocket("/ws/gg-reader")
async def gg_reader_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    capture = ScreenCapture(
        monitor_index=reader_config.monitorIndex,
        debug=reader_config.debug,
        capture_mode=reader_config.captureMode,
    )
    calibration = get_cached_calibration()
    try:
        while True:
            loop_started_at = time.perf_counter()
            if reader_state.running:
                if reader_config.profile == "mock":
                    snapshot = load_mock_snapshot()
                    snapshot, events = enrich_snapshot(snapshot)
                    reader_state.lastSnapshotAt = snapshot.timestamp
                    data = snapshot.model_dump()
                    data["events"] = events
                    await websocket.send_json(data)
                else:
                    try:
                        frame = await asyncio.to_thread(capture.grab)
                        snapshot = await asyncio.to_thread(parse_frame, frame, calibration, FAST_GG_READER)
                    except Exception as exc:
                        await websocket.send_json({
                            "type": "status",
                            "status": "warning",
                            "message": f"לא ניתן לצלם את Monitor {reader_config.monitorIndex}: {exc}",
                            "clearTable": False,
                            "fatal": False,
                            "confidence": 0,
                        })
                        target_interval = max(1.0, 1 / max(reader_config.fps, 0.1)) if reader_state.running else 0.1
                        elapsed = time.perf_counter() - loop_started_at
                        await asyncio.sleep(max(0.0, target_interval - elapsed))
                        continue
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
                            target_interval = max(1.0, 1 / max(reader_config.fps, 0.1)) if reader_state.running else 0.1
                            elapsed = time.perf_counter() - loop_started_at
                            await asyncio.sleep(max(0.0, target_interval - elapsed))
                            continue
                        else:
                            snapshot, events = enrich_snapshot(snapshot)
                            reader_state.lastSnapshotAt = snapshot.timestamp
                            data = snapshot.model_dump()
                            data["captureSource"] = capture.last_source
                            data["window"] = capture.last_window
                            data["frameMs"] = round((time.perf_counter() - loop_started_at) * 1000, 2)
                            metrics = FAST_GG_READER.get_metrics()
                            metrics["readerParseMs"] = metrics.get("parseMs")
                            metrics["parseMs"] = data["frameMs"]
                            data.update(metrics)
                            data["events"] = events
                            reader_state.framesRead += 1
                            reader_state.lastFrameMs = data["frameMs"]
                            reader_state.captureSource = capture.last_source
                            await websocket.send_json(data)
            target_interval = max(1.0, 1 / max(reader_config.fps, 0.1)) if reader_state.running else 0.1
            elapsed = time.perf_counter() - loop_started_at
            await asyncio.sleep(max(0.0, target_interval - elapsed))
    except WebSocketDisconnect:
        capture.close()
        return
    finally:
        capture.close()
