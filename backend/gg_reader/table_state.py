from __future__ import annotations

import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .models import GgSeat, GgTableSnapshot


PUBLISH_INTERVAL_SECONDS = 1.0
ACTION_HOLD_SECONDS = 1.8
NAME_ACCEPT_CONFIDENCE = 0.55
NAME_REPLACE_CONFIDENCE = 0.86
NAME_REPLACE_HITS = 2
NAME_VARIANT_SIMILARITY = 0.78
STACK_ACCEPT_CONFIDENCE = 0.50
STACK_REPLACE_CONFIDENCE = 0.92
STACK_REPLACE_HITS = 2


@dataclass
class _SeatState:
    empty_misses: int = 0
    no_card_misses: int = 0
    zero_bet_hits: int = 0
    last_action: str = "none"
    last_action_amount: float = 0.0
    last_action_until: float = 0.0


@dataclass
class _SeatPositionRecord:
    active: bool = False
    name: str = ""
    name_confidence: float = 0.0
    stack: float = 0.0
    stack_confidence: float = 0.0
    last_seen_at: float = 0.0
    updated_at: float = 0.0
    pending_name: str = ""
    pending_name_hits: int = 0
    pending_name_confidence: float = 0.0
    pending_stack: float = 0.0
    pending_stack_hits: int = 0
    pending_stack_confidence: float = 0.0


class TableStateStabilizer:
    """Field-level smoothing for noisy OCR snapshots.

    The fast reader may see several partial reads while OCR futures complete.
    This class keeps the last accepted table truth and only lets weak fields
    replace known values when they are either confident or repeated.
    """

    def __init__(self) -> None:
        self._stable: GgTableSnapshot | None = None
        self._seat_states: dict[int, _SeatState] = {}
        self._seat_database: dict[int, _SeatPositionRecord] = {}
        self._last_publish_at = 0.0
        self._last_metrics: dict[str, Any] = {}

    def stabilize(self, raw: GgTableSnapshot, *, now: float | None = None) -> GgTableSnapshot:
        current_time = time.monotonic() if now is None else now
        metrics: dict[str, Any] = {
            "stableCadenceMs": int(PUBLISH_INTERVAL_SECONDS * 1000),
            "fieldsHeld": [],
            "fieldsAccepted": [],
            "heldByCadence": False,
        }

        if self._stable is None:
            stable = raw.model_copy(deep=True)
            self._sanitize_placeholder_names(stable, metrics)
            self._apply_seat_database_to_snapshot(stable, current_time, metrics)
            metrics["initialStableSnapshot"] = True
            stable.metrics = {**raw.metrics, "stabilizer": metrics}
            self._stable = stable.model_copy(deep=True)
            self._last_publish_at = current_time
            self._last_metrics = metrics
            return stable

        previous = self._stable
        stable = raw.model_copy(deep=True)
        raw_by_index = {int(seat.physicalSeatIndex): seat for seat in raw.seats}
        previous_by_index = {int(seat.physicalSeatIndex): seat for seat in previous.seats}
        merged_seats: list[GgSeat] = []

        for index in sorted(set(raw_by_index) | set(previous_by_index)):
            raw_seat = raw_by_index.get(index)
            previous_seat = previous_by_index.get(index)
            if raw_seat is None:
                if previous_seat is not None:
                    merged_seats.append(previous_seat.model_copy(deep=True))
                    metrics["fieldsHeld"].append(f"seat-{index}")
                continue
            merged_seats.append(self._stabilize_seat(raw_seat, previous_seat, current_time, metrics))

        stable.seats = sorted(merged_seats, key=lambda seat: int(seat.physicalSeatIndex))
        self._apply_seat_database_to_snapshot(stable, current_time, metrics)
        stable.activePlayerCount = sum(1 for seat in stable.seats if seat.active)
        stable.pot = self._stable_amount(
            "pot",
            float(raw.pot or 0.0),
            _amount_confidence(raw, "pot"),
            float(previous.pot or 0.0),
            metrics,
            min_confidence=0.55,
        )
        if stable.pot != raw.pot:
            metrics["fieldsHeld"].append("pot")

        if not stable.board and previous.board and raw.street == previous.street:
            stable.board = [card.model_copy(deep=True) for card in previous.board]
            metrics["fieldsHeld"].append("board")

        if raw.dealerSeatIndex < 0 and previous.dealerSeatIndex >= 0:
            stable.dealerSeatIndex = previous.dealerSeatIndex
            metrics["fieldsHeld"].append("dealer")

        if current_time - self._last_publish_at < PUBLISH_INTERVAL_SECONDS:
            metrics["heldByCadence"] = True
        else:
            self._last_publish_at = current_time

        stable.metrics = {**raw.metrics, "stabilizer": metrics}
        self._stable = stable.model_copy(deep=True)
        self._last_metrics = metrics
        return stable

    def get_metrics(self) -> dict[str, Any]:
        return dict(self._last_metrics)

    def _stabilize_seat(
        self,
        raw: GgSeat,
        previous: GgSeat | None,
        now: float,
        metrics: dict[str, Any],
    ) -> GgSeat:
        index = int(raw.physicalSeatIndex)
        state = self._seat_states.setdefault(index, _SeatState())
        seat = raw.model_copy(deep=True)

        if not raw.active:
            state.empty_misses += 1
            if previous and previous.active and state.empty_misses < 2:
                held = previous.model_copy(deep=True)
                held.confidence = min(float(held.confidence or 0.0), 0.70)
                metrics["fieldsHeld"].append(f"seat-{index}-active")
                return held
            state.no_card_misses = 0
            state.zero_bet_hits = 0
            return seat

        state.empty_misses = 0
        self._sanitize_seat_name(seat, previous, metrics)
        self._stabilize_seat_amounts(seat, previous, state, metrics)
        self._stabilize_cards(seat, previous, state, metrics)
        self._stabilize_action(seat, previous, state, now, metrics)
        return seat

    def _sanitize_seat_name(self, seat: GgSeat, previous: GgSeat | None, metrics: dict[str, Any]) -> None:
        index = int(seat.physicalSeatIndex)
        if _is_placeholder_name(seat.name):
            seat.name = ""
            seat.nameConfidence = 0.0
            metrics["fieldsHeld"].append(f"seat-{index}-name-placeholder")
        if seat.name and float(seat.nameConfidence or 0.0) >= 0.20:
            metrics["fieldsAccepted"].append(f"seat-{index}-name")
            return
        if previous and previous.active and previous.name and not _is_placeholder_name(previous.name):
            seat.name = previous.name
            seat.nameConfidence = min(float(previous.nameConfidence or 0.5), 0.55)
            metrics["fieldsHeld"].append(f"seat-{index}-name")
        else:
            seat.name = ""
            seat.nameConfidence = 0.0

    def _stabilize_seat_amounts(
        self,
        seat: GgSeat,
        previous: GgSeat | None,
        state: _SeatState,
        metrics: dict[str, Any],
    ) -> None:
        index = int(seat.physicalSeatIndex)
        previous_stack = float(previous.stack or 0.0) if previous else 0.0
        stack_confidence = float(seat.stackConfidence or 0.0)
        if previous_stack > 0 and not _amount_is_sane(previous_stack, float(seat.stack or 0.0), stack_confidence):
            seat.stack = previous_stack
            seat.stackConfidence = min(float(previous.stackConfidence or 0.55), 0.60) if previous else 0.55
            metrics["fieldsHeld"].append(f"seat-{index}-stack")

        previous_bet = float(previous.currentBet or 0.0) if previous else 0.0
        bet_confidence = float(seat.betConfidence or 0.0)
        if float(seat.currentBet or 0.0) == 0.0 and previous_bet > 0 and bet_confidence >= 0.90:
            state.zero_bet_hits += 1
            if state.zero_bet_hits < 2:
                seat.currentBet = previous_bet
                seat.committed = max(float(seat.committed or 0.0), previous_bet)
                seat.betConfidence = min(float(previous.betConfidence or 0.55), 0.62) if previous else 0.55
                metrics["fieldsHeld"].append(f"seat-{index}-bet")
        else:
            state.zero_bet_hits = 0

    def _stabilize_cards(
        self,
        seat: GgSeat,
        previous: GgSeat | None,
        state: _SeatState,
        metrics: dict[str, Any],
    ) -> None:
        index = int(seat.physicalSeatIndex)
        if seat.holeCards:
            state.no_card_misses = 0
            return
        had_cards = bool(previous and previous.active and previous.holeCards)
        if not had_cards:
            return
        if seat.action == "fold" or seat.status == "folded":
            state.no_card_misses = 2
            seat.status = "folded"
            seat.action = "fold"
            seat.actionConfidence = max(float(seat.actionConfidence or 0.0), 0.90)
            seat.actionSource = seat.actionSource or "cards_disappeared"
            return
        state.no_card_misses += 1
        if state.no_card_misses < 2:
            seat.holeCards = [card.model_copy(deep=True) for card in previous.holeCards] if previous else []
            metrics["fieldsHeld"].append(f"seat-{index}-cards")
            return
        seat.status = "folded"
        seat.action = "fold"
        seat.actionConfidence = max(float(seat.actionConfidence or 0.0), 0.88)
        seat.actionSource = seat.actionSource or "cards_disappeared"

    def _stabilize_action(
        self,
        seat: GgSeat,
        previous: GgSeat | None,
        state: _SeatState,
        now: float,
        metrics: dict[str, Any],
    ) -> None:
        index = int(seat.physicalSeatIndex)
        action = str(seat.action or "none")
        if action not in {"none", "waiting"} and float(seat.actionConfidence or 0.0) >= 0.40:
            state.last_action = action
            state.last_action_amount = float(seat.actionAmount or seat.currentBet or 0.0)
            state.last_action_until = now + ACTION_HOLD_SECONDS
            return
        if state.last_action not in {"none", "waiting"} and now <= state.last_action_until:
            seat.action = state.last_action  # type: ignore[assignment]
            seat.actionAmount = state.last_action_amount
            seat.actionConfidence = max(float(seat.actionConfidence or 0.0), 0.55)
            seat.actionSource = seat.actionSource or "held"
            metrics["fieldsHeld"].append(f"seat-{index}-action")
            return
        if previous and previous.action in {"fold"} and previous.status == "folded":
            seat.action = "fold"
            seat.status = "folded"

    def _stable_amount(
        self,
        key: str,
        raw_value: float,
        raw_confidence: float,
        previous_value: float,
        metrics: dict[str, Any],
        *,
        min_confidence: float,
    ) -> float:
        if raw_value > 0 and raw_confidence >= min_confidence:
            return raw_value
        if previous_value > 0:
            return previous_value
        return raw_value

    def _sanitize_placeholder_names(self, snapshot: GgTableSnapshot, metrics: dict[str, Any]) -> None:
        for seat in snapshot.seats:
            self._sanitize_seat_name(seat, None, metrics)

    def _apply_seat_database_to_snapshot(
        self,
        snapshot: GgTableSnapshot,
        now: float,
        metrics: dict[str, Any],
    ) -> None:
        seen_indexes: set[int] = set()
        for seat in snapshot.seats:
            index = int(seat.physicalSeatIndex)
            seen_indexes.add(index)
            self._apply_seat_database(seat, now, metrics)
        metrics["seatDatabase"] = self._seat_database_rows(now, seen_indexes)

    def _apply_seat_database(self, seat: GgSeat, now: float, metrics: dict[str, Any]) -> None:
        index = int(seat.physicalSeatIndex)
        record = self._seat_database.setdefault(index, _SeatPositionRecord())

        if not seat.active:
            if record.active or record.name or record.stack > 0:
                metrics["fieldsAccepted"].append(f"seat-{index}-database-clear")
            self._clear_position_record(record, now)
            seat.name = ""
            seat.nameConfidence = 0.0
            seat.stack = 0.0
            seat.stackConfidence = 0.0
            return

        record.active = True
        record.last_seen_at = now
        self._apply_database_name(seat, record, metrics)
        self._apply_database_stack(seat, record, metrics)

    def _apply_database_name(
        self,
        seat: GgSeat,
        record: _SeatPositionRecord,
        metrics: dict[str, Any],
    ) -> None:
        index = int(seat.physicalSeatIndex)
        observed_name = _record_name(seat.name)
        confidence = float(seat.nameConfidence or 0.0)
        accepted = False

        if observed_name and not _is_placeholder_name(observed_name):
            accepted = self._accept_name_candidate(record, observed_name, confidence)
            if accepted:
                metrics["fieldsAccepted"].append(f"seat-{index}-database-name")

        if record.name:
            if not accepted and observed_name and not _same_name(observed_name, record.name):
                metrics["fieldsHeld"].append(f"seat-{index}-database-name")
            seat.name = record.name
            seat.nameConfidence = max(confidence if accepted else 0.0, min(record.name_confidence, 0.90))
            return

        if not accepted:
            seat.name = ""
            seat.nameConfidence = 0.0

    def _apply_database_stack(
        self,
        seat: GgSeat,
        record: _SeatPositionRecord,
        metrics: dict[str, Any],
    ) -> None:
        index = int(seat.physicalSeatIndex)
        observed_stack = float(seat.stack or 0.0)
        confidence = float(seat.stackConfidence or 0.0)
        accepted = False

        if observed_stack > 0 and confidence >= STACK_ACCEPT_CONFIDENCE:
            accepted = self._accept_stack_candidate(record, observed_stack, confidence)
            if accepted:
                metrics["fieldsAccepted"].append(f"seat-{index}-database-stack")

        if record.stack > 0:
            if not accepted and observed_stack > 0 and not _close_amount(observed_stack, record.stack):
                metrics["fieldsHeld"].append(f"seat-{index}-database-stack")
            seat.stack = record.stack
            seat.stackConfidence = max(confidence if accepted else 0.0, min(record.stack_confidence, 0.90))
            return

        if not accepted:
            seat.stack = 0.0
            seat.stackConfidence = 0.0

    def _accept_name_candidate(self, record: _SeatPositionRecord, name: str, confidence: float) -> bool:
        if confidence < 0.20:
            return False
        if not record.name:
            if confidence >= NAME_ACCEPT_CONFIDENCE:
                _set_record_name(record, name, confidence)
                return True
            hits = _stage_name_candidate(record, name, confidence)
            if hits >= NAME_REPLACE_HITS:
                _set_record_name(record, name, confidence)
                return True
            return False

        if _same_name(name, record.name):
            if _name_quality_score(name) >= _name_quality_score(record.name) or confidence >= record.name_confidence:
                record.name = name
            record.name_confidence = max(record.name_confidence, confidence)
            record.pending_name = ""
            record.pending_name_hits = 0
            return True

        if _name_similarity(name, record.name) >= NAME_VARIANT_SIMILARITY and confidence < NAME_REPLACE_CONFIDENCE:
            _stage_name_candidate(record, name, confidence)
            return False

        if confidence >= NAME_REPLACE_CONFIDENCE:
            _set_record_name(record, name, confidence)
            return True

        hits = _stage_name_candidate(record, name, confidence)
        if confidence >= NAME_ACCEPT_CONFIDENCE and hits >= NAME_REPLACE_HITS:
            _set_record_name(record, name, confidence)
            return True
        return False

    def _accept_stack_candidate(self, record: _SeatPositionRecord, stack: float, confidence: float) -> bool:
        if record.stack <= 0:
            _set_record_stack(record, stack, confidence)
            return True

        if _amount_is_sane(record.stack, stack, confidence):
            _set_record_stack(record, stack, confidence)
            return True

        hits = _stage_stack_candidate(record, stack, confidence)
        if confidence >= STACK_REPLACE_CONFIDENCE or (confidence >= 0.75 and hits >= STACK_REPLACE_HITS):
            _set_record_stack(record, stack, confidence)
            return True
        return False

    def _clear_position_record(self, record: _SeatPositionRecord, now: float) -> None:
        record.active = False
        record.name = ""
        record.name_confidence = 0.0
        record.stack = 0.0
        record.stack_confidence = 0.0
        record.last_seen_at = now
        record.updated_at = now
        record.pending_name = ""
        record.pending_name_hits = 0
        record.pending_name_confidence = 0.0
        record.pending_stack = 0.0
        record.pending_stack_hits = 0
        record.pending_stack_confidence = 0.0

    def _seat_database_rows(self, now: float, seen_indexes: set[int]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index in sorted(seen_indexes | set(self._seat_database)):
            record = self._seat_database.setdefault(index, _SeatPositionRecord())
            rows.append({
                "seatIndex": index,
                "active": bool(record.active),
                "name": record.name,
                "nameConfidence": round(float(record.name_confidence or 0.0), 4),
                "stack": round(float(record.stack or 0.0), 4),
                "stackConfidence": round(float(record.stack_confidence or 0.0), 4),
                "lastSeenMsAgo": round(max(0.0, now - float(record.last_seen_at or now)) * 1000, 2),
                "pendingName": record.pending_name,
                "pendingNameHits": int(record.pending_name_hits),
                "pendingStack": round(float(record.pending_stack or 0.0), 4),
                "pendingStackHits": int(record.pending_stack_hits),
            })
        return rows


def _amount_confidence(snapshot: GgTableSnapshot, key: str) -> float:
    for field in snapshot.metrics.get("amountFields") or []:
        if isinstance(field, dict) and field.get("key") == key:
            try:
                return float(field.get("confidence") or 0.0)
            except (TypeError, ValueError):
                return 0.0
    return float(snapshot.confidence or 0.0)


def _is_placeholder_name(value: str | None) -> bool:
    text = str(value or "").strip()
    return bool(text and text.lower().startswith("gg seat "))


def _record_name(value: str | None) -> str:
    return " ".join(str(value or "").strip().split())


def _same_name(left: str | None, right: str | None) -> bool:
    return _record_name(left).casefold() == _record_name(right).casefold()


def _name_similarity(left: str | None, right: str | None) -> float:
    return SequenceMatcher(None, _record_name(left).casefold(), _record_name(right).casefold()).ratio()


def _name_quality_score(value: str | None) -> float:
    text = _record_name(value)
    if not text:
        return 0.0
    alpha_numeric = sum(1 for char in text if char.isalnum())
    separators = sum(1 for char in text if char in "_. -")
    return alpha_numeric + min(separators, 2) * 0.25


def _set_record_name(record: _SeatPositionRecord, name: str, confidence: float) -> None:
    record.name = _record_name(name)
    record.name_confidence = float(confidence or 0.0)
    record.updated_at = time.monotonic()
    record.pending_name = ""
    record.pending_name_hits = 0
    record.pending_name_confidence = 0.0


def _stage_name_candidate(record: _SeatPositionRecord, name: str, confidence: float) -> int:
    normalized = _record_name(name)
    if _same_name(record.pending_name, normalized):
        record.pending_name_hits += 1
        record.pending_name_confidence = max(record.pending_name_confidence, float(confidence or 0.0))
    else:
        record.pending_name = normalized
        record.pending_name_hits = 1
        record.pending_name_confidence = float(confidence or 0.0)
    return record.pending_name_hits


def _set_record_stack(record: _SeatPositionRecord, stack: float, confidence: float) -> None:
    record.stack = round(float(stack or 0.0), 4)
    record.stack_confidence = float(confidence or 0.0)
    record.updated_at = time.monotonic()
    record.pending_stack = 0.0
    record.pending_stack_hits = 0
    record.pending_stack_confidence = 0.0


def _stage_stack_candidate(record: _SeatPositionRecord, stack: float, confidence: float) -> int:
    value = float(stack or 0.0)
    if record.pending_stack > 0 and _close_amount(record.pending_stack, value):
        record.pending_stack_hits += 1
        record.pending_stack_confidence = max(record.pending_stack_confidence, float(confidence or 0.0))
    else:
        record.pending_stack = value
        record.pending_stack_hits = 1
        record.pending_stack_confidence = float(confidence or 0.0)
    return record.pending_stack_hits


def _close_amount(left: float, right: float) -> bool:
    return abs(float(left or 0.0) - float(right or 0.0)) <= max(0.05, max(abs(left), abs(right)) * 0.002)


def _amount_is_sane(previous: float, current: float, confidence: float) -> bool:
    if current <= 0:
        return confidence >= 0.78 and previous <= 0.5
    if previous <= 0:
        return True
    ratio = current / max(previous, 0.01)
    if 0.35 <= ratio <= 2.8:
        return True
    return confidence >= 0.92
