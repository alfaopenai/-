from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np

from .models import GgCard, GgSeat, GgTableSnapshot
from .ocr import read_amount, read_card, read_name
from .table_crop import detect_clubgg_table_crop


MOCK_SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "mock" / "gg_snapshot_example.json"
MIN_FIELD_CONFIDENCE = 0.75
OCR_REFRESH_SECONDS = 1.2
STACK_OCR_REFRESH_SECONDS = 2.0
NAME_OCR_REFRESH_SECONDS = 4.0
BET_OCR_REFRESH_SECONDS = 0.7
ACTION_OCR_REFRESH_SECONDS = 2.0
_OCR_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="gg-reader-ocr")
_OCR_LOCK = Lock()
_OCR_CACHE: dict[str, dict[str, Any]] = {}


def _warm_ocr() -> None:
    read_amount(np.zeros((28, 90, 3), dtype=np.uint8))


_OCR_EXECUTOR.submit(_warm_ocr)
def load_mock_snapshot() -> GgTableSnapshot:
    data: dict[str, Any] = json.loads(MOCK_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    data["timestamp"] = int(time.time() * 1000)
    return GgTableSnapshot.model_validate(data)


def parse_frame(
    frame: np.ndarray,
    calibration: dict[str, Any],
    fast_reader: Any | None = None,
) -> GgTableSnapshot | None:
    crop_result = detect_clubgg_table_crop(frame)
    frame_for_reader = crop_result.cropped_frame
    crop_metrics = {
        "inputFrameWidth": int(frame.shape[1]) if frame is not None and frame.ndim >= 2 else 0,
        "inputFrameHeight": int(frame.shape[0]) if frame is not None and frame.ndim >= 2 else 0,
        **crop_result.metrics(),
    }
    if fast_reader is not None:
        fast_snapshot = fast_reader.parse(frame_for_reader)
        if fast_snapshot and fast_snapshot.confidence >= 0.58:
            fast_snapshot.metrics = {**fast_snapshot.metrics, **crop_metrics}
            return fast_snapshot

    auto_snapshot = parse_auto_gg_frame(frame_for_reader)
    if auto_snapshot:
        auto_snapshot.metrics = {**auto_snapshot.metrics, **crop_metrics}
        return auto_snapshot

    if not calibration.get("verified"):
        return None
    if not calibration.get("seatRois") or not calibration.get("boardRois"):
        return None

    visible_ids: set[str] = set()
    pot, pot_confidence, _raw_pot = read_amount(crop_roi(frame_for_reader, calibration, calibration.get("potRoi", {})))
    board = parse_board(frame_for_reader, calibration, visible_ids)
    seats = parse_seats(frame_for_reader, calibration, visible_ids)
    if not board and not any(seat.active for seat in seats):
        return None

    dealer_index = detect_dealer_index(frame_for_reader, calibration, seats)
    confidence = estimate_snapshot_confidence([
        0.90 if board else 0.0,
        pot_confidence,
        *[seat.confidence for seat in seats if seat.active],
    ])
    if board or sum(1 for seat in seats if seat.active) >= 2:
        confidence = max(confidence, 0.91)

    snapshot = GgTableSnapshot(
        timestamp=int(time.time() * 1000),
        tableType="9max" if len(seats) > 6 else "6max",
        street=street_from_board(board),
        pot=pot if pot_confidence >= MIN_FIELD_CONFIDENCE else 0,
        activePlayerCount=sum(1 for seat in seats if seat.active),
        dealerSeatIndex=dealer_index,
        heroSeatIndex=0,
        board=board,
        seats=seats,
        confidence=confidence,
    )
    snapshot.metrics = crop_metrics
    return snapshot


AUTO_SEAT_ROIS: dict[int, dict[str, Any]] = {
    0: {
        "name": (0.44, 0.205, 0.14, 0.040),
        "stack": (0.45, 0.245, 0.13, 0.040),
        "bet": (0.380, 0.275, 0.100, 0.060),
        "cards": [(0.45, 0.120, 0.055, 0.095), (0.505, 0.120, 0.055, 0.095)],
    },
    1: {
        "name": (0.72, 0.250, 0.18, 0.045),
        "stack": (0.73, 0.295, 0.14, 0.045),
        "bet": (0.760, 0.500, 0.100, 0.060),
        "cards": [(0.72, 0.155, 0.055, 0.095), (0.775, 0.155, 0.055, 0.095)],
    },
    2: {
        "name": (0.850, 0.505, 0.145, 0.045),
        "stack": (0.865, 0.555, 0.130, 0.045),
        "bet": (0.760, 0.500, 0.100, 0.060),
        "cards": [(0.862, 0.420, 0.055, 0.105), (0.915, 0.420, 0.055, 0.105)],
    },
    3: {
        "name": (0.730, 0.790, 0.145, 0.045),
        "stack": (0.735, 0.820, 0.135, 0.050),
        "bet": (0.665, 0.610, 0.100, 0.060),
        "cards": [(0.735, 0.670, 0.055, 0.115), (0.790, 0.670, 0.055, 0.115)],
    },
    4: {
        "name": (0.430, 0.855, 0.170, 0.050),
        "stack": (0.430, 0.905, 0.160, 0.050),
        "bet": (0.455, 0.610, 0.100, 0.060),
        "cards": [(0.440, 0.700, 0.055, 0.115), (0.495, 0.700, 0.055, 0.115)],
    },
    5: {
        "name": (0.170, 0.785, 0.170, 0.045),
        "stack": (0.180, 0.830, 0.140, 0.050),
        "bet": (0.240, 0.610, 0.100, 0.060),
        "cards": [(0.185, 0.675, 0.055, 0.115), (0.240, 0.675, 0.055, 0.115)],
    },
    6: {
        "name": (0.005, 0.535, 0.180, 0.045),
        "stack": (0.015, 0.575, 0.150, 0.050),
        "bet": (0.135, 0.500, 0.100, 0.060),
        "cards": [(0.025, 0.420, 0.055, 0.115), (0.080, 0.420, 0.055, 0.115)],
    },
    7: {
        "name": (0.055, 0.705, 0.170, 0.045),
        "stack": (0.065, 0.745, 0.145, 0.050),
        "bet": (0.160, 0.610, 0.100, 0.060),
        "cards": [(0.070, 0.610, 0.055, 0.115), (0.125, 0.610, 0.055, 0.115)],
    },
    8: {
        "name": (0.100, 0.295, 0.170, 0.045),
        "stack": (0.110, 0.325, 0.145, 0.050),
        "bet": (0.240, 0.315, 0.100, 0.060),
        "cards": [(0.115, 0.215, 0.055, 0.115), (0.170, 0.215, 0.055, 0.115)],
    },
}


def parse_auto_gg_frame(frame: np.ndarray) -> GgTableSnapshot | None:
    if not looks_like_gg_frame(frame):
        return None

    visible_ids: set[str] = set()
    pot, pot_confidence, _raw_pot = read_amount_cached(
        frame,
        "pot",
        (0.43, 0.335, 0.18, 0.060),
        interval=OCR_REFRESH_SECONDS,
    )
    board = parse_auto_board(frame, visible_ids)
    seats = parse_auto_seats(frame, visible_ids)

    if not board and not any(seat.active for seat in seats):
        return None

    dealer_index = detect_auto_dealer_index(frame, seats)
    confidence = estimate_snapshot_confidence([
        0.90 if board else 0.0,
        pot_confidence,
        *[seat.confidence for seat in seats if seat.active],
    ])
    if board or sum(1 for seat in seats if seat.active) >= 2:
        confidence = max(confidence, 0.91)

    return GgTableSnapshot(
        timestamp=int(time.time() * 1000),
        tableType="9max",
        street=street_from_board(board),
        pot=pot if pot_confidence >= 0.70 else 0,
        activePlayerCount=sum(1 for seat in seats if seat.active),
        dealerSeatIndex=dealer_index,
        heroSeatIndex=4 if len(seats) > 4 and seats[4].active else None,
        board=board,
        seats=seats,
        confidence=confidence,
    )


def read_amount_cached(
    frame: np.ndarray,
    key: str,
    roi: tuple[float, float, float, float],
    *,
    interval: float,
) -> tuple[float, float, str]:
    now = time.monotonic()
    with _OCR_LOCK:
        entry = _OCR_CACHE.setdefault(key, {
            "value": 0.0,
            "confidence": 0.0,
            "raw": "",
            "requested_at": 0.0,
            "future": None,
        })
        future: Future[tuple[float, float, str]] | None = entry.get("future")
        if future and future.done():
            try:
                value, confidence, raw = future.result()
            except Exception:
                value, confidence, raw = 0.0, 0.0, ""
            if confidence > 0 or value > 0:
                candidate = entry.get("candidate")
                candidate_confidence = float(entry.get("candidate_confidence") or 0)
                previous_value = float(entry.get("value") or 0.0)
                is_stable_candidate = candidate is not None and is_close_amount(float(candidate), value)
                is_small_first_value = previous_value == 0 and value > 0 and abs(value) < 1000
                is_close_to_previous = previous_value > 0 and is_close_amount(previous_value, value)
                is_confident_first_value = previous_value == 0 and value > 0 and confidence >= 0.80
                if is_stable_candidate or is_close_to_previous or is_confident_first_value or (confidence >= 0.9 and is_small_first_value):
                    entry["value"] = value
                    entry["confidence"] = max(confidence, candidate_confidence)
                    entry["raw"] = raw
                    entry["candidate"] = None
                    entry["candidate_confidence"] = 0.0
                else:
                    entry["candidate"] = value
                    entry["candidate_confidence"] = confidence
                    entry["candidate_raw"] = raw
            entry["future"] = None

        if entry.get("future") is None and now - float(entry.get("requested_at") or 0) >= interval:
            crop = crop_normalized(frame, roi).copy()
            entry["future"] = _OCR_EXECUTOR.submit(read_amount, crop)
            entry["requested_at"] = now

        return float(entry.get("value") or 0.0), float(entry.get("confidence") or 0.0), str(entry.get("raw") or "")


def read_name_cached(
    frame: np.ndarray,
    key: str,
    roi: tuple[float, float, float, float],
    *,
    interval: float,
) -> tuple[str, float]:
    now = time.monotonic()
    with _OCR_LOCK:
        entry = _OCR_CACHE.setdefault(key, {
            "value": "",
            "confidence": 0.0,
            "requested_at": 0.0,
            "future": None,
        })
        future: Future[tuple[str, float]] | None = entry.get("future")
        if future and future.done():
            try:
                value, confidence = future.result()
            except Exception:
                value, confidence = "", 0.0
            cleaned = clean_player_name(value)
            if cleaned and confidence >= 0.20:
                entry["value"] = cleaned
                entry["confidence"] = confidence
            entry["future"] = None

        if entry.get("future") is None and now - float(entry.get("requested_at") or 0) >= interval:
            crop = crop_normalized(frame, roi).copy()
            entry["future"] = _OCR_EXECUTOR.submit(read_name, crop)
            entry["requested_at"] = now

        return str(entry.get("value") or ""), float(entry.get("confidence") or 0.0)


def read_action_cached(
    frame: np.ndarray,
    key: str,
    roi: tuple[float, float, float, float],
    *,
    interval: float,
) -> tuple[str, float]:
    now = time.monotonic()
    with _OCR_LOCK:
        entry = _OCR_CACHE.setdefault(key, {
            "value": "none",
            "confidence": 0.0,
            "requested_at": 0.0,
            "future": None,
        })
        future: Future[tuple[str, float]] | None = entry.get("future")
        if future and future.done():
            try:
                value, confidence = future.result()
            except Exception:
                value, confidence = "", 0.0
            action = normalize_action_text(value)
            if action != "none" and confidence >= 0.20:
                entry["value"] = action
                entry["confidence"] = confidence
            entry["future"] = None

        if entry.get("future") is None and now - float(entry.get("requested_at") or 0) >= interval:
            crop = crop_normalized(frame, roi).copy()
            entry["future"] = _OCR_EXECUTOR.submit(read_name, crop)
            entry["requested_at"] = now

        return str(entry.get("value") or "none"), float(entry.get("confidence") or 0.0)


def is_close_amount(left: float, right: float) -> bool:
    return abs(left - right) <= max(0.15, abs(left), abs(right)) * 0.05


def looks_like_gg_frame(frame: np.ndarray) -> bool:
    try:
        import cv2
    except Exception:
        return False
    if frame.size == 0 or frame.ndim < 3:
        return False
    channels = frame[:, :, :3]
    hsv = cv2.cvtColor(channels, cv2.COLOR_BGR2HSV)
    green_mask = cv2.inRange(hsv, np.array([35, 45, 35]), np.array([95, 255, 230]))
    green_ratio = float((green_mask > 0).mean())
    dark_ratio = float((cv2.cvtColor(channels, cv2.COLOR_BGR2GRAY) < 45).mean())
    return green_ratio > 0.10 and dark_ratio > 0.18


def parse_auto_board(frame: np.ndarray, visible_ids: set[str]) -> list[GgCard]:
    try:
        import cv2
    except Exception:
        return []

    height, width = frame.shape[:2]
    channels = frame[:, :, :3]
    mask = cv2.inRange(channels, np.array([135, 135, 135]), np.array([255, 255, 255]))
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rects: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, rect_width, rect_height = cv2.boundingRect(contour)
        if rect_width < width * 0.035 or rect_width > width * 0.10:
            continue
        if rect_height < height * 0.08 or rect_height > height * 0.18:
            continue
        if not (height * 0.32 <= y <= height * 0.62):
            continue
        if not (width * 0.20 <= x <= width * 0.78):
            continue
        aspect = rect_width / max(1, rect_height)
        if not (0.48 <= aspect <= 0.90):
            continue
        rects.append((x, y, rect_width, rect_height))

    merged = merge_nearby_rects(rects)
    cards: list[GgCard] = []
    for x, y, rect_width, rect_height in sorted(merged, key=lambda rect: rect[0])[:5]:
        crop = frame[y:y + rect_height, x:x + rect_width]
        card_data = read_card(crop)
        if not card_data.get("rank") or not card_data.get("suit"):
            continue
        card = GgCard(
            rank=str(card_data["rank"]),
            suit=str(card_data["suit"]),
            visible=True,
            confidence=float(card_data.get("confidence") or 0.8),
        )
        card_id = card_id_from_card(card)
        if card_id in visible_ids:
            return []
        visible_ids.add(card_id)
        cards.append(card)
    return cards


def parse_auto_seats(frame: np.ndarray, visible_ids: set[str]) -> list[GgSeat]:
    seats: list[GgSeat] = []
    should_read_names = os.environ.get("GG_READER_READ_NAMES", "1").lower() in {"1", "true", "yes"}
    should_read_actions = os.environ.get("GG_READER_READ_ACTIONS", "1").lower() in {"1", "true", "yes"}
    for index in range(9):
        rois = AUTO_SEAT_ROIS[index]
        stack_roi = crop_normalized(frame, rois["stack"])
        cyan_signal = estimate_cyan_signal(stack_roi)
        hole_cards: list[GgCard] = []
        for card_roi in rois["cards"]:
            card_data = read_card(crop_normalized(frame, card_roi))
            confidence = float(card_data.get("confidence") or 0)
            if confidence < 0.70:
                continue
            if card_data.get("hidden"):
                hole_cards.append(GgCard(hidden=True, visible=False, display="X", confidence=confidence))
                continue
            if card_data.get("rank") and card_data.get("suit"):
                if confidence < 0.90:
                    continue
                card = GgCard(
                    rank=str(card_data["rank"]),
                    suit=str(card_data["suit"]),
                    visible=True,
                    confidence=confidence,
                )
                card_id = card_id_from_card(card)
                if card_id in visible_ids:
                    continue
                visible_ids.add(card_id)
                hole_cards.append(card)

        stack = 0.0
        stack_confidence = 0.0
        name = ""
        name_confidence = 0.0
        likely_active = bool(cyan_signal > 0.025 or hole_cards)
        if likely_active:
            stack, stack_confidence, _raw_stack = read_amount_cached(
                frame,
                f"seat-{index}-stack",
                rois["stack"],
                interval=STACK_OCR_REFRESH_SECONDS,
            )
            current_bet, bet_confidence, _raw_bet = read_amount_cached(
                frame,
                f"seat-{index}-bet",
                rois["bet"],
                interval=BET_OCR_REFRESH_SECONDS,
            )
            if should_read_actions and stack_confidence > 0:
                detected_action, action_confidence = read_action_cached(
                    frame,
                    f"seat-{index}-action",
                    rois.get("action", rois["bet"]),
                    interval=ACTION_OCR_REFRESH_SECONDS,
                )
            else:
                detected_action = "none"
                action_confidence = 0.0
            if should_read_names and stack_confidence > 0:
                name, name_confidence = read_name_cached(
                    frame,
                    f"seat-{index}-name",
                    rois["name"],
                    interval=NAME_OCR_REFRESH_SECONDS,
                )
        else:
            current_bet = 0.0
            bet_confidence = 0.0
            detected_action = "none"
            action_confidence = 0.0
        active = bool(
            stack_confidence >= 0.70
            or bet_confidence >= 0.70
            or cyan_signal > 0.025
            or hole_cards
        )
        if active and (not name or name_confidence < 0.25):
            name = ""
            name_confidence = 0.0
        confidence = estimate_snapshot_confidence([
            stack_confidence,
            min(0.85, cyan_signal * 12),
            name_confidence,
            bet_confidence,
            *[card.confidence for card in hole_cards],
        ])
        current_bet = current_bet if bet_confidence >= 0.70 else 0.0
        action = detected_action if action_confidence >= 0.25 else ("bet" if current_bet > 0 else "none")
        action_source = "label_ocr" if action_confidence >= 0.25 and detected_action != "none" else ("visible_bet" if current_bet > 0 else "none")
        action_amount = current_bet if action in {"bet", "raise", "call", "all-in"} else 0.0
        status = "folded" if action == "fold" else ("active" if active else "empty")
        if action == "fold":
            hole_cards = []
        seats.append(GgSeat(
            physicalSeatIndex=index,
            active=active,
            name=clean_player_name(name) if active else "",
            nameConfidence=name_confidence,
            stack=stack if stack_confidence >= 0.70 else 0,
            stackConfidence=stack_confidence,
            currentBet=current_bet,
            betConfidence=bet_confidence,
            action=action,
            actionAmount=action_amount,
            actionConfidence=action_confidence if action != "none" else (bet_confidence if current_bet > 0 else 0),
            actionSource=action_source,
            status=status,
            isHero=index == 4 and active,
            holeCards=hole_cards,
            confidence=max(confidence, 0.75 if active else 0.9),
        ))
    return seats


def crop_normalized(frame: np.ndarray, roi: tuple[float, float, float, float]) -> np.ndarray:
    height, width = frame.shape[:2]
    x, y, roi_width, roi_height = roi
    left = max(0, min(width, int(round(x * width))))
    top = max(0, min(height, int(round(y * height))))
    right = max(left, min(width, int(round((x + roi_width) * width))))
    bottom = max(top, min(height, int(round((y + roi_height) * height))))
    return frame[top:bottom, left:right]


def merge_nearby_rects(rects: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    merged: list[tuple[int, int, int, int]] = []
    for rect in sorted(rects, key=lambda item: (item[1], item[0])):
        x, y, width, height = rect
        existing_index = None
        for index, existing in enumerate(merged):
            ex, ey, ew, eh = existing
            if abs(x - ex) < max(width, ew) * 0.35 and abs(y - ey) < max(height, eh) * 0.35:
                existing_index = index
                break
        if existing_index is None:
            merged.append(rect)
            continue
        ex, ey, ew, eh = merged[existing_index]
        left = min(x, ex)
        top = min(y, ey)
        right = max(x + width, ex + ew)
        bottom = max(y + height, ey + eh)
        merged[existing_index] = (left, top, right - left, bottom - top)
    return merged


def estimate_cyan_signal(image: np.ndarray) -> float:
    if image.size == 0 or image.ndim < 3:
        return 0.0
    channels = image[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    mask = (blue > 95) & (green > 95) & (red < 125) & ((blue - red) > 35) & ((green - red) > 35)
    return float(mask.mean())


def detect_auto_dealer_index(frame: np.ndarray, seats: list[GgSeat]) -> int:
    try:
        import cv2
    except Exception:
        active = [seat.physicalSeatIndex for seat in seats if seat.active]
        return active[0] if active else 0

    channels = frame[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    mask = ((red > 150) & (green > 115) & (blue < 95)).astype(np.uint8) * 255
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    height, width = frame.shape[:2]
    dealer_points: list[tuple[float, float]] = []
    for contour in contours:
        x, y, rect_width, rect_height = cv2.boundingRect(contour)
        if rect_width < width * 0.015 or rect_height < height * 0.015:
            continue
        if rect_width > width * 0.07 or rect_height > height * 0.07:
            continue
        dealer_points.append((x + rect_width / 2, y + rect_height / 2))
    if not dealer_points:
        active = [seat.physicalSeatIndex for seat in seats if seat.active]
        return active[0] if active else 0

    seat_centers = {
        0: (0.50 * width, 0.23 * height),
        1: (0.79 * width, 0.24 * height),
        2: (0.91 * width, 0.52 * height),
        3: (0.78 * width, 0.76 * height),
        4: (0.50 * width, 0.86 * height),
        5: (0.20 * width, 0.75 * height),
        6: (0.08 * width, 0.55 * height),
        7: (0.12 * width, 0.72 * height),
        8: (0.17 * width, 0.30 * height),
    }
    point = dealer_points[0]
    active_indexes = {seat.physicalSeatIndex for seat in seats if seat.active}
    return min(active_indexes or seat_centers.keys(), key=lambda index: distance(point, seat_centers[index]))


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def clean_player_name(name: str | None) -> str:
    if not name:
        return ""
    cleaned = str(name).replace("|", " ")
    cleaned = re.sub(r"[^0-9A-Za-z\u0590-\u05ff_. -]+", " ", cleaned)
    cleaned = " ".join(cleaned.split())
    cleaned = cleaned.strip(" -_{}[]()\\/")
    if len(cleaned) > 24:
        cleaned = cleaned[:24]
    return cleaned


def normalize_action_text(text: str | None) -> str:
    if not text:
        return "none"
    value = str(text).strip().lower()
    value = re.sub(r"[^a-z\u0590-\u05ff +'-]+", " ", value)
    value = " ".join(value.split())
    if not value:
        return "none"

    checks = {
        "check": "check",
        "checked": "check",
        "צק": "check",
        "צ'ק": "check",
        "fold": "fold",
        "folded": "fold",
        "פולד": "fold",
        "call": "call",
        "called": "call",
        "קול": "call",
        "bet": "bet",
        "bets": "bet",
        "הימור": "bet",
        "raise": "raise",
        "raises": "raise",
        "raised": "raise",
        "רייז": "raise",
        "all in": "all-in",
        "all-in": "all-in",
        "אול אין": "all-in",
    }
    for token, action in checks.items():
        if token in value:
            return action
    return "none"


def parse_board(frame: np.ndarray, calibration: dict[str, Any], visible_ids: set[str]) -> list[GgCard]:
    cards: list[GgCard] = []
    for roi in calibration.get("boardRois", []):
        card = parse_card_roi(frame, calibration, roi, allow_hidden=False)
        if not card:
            continue
        card_id = card_id_from_card(card)
        if card_id and card_id in visible_ids:
            return []
        if card_id:
            visible_ids.add(card_id)
        cards.append(card)
    return cards


def parse_seats(frame: np.ndarray, calibration: dict[str, Any], visible_ids: set[str]) -> list[GgSeat]:
    seats: list[GgSeat] = []
    seat_rois = calibration.get("seatRois", {})
    for raw_index, rois in sorted(seat_rois.items(), key=lambda item: int(item[0])):
        index = int(raw_index)
        name, name_confidence = read_name(crop_roi(frame, calibration, rois.get("name", {})))
        stack, stack_confidence, _raw_stack = read_amount(crop_roi(frame, calibration, rois.get("stack", {})))
        bet, bet_confidence, _raw_bet = read_amount(crop_roi(frame, calibration, rois.get("bet", {})))
        action_text, action_confidence = read_name(crop_roi(frame, calibration, rois.get("action", rois.get("bet", {}))))
        action = normalize_action_text(action_text)
        hole_cards: list[GgCard] = []

        for card_roi in rois.get("cards", []):
            card = parse_card_roi(frame, calibration, card_roi, allow_hidden=True)
            if not card:
                continue
            card_id = card_id_from_card(card)
            if card_id and card_id in visible_ids:
                return []
            if card_id:
                visible_ids.add(card_id)
            hole_cards.append(card)

        active = bool(
            (name and name_confidence >= 0.45)
            or stack_confidence >= MIN_FIELD_CONFIDENCE
            or bet_confidence >= MIN_FIELD_CONFIDENCE
            or hole_cards
        )
        confidence = estimate_snapshot_confidence([name_confidence, stack_confidence, bet_confidence, *[card.confidence for card in hole_cards]])
        if action == "fold":
            hole_cards = []

        parsed_action = action if action_confidence >= 0.25 else ("bet" if bet_confidence >= MIN_FIELD_CONFIDENCE and bet > 0 else "none")
        seats.append(GgSeat(
            physicalSeatIndex=index,
            active=active,
            name=name if name_confidence >= 0.45 else None,
            nameConfidence=name_confidence,
            stack=stack if stack_confidence >= MIN_FIELD_CONFIDENCE else 0,
            stackConfidence=stack_confidence,
            currentBet=bet if bet_confidence >= MIN_FIELD_CONFIDENCE else 0,
            betConfidence=bet_confidence,
            action=parsed_action,
            actionAmount=bet if bet_confidence >= MIN_FIELD_CONFIDENCE and bet > 0 else 0,
            actionConfidence=action_confidence,
            actionSource="label_ocr" if action_confidence >= 0.25 and action != "none" else ("visible_bet" if bet_confidence >= MIN_FIELD_CONFIDENCE and bet > 0 else "none"),
            status="folded" if action == "fold" else ("active" if active else "empty"),
            holeCards=hole_cards,
            confidence=confidence,
        ))
    return seats


def parse_card_roi(frame: np.ndarray, calibration: dict[str, Any], roi: dict[str, Any], *, allow_hidden: bool) -> GgCard | None:
    card_data = read_card(crop_roi(frame, calibration, roi))
    confidence = float(card_data.get("confidence") or 0)
    if confidence < MIN_FIELD_CONFIDENCE:
        return None
    if allow_hidden and card_data.get("hidden"):
        return GgCard(hidden=True, visible=False, display=str(card_data.get("display") or "X"), confidence=confidence)
    rank = card_data.get("rank")
    suit = card_data.get("suit")
    if rank and suit:
        return GgCard(rank=str(rank), suit=str(suit), visible=True, confidence=confidence)
    return None


def crop_roi(frame: np.ndarray, calibration: dict[str, Any], roi: dict[str, Any]) -> np.ndarray:
    if not roi:
        return frame[0:0, 0:0]
    frame_height, frame_width = frame.shape[:2]
    table_box = calibration.get("tableBox") or {"x": 0, "y": 0, "width": frame_width, "height": frame_height}
    table_x = float(table_box.get("x", 0))
    table_y = float(table_box.get("y", 0))
    table_width = float(table_box.get("width", frame_width) or frame_width)
    table_height = float(table_box.get("height", frame_height) or frame_height)

    x = float(roi.get("x", 0))
    y = float(roi.get("y", 0))
    width = float(roi.get("width", 0))
    height = float(roi.get("height", 0))
    if width <= 1 and height <= 1:
        x = table_x + x * table_width
        y = table_y + y * table_height
        width *= table_width
        height *= table_height

    left = max(0, min(frame_width, int(round(x))))
    top = max(0, min(frame_height, int(round(y))))
    right = max(left, min(frame_width, int(round(x + width))))
    bottom = max(top, min(frame_height, int(round(y + height))))
    return frame[top:bottom, left:right]


def detect_dealer_index(_frame: np.ndarray, _calibration: dict[str, Any], seats: list[GgSeat]) -> int:
    active_seats = [seat.physicalSeatIndex for seat in seats if seat.active]
    return active_seats[0] if active_seats else 0


def street_from_board(board: list[GgCard]) -> str:
    count = len([card for card in board if card.visible and not card.hidden])
    if count >= 5:
        return "river"
    if count == 4:
        return "turn"
    if count == 3:
        return "flop"
    if count == 0:
        return "preflop"
    return "unknown"


def card_id_from_card(card: GgCard) -> str:
    if card.hidden or not card.rank or not card.suit:
        return ""
    return f"{card.rank}{card.suit}".upper()


def estimate_snapshot_confidence(values: list[float]) -> float:
    confidences = [value for value in values if value > 0]
    if not confidences:
        return 0.0
    return max(0.0, min(1.0, sum(confidences) / len(confidences)))
