from __future__ import annotations

import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .models import GgCard, GgSeat, GgTableSnapshot


# Stabilization runs on every frame; this value is diagnostic cadence only.
# Keep it aligned with the normal 4 Hz reader rather than implying 1 s lag.
PUBLISH_INTERVAL_SECONDS = 0.25
ACTION_HOLD_SECONDS = 1.8
BET_CLEAR_CONFIDENCE = 0.78
STACK_ZERO_CONFIDENCE = 0.78
NAME_ACCEPT_CONFIDENCE = 0.55
NAME_REPLACE_CONFIDENCE = 0.86
NAME_REPLACE_HITS = 2
NAME_VARIANT_SIMILARITY = 0.78
STACK_ACCEPT_CONFIDENCE = 0.50
STACK_REPLACE_HITS = 2


@dataclass
class _SeatState:
    empty_misses: int = 0
    no_card_misses: int = 0
    zero_bet_hits: int = 0
    zero_stack_hits: int = 0
    pending_stack: float = 0.0
    pending_stack_hits: int = 0
    pending_bet: float = 0.0
    pending_bet_hits: int = 0
    last_action: str = "none"
    last_action_amount: float = 0.0
    last_action_source: str = "none"
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


@dataclass
class _CardSlotRecord:
    card_id: str = ""
    confidence: float = 0.0
    updated_at: float = 0.0
    pending_card_id: str = ""
    pending_hits: int = 0
    pending_confidence: float = 0.0


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
        self._board_database: dict[int, _CardSlotRecord] = {}
        self._last_publish_at = 0.0
        self._last_metrics: dict[str, Any] = {}
        self._pending_pot = 0.0
        self._pending_pot_hits = 0
        self._pending_dealer_index: int | None = None
        self._pending_dealer_hits = 0
        self._pending_preflop_reset_signature: tuple[Any, ...] | None = None
        self._pending_preflop_reset_hits = 0

    def stabilize(self, raw: GgTableSnapshot, *, now: float | None = None) -> GgTableSnapshot:
        current_time = time.monotonic() if now is None else now
        metrics: dict[str, Any] = {
            "stableCadenceMs": int(PUBLISH_INTERVAL_SECONDS * 1000),
            "fieldsHeld": [],
            "fieldsAccepted": [],
            "heldByCadence": False,
            "handReset": False,
            "streetTransition": False,
        }

        if self._stable is None:
            stable = raw.model_copy(deep=True)
            self._sanitize_board(stable, None, False, metrics)
            self._sanitize_placeholder_names(stable, metrics)
            self._apply_seat_database_to_snapshot(stable, current_time, metrics)
            self._apply_board_database_to_snapshot(stable, current_time, metrics)
            for seat in stable.seats:
                if seat.action in {"check", "call", "bet", "raise", "fold", "all-in"}:
                    state = self._seat_states.setdefault(int(seat.physicalSeatIndex), _SeatState())
                    state.last_action = seat.action
                    state.last_action_amount = float(seat.actionAmount or seat.currentBet or 0.0)
                    state.last_action_source = str(seat.actionSource or "state")
                    state.last_action_until = current_time + ACTION_HOLD_SECONDS
            metrics["initialStableSnapshot"] = True
            stable.metrics = {**raw.metrics, "stabilizer": metrics}
            self._stable = stable.model_copy(deep=True)
            self._last_publish_at = current_time
            self._last_metrics = metrics
            return stable

        previous = self._stable
        hand_reset = self._detect_hand_reset(raw, previous)
        if hand_reset:
            self._reset_hand_transients()
        stable = raw.model_copy(deep=True)
        self._sanitize_board(stable, previous, hand_reset, metrics)
        self._stabilize_runouts(stable, previous, hand_reset, metrics)
        self._apply_board_database_to_snapshot(stable, current_time, metrics)
        street_transition = _is_street_transition(previous, stable, hand_reset)
        metrics["handReset"] = hand_reset
        metrics["streetTransition"] = street_transition
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
            merged_seats.append(self._stabilize_seat(
                raw_seat,
                previous_seat,
                current_time,
                metrics,
                hand_reset=hand_reset,
                street_transition=street_transition,
            ))

        stable.seats = sorted(merged_seats, key=lambda seat: int(seat.physicalSeatIndex))
        self._reconcile_street_actions(
            stable.seats,
            previous_by_index,
            street_transition=street_transition,
        )
        exposed_contenders = [
            seat for seat in stable.seats
            if seat.active and _has_two_visible_cards(seat)
        ]
        if len(exposed_contenders) >= 2 and len(stable.board) >= 3:
            stable.street = "showdown"
            for seat in exposed_contenders:
                seat.inHand = True
                if seat.status == "folded" and str(seat.actionSource or "") == "cards_disappeared":
                    seat.status = "active"
                    seat.action = "all-in" if seat.isAllIn else "none"
                    seat.actionSource = "exposed_cards"
            exposed_indexes = {int(seat.physicalSeatIndex) for seat in exposed_contenders}
            for seat in stable.seats:
                if seat.active and int(seat.physicalSeatIndex) not in exposed_indexes:
                    seat.inHand = False
                    seat.status = "folded"
                    seat.holeCards = []
                    if not seat.isAllIn:
                        seat.action = "none"
                        seat.actionAmount = 0.0
                        seat.actionSource = "showdown_non_contender"
        self._apply_seat_database_to_snapshot(stable, current_time, metrics)
        stable.activePlayerCount = sum(1 for seat in stable.seats if seat.active)
        stable.pot = self._stable_pot(
            float(raw.pot or 0.0),
            _amount_confidence(raw, "pot"),
            float(previous.pot or 0.0),
            metrics,
            hand_reset=hand_reset,
            street_transition=street_transition,
        )
        if stable.pot != raw.pot:
            metrics["fieldsHeld"].append("pot")

        if not stable.board and previous.board and not hand_reset and stable.street == previous.street:
            stable.board = [card.model_copy(deep=True) for card in previous.board]
            metrics["fieldsHeld"].append("board")

        if raw.dealerSeatIndex != previous.dealerSeatIndex and (
            not hand_reset or _dealer_confidence(raw) < 0.48
        ):
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

    def has_pending_confirmation(self) -> bool:
        """Return whether another observation can advance held table state.

        The fast reader may reuse an identical frame, but a first observation
        of a new board card, changed stack/bet, pot jump, dealer move, or hand
        boundary is deliberately provisional. Reusing the already-stabilized
        snapshot in that situation would prevent the confirming observation
        forever.
        """

        if (
            self._pending_pot_hits
            or self._pending_dealer_hits
            or self._pending_preflop_reset_hits
        ):
            return True
        if any(
            state.pending_stack_hits or state.pending_bet_hits
            for state in self._seat_states.values()
        ):
            return True
        if any(
            record.pending_name_hits or record.pending_stack_hits
            for record in self._seat_database.values()
        ):
            return True
        return any(record.pending_hits for record in self._board_database.values())

    def _detect_hand_reset(self, raw: GgTableSnapshot, previous: GgTableSnapshot) -> bool:
        if raw.handId and previous.handId and raw.handId != previous.handId:
            self._clear_pending_hand_reset_signals()
            return True

        previous_cards = [_card_id(card) for card in previous.board if _card_id(card)]
        raw_cards = [_card_id(card) for card in raw.board if _card_id(card)]
        raw_board_valid = len(raw_cards) in {0, 3, 4, 5} and len(set(raw_cards)) == len(raw_cards)
        previous_order = _street_order(previous.street)
        raw_order = _street_order(raw.street)

        # Community cards are immutable within a hand. A capture can miss the
        # short board-clear/preflop animation when the table advances quickly,
        # so the next observed hand may already be on a later street. Two or
        # more replaced prefix cards are decisive new-hand evidence even when
        # the apparent street order moved forward (for example old flop -> new
        # river). A single differing card is left to the board stabilizer so a
        # transient rank/suit correction cannot split a hand.
        if raw_board_valid and previous_cards and raw_cards:
            shared_count = min(len(previous_cards), len(raw_cards))
            replaced_prefix_cards = sum(
                1
                for index in range(shared_count)
                if previous_cards[index] != raw_cards[index]
            )
            if shared_count >= 2 and replaced_prefix_cards >= 2:
                self._clear_pending_hand_reset_signals()
                return True

        # A complete, different flop after a later street can only belong to a
        # new hand. A prefix of the old board is just a partial OCR frame.
        if raw_board_valid and raw_order >= 1 and previous_order > raw_order:
            if raw_cards and raw_cards != previous_cards[:len(raw_cards)]:
                self._clear_pending_hand_reset_signals()
                return True

        preflop_candidate = not raw_cards and raw.street == "preflop"
        if preflop_candidate and self._accumulate_late_to_preflop_reset(raw, previous, previous_cards):
            self._clear_pending_hand_reset_signals()
            return True

        dealer_changed = int(raw.dealerSeatIndex) != int(previous.dealerSeatIndex)
        if preflop_candidate and dealer_changed:
            dealer_confidence = _dealer_confidence(raw)
            candidate = int(raw.dealerSeatIndex)
            if dealer_confidence >= 0.48:
                if self._pending_dealer_index == candidate:
                    self._pending_dealer_hits += 1
                else:
                    self._pending_dealer_index = candidate
                    self._pending_dealer_hits = 1
                previous_bets = sum(float(seat.currentBet or 0.0) for seat in previous.seats if seat.active)
                raw_bets = sum(float(seat.currentBet or 0.0) for seat in raw.seats if seat.active)
                pot_reset = previous.pot > 0 and 0 <= float(raw.pot or 0.0) < float(previous.pot or 0.0) * 0.65
                bets_reset = previous_bets > 0 and raw_bets < previous_bets * 0.65
                strong_context = pot_reset or bets_reset
                if strong_context and dealer_confidence >= 0.72 and self._pending_dealer_hits >= 1:
                    self._clear_pending_hand_reset_signals()
                    return True
                if self._pending_dealer_hits >= 2:
                    self._clear_pending_hand_reset_signals()
                    return True
                return False

        self._pending_dealer_index = None
        self._pending_dealer_hits = 0
        if not preflop_candidate:
            self._pending_preflop_reset_signature = None
            self._pending_preflop_reset_hits = 0
        return False

    def _accumulate_late_to_preflop_reset(
        self,
        raw: GgTableSnapshot,
        previous: GgTableSnapshot,
        previous_cards: list[str],
    ) -> bool:
        """Confirm a new deal even when the dealer detector did not move.

        Empty-board OCR frames are common, so a street regression alone is
        not sufficient.  We require a completed prior board plus a repeated,
        internally consistent reset of the pot and/or visible bets to blind
        scale.  Strong pot *and* bet evidence needs two frames; a single
        amount channel needs three.
        """

        previous_order = _street_order(previous.street)
        if previous_order < 3 or len(previous_cards) < 5:
            self._pending_preflop_reset_signature = None
            self._pending_preflop_reset_hits = 0
            return False

        small_blind = max(0.0, float(raw.smallBlind or 0.0))
        big_blind = max(0.0, float(raw.bigBlind or 0.0))
        blind_total = max(0.01, small_blind + big_blind, big_blind * 1.5)
        previous_pot = max(0.0, float(previous.pot or 0.0))
        raw_pot = max(0.0, float(raw.pot or 0.0))
        previous_bets = sum(float(seat.currentBet or 0.0) for seat in previous.seats if seat.active)
        raw_bets = sum(float(seat.currentBet or 0.0) for seat in raw.seats if seat.active)

        pot_confident = _amount_confidence(raw, "pot") >= 0.55
        pot_reset = bool(
            pot_confident
            and raw_pot >= max(0.01, small_blind * 0.5)
            and previous_pot >= max(blind_total * 3.0, raw_pot * 2.5)
            and raw_pot <= max(blind_total * 1.75, big_blind * 2.5)
        )
        bets_reset = bool(
            raw_bets >= max(0.01, small_blind * 0.75)
            and previous_bets >= max(blind_total * 2.0, raw_bets * 2.0)
            and raw_bets <= max(blind_total * 1.5, big_blind * 2.0)
        )
        evidence_count = int(pot_reset) + int(bets_reset)
        if evidence_count == 0:
            self._pending_preflop_reset_signature = None
            self._pending_preflop_reset_hits = 0
            return False

        active_indexes = tuple(sorted(
            int(seat.physicalSeatIndex)
            for seat in raw.seats
            if seat.active
        ))
        dealer_token: int | None = None
        if _dealer_confidence(raw) >= 0.48:
            dealer_token = int(raw.dealerSeatIndex)
        signature = (
            round(small_blind, 2),
            round(big_blind, 2),
            active_indexes,
            dealer_token,
            pot_reset,
            bets_reset,
        )
        if signature == self._pending_preflop_reset_signature:
            self._pending_preflop_reset_hits += 1
        else:
            self._pending_preflop_reset_signature = signature
            self._pending_preflop_reset_hits = 1

        required_hits = 2 if evidence_count == 2 else 3
        return self._pending_preflop_reset_hits >= required_hits

    def _clear_pending_hand_reset_signals(self) -> None:
        self._pending_dealer_index = None
        self._pending_dealer_hits = 0
        self._pending_preflop_reset_signature = None
        self._pending_preflop_reset_hits = 0

    def _reset_hand_transients(self) -> None:
        self._seat_states.clear()
        self._board_database.clear()
        self._pending_pot = 0.0
        self._pending_pot_hits = 0

    def _sanitize_board(
        self,
        snapshot: GgTableSnapshot,
        previous: GgTableSnapshot | None,
        hand_reset: bool,
        metrics: dict[str, Any],
    ) -> None:
        valid_cards: list[GgCard] = []
        seen: set[str] = set()
        invalid_or_duplicate = False
        for card in snapshot.board[:5]:
            card_id = _card_id(card)
            if not card_id or card_id in seen:
                invalid_or_duplicate = True
                continue
            seen.add(card_id)
            valid_cards.append(card)

        count = len(valid_cards)
        previous_cards = [card for card in (previous.board if previous else []) if _card_id(card)]
        previous_ids = [_card_id(card) for card in previous_cards]
        current_ids = [_card_id(card) for card in valid_cards]
        partial_count = count not in {0, 3, 4, 5}
        regressed_prefix = bool(
            previous_cards
            and count < len(previous_cards)
            and current_ids == previous_ids[:count]
        )

        if not hand_reset and previous_cards and (
            partial_count
            or invalid_or_duplicate
            or regressed_prefix
            or count == 0
        ):
            snapshot.board = [card.model_copy(deep=True) for card in previous_cards]
            snapshot.street = previous.street
            metrics["fieldsHeld"].append("board-invalid" if invalid_or_duplicate else "board-partial")
            return

        if partial_count or invalid_or_duplicate:
            snapshot.board = []
            if count > 0:
                snapshot.street = "unknown"
            metrics["fieldsHeld"].append("board-invalid")
            return

        snapshot.board = valid_cards
        if count >= 3 and snapshot.street == "showdown":
            snapshot.street = "showdown"
        elif previous and not hand_reset and previous.street == "showdown" and current_ids == previous_ids:
            snapshot.street = "showdown"
        else:
            snapshot.street = _street_from_card_count(count)

    def _stabilize_runouts(
        self,
        snapshot: GgTableSnapshot,
        previous: GgTableSnapshot | None,
        hand_reset: bool,
        metrics: dict[str, Any],
    ) -> None:
        if hand_reset:
            if not snapshot.runouts:
                snapshot.sharedBoard = []
            return

        previous_runs = previous.runouts if previous else []
        if not snapshot.runouts:
            if previous_runs and snapshot.street == "showdown":
                snapshot.sharedBoard = [card.model_copy(deep=True) for card in previous.sharedBoard]
                snapshot.runouts = [
                    [card.model_copy(deep=True) for card in runout]
                    for runout in previous_runs
                ]
                snapshot.board = [
                    *(card.model_copy(deep=True) for card in snapshot.sharedBoard),
                    *(card.model_copy(deep=True) for card in snapshot.runouts[0]),
                ]
                metrics["fieldsHeld"].append("runouts")
            return

        shared_ids = [_card_id(card) for card in snapshot.sharedBoard]
        run_ids = [[_card_id(card) for card in runout] for runout in snapshot.runouts[:3]]
        all_ids = [card_id for card_id in shared_ids if card_id]
        all_ids.extend(card_id for runout in run_ids for card_id in runout if card_id)
        valid = bool(
            len(shared_ids) == 3
            and all(shared_ids)
            and len(snapshot.runouts) >= 2
            and all(len(runout) <= 2 for runout in run_ids)
            and len(all_ids) == len(set(all_ids))
        )
        if not valid:
            if previous_runs:
                snapshot.sharedBoard = [card.model_copy(deep=True) for card in previous.sharedBoard]
                snapshot.runouts = [
                    [card.model_copy(deep=True) for card in runout]
                    for runout in previous_runs
                ]
                snapshot.board = [
                    *(card.model_copy(deep=True) for card in snapshot.sharedBoard),
                    *(card.model_copy(deep=True) for card in snapshot.runouts[0]),
                ]
            else:
                snapshot.sharedBoard = []
                snapshot.runouts = []
            metrics["fieldsHeld"].append("runouts-invalid")
            return

        if previous_runs and len(previous_runs) == len(snapshot.runouts):
            for index, previous_run in enumerate(previous_runs):
                current_run = snapshot.runouts[index]
                previous_run_ids = [_card_id(card) for card in previous_run]
                current_run_ids = [_card_id(card) for card in current_run]
                if len(current_run_ids) < len(previous_run_ids) and current_run_ids == previous_run_ids[:len(current_run_ids)]:
                    snapshot.runouts[index] = [card.model_copy(deep=True) for card in previous_run]
                    metrics["fieldsHeld"].append(f"runout-{index}")

        snapshot.board = [
            *(card.model_copy(deep=True) for card in snapshot.sharedBoard),
            *(card.model_copy(deep=True) for card in snapshot.runouts[0]),
        ]

    def _stabilize_seat(
        self,
        raw: GgSeat,
        previous: GgSeat | None,
        now: float,
        metrics: dict[str, Any],
        *,
        hand_reset: bool,
        street_transition: bool,
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
            state.zero_stack_hits = 0
            state.pending_stack = 0.0
            state.pending_stack_hits = 0
            state.pending_bet = 0.0
            state.pending_bet_hits = 0
            return seat

        state.empty_misses = 0
        self._sanitize_seat_name(seat, previous, metrics)
        self._stabilize_seat_amounts(
            seat,
            previous,
            state,
            metrics,
            reset_bet=hand_reset or street_transition,
        )
        self._stabilize_cards(seat, previous, state, metrics, hand_reset=hand_reset)
        self._stabilize_action(
            seat,
            previous,
            state,
            now,
            metrics,
            reset_action=hand_reset or street_transition,
        )
        if hand_reset:
            seat.isAllIn = bool(raw.isAllIn)
        elif raw.isAllIn:
            seat.isAllIn = True
        elif previous and previous.isAllIn and float(seat.stack or 0.0) <= 0.05:
            seat.isAllIn = True
        else:
            seat.isAllIn = False
        if (
            previous
            and previous.isAllIn
            and not seat.isAllIn
            and float(seat.stack or 0.0) > 0.05
        ):
            # A zero stack that comes back above zero on the same street is
            # ClubGG returning the uncalled part of a shove.  Clear both the
            # rendered action and its hold cache; otherwise the next frame can
            # resurrect the stale all-in label from ``last_action``.
            state.last_action = "none"
            state.last_action_amount = 0.0
            state.last_action_source = "none"
            state.last_action_until = 0.0
            seat.action = "none"
            seat.actionAmount = 0.0
            seat.actionSource = "uncalled_bet_refund"
            seat.actionConfidence = max(float(seat.stackConfidence or 0.0), 0.80)
        if _has_two_visible_cards(seat):
            seat.inHand = True
            if seat.status == "folded" and str(seat.actionSource or "") in {
                "cards_disappeared",
                "cards_not_visible",
                "held",
                "held_state",
            }:
                seat.status = "active"
                seat.action = "all-in" if seat.isAllIn else "none"
                seat.actionSource = "exposed_cards"
        elif seat.status in {"folded", "empty", "sitting_out"} or seat.action == "fold":
            seat.inHand = False
        elif seat.active and seat.inHand is None:
            seat.inHand = True
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
        *,
        reset_bet: bool,
    ) -> None:
        index = int(seat.physicalSeatIndex)
        previous_stack = float(previous.stack or 0.0) if previous else 0.0
        stack_confidence = float(seat.stackConfidence or 0.0)
        current_stack = float(seat.stack or 0.0)
        if previous_stack > 0 and current_stack <= 0:
            state.pending_stack = 0.0
            state.pending_stack_hits = 0
            explicit_all_in = bool(
                seat.isAllIn
                or (seat.action == "all-in" and float(seat.actionConfidence or 0.0) >= 0.40)
            )
            if explicit_all_in:
                state.zero_stack_hits = 2
                seat.stack = 0.0
                seat.stackConfidence = max(stack_confidence, STACK_ZERO_CONFIDENCE)
            elif stack_confidence >= STACK_ZERO_CONFIDENCE:
                state.zero_stack_hits += 1
                if state.zero_stack_hits < 2:
                    _hold_previous_stack(seat, previous, metrics)
            else:
                state.zero_stack_hits = 0
                _hold_previous_stack(seat, previous, metrics)
        elif (
            previous
            and previous_stack <= 0
            and previous.action == "all-in"
            and current_stack > 0
            and not reset_bet
        ):
            state.zero_stack_hits = 0
            if state.pending_stack > 0 and _close_amount(state.pending_stack, current_stack):
                state.pending_stack_hits += 1
            else:
                state.pending_stack = current_stack
                state.pending_stack_hits = 1
            if state.pending_stack_hits < 2:
                _hold_previous_stack(seat, previous, metrics)
        else:
            state.zero_stack_hits = 0
            state.pending_stack = 0.0
            state.pending_stack_hits = 0

        previous_bet = float(previous.currentBet or 0.0) if previous else 0.0
        bet_confidence = float(seat.betConfidence or 0.0)
        current_bet = float(seat.currentBet or 0.0)
        if reset_bet:
            state.zero_bet_hits = 0
            state.pending_bet = 0.0
            state.pending_bet_hits = 0
            seat.committed = current_bet
        elif current_bet <= 0 and previous_bet > 0:
            # ClubGG removes a player's chip label immediately after their
            # action, even though the wager remains committed for the street.
            # Keep a wager backed by a known action until the street
            # transition.  A high-confidence zero with no action context is a
            # real clear candidate, but still needs two observations so one
            # blank OCR frame cannot erase a bet.  A stack recovery from zero
            # is the distinct uncalled-bet refund path and clears immediately.
            refunded = bool(
                previous
                and float(previous.stack or 0.0) <= 0.05
                and current_stack > 0.05
                and stack_confidence >= STACK_ACCEPT_CONFIDENCE
            )
            committed_action = bool(
                previous
                and (
                    previous.isAllIn
                    or previous.action in {"call", "bet", "raise", "all-in"}
                )
            )
            if refunded:
                seat.currentBet = 0.0
                seat.betConfidence = max(bet_confidence, BET_CLEAR_CONFIDENCE)
                state.zero_bet_hits = 0
            elif committed_action:
                state.zero_bet_hits = 0
                _hold_previous_bet(seat, previous, metrics)
            elif bet_confidence >= BET_CLEAR_CONFIDENCE:
                state.zero_bet_hits += 1
                if state.zero_bet_hits < 2:
                    _hold_previous_bet(seat, previous, metrics)
            else:
                state.zero_bet_hits = 0
                _hold_previous_bet(seat, previous, metrics)
        elif 0 < current_bet < previous_bet - 0.01:
            state.zero_bet_hits = 0
            if state.pending_bet > 0 and _close_amount(state.pending_bet, current_bet):
                state.pending_bet_hits += 1
            else:
                state.pending_bet = current_bet
                state.pending_bet_hits = 1
            if state.pending_bet_hits < 2:
                _hold_previous_bet(seat, previous, metrics)
        else:
            state.zero_bet_hits = 0
            state.pending_bet = 0.0
            state.pending_bet_hits = 0

    def _reconcile_street_actions(
        self,
        seats: list[GgSeat],
        previous_by_index: dict[int, GgSeat],
        *,
        street_transition: bool,
    ) -> None:
        if street_transition:
            return
        previous_max = max(
            [float(seat.currentBet or 0.0) for seat in previous_by_index.values() if seat.active]
            or [0.0]
        )
        current_max = max([float(seat.currentBet or 0.0) for seat in seats if seat.active] or [0.0])
        target = max(previous_max, current_max)
        for seat in seats:
            if not seat.active:
                continue
            current = float(seat.currentBet or 0.0)
            previous = previous_by_index.get(int(seat.physicalSeatIndex))
            previous_bet = float(previous.currentBet or 0.0) if previous else 0.0
            stack_dropped = bool(
                previous
                and float(previous.stack or 0.0) > float(seat.stack or 0.0) + 0.01
            )
            if seat.action == "check" and previous and previous.action == "call":
                seat.action = "call"
                seat.actionSource = "held_call"
                seat.actionConfidence = max(float(seat.actionConfidence or 0.0), 0.72)
            elif seat.action == "check" and stack_dropped and target > previous_bet + 0.01:
                seat.action = "call"
                seat.actionSource = "stack_delta"
                seat.actionConfidence = max(float(seat.actionConfidence or 0.0), 0.88)
            if seat.action == "call" and target > current + 0.01:
                seat.currentBet = target
                seat.actionAmount = target
                seat.committed = max(float(seat.committed or 0.0), target)
                seat.betConfidence = max(float(seat.betConfidence or 0.0), 0.82)
            elif seat.action == "bet" and previous_max > 0 and current > previous_max + 0.01:
                seat.action = "raise"
                seat.actionAmount = current
                seat.actionSource = "bet_delta"
                seat.actionConfidence = max(float(seat.actionConfidence or 0.0), 0.82)

    def _stabilize_cards(
        self,
        seat: GgSeat,
        previous: GgSeat | None,
        state: _SeatState,
        metrics: dict[str, Any],
        *,
        hand_reset: bool,
    ) -> None:
        index = int(seat.physicalSeatIndex)
        if _has_two_visible_cards(seat):
            state.no_card_misses = 0
            seat.inHand = True
            if seat.status == "folded" and str(seat.actionSource or "") != "label_ocr":
                seat.status = "active"
                seat.action = "all-in" if seat.isAllIn else "none"
                seat.actionSource = "exposed_cards"
            return
        if seat.holeCards:
            state.no_card_misses = 0
            return
        if hand_reset:
            state.no_card_misses = 0
            return
        had_cards = bool(previous and previous.active and previous.holeCards)
        if not had_cards:
            return
        if seat.isAllIn:
            state.no_card_misses += 1
            if previous and previous.holeCards:
                seat.holeCards = [card.model_copy(deep=True) for card in previous.holeCards]
                metrics["fieldsHeld"].append(f"seat-{index}-cards-all-in-reveal")
            seat.status = "active"
            seat.inHand = True
            seat.action = "all-in"
            seat.actionSource = "all_in_reveal_transition"
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
        *,
        reset_action: bool,
    ) -> None:
        index = int(seat.physicalSeatIndex)
        if reset_action:
            state.last_action = "none"
            state.last_action_amount = 0.0
            state.last_action_source = "none"
            state.last_action_until = 0.0
            if seat.action in {"none", "waiting"}:
                seat.action = "none"
                seat.actionAmount = 0.0
                seat.actionSource = "none"
                if seat.active and seat.status != "folded":
                    seat.status = "active"
            return
        action = str(seat.action or "none")
        action_source = str(seat.actionSource or "")
        provisional_bet = action == "bet" and action_source in {"", "none", "visible_bet", "held"}
        if (
            action not in {"none", "waiting"}
            and not provisional_bet
            and float(seat.actionConfidence or 0.0) >= 0.40
        ):
            state.last_action = action
            state.last_action_amount = float(seat.actionAmount or seat.currentBet or 0.0)
            state.last_action_source = action_source or "state"
            state.last_action_until = now + ACTION_HOLD_SECONDS
            return
        if state.last_action not in {"none", "waiting"} and now <= state.last_action_until:
            seat.action = state.last_action  # type: ignore[assignment]
            seat.actionAmount = state.last_action_amount
            seat.actionConfidence = max(float(seat.actionConfidence or 0.0), 0.55)
            seat.actionSource = "held_label" if state.last_action_source == "label_ocr" else "held_state"
            metrics["fieldsHeld"].append(f"seat-{index}-action")
            return
        if (
            previous
            and previous.action in {"call", "bet", "raise"}
            and float(previous.currentBet or 0.0) > 0.0
            and float(seat.currentBet or 0.0) >= float(previous.currentBet or 0.0) - 0.01
            and action in {"none", "waiting", "bet"}
        ):
            # Action pills disappear quickly, while the chips remain until the
            # street closes.  The committed wager is therefore the stronger
            # same-street signal and lets the UI keep the exact action rather
            # than degrading Raise/Call back to a generic Bet.
            seat.action = previous.action
            seat.actionAmount = float(previous.actionAmount or previous.currentBet or 0.0)
            seat.actionConfidence = max(float(previous.actionConfidence or 0.0), 0.62)
            seat.actionSource = "held_wager"
            metrics["fieldsHeld"].append(f"seat-{index}-action-wager")
            return
        if (
            previous
            and previous.action in {"fold"}
            and previous.status == "folded"
            and not _has_two_visible_cards(seat)
            and not seat.isAllIn
        ):
            seat.action = "fold"
            seat.status = "folded"

    def _stable_pot(
        self,
        raw_value: float,
        raw_confidence: float,
        previous_value: float,
        metrics: dict[str, Any],
        *,
        hand_reset: bool,
        street_transition: bool,
    ) -> float:
        if hand_reset:
            self._pending_pot = 0.0
            self._pending_pot_hits = 0
            return raw_value if raw_value > 0 and raw_confidence >= 0.55 else 0.0
        if raw_value <= 0 or raw_confidence < 0.55:
            if previous_value > 0:
                return previous_value
            return raw_value
        if previous_value <= 0 or _close_pot(previous_value, raw_value):
            self._pending_pot = 0.0
            self._pending_pot_hits = 0
            return raw_value
        if street_transition and raw_value >= previous_value:
            self._pending_pot = 0.0
            self._pending_pot_hits = 0
            return raw_value
        plausible_growth = previous_value < raw_value <= max(previous_value + 2.0, previous_value * 4.0)
        if plausible_growth:
            self._pending_pot = 0.0
            self._pending_pot_hits = 0
            return raw_value
        if self._pending_pot > 0 and _close_pot(self._pending_pot, raw_value):
            self._pending_pot_hits += 1
        else:
            self._pending_pot = raw_value
            self._pending_pot_hits = 1
        required_hits = 2 if raw_value > previous_value else 3
        if self._pending_pot_hits >= required_hits:
            self._pending_pot = 0.0
            self._pending_pot_hits = 0
            return raw_value
        metrics["fieldsHeld"].append("pot-sanity")
        return previous_value

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

        if observed_stack <= 0 and confidence >= STACK_ZERO_CONFIDENCE:
            _set_record_stack(record, 0.0, confidence)
            accepted = True
            metrics["fieldsAccepted"].append(f"seat-{index}-database-stack-zero")
        elif observed_stack > 0 and confidence >= STACK_ACCEPT_CONFIDENCE:
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
        if confidence >= 0.75 and hits >= STACK_REPLACE_HITS:
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

    def _apply_board_database_to_snapshot(
        self,
        snapshot: GgTableSnapshot,
        now: float,
        metrics: dict[str, Any],
    ) -> None:
        if snapshot.street == "preflop" or not snapshot.board:
            if self._board_database:
                metrics["fieldsAccepted"].append("board-database-clear")
            self._board_database.clear()
            metrics["boardDatabase"] = []
            return

        accepted_board: list[GgCard] = []
        had_board_database = bool(self._board_database)
        requested_street = snapshot.street
        for index, card in enumerate(snapshot.board[:5]):
            existing_record = self._board_database.get(index)
            is_new_slot = had_board_database and (existing_record is None or not existing_record.card_id)
            record = self._board_database.setdefault(index, _CardSlotRecord())
            observed_id = _card_id(card)
            confidence = float(card.confidence or 0.0)
            accepted = False
            if observed_id and confidence >= 0.70:
                accepted = self._accept_board_card_candidate(
                    record,
                    observed_id,
                    confidence,
                    require_confirmation=is_new_slot,
                )
                if accepted:
                    metrics["fieldsAccepted"].append(f"board-{index}-database-card")
            if record.card_id:
                if observed_id and not accepted and observed_id != record.card_id:
                    metrics["fieldsHeld"].append(f"board-{index}-database-card")
                accepted_board.append(_card_from_id(record.card_id, min(max(record.confidence, confidence), 0.92)))
            elif observed_id and accepted:
                accepted_board.append(card)
        snapshot.board = accepted_board
        if requested_street == "showdown" and len(accepted_board) == 5:
            snapshot.street = "showdown"
        else:
            snapshot.street = _street_from_card_count(len(accepted_board))
        metrics["boardDatabase"] = self._board_database_rows()

    def _accept_board_card_candidate(
        self,
        record: _CardSlotRecord,
        card_id: str,
        confidence: float,
        *,
        require_confirmation: bool = False,
    ) -> bool:
        if not record.card_id:
            if not require_confirmation or confidence >= 0.92:
                _set_board_card(record, card_id, confidence)
                return True
            if record.pending_card_id == card_id:
                record.pending_hits += 1
                record.pending_confidence = max(record.pending_confidence, confidence)
            else:
                record.pending_card_id = card_id
                record.pending_hits = 1
                record.pending_confidence = confidence
            if confidence >= 0.72 and record.pending_hits >= 2:
                _set_board_card(record, card_id, confidence)
                return True
            return False
        if card_id == record.card_id:
            record.confidence = max(record.confidence, confidence)
            record.pending_card_id = ""
            record.pending_hits = 0
            record.pending_confidence = 0.0
            return True
        if confidence >= 0.94:
            _set_board_card(record, card_id, confidence)
            return True
        if record.pending_card_id == card_id:
            record.pending_hits += 1
            record.pending_confidence = max(record.pending_confidence, confidence)
        else:
            record.pending_card_id = card_id
            record.pending_hits = 1
            record.pending_confidence = confidence
        if confidence >= 0.78 and record.pending_hits >= 2:
            _set_board_card(record, card_id, confidence)
            return True
        return False

    def _board_database_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "slot": index,
                "card": record.card_id,
                "confidence": round(float(record.confidence or 0.0), 4),
                "pendingCard": record.pending_card_id,
                "pendingHits": int(record.pending_hits),
            }
            for index, record in sorted(self._board_database.items())
        ]


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


def _close_pot(left: float, right: float) -> bool:
    return abs(float(left or 0.0) - float(right or 0.0)) <= max(0.15, max(abs(left), abs(right)) * 0.03)


def _card_id(card: GgCard | None) -> str:
    if not card or card.hidden or not card.rank or not card.suit:
        return ""
    return f"{card.rank}{card.suit}".upper()


def _has_two_visible_cards(seat: GgSeat | None) -> bool:
    if seat is None or len(seat.holeCards) < 2:
        return False
    return all(
        bool(card.visible and not card.hidden and card.rank and card.suit)
        for card in seat.holeCards[:2]
    )


def _card_from_id(card_id: str, confidence: float) -> GgCard:
    value = str(card_id or "").upper()
    suit = value[-1:] if value[-1:] in {"S", "H", "D", "C"} else ""
    rank = value[:-1] if suit else ""
    return GgCard(rank=rank or None, suit=suit or None, visible=bool(rank and suit), hidden=False, confidence=confidence)


def _set_board_card(record: _CardSlotRecord, card_id: str, confidence: float) -> None:
    record.card_id = str(card_id or "").upper()
    record.confidence = float(confidence or 0.0)
    record.updated_at = time.monotonic()
    record.pending_card_id = ""
    record.pending_hits = 0
    record.pending_confidence = 0.0


def _hold_previous_stack(seat: GgSeat, previous: GgSeat | None, metrics: dict[str, Any]) -> None:
    if previous is None:
        return
    index = int(seat.physicalSeatIndex)
    seat.stack = float(previous.stack or 0.0)
    seat.stackConfidence = min(float(previous.stackConfidence or 0.55), 0.60)
    metrics["fieldsHeld"].append(f"seat-{index}-stack")


def _hold_previous_bet(seat: GgSeat, previous: GgSeat | None, metrics: dict[str, Any]) -> None:
    if previous is None:
        return
    index = int(seat.physicalSeatIndex)
    previous_bet = float(previous.currentBet or 0.0)
    seat.currentBet = previous_bet
    seat.committed = max(float(seat.committed or 0.0), previous_bet)
    seat.betConfidence = min(float(previous.betConfidence or 0.55), 0.62)
    metrics["fieldsHeld"].append(f"seat-{index}-bet")


def _is_street_transition(previous: GgTableSnapshot, raw: GgTableSnapshot, hand_reset: bool) -> bool:
    if hand_reset:
        return False
    previous_order = _street_order(previous.street)
    raw_order = _street_order(raw.street)
    return previous_order >= 0 and raw_order > previous_order


def _street_order(street: str) -> int:
    return {
        "unknown": -1,
        "preflop": 0,
        "flop": 1,
        "turn": 2,
        "river": 3,
        "showdown": 4,
    }.get(str(street or "unknown"), -1)


def _street_from_card_count(count: int) -> str:
    if count >= 5:
        return "river"
    if count == 4:
        return "turn"
    if count == 3:
        return "flop"
    if count == 0:
        return "preflop"
    return "unknown"


def _dealer_confidence(snapshot: GgTableSnapshot) -> float:
    metrics = snapshot.metrics if isinstance(snapshot.metrics, dict) else {}
    direct = metrics.get("dealerConfidence")
    if direct is None and isinstance(metrics.get("stabilizer"), dict):
        direct = metrics["stabilizer"].get("dealerConfidence")
    try:
        return max(0.0, min(1.0, float(direct)))
    except (TypeError, ValueError):
        # Calibrated/fallback parsers do not always expose a dealer score. Two
        # matching preflop frames are still required before accepting a move.
        return 0.65


def _amount_is_sane(previous: float, current: float, confidence: float) -> bool:
    if current <= 0:
        return confidence >= 0.78 and previous <= 0.5
    if previous <= 0:
        return True
    ratio = current / max(previous, 0.01)
    if 0.35 <= ratio <= 2.8:
        return True
    return False
