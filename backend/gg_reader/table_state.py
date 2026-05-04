from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .models import GgSeat, GgTableSnapshot


PUBLISH_INTERVAL_SECONDS = 1.0
ACTION_HOLD_SECONDS = 1.8


@dataclass
class _SeatState:
    empty_misses: int = 0
    no_card_misses: int = 0
    zero_bet_hits: int = 0
    last_action: str = "none"
    last_action_amount: float = 0.0
    last_action_until: float = 0.0


class TableStateStabilizer:
    """Field-level smoothing for noisy OCR snapshots.

    The fast reader may see several partial reads while OCR futures complete.
    This class keeps the last accepted table truth and only lets weak fields
    replace known values when they are either confident or repeated.
    """

    def __init__(self) -> None:
        self._stable: GgTableSnapshot | None = None
        self._seat_states: dict[int, _SeatState] = {}
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
            self._stable = stable.model_copy(deep=True)
            self._last_publish_at = current_time
            metrics["initialStableSnapshot"] = True
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


def _amount_is_sane(previous: float, current: float, confidence: float) -> bool:
    if current <= 0:
        return confidence >= 0.78 and previous <= 0.5
    if previous <= 0:
        return True
    ratio = current / max(previous, 0.01)
    if 0.35 <= ratio <= 2.8:
        return True
    return confidence >= 0.92
