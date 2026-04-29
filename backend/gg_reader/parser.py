from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from .models import GgCard, GgSeat, GgTableSnapshot
from .ocr import read_amount, read_card, read_name


MOCK_SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "mock" / "gg_snapshot_example.json"
MIN_FIELD_CONFIDENCE = 0.75


def load_mock_snapshot() -> GgTableSnapshot:
    data: dict[str, Any] = json.loads(MOCK_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    data["timestamp"] = int(time.time() * 1000)
    return GgTableSnapshot.model_validate(data)


def parse_frame(frame: np.ndarray, calibration: dict[str, Any]) -> GgTableSnapshot | None:
    if not calibration.get("verified"):
        return None
    if not calibration.get("seatRois") or not calibration.get("boardRois"):
        return None

    visible_ids: set[str] = set()
    pot, pot_confidence, _raw_pot = read_amount(crop_roi(frame, calibration, calibration.get("potRoi", {})))
    board = parse_board(frame, calibration, visible_ids)
    seats = parse_seats(frame, calibration, visible_ids)
    if not board and not any(seat.active for seat in seats):
        return None

    dealer_index = detect_dealer_index(frame, calibration, seats)
    return GgTableSnapshot(
        timestamp=int(time.time() * 1000),
        tableType="9max" if len(seats) > 6 else "6max",
        street=street_from_board(board),
        pot=pot if pot_confidence >= MIN_FIELD_CONFIDENCE else 0,
        dealerSeatIndex=dealer_index,
        heroSeatIndex=0,
        board=board,
        seats=seats,
        confidence=estimate_snapshot_confidence([pot_confidence, *[seat.confidence for seat in seats]]),
    )


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

        seats.append(GgSeat(
            physicalSeatIndex=index,
            active=active,
            name=name if name_confidence >= 0.45 else None,
            stack=stack if stack_confidence >= MIN_FIELD_CONFIDENCE else 0,
            currentBet=bet if bet_confidence >= MIN_FIELD_CONFIDENCE else 0,
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
