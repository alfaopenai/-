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
from .gg_reader.data_paths import get_data_dir
from .gg_reader.fast_reader import FastGgReader
from .gg_reader.history_store import append_event, read_hands, read_history, record_snapshot
from .gg_reader.models import GgReaderStartRequest, GgReaderStatus, GgTableSnapshot
from .gg_reader.parser import load_mock_snapshot, parse_frame, reset_parser_cache
from .gg_reader.table_crop import detect_clubgg_table_crop


DATA_DIR = get_data_dir()
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
_reader_pipeline_task: asyncio.Task[Any] | None = None
_reader_session_generation = 0
_last_browser_frame_seq: int | None = None
_native_subscriber_counter = 0
_native_capture_owner: int | None = None
_native_subscribers: dict[int, asyncio.Queue[tuple[int, dict[str, Any]]]] = {}
_native_latest_payload: tuple[int, dict[str, Any]] | None = None


POSITIONS_BY_PLAYER_COUNT = {
    2: ["SB", "BB"],
    3: ["BTN", "SB", "BB"],
    4: ["BTN", "SB", "BB", "CO"],
    5: ["BTN", "SB", "BB", "UTG", "CO"],
    6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"],
    7: ["BTN", "SB", "BB", "UTG", "MP", "HJ", "CO"],
    8: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "HJ", "CO"],
    9: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"],
}
STREET_ORDER = {"unknown": -1, "preflop": 0, "flop": 1, "turn": 2, "river": 3, "showdown": 4}
READ_RATE_MARGIN = 1.15


def build_normalized_state(snapshot: GgTableSnapshot, metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    payload_metrics = dict(metrics or snapshot.metrics or {})
    amount_fields = payload_metrics.get("amountFields") or snapshot.metrics.get("amountFields") or []
    pot_field = next((field for field in amount_fields if isinstance(field, dict) and field.get("key") == "pot"), {})
    seat_database = _seat_database_payload(payload_metrics or snapshot.metrics or {})
    board_database = _board_database_payload(payload_metrics or snapshot.metrics or {})
    visible_bets = [
        round(float(seat.currentBet or 0.0), 4)
        for seat in snapshot.seats
        if seat.active and float(seat.currentBet or 0.0) > 0
    ]
    calculated_pot = round(sum(visible_bets), 4) if visible_bets else None
    detected_pot = round(float(snapshot.pot or 0.0), 4)
    warnings: list[str] = []
    if calculated_pot is not None and detected_pot > 0:
        # The total pot legitimately exceeds the chips still visible on later
        # streets. Only the impossible inverse is a useful warning.
        shortfall = calculated_pot - detected_pot
        if shortfall > max(0.5, calculated_pot * 0.20):
            warnings.append(f"detected pot {detected_pot:g} BB is below visible bets {calculated_pot:g} BB")
    warnings.extend(str(item) for item in payload_metrics.get("cropWarnings") or [] if item)

    board_cards = [_card_code(card) for card in snapshot.board if _card_code(card)]
    normalized_seats = []
    for seat in sorted(snapshot.seats, key=lambda item: int(item.physicalSeatIndex)):
        cards = [_card_code(card) or (card.display or "X") for card in seat.holeCards]
        normalized_seats.append({
            "seat_index": int(seat.physicalSeatIndex),
            "occupied": bool(seat.active),
            "empty_seat": not bool(seat.active),
            "player_name": seat.name or "",
            "stack_bb": round(float(seat.stack or 0.0), 4) if seat.active and float(seat.stack or 0.0) > 0 else None,
            "current_bet_bb": round(float(seat.currentBet or 0.0), 4) if seat.active and float(seat.currentBet or 0.0) > 0 else None,
            "cards": cards,
            "cards_visible": any(card.visible and not card.hidden and bool(_card_code(card)) for card in seat.holeCards),
            "has_hidden_cards": any(card.hidden or card.visible is False for card in seat.holeCards),
            "is_dealer": bool(seat.isDealer or int(seat.physicalSeatIndex) == int(snapshot.dealerSeatIndex)),
            "status": seat.status,
            "position": seat.position,
            "action": seat.action,
            "action_amount_bb": round(float(seat.actionAmount or 0.0), 4) if float(seat.actionAmount or 0.0) > 0 else None,
            "action_source": seat.actionSource or "none",
            "last_updated_at": int(snapshot.timestamp),
            "confidence": {
                "name": round(float(seat.nameConfidence or 0.0), 4),
                "stack": round(float(seat.stackConfidence or 0.0), 4),
                "bet": round(float(seat.betConfidence or 0.0), 4),
                "action": round(float(seat.actionConfidence or 0.0), 4),
                "cards": round(_cards_confidence(seat.holeCards), 4),
                "seat": round(float(seat.confidence or 0.0), 4),
            },
        })

    return {
        "table": {
            "window_found": bool(payload_metrics.get("isRealClubGg", True)),
            "read_rate_hz": round(float(payload_metrics.get("actualReaderFps") or 0.0), 4),
            "street": snapshot.street,
            "detected_pot_text": str(pot_field.get("raw") or ""),
            "total_pot_bb": detected_pot if detected_pot > 0 else None,
            "calculated_pot_from_bets_bb": calculated_pot,
            "board_cards": board_cards,
            "dealer_seat": int(snapshot.dealerSeatIndex),
            "active_player_count": int(snapshot.activePlayerCount),
            "warnings": warnings,
        },
        "seats": normalized_seats,
        "seat_database": seat_database,
        "board_database": board_database,
    }


def _card_code(card: Any) -> str:
    if not card or bool(getattr(card, "hidden", False)) or getattr(card, "visible", True) is False:
        return ""
    rank = str(getattr(card, "rank", "") or "").strip().upper()
    suit = str(getattr(card, "suit", "") or "").strip().upper()[:1]
    return f"{rank}{suit}" if rank and suit else ""


def _cards_confidence(cards: list[Any]) -> float:
    values = [float(getattr(card, "confidence", 0.0) or 0.0) for card in cards]
    return sum(values) / len(values) if values else 0.0


def _seat_database_payload(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    stabilizer = metrics.get("stabilizer") if isinstance(metrics, dict) else None
    records = stabilizer.get("seatDatabase") if isinstance(stabilizer, dict) else []
    if not isinstance(records, list):
        return []
    normalized: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            seat_index = int(record.get("seatIndex"))
        except (TypeError, ValueError):
            continue
        stack = _safe_float(record.get("stack"))
        pending_stack = _safe_float(record.get("pendingStack"))
        normalized.append({
            "seat_index": seat_index,
            "occupied": bool(record.get("active")),
            "player_name": str(record.get("name") or ""),
            "stack_bb": round(stack, 4) if stack > 0 else None,
            "confidence": {
                "name": round(_safe_float(record.get("nameConfidence")), 4),
                "stack": round(_safe_float(record.get("stackConfidence")), 4),
            },
            "pending_name": str(record.get("pendingName") or ""),
            "pending_name_hits": int(record.get("pendingNameHits") or 0),
            "pending_stack_bb": round(pending_stack, 4) if pending_stack > 0 else None,
            "pending_stack_hits": int(record.get("pendingStackHits") or 0),
        })
    return normalized


def _board_database_payload(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    stabilizer = metrics.get("stabilizer") if isinstance(metrics, dict) else None
    records = stabilizer.get("boardDatabase") if isinstance(stabilizer, dict) else []
    if not isinstance(records, list):
        return []
    normalized: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            slot = int(record.get("slot"))
        except (TypeError, ValueError):
            continue
        normalized.append({
            "slot": slot,
            "card": str(record.get("card") or ""),
            "confidence": round(_safe_float(record.get("confidence")), 4),
            "pending_card": str(record.get("pendingCard") or ""),
            "pending_hits": int(record.get("pendingHits") or 0),
        })
    return normalized


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


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
    stabilizer_metrics = snapshot.metrics.get("stabilizer") if isinstance(snapshot.metrics, dict) else None
    if isinstance(stabilizer_metrics, dict) and bool(stabilizer_metrics.get("handReset")):
        return True
    previous_street = STREET_ORDER.get(previous.street, -1)
    next_street = STREET_ORDER.get(snapshot.street, -1)
    previous_board_count = sum(1 for card in previous.board if card.visible and not card.hidden)
    next_board_count = sum(1 for card in snapshot.board if card.visible and not card.hidden)
    if next_street >= 0 and previous_street > next_street:
        return True
    if previous_board_count > 0 and next_board_count == 0 and snapshot.street == "preflop":
        return True
    return False


def assign_positions(snapshot: GgTableSnapshot, active_indexes: list[int]) -> None:
    if not active_indexes:
        return

    if snapshot.dealerSeatIndex not in active_indexes:
        snapshot.dealerSeatIndex = active_indexes[0]

    dealer_order_index = active_indexes.index(snapshot.dealerSeatIndex)
    positions = POSITIONS_BY_PLAYER_COUNT.get(len(active_indexes), POSITIONS_BY_PLAYER_COUNT[9])
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
    same_hand = bool(
        previous
        and (not previous.handId or not snapshot.handId or previous.handId == snapshot.handId)
    )
    same_street = bool(same_hand and previous and previous.street == snapshot.street)
    previous_seats = {seat.physicalSeatIndex: seat for seat in previous.seats} if same_hand and previous else {}
    previous_max_bet = max(
        [round(float(seat.currentBet or 0), 2) for seat in previous.seats if seat.active] or [0.0]
    ) if same_street and previous else 0.0
    now_ms = int(snapshot.timestamp or time.time() * 1000)

    for seat in snapshot.seats:
        if not seat.active:
            seat.action = "none"
            seat.actionAmount = 0
            seat.actionSource = "empty"
            seat.status = "empty"
            seat.inHand = False
            seat.isAllIn = False
            continue

        before = previous_seats.get(seat.physicalSeatIndex)
        current_bet = round(float(seat.currentBet or 0), 2)
        before_bet = round(float(before.currentBet or 0), 2) if before and same_street else 0.0
        had_cards = bool(before and before.holeCards)
        has_cards = bool(seat.holeCards)
        has_visible_cards = bool(
            len(seat.holeCards) >= 2
            and all(card.visible and not card.hidden and card.rank and card.suit for card in seat.holeCards[:2])
        )
        explicit_action = seat.action if seat.action in {"check", "call", "bet", "raise", "fold", "all-in", "waiting"} else "none"
        action_source = str(seat.actionSource or "")
        provisional_visible_bet = explicit_action == "bet" and action_source in {"visible_bet", "held", "none", ""}

        # A chip amount alone only tells us that money is present; it cannot
        # distinguish a bet, call, or raise. Preserve actual action labels and
        # state-derived folds/all-ins, then classify visible chips by delta.
        if has_visible_cards:
            # Face-up cards at showdown are definitive in-hand evidence.  They
            # must recover from a transient cards-disappeared fold during the
            # reveal animation and from red equity glyphs mistaken for Fold.
            seat.status = "active"
            seat.inHand = True
            seat.isAllIn = bool(seat.isAllIn or (before and before.isAllIn))
            if explicit_action == "fold" or (before and before.status == "folded"):
                seat.action = "all-in" if seat.isAllIn else "none"
                seat.actionAmount = float(seat.currentBet or 0.0)
                seat.actionConfidence = max(float(seat.actionConfidence or 0.0), 0.88)
                seat.actionSource = "exposed_cards"
            continue

        if (
            explicit_action != "none"
            and not provisional_visible_bet
            and float(seat.actionConfidence or 0.0) >= 0.45
        ):
            if not seat.actionSource:
                seat.actionSource = "label_ocr" if explicit_action != "bet" else "visible_bet"
            if explicit_action == "fold":
                seat.holeCards = []
                seat.status = "folded"
                seat.inHand = False
                seat.actionAmount = 0
                seat.actionSource = seat.actionSource or "label_ocr"
            elif explicit_action in {"call", "bet", "raise", "all-in"}:
                seat.actionAmount = current_bet or float(seat.actionAmount or 0)
                if explicit_action == "all-in":
                    seat.isAllIn = True
                    seat.inHand = True
            continue

        if before and before.active and before.status == "folded" and same_hand:
            seat.action = "fold"
            seat.actionAmount = 0
            seat.actionConfidence = max(float(seat.actionConfidence or 0), 0.80)
            seat.actionSource = before.actionSource or "held"
            seat.status = "folded"
            seat.inHand = False
            seat.holeCards = []
            continue

        if same_hand and before and before.active and had_cards and not has_cards:
            seat.action = "fold"
            seat.actionAmount = 0
            seat.actionConfidence = max(float(seat.actionConfidence or 0), 0.90)
            seat.actionSource = "cards_disappeared"
            seat.status = "folded"
            seat.inHand = False
            continue

        if float(seat.stack or 0.0) <= 0.05 and (current_bet > 0 or float(seat.committed or 0) > 0):
            seat.action = "all-in"
            seat.actionAmount = max(current_bet, float(seat.committed or 0))
            seat.actionConfidence = max(float(seat.actionConfidence or 0), 0.82)
            seat.actionSource = "stack_zero"
            seat.isAllIn = True
            seat.inHand = True
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

        if (
            before
            and before.action in {"check", "fold", "call", "bet", "raise", "all-in"}
            and str(before.actionSource or "") not in {"", "none", "held", "visible_bet"}
        ):
            age_ms = max(0, now_ms - int(previous.timestamp or now_ms))
            if age_ms <= 2000:
                seat.action = before.action
                seat.actionAmount = float(before.actionAmount or 0)
                seat.actionConfidence = min(float(before.actionConfidence or 0.0), 0.55)
                seat.actionSource = "held"
                if before.status == "folded":
                    seat.status = "folded"
                continue

        if current_bet > 0 and before is None:
            seat.action = "bet"
            seat.actionAmount = current_bet
            seat.actionConfidence = max(float(seat.betConfidence or 0), 0.55)
            seat.actionSource = "visible_bet"
            continue

        seat.action = "none"
        seat.actionSource = "none"
        seat.actionAmount = 0
        seat.actionConfidence = 0.0


def target_reader_interval_seconds(fps: float) -> float:
    requested_fps = max(float(fps or 0.1), 0.1)
    return max(0.05, 1 / (requested_fps * READ_RATE_MARGIN))


def _offer_native_payload(
    queue: asyncio.Queue[tuple[int, dict[str, Any]]],
    payload: tuple[int, dict[str, Any]],
) -> None:
    """Keep only the newest observation for a websocket subscriber."""

    while not queue.empty():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break
    queue.put_nowait(payload)


def _register_native_subscriber() -> tuple[int, asyncio.Queue[tuple[int, dict[str, Any]]]]:
    global _native_subscriber_counter, _native_capture_owner

    _native_subscriber_counter += 1
    subscriber_id = _native_subscriber_counter
    queue: asyncio.Queue[tuple[int, dict[str, Any]]] = asyncio.Queue(maxsize=1)
    _native_subscribers[subscriber_id] = queue
    if _native_capture_owner is None:
        _native_capture_owner = subscriber_id
    if (
        _native_latest_payload is not None
        and _native_latest_payload[0] == _reader_session_generation
        and reader_state.running
    ):
        _offer_native_payload(queue, _native_latest_payload)
    return subscriber_id, queue


def _unregister_native_subscriber(subscriber_id: int) -> None:
    global _native_capture_owner

    _native_subscribers.pop(subscriber_id, None)
    if _native_capture_owner == subscriber_id:
        # Dict insertion order gives deterministic ownership and, importantly,
        # ownership changes only after the old owner's capture task has exited.
        _native_capture_owner = next(iter(_native_subscribers), None)


def _is_native_capture_owner(subscriber_id: int) -> bool:
    return _native_capture_owner == subscriber_id


def _clear_native_delivery_state() -> None:
    global _native_latest_payload

    _native_latest_payload = None
    for queue in tuple(_native_subscribers.values()):
        while not queue.empty():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break


def _publish_native_payload(generation: int, data: dict[str, Any]) -> bool:
    global _native_latest_payload

    if not _reader_session_is_current(generation) or reader_config.captureMode == "browser":
        return False
    payload = (generation, data)
    _native_latest_payload = payload
    for queue in tuple(_native_subscribers.values()):
        _offer_native_payload(queue, payload)
    return True


async def _receive_native_payload(
    queue: asyncio.Queue[tuple[int, dict[str, Any]]],
    *,
    timeout: float,
) -> dict[str, Any] | None:
    try:
        generation, data = await asyncio.wait_for(queue.get(), timeout=timeout)
    except asyncio.TimeoutError:
        return None
    if (
        not _reader_session_is_current(generation)
        or reader_config.captureMode == "browser"
    ):
        return None
    return data


def _invalidate_reader_session() -> int:
    global _reader_session_generation, _last_browser_frame_seq

    _reader_session_generation += 1
    _last_browser_frame_seq = None
    _clear_native_delivery_state()
    return _reader_session_generation


def _reader_session_is_current(generation: int) -> bool:
    return generation == _reader_session_generation and bool(reader_state.running)


def _browser_session_is_current(generation: int) -> bool:
    return _reader_session_is_current(generation) and reader_config.captureMode == "browser"


def _claim_browser_frame_sequence(seq: int | None, generation: int) -> str | None:
    global _last_browser_frame_seq

    if not _browser_session_is_current(generation):
        return "session-stale"
    if seq is None:
        return None
    normalized_seq = int(seq)
    if _last_browser_frame_seq is not None and normalized_seq <= _last_browser_frame_seq:
        return "duplicate-seq" if normalized_seq == _last_browser_frame_seq else "out-of-order-seq"
    _last_browser_frame_seq = normalized_seq
    return None


@app.post("/api/gg-reader/start")
async def start_reader(request: GgReaderStartRequest) -> GgReaderStatus:
    global reader_config, reader_state, current_hand_id, last_snapshot
    generation = _invalidate_reader_session()
    reader_state.running = False
    reader_state.message = "starting"
    resolved_index, monitor_message = resolve_monitor_index(request.monitorIndex)
    await _reset_reader_runtime()
    if generation != _reader_session_generation:
        return reader_state
    reader_config = request.model_copy(update={"monitorIndex": resolved_index})
    current_hand_id = None
    last_snapshot = None
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
    generation = _invalidate_reader_session()
    reader_state.running = False
    reader_state.message = "stopped"
    await _reset_reader_runtime()
    if generation != _reader_session_generation:
        return reader_state
    append_event({"time": int(time.time() * 1000), "type": "reader_stopped", "message": "GG reader stopped"})
    return reader_state


@app.get("/api/gg-reader/status")
async def get_status() -> GgReaderStatus:
    return reader_state


@app.get("/api/gg-reader/monitors")
async def get_monitors() -> list[dict[str, int]]:
    return list_monitors()


@app.get("/api/gg-reader/windows")
async def get_windows(includeRejected: bool = False) -> list[dict[str, Any]]:
    return list_gg_windows(include_rejected=includeRejected)


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
    # A browser upload is not necessarily the current monitor at native size:
    # getDisplayMedia may send a resized screen, an individual window, or a
    # screenshot supplied by another machine. In those cases the locally
    # selected HWND metadata must not validate unrelated pixels. Geometry may
    # still guide a confirmed full-monitor crop, but arbitrary-frame fallbacks
    # are intentionally validated from their visual ClubGG anchors alone.
    pixels_only = bool(metrics.get("ignoreSelectedWindowForCropValidation"))
    crop_metadata: dict[str, Any] = {
        "source": metrics.get("cropSource"),
        "captureSource": metrics.get("captureSource"),
    }
    if not pixels_only:
        crop_metadata.update({
            **metrics,
            "title": metrics.get("selectedWindowTitle"),
            **(metrics.get("selectedWindow") if isinstance(metrics.get("selectedWindow"), dict) else {}),
        })
    crop_result = detect_clubgg_table_crop(frame, crop_metadata)
    refined_metrics = dict(metrics)
    base_rect = metrics.get("cropRect") or {"left": 0, "top": 0, "width": frame.shape[1], "height": frame.shape[0]}
    local_rect = crop_result.crop_rect
    combined_rect = {
        "left": int(base_rect.get("left") or 0) + int(local_rect.get("left") or 0),
        "top": int(base_rect.get("top") or 0) + int(local_rect.get("top") or 0),
        "width": int(local_rect.get("width") or 0),
        "height": int(local_rect.get("height") or 0),
    }
    incoming_warnings = list(metrics.get("cropWarnings") or [])
    refined_metrics.update(crop_result.metrics())
    refined_metrics["cropWarnings"] = list(dict.fromkeys([
        *incoming_warnings,
        *list(refined_metrics.get("cropWarnings") or []),
    ]))
    refined_metrics["cropSource"] = (
        str(metrics.get("cropSource") or "browser")
        if crop_result.source in {"window-client", "browser-window-direct"}
        else f"{metrics.get('cropSource') or 'browser'}+{crop_result.source}"
    )
    refined_metrics["cropRect"] = combined_rect
    refined_metrics["inputFrameWidth"] = int(metrics.get("inputFrameWidth") or frame.shape[1])
    refined_metrics["inputFrameHeight"] = int(metrics.get("inputFrameHeight") or frame.shape[0])
    refined_metrics.pop("ignoreSelectedWindowForCropValidation", None)
    return crop_result.cropped_frame, refined_metrics


def _refine_arbitrary_browser_frame(
    frame: Any,
    metrics: dict[str, Any],
    *,
    warning: str,
) -> tuple[Any, dict[str, Any]]:
    fallback_metrics = dict(metrics)
    fallback_metrics["cropSource"] = "browser-arbitrary-frame"
    fallback_metrics["browserFrameGeometryFallback"] = True
    fallback_metrics["ignoreSelectedWindowForCropValidation"] = True
    fallback_metrics["cropWarnings"] = [warning]
    return refine_gg_table_crop(frame, fallback_metrics)


def crop_browser_frame_to_gg_window_with_metrics(frame: Any) -> tuple[Any, dict[str, Any]]:
    frame_height, frame_width = frame.shape[:2]
    metrics: dict[str, Any] = {
        "inputFrameWidth": int(frame_width),
        "inputFrameHeight": int(frame_height),
        "croppedFrameWidth": int(frame_width),
        "croppedFrameHeight": int(frame_height),
        "cropSource": "browser-no-window",
        "captureSource": "browser",
        "selectedWindowTitle": None,
        "selectedWindow": None,
        "selectedWindowRect": None,
        "cropRect": {"left": 0, "top": 0, "width": int(frame_width), "height": int(frame_height)},
    }
    windows = get_cached_gg_windows()
    if not windows:
        return refine_gg_table_crop(frame, metrics)

    window = windows[0]
    metrics["selectedWindow"] = dict(window)
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
        return _refine_arbitrary_browser_frame(frame, metrics, warning="browser-invalid-window")

    # If the browser shared only the GG window, keep the frame as-is.
    if frame_width <= window_width * 1.35 and frame_height <= window_height * 1.35:
        metrics["cropSource"] = "browser-window-direct"
        metrics["ignoreSelectedWindowForCropValidation"] = True
        return refine_gg_table_crop(frame, metrics)

    monitors = get_cached_monitors()
    if not _browser_frame_looks_like_full_monitor(frame_width, frame_height, monitors):
        return _refine_arbitrary_browser_frame(
            frame,
            metrics,
            warning="browser-frame-not-full-monitor",
        )

    monitor = next(
        (
            item for item in monitors
            if int(item["left"]) <= int(window["left"]) < int(item["left"]) + int(item["width"])
            and int(item["top"]) <= int(window["top"]) < int(item["top"]) + int(item["height"])
        ),
        monitors[0] if monitors else None,
    )
    if not monitor:
        return _refine_arbitrary_browser_frame(frame, metrics, warning="browser-monitor-unavailable")

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
        return _refine_arbitrary_browser_frame(
            frame,
            metrics,
            warning="browser-window-rect-outside-frame",
        )
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


def _browser_frame_looks_like_full_monitor(frame_width: int, frame_height: int, monitors: list[dict[str, Any]]) -> bool:
    if not monitors:
        return False
    frame_aspect = frame_width / max(1, frame_height)
    for monitor in monitors:
        monitor_width = int(monitor.get("width") or 0)
        monitor_height = int(monitor.get("height") or 0)
        if monitor_width <= 0 or monitor_height <= 0:
            continue
        monitor_aspect = monitor_width / max(1, monitor_height)
        if abs(frame_aspect - monitor_aspect) <= 0.08:
            return True
        scale_x = frame_width / monitor_width
        scale_y = frame_height / monitor_height
        if 0.25 <= scale_x <= 2.5 and abs(scale_x - scale_y) <= 0.08:
            return True
    return False


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


def _extract_crop_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "inputFrameWidth",
        "inputFrameHeight",
        "croppedFrameWidth",
        "croppedFrameHeight",
        "cropSource",
        "captureSource",
        "selectedWindowTitle",
        "selectedWindowRect",
        "selectedWindow",
        "cropRect",
        "innerTableRect",
        "cropConfidence",
        "cropWarnings",
        "cropDiagnostics",
        "isRealClubGg",
        "realClubGgScore",
        "clubggAnchorsFound",
        "rejectedLocalhostTable",
        "rejectedBrowserChrome",
        "rejectedReason",
        "selectedCropCandidate",
        "cropCandidates",
        "browserFrameGeometryFallback",
    }
    return {key: value for key, value in metrics.items() if key in keys}


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


def _reader_pipeline_busy() -> bool:
    return _reader_pipeline_task is not None and not _reader_pipeline_task.done()


def _start_reader_pipeline(awaitable: Any) -> asyncio.Task[Any]:
    global _reader_pipeline_task
    if _reader_pipeline_busy():
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        raise RuntimeError("GG reader pipeline is already busy")
    task = asyncio.create_task(awaitable)
    _reader_pipeline_task = task
    task.add_done_callback(_reader_pipeline_finished)
    return task


def _reader_pipeline_finished(task: asyncio.Task[Any]) -> None:
    global _reader_pipeline_task
    if _reader_pipeline_task is task:
        _reader_pipeline_task = None
    try:
        task.exception()
    except (asyncio.CancelledError, Exception):
        pass


async def _wait_for_reader_pipeline() -> None:
    task = _reader_pipeline_task
    if task is None:
        return
    try:
        await asyncio.shield(task)
    except Exception:
        pass


async def _reset_reader_runtime() -> None:
    async def reset_pipeline() -> None:
        await _to_thread_until_complete(FAST_GG_READER.reset)
        await _to_thread_until_complete(reset_parser_cache)

    while True:
        await _wait_for_reader_pipeline()
        try:
            task = _start_reader_pipeline(reset_pipeline())
        except RuntimeError:
            continue
        await asyncio.shield(task)
        return


async def _to_thread_until_complete(function: Any, *args: Any) -> Any:
    """Keep ownership until the real worker exits, even if its waiter is cancelled."""

    worker = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        try:
            await asyncio.shield(worker)
        except Exception:
            pass
        raise


async def _process_browser_pipeline(body: bytes) -> dict[str, Any]:
    decode_started_at = time.perf_counter()
    frame = await _to_thread_until_complete(decode_browser_frame, body)
    decode_ms = round((time.perf_counter() - decode_started_at) * 1000, 2)
    crop_started_at = time.perf_counter()
    frame, crop_metrics = await _to_thread_until_complete(crop_browser_frame_to_gg_window_with_metrics, frame)
    crop_ms = round((time.perf_counter() - crop_started_at) * 1000, 2)
    schedule_cropped_debug_frame_save(frame)
    parse_started_at = time.perf_counter()
    if not bool(crop_metrics.get("isRealClubGg")):
        snapshot = None
        backend_parse_ms = 0.0
    else:
        snapshot = await _to_thread_until_complete(
            parse_frame,
            frame,
            get_cached_calibration(),
            FAST_GG_READER,
            {**crop_metrics, "source": crop_metrics.get("cropSource")},
        )
        backend_parse_ms = round((time.perf_counter() - parse_started_at) * 1000, 2)
    return {
        "snapshot": snapshot,
        "cropMetrics": crop_metrics,
        "decodeMs": decode_ms,
        "cropMs": crop_ms,
        "parseMs": backend_parse_ms,
    }


async def _capture_reader_pipeline(capture: ScreenCapture, calibration: dict[str, Any]) -> GgTableSnapshot | None:
    frame = await _to_thread_until_complete(capture.grab)
    window_metadata = {
        **(capture.last_window or {}),
        "source": capture.last_source,
        "captureSource": capture.last_source,
        "captureWarning": capture.last_capture_warning,
        "captureDiagnostics": dict(capture.last_capture_diagnostics),
    }
    snapshot = await _to_thread_until_complete(
        parse_frame,
        frame,
        calibration,
        FAST_GG_READER,
        window_metadata,
    )
    if snapshot is not None:
        snapshot.metrics["captureSource"] = capture.last_source
        snapshot.metrics["captureDiagnostics"] = dict(capture.last_capture_diagnostics)
        if capture.last_capture_warning:
            snapshot.metrics["captureWarning"] = capture.last_capture_warning
    return snapshot


@app.post("/api/gg-reader/parse-frame")
async def parse_browser_frame(request: Request, seq: int | None = None) -> dict[str, Any]:
    loop_started_at = time.perf_counter()
    server_received_at = int(time.time() * 1000)
    generation = _reader_session_generation
    if not _browser_session_is_current(generation):
        reason = "reader-not-running" if not reader_state.running else "capture-mode-not-browser"
        return _dropped_browser_frame_response(
            seq=seq,
            server_received_at=server_received_at,
            frame_bytes=0,
            reason=reason,
        )

    body = await request.body()
    frame_bytes = len(body)
    if not _browser_session_is_current(generation):
        return _dropped_browser_frame_response(
            seq=seq,
            server_received_at=server_received_at,
            frame_bytes=frame_bytes,
            reason="session-stale",
        )
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

    sequence_rejection = _claim_browser_frame_sequence(seq, generation)
    if sequence_rejection is not None:
        if _browser_session_is_current(generation):
            reader_state.framesDropped += 1
        return _dropped_browser_frame_response(
            seq=seq,
            server_received_at=server_received_at,
            frame_bytes=frame_bytes,
            reason=sequence_rejection,
        )

    # FastGgReader is stateful and internally serialized. Letting every HTTP
    # request wait on its lock creates an ever-growing queue of obsolete
    # frames. Drop while busy and return the latest stable state instead.
    if _reader_pipeline_busy():
        reader_state.framesDropped += 1
        return _dropped_browser_frame_response(
            seq=seq,
            server_received_at=server_received_at,
            frame_bytes=frame_bytes,
            reason="reader-busy",
        )
    try:
        pipeline_task = _start_reader_pipeline(_process_browser_pipeline(body))
        pipeline_result = await asyncio.shield(pipeline_task)
        snapshot = pipeline_result["snapshot"]
        crop_metrics = pipeline_result["cropMetrics"]
        decode_ms = float(pipeline_result["decodeMs"])
        crop_ms = float(pipeline_result["cropMs"])
        backend_parse_ms = float(pipeline_result["parseMs"])
    except Exception as exc:
        if not _browser_session_is_current(generation):
            return _dropped_browser_frame_response(
                seq=seq,
                server_received_at=server_received_at,
                frame_bytes=frame_bytes,
                reason="session-stale",
            )
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

    if not _browser_session_is_current(generation):
        return _dropped_browser_frame_response(
            seq=seq,
            server_received_at=server_received_at,
            frame_bytes=frame_bytes,
            reason="session-stale",
        )

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
            "observationAccepted": True,
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
    data["normalizedState"] = build_normalized_state(snapshot, metrics)
    data["events"] = events
    data["observationAccepted"] = True
    return data


def _dropped_browser_frame_response(
    *,
    seq: int | None,
    server_received_at: int,
    frame_bytes: int,
    reason: str,
) -> dict[str, Any]:
    return {
        "type": "status",
        "status": "stale" if reason in {"session-stale", "duplicate-seq", "out-of-order-seq"} else "dropped",
        "message": "GG frame was not accepted",
        "clearTable": False,
        "confidence": 0,
        "captureSource": "browser",
        "frameSeq": seq,
        "serverReceivedAt": server_received_at,
        "frameBytes": frame_bytes,
        "frameDropped": True,
        "dropReason": reason,
        "observationAccepted": False,
        "events": [],
    }


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
        "captureSource": capture_source,
        "selectedWindow": captured_window,
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
        "captureWarning": capture.last_capture_warning,
        "captureDiagnostics": dict(capture.last_capture_diagnostics),
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
        "framesDropped": reader_state.framesDropped,
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


@app.get("/api/gg-reader/debug/last-snapshot")
async def get_debug_last_snapshot() -> dict[str, Any]:
    detailed = await get_debug_last_snapshot_detailed()
    detailed["rawFramePath"] = str(DEBUG_FRAME_PATH)
    detailed["croppedFramePath"] = str(DEBUG_CROPPED_FRAME_PATH)
    detailed["roiOverlayPath"] = str(DEBUG_ROI_OVERLAY_PATH)
    detailed["fieldCropsPath"] = str(DEBUG_FIELD_CROPS_DIR)
    return detailed


@app.websocket("/ws/gg-reader")
async def gg_reader_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    subscriber_id, delivery_queue = _register_native_subscriber()
    capture: ScreenCapture | None = None
    capture_generation: int | None = None
    calibration: dict[str, Any] = {}
    owned_pipeline_task: asyncio.Task[Any] | None = None
    try:
        while True:
            loop_started_at = time.perf_counter()
            if not reader_state.running or reader_config.captureMode == "browser":
                await asyncio.sleep(0.1)
                continue

            generation = _reader_session_generation
            target_interval = target_reader_interval_seconds(reader_config.fps)
            if _is_native_capture_owner(subscriber_id):
                if reader_config.profile == "mock":
                    snapshot = load_mock_snapshot()
                    snapshot, events = enrich_snapshot(snapshot)
                    reader_state.lastSnapshotAt = snapshot.timestamp
                    data = snapshot.model_dump()
                    data["events"] = events
                    _publish_native_payload(generation, data)
                else:
                    if capture_generation != generation:
                        if capture is not None:
                            capture.close()
                        capture = ScreenCapture(
                            monitor_index=reader_config.monitorIndex,
                            debug=reader_config.debug,
                            capture_mode=reader_config.captureMode,
                        )
                        capture_generation = generation
                        calibration = get_cached_calibration()

                    if _reader_pipeline_busy():
                        elapsed = time.perf_counter() - loop_started_at
                        await asyncio.sleep(max(0.01, target_interval - elapsed))
                        continue
                    try:
                        assert capture is not None
                        owned_pipeline_task = _start_reader_pipeline(
                            _capture_reader_pipeline(capture, calibration)
                        )
                        snapshot = await asyncio.shield(owned_pipeline_task)
                        owned_pipeline_task = None
                        if not _reader_session_is_current(generation):
                            continue
                    except Exception as exc:
                        if not _reader_session_is_current(generation):
                            continue
                        server_received_at = int(time.time() * 1000)
                        _publish_native_payload(generation, {
                            "type": "status",
                            "status": "warning",
                            "message": f"לא ניתן לצלם את Monitor {reader_config.monitorIndex}: {exc}",
                            "clearTable": False,
                            "fatal": False,
                            "confidence": 0,
                            "serverReceivedAt": server_received_at,
                        })
                    else:
                        if snapshot is None:
                            server_received_at = int(time.time() * 1000)
                            _publish_native_payload(generation, {
                                "type": "status",
                                "status": "waiting",
                                "message": "מחובר, ממתין לזיהוי שולחן GG",
                                "clearTable": False,
                                "calibrationVerified": bool(calibration.get("verified")),
                                "confidence": 0,
                                "serverReceivedAt": server_received_at,
                                **last_crop_metrics,
                            })
                        else:
                            snapshot, events = enrich_snapshot(snapshot)
                            crop_metrics = _extract_crop_metrics(snapshot.metrics)
                            if crop_metrics:
                                last_crop_metrics.clear()
                                last_crop_metrics.update(crop_metrics)
                            reader_state.lastSnapshotAt = snapshot.timestamp
                            data = snapshot.model_dump()
                            data["captureSource"] = capture.last_source
                            data["window"] = capture.last_window
                            data["serverReceivedAt"] = int(time.time() * 1000)
                            data["frameMs"] = round((time.perf_counter() - loop_started_at) * 1000, 2)
                            metrics = FAST_GG_READER.get_metrics()
                            metrics["readerParseMs"] = metrics.get("parseMs")
                            metrics["parseMs"] = data["frameMs"]
                            data.update(metrics)
                            data["normalizedState"] = build_normalized_state(snapshot, metrics)
                            data["events"] = events
                            reader_state.framesRead += 1
                            reader_state.lastFrameMs = data["frameMs"]
                            reader_state.captureSource = capture.last_source
                            _publish_native_payload(generation, data)

            data = await _receive_native_payload(delivery_queue, timeout=max(0.05, target_interval))
            if data is not None and _reader_session_is_current(generation):
                await websocket.send_json(data)
            elapsed = time.perf_counter() - loop_started_at
            if _is_native_capture_owner(subscriber_id):
                await asyncio.sleep(max(0.0, target_interval - elapsed))
    except WebSocketDisconnect:
        return
    finally:
        if owned_pipeline_task is not None and not owned_pipeline_task.done():
            try:
                await asyncio.shield(owned_pipeline_task)
            except (asyncio.CancelledError, Exception):
                pass
        # Release ownership only after the stateful capture pipeline has fully
        # exited, so the elected successor can never overlap it.
        _unregister_native_subscriber(subscriber_id)
        if capture is not None:
            capture.close()
