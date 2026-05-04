from __future__ import annotations

import re
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

import numpy as np

from .fast_amount import amount_text_signal, read_amount_fast, read_amount_tight_ocr
from .fixed_profile import FixedGgProfile, FixedSeatProfile, get_fixed_profile
from .models import GgCard, GgSeat, GgTableSnapshot
from .ocr import normalize_amount, read_amount, read_card, read_name
from .profile_matcher import FittedGgProfile, choose_and_fit_profile
from .roi import crop_norm, downscale_hash, draw_roi_overlay, roi_changed, roi_mean_abs_diff
from .table_state import TableStateStabilizer


MIN_FAST_CONFIDENCE = 0.58
CARD_CHANGE_THRESHOLD = 3.5
TEXT_CHANGE_THRESHOLD = 4.0
DEALER_HOLD_SECONDS = 1.5
BAD_FRAME_HOLD_SECONDS = 1.2
MAX_PENDING_OCR = 8
QUICK_REUSE_MIN_FPS = 2.5
PROFILE_REFIT_SECONDS = 30.0


@dataclass
class _FieldCache:
    value: Any = None
    confidence: float = 0.0
    raw: str = ""
    source: str = "unknown"
    image_hash: np.ndarray | None = None
    future: Future[Any] | None = None
    requested_at: float = 0.0
    completed_at: float = 0.0
    known: bool = False
    consecutive_hits: int = 0
    consecutive_misses: int = 0
    candidate_value: Any = None
    candidate_raw: str = ""
    candidate_confidence: float = 0.0
    kind: str = "generic"


class FastGgReader:
    def __init__(self, profile: FixedGgProfile | None = None, *, ocr_workers: int = 5) -> None:
        self.profile = profile or get_fixed_profile()
        self._profile_locked = profile is not None
        self._executor = ThreadPoolExecutor(max_workers=ocr_workers, thread_name_prefix="fast-gg-ocr")
        self._lock = RLock()
        self._fields: dict[str, _FieldCache] = {}
        self._last_snapshot: GgTableSnapshot | None = None
        self._last_snapshot_at = 0.0
        self._last_frame: np.ndarray | None = None
        self._last_quick_hash: np.ndarray | None = None
        self._last_dealer_index = 0
        self._last_dealer_at = 0.0
        self._parse_timestamps: deque[float] = deque(maxlen=240)
        self._parse_durations_ms: deque[float] = deque(maxlen=240)
        self._last_amount_fields: list[dict[str, Any]] = []
        self._last_board_card_debug: list[dict[str, Any]] = []
        self._profile_shape: tuple[int, int] | None = None
        self._profile_fit_signature: tuple[str, float, float, float, float] | None = None
        self._last_profile_fit_at = 0.0
        self._stabilizer = TableStateStabilizer()
        self._last_metrics: dict[str, Any] = {
            "reader": "fast_roi",
            "actualReaderFps": 0.0,
            "parseMs": 0.0,
            "ocrMs": 0.0,
            "fieldsUpdated": 0,
            "fieldsReused": 0,
            "changedRois": 0,
            "confidence": 0.0,
        }
        self._warm_fast_paths()

    def parse(self, frame: np.ndarray) -> GgTableSnapshot | None:
        started_at = time.perf_counter()
        with self._lock:
            if frame is None or frame.size == 0 or frame.ndim < 2:
                metrics = self._new_metrics()
                return self._held_snapshot(metrics, started_at)

            metrics = self._new_metrics()
            if not self._looks_like_fixed_gg_frame(frame):
                return self._held_snapshot(metrics, started_at)

            self._select_profile(frame)
            metrics = self._new_metrics()
            if getattr(self.profile, "fit_score", 1.0) <= 0.0 and (
                (getattr(self.profile, "diagnostics", None) or {}).get("fitError") == "source-not-real-clubgg"
            ):
                metrics["sourceRejected"] = True
                metrics["rejectedReason"] = (getattr(self.profile, "diagnostics", None) or {}).get(
                    "rejectedReason",
                    "source-not-real-clubgg",
                )
                return self._held_snapshot(metrics, started_at)
            quick_hash = self._quick_frame_hash(frame)
            quick_reuse = self._quick_reuse_snapshot(quick_hash, metrics, started_at)
            if quick_reuse is not None:
                return quick_reuse

            self._last_frame = frame
            self._last_quick_hash = quick_hash

            now = time.monotonic()
            title_text, title_confidence = self._read_name_cached(
                "title/blinds",
                crop_norm(frame, self.profile.title_blinds),
                now=now,
                metrics=metrics,
                stale_seconds=15.0,
                min_confidence=0.15,
            )
            small_blind, big_blind = self._parse_blinds(title_text)

            visible_ids: set[str] = set()
            board = self._read_board(frame, visible_ids, metrics)
            pot, pot_confidence, _raw_pot = self._read_amount_cached(
                "pot",
                crop_norm(frame, self.profile.pot),
                now=now,
                metrics=metrics,
                stale_seconds=0.333,
                empty_is_zero=False,
            )
            seats = self._read_seats(frame, visible_ids, now, metrics)
            active_count = sum(1 for seat in seats if seat.active)
            dealer_index = self._detect_dealer(frame, seats, now, metrics)
            confidence = self._snapshot_confidence(seats, pot_confidence, title_confidence, dealer_index)

            snapshot = GgTableSnapshot(
                timestamp=int(time.time() * 1000),
                tableType=self.profile.table_type,
                street=_street_from_board(board),
                pot=pot if pot_confidence >= 0.55 else 0.0,
                smallBlind=small_blind,
                bigBlind=big_blind,
                activePlayerCount=active_count,
                dealerSeatIndex=dealer_index,
                heroSeatIndex=self.profile.hero_seat_index
                if self.profile.hero_seat_index is not None
                and any(seat.physicalSeatIndex == self.profile.hero_seat_index and seat.active for seat in seats)
                else None,
                board=board,
                seats=seats,
                confidence=confidence,
            )
            snapshot.metrics = dict(metrics)
            snapshot = self._stabilizer.stabilize(snapshot, now=now)
            metrics["stabilizer"] = self._stabilizer.get_metrics()
            self._finish_metrics(metrics, started_at, snapshot.confidence)
            snapshot.metrics = {**snapshot.metrics, **metrics}

            if confidence >= MIN_FAST_CONFIDENCE and active_count >= 2:
                self._last_snapshot = snapshot.model_copy(deep=True)
                self._last_snapshot_at = time.monotonic()
            return snapshot if confidence >= MIN_FAST_CONFIDENCE else None

    def get_metrics(self) -> dict[str, Any]:
        with self._lock:
            pending = self._pending_ocr_count()
            metrics = dict(self._last_metrics)
            metrics["ocrPending"] = pending
            metrics["ocrPendingByKind"] = self._pending_ocr_by_kind()
            metrics["cacheFields"] = len(self._fields)
            metrics["lastSnapshotAgeMs"] = (
                round((time.monotonic() - self._last_snapshot_at) * 1000, 2)
                if self._last_snapshot_at
                else None
            )
            metrics["p95ParseMs"] = self._percentile(self._parse_durations_ms, 0.95)
            metrics["maxParseMs"] = round(max(self._parse_durations_ms), 2) if self._parse_durations_ms else 0.0
            return metrics

    def save_roi_overlay(self, output_path: str | Path, frame: np.ndarray | None = None) -> dict[str, Any]:
        with self._lock:
            source = frame if frame is not None else self._last_frame
            if source is None:
                raise RuntimeError("No GG frame has been parsed yet.")
            return draw_roi_overlay(source, self.profile, output_path)

    def save_field_crops(self, output_dir: str | Path, frame: np.ndarray | None = None) -> dict[str, Any]:
        import cv2

        with self._lock:
            source = frame if frame is not None else self._last_frame
            if source is None:
                raise RuntimeError("No GG frame has been parsed yet.")
            output = Path(output_dir)
            output.mkdir(parents=True, exist_ok=True)
            fields: list[dict[str, Any]] = []
            crops_by_key: dict[str, dict[str, Any]] = {}
            for label, roi in self.profile.all_rois():
                crop = crop_norm(source, roi)
                safe_label = re.sub(r"[^0-9A-Za-z_.-]+", "_", label).strip("_") or "field"
                path = output / f"{safe_label}.png"
                cv2.imwrite(str(path), crop)
                cache_key = _label_to_cache_key(label)
                entry = self._fields.get(cache_key) or self._fields.get(label)
                parsed_value = entry.value if entry else None
                if hasattr(parsed_value, "model_dump"):
                    parsed_value = parsed_value.model_dump()
                changed_since_cache = False
                if entry and entry.image_hash is not None:
                    changed_since_cache = roi_changed(entry.image_hash, downscale_hash(crop), TEXT_CHANGE_THRESHOLD)
                accepted = bool(entry and entry.known and not changed_since_cache)
                field_payload = {
                    "key": cache_key,
                    "label": label,
                    "path": str(path),
                    "raw": str(entry.raw or "") if entry else "",
                    "parsedValue": parsed_value,
                    "confidence": round(float(entry.confidence or 0.0), 4) if entry else 0.0,
                    "source": "stale-cache" if changed_since_cache else (str(entry.source or "unread") if entry else "unread"),
                    "roiChanged": bool(changed_since_cache),
                    "accepted": accepted,
                    "rejectReason": (
                        ""
                        if accepted
                        else ("roi-changed-since-cache" if changed_since_cache else "not-read-yet")
                    ),
                }
                fields.append(field_payload)
                crops_by_key[cache_key] = field_payload
            seats = self._field_crop_seat_debug(crops_by_key)
            return {
                "path": str(output),
                "profile": self.profile.name,
                "profileFitScore": round(float(getattr(self.profile, "fit_score", 0.0) or 0.0), 4),
                "fieldCount": len(fields),
                "fields": fields,
                "seats": seats,
            }

    def _field_crop_seat_debug(self, crops_by_key: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        snapshot = self._last_snapshot
        seat_by_index = {int(seat.physicalSeatIndex): seat for seat in snapshot.seats} if snapshot else {}
        seats: list[dict[str, Any]] = []
        for seat_profile in self.profile.seats:
            index = int(seat_profile.index)
            seat = seat_by_index.get(index)
            name = crops_by_key.get(f"seat-{index}-name", {})
            stack = crops_by_key.get(f"seat-{index}-stack", {})
            bet = crops_by_key.get(f"seat-{index}-bet", {})
            action = crops_by_key.get(f"seat-{index}-action", {})
            card1 = self._card_field_debug(index, 0, crops_by_key)
            card2 = self._card_field_debug(index, 1, crops_by_key)
            seats.append({
                "seatIndex": index,
                "state": str(seat.status if seat else "unknown"),
                "active": bool(seat.active) if seat else False,
                "folded": bool(seat and seat.status == "folded"),
                "name": {
                    "path": name.get("path"),
                    "raw": name.get("raw", ""),
                    "parsedName": seat.name if seat else name.get("parsedValue"),
                    "confidence": seat.nameConfidence if seat else name.get("confidence", 0.0),
                    "source": name.get("source", "unread"),
                    "accepted": bool(name.get("accepted")),
                    "rejectReason": name.get("rejectReason", ""),
                },
                "stack": {
                    "path": stack.get("path"),
                    "raw": stack.get("raw", ""),
                    "parsedBbAmount": seat.stack if seat else stack.get("parsedValue"),
                    "confidence": seat.stackConfidence if seat else stack.get("confidence", 0.0),
                    "source": stack.get("source", "unread"),
                    "accepted": bool(stack.get("accepted")),
                    "rejectReason": stack.get("rejectReason", ""),
                },
                "bet": {
                    "path": bet.get("path"),
                    "raw": bet.get("raw", ""),
                    "parsedBbAmount": seat.currentBet if seat else bet.get("parsedValue"),
                    "confidence": seat.betConfidence if seat else bet.get("confidence", 0.0),
                    "source": bet.get("source", "unread"),
                    "accepted": bool(bet.get("accepted")),
                    "rejectReason": bet.get("rejectReason", ""),
                },
                "action": {
                    "path": action.get("path"),
                    "raw": action.get("raw", ""),
                    "parsedAction": seat.action if seat else action.get("parsedValue"),
                    "actionAmount": seat.actionAmount if seat else None,
                    "confidence": seat.actionConfidence if seat else action.get("confidence", 0.0),
                    "source": seat.actionSource if seat and seat.actionSource else action.get("source", "state_inference"),
                    "accepted": bool(action.get("accepted")) or bool(seat and seat.action != "none"),
                    "rejectReason": action.get("rejectReason", ""),
                },
                "card1": card1,
                "card2": card2,
            })
        return seats

    def _card_field_debug(
        self,
        seat_index: int,
        card_index: int,
        crops_by_key: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        key = f"seat-{seat_index}-card-{card_index}"
        crop = crops_by_key.get(key, {})
        entry = self._fields.get(key)
        card = entry.value if entry else None
        result = "none"
        if isinstance(card, GgCard):
            if card.hidden:
                result = "hidden"
            elif card.visible and card.rank and card.suit:
                result = f"{card.rank}{card.suit}"
        return {
            "path": crop.get("path"),
            "result": result,
            "hidden": bool(isinstance(card, GgCard) and card.hidden),
            "visible": bool(isinstance(card, GgCard) and card.visible and not card.hidden),
            "confidence": round(float(card.confidence if isinstance(card, GgCard) else entry.confidence if entry else 0.0), 4),
            "source": crop.get("source", "visual_card_detection"),
            "accepted": bool(crop.get("accepted")),
            "rejectReason": crop.get("rejectReason", ""),
        }

    def _warm_fast_paths(self) -> None:
        try:
            import cv2

            sample = np.zeros((36, 96, 3), dtype=np.uint8)
            cv2.putText(sample, "1BB", (4, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 210, 230), 1, cv2.LINE_AA)
            downscale_hash(sample)
            amount_text_signal(sample)
            read_amount_fast(sample)
            read_card(np.zeros((64, 40, 3), dtype=np.uint8))
            _dealer_signal(sample)
        except Exception:
            return

    def _new_metrics(self) -> dict[str, Any]:
        profile_fit_score = float(getattr(self.profile, "fit_score", 0.0) or 0.0)
        profile_diagnostics = getattr(self.profile, "diagnostics", None) or {}
        return {
            "reader": "fast_roi",
            "profile": self.profile.name,
            "profileFitScore": round(profile_fit_score, 4),
            "profileOffset": {
                "x": round(float(getattr(self.profile, "offset_x", 0.0) or 0.0), 4),
                "y": round(float(getattr(self.profile, "offset_y", 0.0) or 0.0), 4),
                "scaleX": round(float(getattr(self.profile, "scale_x", 1.0) or 1.0), 4),
                "scaleY": round(float(getattr(self.profile, "scale_y", 1.0) or 1.0), 4),
            },
            "profileDiagnostics": profile_diagnostics,
            "parseMs": 0.0,
            "ocrMs": 0.0,
            "actualReaderFps": self._actual_fps(),
            "fieldsUpdated": 0,
            "fieldsReused": 0,
            "changedRois": 0,
            "changedRoiLabels": [],
            "ocrQueued": 0,
            "ocrCompleted": 0,
            "ocrPending": 0,
            "confidence": 0.0,
            "amountFields": [],
            "boardCardDebug": [],
            "seatDebug": [],
        }

    def _select_profile(self, frame: np.ndarray) -> None:
        now = time.monotonic()
        shape = tuple(int(value) for value in frame.shape[:2])
        if (
            self._profile_shape == shape
            and now - self._last_profile_fit_at < PROFILE_REFIT_SECONDS
            and isinstance(self.profile, FittedGgProfile)
        ):
            return
        if self._profile_locked:
            selected = choose_and_fit_profile(frame, self.profile)
        else:
            preferred = get_fixed_profile(frame_shape=frame.shape)
            selected = choose_and_fit_profile(frame, preferred)
        signature = selected.fit_signature
        self._profile_shape = shape
        self._last_profile_fit_at = now
        if signature == self._profile_fit_signature:
            self.profile = selected
            return
        self.profile = selected
        self._profile_fit_signature = signature
        self._last_quick_hash = None
        self._last_snapshot = None
        self._last_snapshot_at = 0.0
        self._last_amount_fields = []
        self._last_board_card_debug = []
        self._fields.clear()

    def _finish_metrics(self, metrics: dict[str, Any], started_at: float, confidence: float) -> None:
        parse_ms = round((time.perf_counter() - started_at) * 1000, 2)
        now = time.monotonic()
        self._parse_timestamps.append(now)
        self._parse_durations_ms.append(parse_ms)
        metrics["parseMs"] = parse_ms
        metrics["actualReaderFps"] = self._actual_fps()
        metrics["ocrPending"] = self._pending_ocr_count()
        metrics["confidence"] = round(float(confidence), 4)
        if not metrics.get("amountFields"):
            metrics["amountFields"] = self._amount_field_cache_debug()
        if isinstance(metrics.get("amountFields"), list) and metrics["amountFields"]:
            self._last_amount_fields = [dict(item) for item in metrics["amountFields"]]
        else:
            metrics["amountFields"] = list(self._last_amount_fields)
        if not metrics.get("boardCardDebug"):
            metrics["boardCardDebug"] = self._board_card_cache_debug()
        if isinstance(metrics.get("boardCardDebug"), list) and metrics["boardCardDebug"]:
            self._last_board_card_debug = [dict(item) for item in metrics["boardCardDebug"]]
        else:
            metrics["boardCardDebug"] = list(self._last_board_card_debug)
        self._last_metrics = dict(metrics)

    def _amount_field_cache_debug(self) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        for key, entry in self._fields.items():
            if key != "pot" and "-stack" not in key and "-bet" not in key:
                continue
            fields.append({
                "key": key,
                "raw": str(entry.raw or ""),
                "value": round(float(entry.value or 0.0), 4),
                "confidence": round(float(entry.confidence or 0.0), 4),
                "source": str(entry.source or "cache"),
                "roiChanged": False,
            })
        return fields[:64]

    def _board_card_cache_debug(self) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for index in range(len(self.profile.board)):
            entry = self._fields.get(f"board-{index}")
            card = entry.value if entry else None
            cards.append(_card_debug_payload(index, card, float(entry.confidence or 0.0) if entry else 0.0, False))
        return cards

    def _held_snapshot(self, metrics: dict[str, Any], started_at: float) -> GgTableSnapshot | None:
        now = time.monotonic()
        if self._last_snapshot is None or now - self._last_snapshot_at > BAD_FRAME_HOLD_SECONDS:
            self._finish_metrics(metrics, started_at, 0.0)
            return None
        held = self._last_snapshot.model_copy(deep=True)
        held.timestamp = int(time.time() * 1000)
        held.confidence = min(float(held.confidence), 0.72)
        metrics["heldSnapshot"] = True
        self._finish_metrics(metrics, started_at, held.confidence)
        held.metrics = dict(metrics)
        return held

    def _quick_reuse_snapshot(
        self,
        quick_hash: np.ndarray,
        metrics: dict[str, Any],
        started_at: float,
    ) -> GgTableSnapshot | None:
        if self._last_snapshot is None or self._last_quick_hash is None:
            return None
        if self._pending_ocr_count() > 0:
            return None
        if self._actual_fps() < QUICK_REUSE_MIN_FPS:
            return None
        if not np.array_equal(quick_hash, self._last_quick_hash):
            return None

        snapshot = self._last_snapshot.model_copy(deep=True)
        snapshot.timestamp = int(time.time() * 1000)
        metrics["quickReuse"] = True
        metrics["fieldsReused"] = len(self._fields)
        self._finish_metrics(metrics, started_at, snapshot.confidence)
        snapshot.metrics = dict(metrics)
        self._last_snapshot = snapshot.model_copy(deep=True)
        self._last_snapshot_at = time.monotonic()
        return snapshot

    def _quick_frame_hash(self, frame: np.ndarray) -> np.ndarray:
        sample = frame[::24, ::24, :3] if frame.ndim == 3 else frame[::24, ::24]
        return np.ascontiguousarray(sample)

    def _looks_like_fixed_gg_frame(self, frame: np.ndarray) -> bool:
        import cv2

        center = crop_norm(frame, (0.08, 0.18, 0.84, 0.66))
        if center.size == 0 or center.ndim < 3:
            return False
        channels = center[::4, ::4, :3]
        hsv = cv2.cvtColor(channels, cv2.COLOR_BGR2HSV)
        green_mask = cv2.inRange(hsv, np.array([35, 35, 30]), np.array([95, 255, 240]))
        green_ratio = float((green_mask > 0).mean())
        gray = cv2.cvtColor(channels, cv2.COLOR_BGR2GRAY)
        dark_ratio = float((gray < 55).mean())
        return green_ratio > 0.08 and dark_ratio > 0.10

    def _read_board(self, frame: np.ndarray, visible_ids: set[str], metrics: dict[str, Any]) -> list[GgCard]:
        cards: list[GgCard] = []
        for index, roi in enumerate(self.profile.board):
            card = self._read_card_cached(
                f"board-{index}",
                crop_norm(frame, roi),
                allow_hidden=False,
                metrics=metrics,
                board_index=index,
            )
            if not card:
                continue
            card_id = _card_id(card)
            if card_id in visible_ids:
                continue
            visible_ids.add(card_id)
            cards.append(card)
        return cards

    def _read_seats(
        self,
        frame: np.ndarray,
        visible_ids: set[str],
        now: float,
        metrics: dict[str, Any],
    ) -> list[GgSeat]:
        seats: list[GgSeat] = []
        for seat_profile in self.profile.seats:
            seats.append(self._read_seat(frame, seat_profile, visible_ids, now, metrics))
        return seats

    def _read_seat(
        self,
        frame: np.ndarray,
        seat_profile: FixedSeatProfile,
        visible_ids: set[str],
        now: float,
        metrics: dict[str, Any],
    ) -> GgSeat:
        hole_cards: list[GgCard] = []
        for card_index, card_roi in enumerate(seat_profile.cards):
            card = self._read_card_cached(
                f"seat-{seat_profile.index}-card-{card_index}",
                crop_norm(frame, card_roi),
                allow_hidden=True,
                metrics=metrics,
            )
            if not card:
                continue
            card_id = _card_id(card)
            if card_id:
                if card_id in visible_ids:
                    continue
                visible_ids.add(card_id)
            hole_cards.append(card)
        if len(hole_cards) == 1 and hole_cards[0].hidden:
            # Opponent hole cards are rendered as a pair of backs. If one back
            # is strong and the neighboring ROI is slightly blurred, keep the
            # semantic table state as X/X instead of flickering to a one-card hand.
            hole_cards.append(GgCard(hidden=True, visible=False, display="X", confidence=min(0.72, hole_cards[0].confidence)))

        stack_crop = crop_norm(frame, seat_profile.stack)
        bet_crop = crop_norm(frame, seat_profile.bet)
        active_crop = crop_norm(frame, seat_profile.active)
        stack_signal = _cyan_signal(stack_crop)
        stack_text_signal = amount_text_signal(stack_crop)
        bet_text_signal = amount_text_signal(bet_crop)
        has_two_hole_cards = len(hole_cards) >= 2
        has_clear_stack_text = stack_text_signal >= 0.025
        has_clear_bet_text = bet_text_signal >= 0.020
        has_clear_cyan_stack = stack_signal >= 0.025
        empty_take_seat = _looks_like_empty_take_seat(
            active_crop,
            has_two_hole_cards=has_two_hole_cards,
            stack_signal=stack_signal,
            stack_text_signal=stack_text_signal,
            bet_text_signal=bet_text_signal,
        )
        likely_active = bool(
            not empty_take_seat
            and (has_two_hole_cards or has_clear_stack_text or has_clear_bet_text or has_clear_cyan_stack)
        )

        stack = 0.0
        stack_confidence = 0.0
        current_bet = 0.0
        bet_confidence = 0.0
        name = ""
        name_confidence = 0.0
        detected_action = "none"
        action_confidence = 0.0
        if likely_active:
            stack, stack_confidence, _raw_stack = self._read_amount_cached(
                f"seat-{seat_profile.index}-stack",
                stack_crop,
                now=now,
                metrics=metrics,
                stale_seconds=0.75,
                empty_is_zero=False,
            )
            current_bet, bet_confidence, _raw_bet = self._read_amount_cached(
                f"seat-{seat_profile.index}-bet",
                bet_crop,
                now=now,
                metrics=metrics,
                stale_seconds=0.333,
                empty_is_zero=True,
            )
            name, name_confidence = self._read_name_cached(
                f"seat-{seat_profile.index}-name",
                crop_norm(frame, seat_profile.name),
                now=now,
                metrics=metrics,
                stale_seconds=20.0,
                min_confidence=0.18,
            )
            action_roi = seat_profile.action or seat_profile.bet
            detected_action, action_confidence = self._read_action_cached(
                f"seat-{seat_profile.index}-action",
                crop_norm(frame, action_roi),
                now=now,
                metrics=metrics,
                stale_seconds=1.0,
            )

        name_with_money = bool(name_confidence >= 0.25 and (stack_confidence >= 0.50 or bet_confidence >= 0.50))
        active = bool(
            not empty_take_seat
            and (
                likely_active
                or name_with_money
                or stack_confidence >= 0.55
                or bet_confidence >= 0.55
                or stack > 0
                or current_bet > 0
            )
        )

        current_bet = current_bet if bet_confidence >= 0.50 else 0.0
        stack = stack if stack_confidence >= 0.50 else 0.0
        if detected_action != "none" and action_confidence >= 0.25:
            action = detected_action
            action_source = "label_ocr"
        elif current_bet > 0:
            action = "bet"
            action_source = "visible_bet"
        else:
            action = "none"
            action_source = "none"
        confidence = _estimate_confidence([
            min(0.90, stack_signal * 16),
            min(0.90, stack_text_signal * 10),
            min(0.90, bet_text_signal * 12),
            stack_confidence,
            bet_confidence,
            name_confidence,
            action_confidence,
            *[card.confidence for card in hole_cards],
        ])
        if active and confidence < 0.72:
            confidence = 0.72
        if empty_take_seat:
            metrics["emptyTakeSeats"] = int(metrics.get("emptyTakeSeats") or 0) + 1
        seat_debug = metrics.get("seatDebug")
        if isinstance(seat_debug, list):
            seat_debug.append({
                "index": seat_profile.index,
                "activeSignal": round(float(_active_signal(active_crop)), 4),
                "emptyTakeSeat": bool(empty_take_seat),
                "stackTextSignal": round(float(stack_text_signal), 4),
                "stackCyanSignal": round(float(stack_signal), 4),
                "betTextSignal": round(float(bet_text_signal), 4),
                "card0Present": bool(len(hole_cards) >= 1),
                "card1Present": bool(len(hole_cards) >= 2),
                "nameUnknown": bool(active and not name),
                "actionRaw": detected_action,
                "actionConfidence": round(float(action_confidence), 4),
            })

        return GgSeat(
            physicalSeatIndex=seat_profile.index,
            active=active,
            name=_clean_player_name(name) if active else "",
            nameConfidence=name_confidence,
            stack=stack,
            stackConfidence=stack_confidence,
            currentBet=current_bet,
            betConfidence=bet_confidence,
            action=action,
            actionAmount=current_bet if current_bet > 0 else 0.0,
            actionConfidence=bet_confidence if current_bet > 0 else 0.0,
            actionSource=action_source,
            status="active" if active else "empty",
            isHero=bool(active and self.profile.hero_seat_index == seat_profile.index),
            holeCards=hole_cards if active else [],
            confidence=confidence if active else 0.92,
        )

    def _read_card_cached(
        self,
        key: str,
        crop: np.ndarray,
        *,
        allow_hidden: bool,
        metrics: dict[str, Any],
        board_index: int | None = None,
    ) -> GgCard | None:
        entry = self._fields.setdefault(key, _FieldCache())
        new_hash = downscale_hash(crop)
        changed = roi_changed(entry.image_hash, new_hash, CARD_CHANGE_THRESHOLD) if entry.image_hash is not None else True
        if changed:
            self._mark_changed(metrics, key)
        if changed or not entry.known:
            data = read_card(crop)
            entry.image_hash = new_hash
            entry.known = True
            entry.completed_at = time.monotonic()
            entry.value = self._card_from_data(data, allow_hidden=allow_hidden)
            entry.confidence = float(data.get("confidence") or 0.0)
            metrics["fieldsUpdated"] += 1
        else:
            metrics["fieldsReused"] += 1
        if board_index is not None:
            board_debug = metrics.get("boardCardDebug")
            if isinstance(board_debug, list):
                board_debug.append(_card_debug_payload(board_index, entry.value, float(entry.confidence or 0.0), changed))
        return entry.value

    def _card_from_data(self, data: dict[str, object], *, allow_hidden: bool) -> GgCard | None:
        confidence = float(data.get("confidence") or 0.0)
        if allow_hidden and data.get("hidden") and confidence >= 0.70:
            return GgCard(hidden=True, visible=False, display=str(data.get("display") or "X"), confidence=confidence)
        rank = data.get("rank")
        suit = data.get("suit")
        if rank and suit and confidence >= 0.70:
            return GgCard(rank=str(rank), suit=str(suit), visible=True, hidden=False, confidence=confidence)
        return None

    def _read_amount_cached(
        self,
        key: str,
        crop: np.ndarray,
        *,
        now: float,
        metrics: dict[str, Any],
        stale_seconds: float,
        empty_is_zero: bool,
    ) -> tuple[float, float, str]:
        entry = self._fields.setdefault(key, _FieldCache(value=0.0))
        self._consume_amount_future(key, entry, metrics)
        new_hash = downscale_hash(crop)
        changed = roi_changed(entry.image_hash, new_hash, TEXT_CHANGE_THRESHOLD) if entry.image_hash is not None else True
        if changed:
            self._mark_changed(metrics, key)
        if entry.future is not None:
            metrics["fieldsReused"] += 1
            entry.image_hash = new_hash
            self._record_amount_debug(metrics, key, entry, changed, "cache_pending")
            return float(entry.value or 0.0), float(entry.confidence or 0.0), str(entry.raw or "")
        retry_window_due = (
            entry.future is None
            and float(entry.confidence or 0.0) < 0.50
            and now - float(entry.requested_at or 0.0) >= max(5.0, stale_seconds)
        )
        if not changed and entry.known and not retry_window_due:
            metrics["fieldsReused"] += 1
            entry.image_hash = new_hash
            self._record_amount_debug(metrics, key, entry, changed, "cache")
            return float(entry.value or 0.0), float(entry.confidence or 0.0), str(entry.raw or "")

        signal = amount_text_signal(crop)
        if empty_is_zero and signal < 0.008:
            entry.consecutive_misses += 1
            if float(entry.value or 0.0) > 0.0 and entry.consecutive_misses < 2:
                metrics["fieldsReused"] += 1
                entry.image_hash = new_hash
                entry.source = "held_empty_pending"
                self._record_amount_debug(metrics, key, entry, changed, "held_empty_pending")
                return float(entry.value or 0.0), min(float(entry.confidence or 0.0), 0.62), str(entry.raw or "")
            if changed or not entry.known or float(entry.value or 0.0) != 0.0:
                entry.value = 0.0
                entry.confidence = 0.92
                entry.raw = ""
                entry.source = "empty"
                entry.known = True
                entry.completed_at = now
                metrics["fieldsUpdated"] += 1
            else:
                metrics["fieldsReused"] += 1
            entry.image_hash = new_hash
            self._record_amount_debug(metrics, key, entry, changed, "empty")
            return 0.0, 0.92, ""
        entry.consecutive_misses = 0

        retry_due = retry_window_due and signal >= 0.008
        should_refresh = changed or not entry.known or retry_due
        if should_refresh:
            fast_started_at = time.perf_counter()
            amount, confidence, raw = read_amount_fast(crop)
            metrics["ocrMs"] += round((time.perf_counter() - fast_started_at) * 1000, 2)
            fast_accept_confidence = 0.80 if key == "pot" else 0.88
            if amount > 0 and confidence >= fast_accept_confidence:
                if self._apply_amount_candidate(entry, key, amount, confidence, raw, "fast_amount", now):
                    metrics["fieldsUpdated"] += 1
                else:
                    metrics["fieldsReused"] += 1
            elif key != "pot" and signal >= 0.020 and not entry.known:
                if entry.future is None and self._can_queue_ocr(now, priority=False):
                    entry.future = self._executor.submit(_read_amount_source, crop.copy())
                    entry.requested_at = now
                    metrics["ocrQueued"] += 1
                    entry.source = "queued_tight_ocr"
                    entry.known = True
                    entry.completed_at = now
                    metrics["fieldsUpdated"] += 1
                else:
                    metrics["fieldsReused"] += 1
            elif key == "pot" and (not entry.known or float(entry.value or 0.0) <= 0.0):
                tight_started_at = time.perf_counter()
                value, tight_confidence, tight_raw = read_amount_tight_ocr(
                    crop,
                    squash_bb_suffix=True,
                    quick=True,
                )
                metrics["ocrMs"] += round((time.perf_counter() - tight_started_at) * 1000, 2)
                suspicious_tight_pot = (
                    float(value or 0.0) > 20
                    and not re.search(r"(?i)[.KMB]|BB", str(tight_raw or ""))
                )
                if value > 0 and tight_confidence >= 0.65 and not suspicious_tight_pot:
                    if self._apply_amount_candidate(entry, key, value, tight_confidence, tight_raw, "tight_ocr", now):
                        metrics["fieldsUpdated"] += 1
                    else:
                        metrics["fieldsReused"] += 1
                elif entry.future is None and self._can_queue_ocr(now, priority=True):
                    entry.future = self._executor.submit(_read_pot_amount_source, crop.copy())
                    entry.requested_at = now
                    entry.source = "queued_tight_ocr"
                    entry.known = True
                    entry.completed_at = now
                    metrics["ocrQueued"] += 1
                    metrics["fieldsUpdated"] += 1
                else:
                    metrics["fieldsReused"] += 1
            elif entry.future is None and self._can_queue_ocr(now, priority=key == "pot"):
                reader = _read_pot_amount_source if key == "pot" else _read_amount_source
                entry.future = self._executor.submit(reader, crop.copy())
                entry.requested_at = now
                metrics["ocrQueued"] += 1
                if not entry.source or entry.source == "unknown":
                    entry.source = "queued_tight_ocr" if key == "pot" else "queued_tesseract"
                if not entry.known:
                    entry.known = True
                    entry.completed_at = now
                    metrics["fieldsUpdated"] += 1
                else:
                    metrics["fieldsReused"] += 1
            else:
                if not entry.known:
                    entry.known = True
                    entry.completed_at = now
                    entry.source = "fast_amount_low_confidence"
                metrics["fieldsReused"] += 1
        else:
            metrics["fieldsReused"] += 1
        entry.image_hash = new_hash
        self._record_amount_debug(metrics, key, entry, changed, entry.source or "cache")
        return float(entry.value or 0.0), float(entry.confidence or 0.0), str(entry.raw or "")

    def _consume_amount_future(self, key: str, entry: _FieldCache, metrics: dict[str, Any]) -> None:
        future = entry.future
        if future is None or not future.done():
            return
        try:
            result = future.result()
        except Exception:
            result = (0.0, 0.0, "", "tesseract_error")
        if isinstance(result, tuple) and len(result) >= 4:
            value, confidence, raw, source = result[:4]
        else:
            value, confidence, raw = result
            source = "tesseract"
        entry.future = None
        suspicious_pot = key == "pot" and float(value or 0.0) > 20 and not re.search(r"(?i)[.KMB]|BB", str(raw or ""))
        if value > 0 and confidence >= 0.40 and not suspicious_pot:
            if self._apply_amount_candidate(
                entry,
                key,
                float(value),
                float(confidence),
                str(raw or ""),
                str(source or "tesseract"),
                time.monotonic(),
            ):
                metrics["fieldsUpdated"] += 1
            else:
                metrics["fieldsReused"] += 1
        metrics["ocrCompleted"] += 1

    def _apply_amount_candidate(
        self,
        entry: _FieldCache,
        key: str,
        value: float,
        confidence: float,
        raw: str,
        source: str,
        now: float,
    ) -> bool:
        previous = float(entry.value or 0.0)
        field_is_stack = "-stack" in key
        field_is_pot = key == "pot"
        if value <= 0 or confidence <= 0:
            return False
        if field_is_pot and value > 500 and not re.search(r"(?i)[.KMB]|BB", raw or ""):
            return False
        if previous > 0 and (field_is_stack or field_is_pot):
            ratio = value / max(previous, 0.01)
            suspicious_jump = ratio < 0.35 or ratio > 2.8
            if suspicious_jump and confidence < 0.92:
                candidate_matches = (
                    entry.candidate_value is not None
                    and _close_amount(float(entry.candidate_value), value)
                )
                entry.candidate_value = value
                entry.candidate_raw = raw
                entry.candidate_confidence = confidence
                if not candidate_matches:
                    entry.source = f"{source}_candidate"
                    return False
        entry.value = float(value)
        entry.confidence = float(confidence)
        entry.raw = str(raw or "")
        entry.source = str(source or "tesseract")
        entry.known = True
        entry.completed_at = now
        entry.consecutive_hits += 1
        entry.candidate_value = None
        entry.candidate_raw = ""
        entry.candidate_confidence = 0.0
        return True

    def _record_amount_debug(
        self,
        metrics: dict[str, Any],
        key: str,
        entry: _FieldCache,
        roi_changed_value: bool,
        source: str,
    ) -> None:
        amount_fields = metrics.get("amountFields")
        if not isinstance(amount_fields, list) or len(amount_fields) >= 64:
            return
        amount_fields.append({
            "key": key,
            "raw": str(entry.raw or ""),
            "value": round(float(entry.value or 0.0), 4),
            "confidence": round(float(entry.confidence or 0.0), 4),
            "source": source,
            "roiChanged": bool(roi_changed_value),
        })

    def _read_name_cached(
        self,
        key: str,
        crop: np.ndarray,
        *,
        now: float,
        metrics: dict[str, Any],
        stale_seconds: float,
        min_confidence: float,
    ) -> tuple[str, float]:
        entry = self._fields.setdefault(key, _FieldCache(value=""))
        self._consume_name_future(entry, metrics, min_confidence=min_confidence)
        new_hash = downscale_hash(crop)
        diff = roi_mean_abs_diff(entry.image_hash, new_hash)
        changed = diff > TEXT_CHANGE_THRESHOLD if entry.image_hash is not None else True
        if changed:
            self._mark_changed(metrics, key)
        missing_retry_due = not entry.value and now - float(entry.requested_at or 0.0) >= 1.0
        stale_known_due = bool(entry.value) and now - entry.completed_at >= stale_seconds
        should_refresh = changed or not entry.known or missing_retry_due or stale_known_due
        if should_refresh and entry.future is None and self._can_queue_ocr(now):
            entry.future = self._executor.submit(read_name, crop.copy())
            entry.requested_at = now
            metrics["ocrQueued"] += 1
            if not entry.known:
                entry.known = True
                entry.completed_at = now
                metrics["fieldsUpdated"] += 1
            else:
                metrics["fieldsReused"] += 1
        else:
            metrics["fieldsReused"] += 1
        entry.image_hash = new_hash
        return str(entry.value or ""), float(entry.confidence or 0.0)

    def _consume_name_future(self, entry: _FieldCache, metrics: dict[str, Any], *, min_confidence: float) -> None:
        future = entry.future
        if future is None or not future.done():
            return
        try:
            value, confidence = future.result()
        except Exception:
            value, confidence = "", 0.0
        entry.future = None
        cleaned = _clean_player_name(value)
        if cleaned and confidence >= min_confidence:
            entry.value = cleaned
            entry.confidence = float(confidence)
            entry.known = True
            entry.completed_at = time.monotonic()
            metrics["fieldsUpdated"] += 1
        else:
            entry.completed_at = time.monotonic()
        metrics["ocrCompleted"] += 1

    def _read_action_cached(
        self,
        key: str,
        crop: np.ndarray,
        *,
        now: float,
        metrics: dict[str, Any],
        stale_seconds: float,
    ) -> tuple[str, float]:
        entry = self._fields.setdefault(key, _FieldCache(value="none"))
        self._consume_action_future(entry, metrics)
        new_hash = downscale_hash(crop)
        changed = roi_changed(entry.image_hash, new_hash, TEXT_CHANGE_THRESHOLD) if entry.image_hash is not None else True
        if changed:
            self._mark_changed(metrics, key)
        should_refresh = changed or not entry.known or now - entry.completed_at >= stale_seconds
        if should_refresh and entry.future is None and self._can_queue_ocr(now):
            entry.future = self._executor.submit(read_name, crop.copy())
            entry.requested_at = now
            metrics["ocrQueued"] += 1
            metrics["fieldsReused"] += 1 if entry.known else 0
            if not entry.known:
                entry.known = True
                entry.completed_at = now
                metrics["fieldsUpdated"] += 1
        else:
            metrics["fieldsReused"] += 1
        entry.image_hash = new_hash
        return str(entry.value or "none"), float(entry.confidence or 0.0)

    def _consume_action_future(self, entry: _FieldCache, metrics: dict[str, Any]) -> None:
        future = entry.future
        if future is None or not future.done():
            return
        try:
            value, confidence = future.result()
        except Exception:
            value, confidence = "", 0.0
        entry.future = None
        action = _normalize_action_text(value)
        if action != "none" and confidence >= 0.18:
            entry.value = action
            entry.confidence = float(confidence)
            entry.known = True
            entry.completed_at = time.monotonic()
            metrics["fieldsUpdated"] += 1
        else:
            entry.value = "none"
            entry.confidence = 0.0
            entry.completed_at = time.monotonic()
        metrics["ocrCompleted"] += 1

    def _detect_dealer(
        self,
        frame: np.ndarray,
        seats: list[GgSeat],
        now: float,
        metrics: dict[str, Any],
    ) -> int:
        best_index = None
        best_score = 0.0
        for seat in self.profile.seats:
            crop = crop_norm(frame, seat.dealer)
            score = _dealer_signal(crop)
            if score > best_score:
                best_index = seat.index
                best_score = score
        if best_index is not None and best_score >= 0.10:
            self._last_dealer_index = int(best_index)
            self._last_dealer_at = now
            metrics["dealerConfidence"] = round(best_score, 4)
            return int(best_index)

        active_indexes = [seat.physicalSeatIndex for seat in seats if seat.active]
        if now - self._last_dealer_at <= DEALER_HOLD_SECONDS and self._last_dealer_index in active_indexes:
            metrics["dealerHeld"] = True
            return self._last_dealer_index
        return active_indexes[0] if active_indexes else self._last_dealer_index

    def _parse_blinds(self, title_text: str) -> tuple[float, float]:
        value = title_text or ""
        slash_matches = re.findall(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", value)
        if slash_matches:
            small, big = slash_matches[-1]
            return float(small), float(big)
        dash_matches = re.findall(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", value)
        if dash_matches:
            small, big = dash_matches[-1]
            return float(small), float(big)
        return self.profile.small_blind, self.profile.big_blind

    def _snapshot_confidence(
        self,
        seats: list[GgSeat],
        pot_confidence: float,
        title_confidence: float,
        dealer_index: int,
    ) -> float:
        active = [seat for seat in seats if seat.active]
        values = [seat.confidence for seat in active]
        values.append(pot_confidence)
        values.append(title_confidence)
        if dealer_index >= 0:
            values.append(0.80)
        confidence = _estimate_confidence(values)
        if len(active) >= 2:
            confidence = max(confidence, 0.82)
        return min(0.98, confidence)

    def _actual_fps(self) -> float:
        now = time.monotonic()
        cutoff = now - 5.0
        while self._parse_timestamps and self._parse_timestamps[0] < cutoff:
            self._parse_timestamps.popleft()
            if self._parse_durations_ms:
                self._parse_durations_ms.popleft()
        if len(self._parse_timestamps) < 2:
            return 0.0
        span = max(0.25, self._parse_timestamps[-1] - self._parse_timestamps[0])
        return round((len(self._parse_timestamps) - 1) / span, 3)

    def _can_queue_ocr(self, now: float, *, priority: bool = False) -> bool:
        if self._pending_ocr_count() >= MAX_PENDING_OCR:
            return False
        if priority:
            return True
        if not self._parse_timestamps:
            return True
        current_fps = self._actual_fps()
        if current_fps and current_fps > 4.5:
            return False
        return True

    def _pending_ocr_count(self) -> int:
        return sum(1 for entry in self._fields.values() if entry.future is not None)

    def _pending_ocr_by_kind(self) -> dict[str, int]:
        counts = {"amount": 0, "name": 0, "action": 0, "card": 0, "other": 0}
        for key, entry in self._fields.items():
            if entry.future is None:
                continue
            if key == "pot" or "-stack" in key or "-bet" in key:
                counts["amount"] += 1
            elif "-name" in key or key == "title/blinds":
                counts["name"] += 1
            elif "-action" in key:
                counts["action"] += 1
            elif "-card-" in key or key.startswith("board-"):
                counts["card"] += 1
            else:
                counts["other"] += 1
        return counts

    def _percentile(self, values: deque[float], percentile: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
        return round(float(ordered[index]), 2)

    def _mark_changed(self, metrics: dict[str, Any], label: str) -> None:
        metrics["changedRois"] += 1
        changed_labels = metrics.get("changedRoiLabels")
        if isinstance(changed_labels, list) and len(changed_labels) < 24:
            changed_labels.append(label)


def _cyan_signal(image: np.ndarray) -> float:
    if image.size == 0 or image.ndim < 3:
        return 0.0
    channels = image[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    mask = (blue > 90) & (green > 90) & (red < 140) & ((blue - red) > 25) & ((green - red) > 25)
    return float(mask.mean())


def _read_amount_source(image: np.ndarray) -> tuple[float, float, str, str]:
    amount, confidence, raw = read_amount_tight_ocr(image, squash_bb_suffix=True)
    if amount > 0 and confidence > 0:
        return amount, confidence, raw, "tight_ocr"
    amount, confidence, raw = read_amount(image)
    return amount, confidence, raw, "tesseract"


def _read_pot_amount_source(image: np.ndarray) -> tuple[float, float, str, str]:
    amount, confidence, raw = read_amount_tight_ocr(image, squash_bb_suffix=True)
    if amount > 0 and confidence > 0:
        return amount, confidence, raw, "tight_ocr"
    amount, confidence, raw = read_amount(image)
    return amount, confidence, raw, "tesseract"


def _active_signal(image: np.ndarray) -> float:
    if image.size == 0 or image.ndim < 3:
        return 0.0
    channels = image[:, :, :3]
    gray = np.mean(channels, axis=2)
    bright = float((gray > 120).mean())
    cyan = _cyan_signal(image)
    return min(1.0, bright * 1.5 + cyan * 8)


def _looks_like_empty_take_seat(
    image: np.ndarray,
    *,
    has_two_hole_cards: bool,
    stack_signal: float,
    stack_text_signal: float,
    bet_text_signal: float,
) -> bool:
    if has_two_hole_cards or stack_signal >= 0.025 or stack_text_signal >= 0.025 or bet_text_signal >= 0.020:
        return False
    if image.size == 0 or image.ndim < 3:
        return True
    channels = image[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    white_ratio = float(((red > 165) & (green > 165) & (blue > 165)).mean())
    gray = np.mean(channels, axis=2)
    bright_ratio = float((gray > 115).mean())
    return white_ratio >= 0.006 or bright_ratio >= 0.035


def _dealer_signal(image: np.ndarray) -> float:
    if image.size == 0 or image.ndim < 3:
        return 0.0
    channels = image[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    mask = (red > 130) & (green > 90) & (blue < 135) & ((red - blue) > 30)
    ratio = float(mask.mean())
    if ratio < 0.025:
        return 0.0
    return min(1.0, ratio * 4.0)


def _clean_player_name(name: str | None) -> str:
    if not name:
        return ""
    cleaned = str(name).replace("|", " ")
    cleaned = re.sub(r"[^0-9A-Za-z\u0590-\u05ff_. -]+", " ", cleaned)
    cleaned = " ".join(cleaned.split())
    cleaned = cleaned.strip(" -_{}[]()\\/")
    if len(cleaned) > 24:
        cleaned = cleaned[:24]
    return cleaned


def _normalize_action_text(text: str | None) -> str:
    if not text:
        return "none"
    value = str(text).strip().lower()
    value = re.sub(r"[^a-z\u0590-\u05ff +'-]+", " ", value)
    value = " ".join(value.split())
    checks = {
        "check": "check",
        "checked": "check",
        "fold": "fold",
        "folded": "fold",
        "call": "call",
        "called": "call",
        "bet": "bet",
        "bets": "bet",
        "raise": "raise",
        "raises": "raise",
        "raised": "raise",
        "all in": "all-in",
        "all-in": "all-in",
        "waiting": "waiting",
        "sit out": "waiting",
        "פולד": "fold",
        "צק": "check",
        "צ'ק": "check",
        "קול": "call",
        "הימור": "bet",
        "רייז": "raise",
        "אול אין": "all-in",
    }
    for token, action in checks.items():
        if token in value:
            return action
    return "none"


def _street_from_board(board: list[GgCard]) -> str:
    visible = len([card for card in board if card.visible and not card.hidden])
    if visible >= 5:
        return "river"
    if visible == 4:
        return "turn"
    if visible == 3:
        return "flop"
    if visible == 0:
        return "preflop"
    return "unknown"


def _card_id(card: GgCard) -> str:
    if card.hidden or not card.rank or not card.suit:
        return ""
    return f"{card.rank}{card.suit}".upper()


def _card_debug_payload(index: int, card: GgCard | None, confidence: float, roi_changed_value: bool) -> dict[str, Any]:
    return {
        "index": int(index),
        "detected": bool(card and card.visible and not card.hidden and card.rank and card.suit),
        "rank": card.rank if card else None,
        "suit": card.suit if card else None,
        "confidence": round(float(card.confidence if card else confidence or 0.0), 4),
        "roiChanged": bool(roi_changed_value),
    }


def _label_to_cache_key(label: str) -> str:
    if label == "pot" or label == "title/blinds":
        return label
    board_match = re.search(r"board-(\d+)", label)
    if board_match:
        return f"board-{int(board_match.group(1)) - 1}"
    seat_match = re.search(r"seat-(\d+):.*:(name|stack|bet|action)", label)
    if seat_match:
        return f"seat-{seat_match.group(1)}-{seat_match.group(2)}"
    card_match = re.search(r"seat-(\d+):.*:card-(\d+)", label)
    if card_match:
        return f"seat-{card_match.group(1)}-card-{int(card_match.group(2)) - 1}"
    return label


def _estimate_confidence(values: list[float]) -> float:
    usable = [float(value) for value in values if value and value > 0]
    if not usable:
        return 0.0
    return max(0.0, min(1.0, sum(usable) / len(usable)))


def _close_amount(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) <= max(0.15, abs(float(left)), abs(float(right))) * 0.05
