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

from .fast_amount import amount_text_signal, read_amount_fast, read_amount_rapidocr, read_amount_tight_ocr
from .fixed_profile import FixedGgProfile, FixedSeatProfile, get_fixed_profile
from .models import GgCard, GgSeat, GgTableSnapshot
from .multirun import MultiRunBoardDetection, detect_multirun_board, has_multirun_layout
from .ocr import normalize_amount, read_amount, read_card, read_name, read_name_detailed, read_table_title
from .profile_matcher import FittedGgProfile, choose_and_fit_profile
from .roi import crop_norm, downscale_hash, draw_roi_overlay, roi_changed, roi_mean_abs_diff
from .table_state import TableStateStabilizer


MIN_FAST_CONFIDENCE = 0.58
CARD_CHANGE_THRESHOLD = 3.5
BOARD_CARD_CHANGE_THRESHOLD = 0.45
TEXT_CHANGE_THRESHOLD = 4.0
POT_CHANGE_THRESHOLD = 0.45
STACK_CHANGE_THRESHOLD = 1.0
BET_CHANGE_THRESHOLD = 1.0
DEALER_HOLD_SECONDS = 1.5
BAD_FRAME_HOLD_SECONDS = 1.2
MAX_PENDING_OCR = 6
QUICK_REUSE_MIN_FPS = 2.5
QUICK_REUSE_OCR_FULL_PASS_FRAMES = 8
QUICK_REUSE_OCR_FULL_PASS_SECONDS = 1.0
MAX_BACKGROUND_OCR = 3
MAX_NAME_RETRIES = 4
PROFILE_REFIT_SECONDS = 300.0


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
    reject_reason: str = ""


class FastGgReader:
    def __init__(self, profile: FixedGgProfile | None = None, *, ocr_workers: int = 2) -> None:
        self._initial_profile = profile
        self.profile = profile or get_fixed_profile()
        self._profile_locked = profile is not None
        self._executor = ThreadPoolExecutor(max_workers=ocr_workers, thread_name_prefix="fast-gg-ocr")
        self._closed = False
        self._lock = RLock()
        self._fields: dict[str, _FieldCache] = {}
        self._last_snapshot: GgTableSnapshot | None = None
        self._last_snapshot_at = 0.0
        self._last_frame: np.ndarray | None = None
        self._last_reuse_frame: np.ndarray | None = None
        self._last_reuse_hash: np.ndarray | None = None
        self._quick_reuses_since_full_pass = 0
        self._last_full_pass_at = 0.0
        self._last_dealer_index = 0
        self._last_dealer_at = 0.0
        self._parse_timestamps: deque[float] = deque(maxlen=240)
        self._parse_durations_ms: deque[float] = deque(maxlen=240)
        self._last_amount_fields: list[dict[str, Any]] = []
        self._last_board_card_debug: list[dict[str, Any]] = []
        self._profile_shape: tuple[int, int] | None = None
        self._profile_fit_signature: tuple[str, float, float, float, float] | None = None
        self._last_profile_fit_at = 0.0
        # A profile describes geometry, not the table stakes.  In particular,
        # the same compact layout is used by both 1/2 and 2/4 tables, so its
        # defaults must never be published while the title read is pending.
        self._resolved_blinds: tuple[float, float] | None = None
        self._postflop_context = False
        self._multirun_hash: np.ndarray | None = None
        self._multirun_detection: MultiRunBoardDetection | None = None
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
            quick_hash = self._quick_frame_hash(frame)
            quick_reuse = self._quick_reuse_snapshot(frame, quick_hash, metrics, started_at)
            if quick_reuse is not None:
                return quick_reuse

            if not self._looks_like_fixed_gg_frame(frame):
                return self._held_snapshot(metrics, started_at)
            self._select_profile(frame)
            quick_reuse_diagnostics = {
                key: value for key, value in metrics.items() if key.startswith("quickReuse")
            }
            metrics = {**self._new_metrics(), **quick_reuse_diagnostics}
            if getattr(self.profile, "fit_score", 1.0) <= 0.0 and (
                (getattr(self.profile, "diagnostics", None) or {}).get("fitError") == "source-not-real-clubgg"
            ):
                metrics["sourceRejected"] = True
                metrics["rejectedReason"] = (getattr(self.profile, "diagnostics", None) or {}).get(
                    "rejectedReason",
                    "source-not-real-clubgg",
                )
                return self._held_snapshot(metrics, started_at)
            # Reaching this point means the cadence (or a changed frame) asked
            # for a real field pass. Keep the original pixels, not a caller-
            # owned view that could later be mutated and defeat exact reuse.
            self._quick_reuses_since_full_pass = 0
            self._last_full_pass_at = time.monotonic()
            self._last_frame = frame.copy()

            now = time.monotonic()
            title_text, title_confidence = self._read_name_cached(
                "title/blinds",
                crop_norm(frame, self.profile.title_blinds),
                now=now,
                metrics=metrics,
                stale_seconds=15.0,
                min_confidence=0.15,
                allow_slow_fallback=False,
            )
            title_entry = self._fields.get("title/blinds")
            # ``entry.raw`` preserves the slash which player-name cleanup
            # intentionally strips.  Parse both representations so a completed
            # title future takes effect on the very next frame.
            title_for_blinds = " ".join(
                value for value in (title_text, str(title_entry.raw or "") if title_entry else "") if value
            )
            parsed_blinds = self._parse_blinds_candidate(title_for_blinds)
            if parsed_blinds is not None:
                self._resolved_blinds = parsed_blinds
                metrics["stakesSource"] = "title"
            elif self._resolved_blinds is not None:
                metrics["stakesSource"] = "cached-title"
            else:
                metrics["stakesSource"] = "profile-pending-title"
            stakes_resolved = self._resolved_blinds is not None
            metrics["stakesPending"] = not stakes_resolved
            small_blind, big_blind = self._resolved_blinds or (
                self.profile.small_blind,
                self.profile.big_blind,
            )

            visible_ids: set[str] = set()
            board = self._read_board(frame, visible_ids, metrics)
            multirun = self._read_multirun_board(frame, board, metrics)
            shared_board: list[GgCard] = []
            runouts: list[list[GgCard]] = []
            if multirun is not None and multirun.is_multiple:
                board = multirun.primary_board()
                shared_board = [card.model_copy(deep=True) for card in multirun.shared_flop]
                runouts = [
                    [card.model_copy(deep=True) for card in runout.cards]
                    for runout in multirun.runouts
                ]
                visible_ids = {
                    _card_id(card)
                    for card in [*shared_board, *(card for runout in runouts for card in runout)]
                    if _card_id(card)
                }
            pot, pot_confidence, _raw_pot = self._read_amount_cached(
                "pot",
                crop_norm(frame, self.profile.pot),
                now=now,
                metrics=metrics,
                stale_seconds=0.333,
                empty_is_zero=False,
            )
            self._postflop_context = bool(board)
            seats = self._read_seats(frame, visible_ids, now, metrics)
            self._normalize_table_actions(seats, board)
            exposed_contenders = sum(
                1
                for seat in seats
                if seat.active
                and len(seat.holeCards) >= 2
                and all(card.visible and not card.hidden and card.rank and card.suit for card in seat.holeCards[:2])
            )
            street = "showdown" if len(board) >= 3 and exposed_contenders >= 2 else _street_from_board(board)
            if street == "showdown":
                for seat in seats:
                    has_exposed_hand = bool(
                        len(seat.holeCards) >= 2
                        and all(
                            card.visible and not card.hidden and card.rank and card.suit
                            for card in seat.holeCards[:2]
                        )
                    )
                    if seat.active and not has_exposed_hand:
                        seat.inHand = False
                        seat.status = "folded"
                        seat.holeCards = []
                        if seat.action not in {"all-in"}:
                            seat.action = "none"
                            seat.actionAmount = 0.0
                            seat.actionSource = "showdown_non_contender"
            dealer_index = self._detect_dealer(frame, seats, now, metrics)
            self._apply_positions(seats, dealer_index)
            active_count = sum(1 for seat in seats if seat.active)
            confidence = self._snapshot_confidence(seats, pot_confidence, title_confidence, dealer_index)

            snapshot = GgTableSnapshot(
                timestamp=int(time.time() * 1000),
                tableType=self.profile.table_type,
                street=street,
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
                sharedBoard=shared_board,
                runouts=runouts,
                seats=seats,
                confidence=confidence,
            )
            snapshot.metrics = dict(metrics)
            snapshot = self._stabilizer.stabilize(snapshot, now=now)
            stabilizer_metrics = self._stabilizer.get_metrics()
            metrics["stabilizer"] = stabilizer_metrics
            hand_reset = bool(stabilizer_metrics.get("handReset"))
            if hand_reset:
                self._invalidate_hand_caches()
            self._finish_metrics(metrics, started_at, snapshot.confidence)
            snapshot.metrics = {**snapshot.metrics, **metrics}

            if stakes_resolved and confidence >= MIN_FAST_CONFIDENCE and active_count >= 2:
                self._last_snapshot = snapshot.model_copy(deep=True)
                self._last_snapshot_at = time.monotonic()
                # Reuse must be anchored to the same frame that produced the
                # accepted snapshot. A later low-confidence transition may be
                # useful for diagnostics, but must never make an older table
                # state appear current.
                if hand_reset:
                    # Force one fresh field pass on the next camera tick.  The
                    # boundary frame itself can still contain the prior pot or
                    # card cache, and exact-frame reuse would otherwise keep it
                    # alive into the new deal.
                    self._last_reuse_frame = None
                    self._last_reuse_hash = None
                else:
                    self._last_reuse_frame = self._last_frame
                    self._last_reuse_hash = quick_hash
            # Do not expose a geometrical profile's default stakes during a
            # transient OCR failure.  The field work above is intentionally
            # retained so the first resolved snapshot is otherwise complete.
            return snapshot if stakes_resolved and confidence >= MIN_FAST_CONFIDENCE else None

    def get_metrics(self) -> dict[str, Any]:
        with self._lock:
            pending = self._pending_ocr_count()
            metrics = dict(self._last_metrics)
            metrics["ocrPending"] = pending
            metrics["ocrPendingByKind"] = self._pending_ocr_by_kind()
            metrics["retryableMissingNames"] = self._has_retryable_missing_names()
            metrics["cacheFields"] = len(self._fields)
            metrics["lastSnapshotAgeMs"] = (
                round((time.monotonic() - self._last_snapshot_at) * 1000, 2)
                if self._last_snapshot_at
                else None
            )
            metrics["p95ParseMs"] = self._percentile(self._parse_durations_ms, 0.95)
            metrics["maxParseMs"] = round(max(self._parse_durations_ms), 2) if self._parse_durations_ms else 0.0
            return metrics

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for entry in self._fields.values():
                if entry.future is not None:
                    entry.future.cancel()
                    entry.future = None
        # The queue is bounded and queued jobs were cancelled above. Waiting
        # for the at-most-two running recognizers prevents orphan OCR workers
        # from degrading the next reader instance (and the live frame rate).
        self._executor.shutdown(wait=True, cancel_futures=True)

    def reset(self) -> None:
        """Clear all table/hand state while keeping the warm OCR executor."""

        with self._lock:
            if self._closed:
                return
            for entry in self._fields.values():
                if entry.future is not None:
                    entry.future.cancel()
            self._fields.clear()
            self.profile = self._initial_profile or get_fixed_profile()
            self._last_snapshot = None
            self._last_snapshot_at = 0.0
            self._last_frame = None
            self._last_reuse_frame = None
            self._last_reuse_hash = None
            self._quick_reuses_since_full_pass = 0
            self._last_full_pass_at = 0.0
            self._last_dealer_index = 0
            self._last_dealer_at = 0.0
            self._last_amount_fields = []
            self._last_board_card_debug = []
            self._profile_shape = None
            self._profile_fit_signature = None
            self._last_profile_fit_at = 0.0
            self._resolved_blinds = None
            self._postflop_context = False
            self._parse_timestamps.clear()
            self._parse_durations_ms.clear()
            self._stabilizer = TableStateStabilizer()

    def _invalidate_hand_caches(self) -> None:
        """Drop fields whose meaning cannot cross a detected hand boundary."""

        transient_keys = [
            key
            for key in self._fields
            if key == "pot"
            or key.startswith("board-")
            or (
                key.startswith("seat-")
                and any(marker in key for marker in ("-bet", "-action", "-card-"))
            )
        ]
        for key in transient_keys:
            entry = self._fields.pop(key, None)
            if entry is not None and entry.future is not None:
                entry.future.cancel()
        self._multirun_hash = None
        self._multirun_detection = None

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
                accepted = bool(
                    entry
                    and entry.known
                    and not changed_since_cache
                    and not entry.reject_reason
                    and (
                        float(entry.confidence or 0.0) > 0.0
                        or entry.source in {"empty", "visual_card_detection"}
                        or entry.value not in (None, "")
                    )
                )
                field_payload = {
                    "key": cache_key,
                    "label": label,
                    "path": str(path),
                    "raw": str(entry.raw or "") if entry else "",
                    "cleaned": _clean_player_name(str(entry.value or "")) if entry and "-name" in cache_key else None,
                    "parsedValue": parsed_value,
                    "confidence": round(float(entry.confidence or 0.0), 4) if entry else 0.0,
                    "source": "stale-cache" if changed_since_cache else (str(entry.source or "unread") if entry else "unread"),
                    "roiChanged": bool(changed_since_cache),
                    "accepted": accepted,
                    "rejectReason": (
                        ""
                        if accepted
                        else (
                            "roi-changed-since-cache"
                            if changed_since_cache
                            else (str(entry.reject_reason or "") if entry else "not-read-yet") or "not-read-yet"
                        )
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
            "visualHoleCardsBySeat": {},
            "winnerOverlaySeats": [],
            "terminalFoldedSeats": [],
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
        self._last_reuse_frame = None
        self._last_reuse_hash = None
        self._last_snapshot = None
        self._last_snapshot_at = 0.0
        self._last_amount_fields = []
        self._last_board_card_debug = []
        # The title ROI belongs to the fitted geometry.  Never carry stakes
        # across a material layout/profile refit before that title is read.
        self._resolved_blinds = None
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
        frame: np.ndarray,
        quick_hash: np.ndarray,
        metrics: dict[str, Any],
        started_at: float,
    ) -> GgTableSnapshot | None:
        if self._last_snapshot is None or self._last_reuse_hash is None or self._last_reuse_frame is None:
            return None
        if not np.array_equal(quick_hash, self._last_reuse_hash):
            return None
        # The sparse hash is only an inexpensive rejection filter. Exact pixel
        # equality prevents a change between sampled pixels from returning a
        # stale table snapshot.
        if frame.shape != self._last_reuse_frame.shape or not np.array_equal(frame, self._last_reuse_frame):
            return None
        if self._actual_fps() < QUICK_REUSE_MIN_FPS:
            return None

        # Stabilization intentionally asks for repeated evidence before
        # publishing some transitions. If the first changed frame is reused as
        # pixels instead of parsed again, that confirmation can never arrive
        # and a new river card/pot/dealer can remain stale indefinitely.
        if self._stabilizer.has_pending_confirmation():
            metrics["quickReuseBypass"] = "stabilizer-pending"
            return None
        if any(entry.candidate_value is not None for entry in self._fields.values()):
            metrics["quickReuseBypass"] = "amount-candidate-pending"
            return None

        pending_ocr = self._pending_ocr_count()
        retryable_missing_names = self._has_retryable_missing_names()
        if pending_ocr > 0 or retryable_missing_names:
            now = time.monotonic()
            frames_due = self._quick_reuses_since_full_pass >= QUICK_REUSE_OCR_FULL_PASS_FRAMES
            time_due = bool(
                self._last_full_pass_at
                and now - self._last_full_pass_at >= QUICK_REUSE_OCR_FULL_PASS_SECONDS
            )
            if frames_due or time_due:
                metrics["quickReuseBypass"] = "ocr-cadence"
                metrics["quickReuseCadenceFrames"] = self._quick_reuses_since_full_pass
                return None

        snapshot = self._last_snapshot.model_copy(deep=True)
        snapshot.timestamp = int(time.time() * 1000)
        metrics["quickReuse"] = True
        self._quick_reuses_since_full_pass = min(
            QUICK_REUSE_OCR_FULL_PASS_FRAMES,
            self._quick_reuses_since_full_pass + 1,
        )
        if pending_ocr > 0:
            metrics["quickReuseOcrPending"] = pending_ocr
        if retryable_missing_names:
            metrics["quickReuseMissingNames"] = True
        metrics["quickReuseCadenceFrames"] = self._quick_reuses_since_full_pass
        metrics["fieldsReused"] = len(self._fields)
        self._finish_metrics(metrics, started_at, snapshot.confidence)
        snapshot.metrics = dict(metrics)
        self._last_snapshot = snapshot.model_copy(deep=True)
        self._last_snapshot_at = time.monotonic()
        return snapshot

    def _has_retryable_missing_names(self) -> bool:
        if self._last_snapshot is None:
            return False
        now = time.monotonic()
        for seat in self._last_snapshot.seats:
            if not seat.active or seat.name:
                continue
            entry = self._fields.get(f"seat-{seat.physicalSeatIndex}-name")
            if entry is None:
                return True
            if entry.consecutive_misses >= MAX_NAME_RETRIES:
                continue
            retry_delay = min(30.0, 1.0 * (2 ** min(entry.consecutive_misses, 5)))
            if entry.future is None and now - float(entry.requested_at or 0.0) >= retry_delay:
                return True
        return False

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
        slots: list[GgCard | None] = []
        for index, roi in enumerate(self.profile.board):
            card = self._read_card_cached(
                f"board-{index}",
                crop_norm(frame, roi),
                allow_hidden=False,
                metrics=metrics,
                board_index=index,
            )
            if not card:
                slots.append(None)
                continue
            card_id = _card_id(card)
            if card_id in visible_ids:
                slots.append(None)
                continue
            visible_ids.add(card_id)
            slots.append(card)
        present = [index for index, card in enumerate(slots) if card is not None]
        if not present:
            return []
        contiguous = present == list(range(len(present)))
        if not contiguous or len(present) not in {3, 4, 5}:
            metrics["partialBoardRejected"] = True
            metrics["boardSlotsPresent"] = present
            return []
        return [card for card in slots[: len(present)] if card is not None]

    def _read_multirun_board(
        self,
        frame: np.ndarray,
        normal_board: list[GgCard],
        metrics: dict[str, Any],
    ) -> MultiRunBoardDetection | None:
        # Hash only the central fan area. Avatar/action animations elsewhere on
        # the table must not rerun seven card classifiers.
        fan_crop = crop_norm(frame, (0.28, 0.25, 0.45, 0.36))
        fan_hash = downscale_hash(fan_crop)
        unchanged = bool(
            self._multirun_hash is not None
            and np.array_equal(self._multirun_hash, fan_hash)
        )
        if unchanged and self._multirun_detection is not None:
            metrics["multirunCache"] = "reused"
            return self._multirun_detection

        self._multirun_hash = fan_hash
        if not has_multirun_layout(frame, profile=self.profile):
            if not normal_board:
                self._multirun_detection = None
            metrics["multirunLayout"] = "single"
            return None

        started_at = time.perf_counter()
        detection = detect_multirun_board(frame, profile=self.profile)
        metrics["multirunMs"] = round((time.perf_counter() - started_at) * 1000, 2)
        metrics["multirunLayout"] = detection.layout
        metrics["multirunConfidence"] = round(float(detection.confidence or 0.0), 4)
        if detection.is_multiple:
            self._multirun_detection = detection
            return detection
        return None

    def _read_seats(
        self,
        frame: np.ndarray,
        visible_ids: set[str],
        now: float,
        metrics: dict[str, Any],
    ) -> list[GgSeat]:
        postflop = self._postflop_context
        # Queue the stable, high-signal name fields before any seat can submit
        # a slow stack/bet fallback.  ThreadPoolExecutor is FIFO and the queue
        # is intentionally bounded, so interleaving stack -> name per seat let
        # amount work from early seats starve all names later in the clockwise
        # order.  This pass is cheap (color signal + cache lookup) and does not
        # increase either the worker count or the global pending-job cap.
        for seat_profile in self.profile.seats:
            name_crop = crop_norm(frame, seat_profile.name)
            if _name_text_signal(name_crop) < 0.010 and not self._field_known(
                f"seat-{seat_profile.index}-name"
            ):
                continue
            self._read_name_cached(
                f"seat-{seat_profile.index}-name",
                name_crop,
                now=now,
                metrics=metrics,
                stale_seconds=120.0,
                min_confidence=0.18,
            )

        seats: list[GgSeat] = []
        for seat_profile in self.profile.seats:
            seats.append(self._read_seat(frame, seat_profile, visible_ids, now, metrics))

        winner_seats = {
            int(index)
            for index in (metrics.get("winnerOverlaySeats") or [])
        }
        if postflop or winner_seats:
            visual_by_seat = metrics.get("visualHoleCardsBySeat") or {}
            terminal_folded: list[int] = []
            for seat in seats:
                index = int(seat.physicalSeatIndex)
                if (
                    seat.active
                    and index not in winner_seats
                    and not seat.isAllIn
                    and not bool(visual_by_seat.get(str(index), False))
                ):
                    # ClubGG removes a player's card backs when that player
                    # folds. Once community cards are present this is stronger
                    # evidence than the occupied player panel: keep the player
                    # in the seating/position map, but do not fabricate X/X.
                    # WIN provides the same evidence at the terminal frame.
                    self._clear_seat_transient_cache(
                        index,
                        now,
                        metrics,
                        source="cards_not_visible_postflop",
                    )
                    seat.status = "folded"
                    seat.inHand = False
                    seat.holeCards = []
                    seat.currentBet = 0.0
                    seat.betConfidence = 0.0
                    if seat.action not in {"fold", "waiting"}:
                        seat.action = "none"
                        seat.actionAmount = 0.0
                        seat.actionConfidence = 0.0
                        seat.actionSource = "cards_not_visible"
                    terminal_folded.append(index)
            metrics["terminalFoldedSeats"] = terminal_folded
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
            # Exposed opponent cards overlap from right to left.  The legacy
            # ROI began on the rank itself for the second card (and on several
            # fitted first cards), clipping 9/J/A into an unrecognisable sliver.
            # A small left-only pad captures the full upper-left corner while
            # the corner classifier ignores the neighbouring card border.
            hole_card_roi = _pad_hole_card_roi_left(card_roi)
            card = self._read_card_cached(
                f"seat-{seat_profile.index}-card-{card_index}",
                crop_norm(frame, hole_card_roi),
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
        name_crop = crop_norm(frame, seat_profile.name)
        action_roi = seat_profile.action or seat_profile.bet
        action_crop = crop_norm(frame, action_roi)
        action_label_crop = crop_norm(frame, _action_label_roi(seat_profile.name))
        action_pill, action_pill_confidence = _detect_action_pill(action_label_crop)
        active_crop = crop_norm(frame, seat_profile.active)
        stack_signal = _cyan_signal(stack_crop)
        stack_text_signal = amount_text_signal(stack_crop)
        bet_text_signal = amount_text_signal(bet_crop)
        win_text_signal = _yellow_win_text_signal(bet_crop)
        name_text_signal = _name_text_signal(name_crop)
        panel_signal = _panel_signal(active_crop)
        action_text_signal = _yellow_win_text_signal(action_crop)
        has_two_hole_cards = len(hole_cards) >= 2
        has_clear_stack_text = stack_text_signal >= 0.014
        has_clear_bet_text = bet_text_signal >= 0.012
        has_clear_cyan_stack = stack_signal >= 0.014
        empty_take_seat = _looks_like_empty_take_seat(
            active_crop,
            has_two_hole_cards=has_two_hole_cards,
            stack_signal=stack_signal,
            stack_text_signal=stack_text_signal,
            bet_text_signal=bet_text_signal,
        )
        strong_empty_take_seat = bool(
            empty_take_seat
            and not has_two_hole_cards
            and not has_clear_stack_text
            and stack_signal < 0.010
        )
        winner_overlay = bool(
            has_two_hole_cards
            and (
                _looks_like_winner_overlay(
                    bet_crop,
                    action_crop,
                    bet_text_signal=bet_text_signal,
                    bet_yellow_signal=win_text_signal,
                    action_yellow_signal=action_text_signal,
                )
                or _looks_like_winner_label_overlay(action_label_crop, action_pill)
            )
        )
        visual_hole_cards = bool(has_two_hole_cards)
        visual_map = metrics.get("visualHoleCardsBySeat")
        if isinstance(visual_map, dict):
            visual_map[str(seat_profile.index)] = visual_hole_cards
        if winner_overlay:
            winner_seats = metrics.get("winnerOverlaySeats")
            if isinstance(winner_seats, list) and seat_profile.index not in winner_seats:
                winner_seats.append(seat_profile.index)

        # A central pot label can overlap the broad bottom-seat bet ROI while
        # that seat visibly says Take Seat.  Empty-seat evidence has precedence
        # over every cached textual field, including work queued by the name
        # pre-pass above.  Likewise, WIN is a terminal decoration rather than a
        # live bet/action and must clear values held from the previous frame.
        if strong_empty_take_seat:
            self._clear_empty_seat_cache(seat_profile.index, now, metrics)
        elif winner_overlay:
            self._clear_seat_transient_cache(
                seat_profile.index,
                now,
                metrics,
                source="winner_overlay",
            )

        stack = 0.0
        stack_confidence = 0.0
        raw_stack = ""
        current_bet = 0.0
        bet_confidence = 0.0
        name = ""
        name_confidence = 0.0
        detected_action = "none"
        action_confidence = 0.0
        should_read_stack = not strong_empty_take_seat and (
            has_clear_stack_text
            or has_clear_cyan_stack
            or self._field_known(f"seat-{seat_profile.index}-stack")
        )
        should_read_bet = not strong_empty_take_seat and not winner_overlay and win_text_signal < 0.010 and (
            has_clear_bet_text
            or self._field_known(f"seat-{seat_profile.index}-bet")
        )
        should_read_name = not strong_empty_take_seat and (
            name_text_signal >= 0.010
            or (
                panel_signal >= 0.28
                and (has_two_hole_cards or has_clear_stack_text or has_clear_cyan_stack)
            )
            or self._field_known(f"seat-{seat_profile.index}-name")
        )
        should_read_action = not strong_empty_take_seat and not winner_overlay and (
            action_pill != "none"
            or action_text_signal >= 0.006
            or self._field_known(f"seat-{seat_profile.index}-action")
        )
        if should_read_stack:
            stack, stack_confidence, raw_stack = self._read_amount_cached(
                f"seat-{seat_profile.index}-stack",
                stack_crop,
                now=now,
                metrics=metrics,
                stale_seconds=0.75,
                empty_is_zero=False,
            )
        if should_read_bet:
            current_bet, bet_confidence, _raw_bet = self._read_amount_cached(
                f"seat-{seat_profile.index}-bet",
                bet_crop,
                now=now,
                metrics=metrics,
                stale_seconds=0.333,
                empty_is_zero=True,
            )
        if should_read_name:
            name, name_confidence = self._read_name_cached(
                f"seat-{seat_profile.index}-name",
                name_crop,
                now=now,
                metrics=metrics,
                stale_seconds=120.0,
                min_confidence=0.18,
            )
        if should_read_action:
            detected_action, action_confidence = self._read_action_cached(
                f"seat-{seat_profile.index}-action",
                action_label_crop,
                now=now,
                metrics=metrics,
                stale_seconds=1.0,
            )

        # A high-contrast white card-back pattern can resemble two exposed
        # ranks to the showdown corner classifier.  Before any community card
        # exists, opponent face-up cards are valid only when the rendered zero
        # stack proves a preflop all-in.  Convert other apparent faces back to
        # X/X and update the ROI cache as well, so the false faces cannot leak
        # into later streets when the same card backs remain on screen.  The
        # fixed hero seat is exempt because a seated hero legitimately sees
        # their own cards preflop.
        provisional_zero_stack = bool(
            stack <= 0.0
            and stack_confidence >= 0.80
            and re.fullmatch(r"0(?:[.]0+)?BB?", str(raw_stack or "").upper())
        )
        has_apparent_face = any(
            card.visible and not card.hidden and card.rank and card.suit
            for card in hole_cards
        )
        if (
            has_apparent_face
            and not self._postflop_context
            and not provisional_zero_stack
            and self.profile.hero_seat_index != seat_profile.index
        ):
            hidden_confidence = max(0.78, min(0.82, max((card.confidence for card in hole_cards), default=0.78)))
            hole_cards = [
                GgCard(hidden=True, visible=False, display="X", confidence=hidden_confidence),
                GgCard(hidden=True, visible=False, display="X", confidence=hidden_confidence),
            ]
            for card_index in range(2):
                entry = self._fields.get(f"seat-{seat_profile.index}-card-{card_index}")
                if entry is not None:
                    entry.value = hole_cards[card_index].model_copy(deep=True)
                    entry.confidence = hidden_confidence
                    entry.raw = "X"
                    entry.source = "preflop_card_back_guard"
                    entry.reject_reason = ""
            metrics.setdefault("preflopCardBackGuards", []).append(seat_profile.index)

        # WIN uses the same bright yellow palette and overlaps the action-label
        # strip.  It is terminal decoration, never a Check/Call pill.
        exposed_face_cards = bool(
            len(hole_cards) >= 2
            and all(card.visible and not card.hidden and card.rank and card.suit for card in hole_cards[:2])
        )
        if winner_overlay:
            detected_action = "none"
            action_confidence = 0.0
        elif exposed_face_cards:
            # Red percentage glyphs replace the name line at showdown and can
            # resemble ClubGG's red Fold pill.  Face-up cards are stronger,
            # terminal evidence that the player remains a contender.
            detected_action = "none"
            action_confidence = 0.0
        elif action_pill == "fold":
            detected_action = "fold"
            action_confidence = action_pill_confidence
        elif action_pill == "yellow":
            if detected_action not in {"call", "check"}:
                detected_action = "call" if current_bet > 0 else "check"
            action_confidence = max(action_confidence, action_pill_confidence)
        elif action_pill == "blue":
            if detected_action not in {"bet", "raise", "all-in"}:
                detected_action = "bet"
            action_confidence = max(action_confidence, action_pill_confidence)
        elif action_pill == "none" and not winner_overlay and not exposed_face_cards:
            # OCR/cache completion can outlive the short-lived visual pill.
            # Once the coloured pill is gone it is not a new current action;
            # the stabilizer may still hold the prior action briefly.
            detected_action = "none"
            action_confidence = 0.0

        if strong_empty_take_seat:
            stack = 0.0
            stack_confidence = 0.0
            current_bet = 0.0
            bet_confidence = 0.0
            name = ""
            name_confidence = 0.0
            detected_action = "none"
            action_confidence = 0.0

        valid_stack = bool(stack > 0 and stack_confidence >= 0.50)
        valid_bet = bool(current_bet > 0 and bet_confidence >= 0.50)
        valid_name_with_panel = bool(name and name_confidence >= 0.18 and panel_signal >= 0.22)
        empty = bool(strong_empty_take_seat and not valid_stack and not valid_bet)
        active = bool(
            not empty
            and (
                has_two_hole_cards
                or valid_stack
                or valid_bet
                or valid_name_with_panel
                or has_clear_cyan_stack
            )
        )

        current_bet = current_bet if bet_confidence >= 0.50 else 0.0
        stack = stack if stack_confidence >= 0.50 else 0.0
        explicit_zero_stack = bool(
            stack <= 0.0
            and stack_confidence >= 0.80
            and re.fullmatch(r"0(?:[.]0+)?BB?", str(raw_stack or "").upper())
        )
        if explicit_zero_stack and active:
            action = "all-in"
            action_source = "visible_zero_stack"
            action_confidence = max(action_confidence, stack_confidence)
        elif detected_action != "none" and action_confidence >= 0.25:
            action = detected_action
            action_source = "label_ocr"
        elif current_bet > 0:
            action = "bet"
            action_source = "visible_bet"
        else:
            action = "none"
            action_source = "none"
        if active and not hole_cards and action != "fold" and (valid_stack or valid_name_with_panel or has_clear_cyan_stack):
            hole_cards = [
                GgCard(hidden=True, visible=False, display="X", confidence=0.72),
                GgCard(hidden=True, visible=False, display="X", confidence=0.72),
            ]
        confidence = _estimate_confidence([
            min(0.90, stack_signal * 16),
            min(0.90, stack_text_signal * 10),
            min(0.90, bet_text_signal * 12),
            min(0.90, name_text_signal * 12),
            min(0.90, panel_signal),
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
                "panelSignal": round(float(panel_signal), 4),
                "emptyTakeSeat": bool(empty_take_seat),
                "empty": bool(empty),
                "stackTextSignal": round(float(stack_text_signal), 4),
                "stackCyanSignal": round(float(stack_signal), 4),
                "betTextSignal": round(float(bet_text_signal), 4),
                "winTextSignal": round(float(win_text_signal), 4),
                "winnerOverlay": bool(winner_overlay),
                "nameTextSignal": round(float(name_text_signal), 4),
                "card0Present": bool(len(hole_cards) >= 1),
                "card1Present": bool(len(hole_cards) >= 2),
                "visualHoleCards": visual_hole_cards,
                "nameUnknown": bool(active and not name),
                "actionRaw": detected_action,
                "actionConfidence": round(float(action_confidence), 4),
                "actionPill": action_pill,
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
            actionConfidence=(
                action_confidence
                if action_source == "label_ocr"
                else (bet_confidence if current_bet > 0 else 0.0)
            ),
            actionSource=action_source,
            status="folded" if active and action == "fold" else ("active" if active else "empty"),
            inHand=bool(active and action != "fold"),
            isAllIn=bool(active and explicit_zero_stack),
            isHero=bool(active and self.profile.hero_seat_index == seat_profile.index),
            holeCards=hole_cards if active else [],
            confidence=confidence if active else 0.92,
        )

    def _normalize_table_actions(self, seats: list[GgSeat], board: list[GgCard]) -> None:
        if board:
            return
        for seat in seats:
            if not seat.active or seat.action != "bet" or seat.actionSource != "label_ocr":
                continue
            other_max = max(
                [
                    float(other.currentBet or 0.0)
                    for other in seats
                    if other.active and other.physicalSeatIndex != seat.physicalSeatIndex
                ]
                or [0.0]
            )
            if other_max > 0 and float(seat.currentBet or 0.0) > other_max + 0.01:
                seat.action = "raise"
                seat.actionAmount = float(seat.currentBet or 0.0)
                seat.actionSource = "bet_delta"
                seat.actionConfidence = max(float(seat.actionConfidence or 0.0), 0.88)

    def _clear_empty_seat_cache(self, seat_index: int, now: float, metrics: dict[str, Any]) -> None:
        fields = {
            f"seat-{seat_index}-stack": (0.0, ""),
            f"seat-{seat_index}-bet": (0.0, ""),
            f"seat-{seat_index}-name": ("", ""),
            f"seat-{seat_index}-action": ("none", "none"),
        }
        cleared = 0
        for key, (value, raw) in fields.items():
            entry = self._fields.get(key)
            if entry is None:
                continue
            if entry.future is not None:
                entry.future.cancel()
                entry.future = None
            entry.value = value
            entry.confidence = 0.0
            entry.raw = raw
            entry.source = "empty_take_seat"
            entry.reject_reason = ""
            entry.known = True
            entry.completed_at = now
            entry.candidate_value = None
            entry.candidate_raw = ""
            entry.candidate_confidence = 0.0
            cleared += 1
        if cleared:
            metrics["emptySeatCacheClears"] = int(metrics.get("emptySeatCacheClears") or 0) + cleared

    def _clear_seat_transient_cache(
        self,
        seat_index: int,
        now: float,
        metrics: dict[str, Any],
        *,
        source: str,
    ) -> None:
        fields = {
            f"seat-{seat_index}-bet": (0.0, ""),
            f"seat-{seat_index}-action": ("none", "none"),
        }
        cleared = 0
        for key, (value, raw) in fields.items():
            entry = self._fields.get(key)
            if entry is None:
                continue
            if entry.future is not None:
                entry.future.cancel()
                entry.future = None
            entry.value = value
            entry.confidence = 0.0
            entry.raw = raw
            entry.source = source
            entry.reject_reason = ""
            entry.known = True
            entry.completed_at = now
            entry.consecutive_misses = 0
            entry.candidate_value = None
            entry.candidate_raw = ""
            entry.candidate_confidence = 0.0
            cleared += 1
        if cleared:
            metrics["transientSeatCacheClears"] = int(metrics.get("transientSeatCacheClears") or 0) + cleared

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
        change_threshold = BOARD_CARD_CHANGE_THRESHOLD if board_index is not None else CARD_CHANGE_THRESHOLD
        changed = roi_changed(entry.image_hash, new_hash, change_threshold) if entry.image_hash is not None else True
        if changed:
            self._mark_changed(metrics, key)
        if changed or not entry.known:
            data = read_card(crop, prefer_exposed=allow_hidden)
            entry.image_hash = new_hash
            entry.known = True
            entry.completed_at = time.monotonic()
            candidate = self._card_from_data(data, allow_hidden=allow_hidden)
            previous = entry.value if isinstance(entry.value, GgCard) else None
            previous_visible = bool(previous and previous.visible and not previous.hidden and previous.rank and previous.suit)
            candidate_visible = bool(candidate and candidate.visible and not candidate.hidden and candidate.rank and candidate.suit)
            # Once a face-up showdown card is accepted it cannot legitimately
            # change during the same postflop hand.  WIN/dimming animations do
            # temporarily turn it into a back, blank, or another glyph.  Hold
            # the proven card until the board clears for the next hand.
            if allow_hidden and self._postflop_context and previous_visible:
                if not candidate_visible or _card_id(candidate) != _card_id(previous):
                    candidate = previous.model_copy(deep=True)
                    metrics.setdefault("heldExposedCards", []).append(key)
            entry.value = candidate
            entry.confidence = float(data.get("confidence") or 0.0)
            entry.source = "visual_card_detection"
            entry.raw = _card_id(entry.value) if isinstance(entry.value, GgCard) else ("X" if data.get("hidden") else "")
            entry.reject_reason = "" if entry.value is not None else "no-card-detected"
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
        visible_min_confidence = 0.78 if allow_hidden else 0.70
        if rank and suit and confidence >= visible_min_confidence:
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
        if key == "pot":
            change_threshold = POT_CHANGE_THRESHOLD
        elif "-bet" in key:
            change_threshold = BET_CHANGE_THRESHOLD
        elif "-stack" in key:
            change_threshold = STACK_CHANGE_THRESHOLD
        else:
            change_threshold = TEXT_CHANGE_THRESHOLD
        hash_differs = bool(
            entry.image_hash is None
            or not np.array_equal(entry.image_hash, new_hash)
        )
        changed = roi_changed(entry.image_hash, new_hash, change_threshold) if entry.image_hash is not None else True
        if changed:
            self._mark_changed(metrics, key)
        if entry.future is not None:
            metrics["fieldsReused"] += 1
            self._record_amount_debug(metrics, key, entry, changed, "cache_pending")
            return float(entry.value or 0.0), float(entry.confidence or 0.0), str(entry.raw or "")
        retry_window_due = (
            entry.future is None
            and float(entry.confidence or 0.0) < 0.50
            and now - float(entry.requested_at or 0.0) >= max(5.0, stale_seconds)
        )
        candidate_confirmation_due = entry.candidate_value is not None
        stale_known_due = bool(
            entry.known
            and entry.future is None
            and hash_differs
            and now - float(entry.completed_at or 0.0) >= stale_seconds
        )
        if (
            not changed
            and entry.known
            and not retry_window_due
            and not stale_known_due
            and not candidate_confirmation_due
        ):
            metrics["fieldsReused"] += 1
            self._record_amount_debug(metrics, key, entry, changed, "cache")
            return float(entry.value or 0.0), float(entry.confidence or 0.0), str(entry.raw or "")

        signal = amount_text_signal(crop)
        if empty_is_zero and signal < 0.008:
            entry.consecutive_misses += 1
            if float(entry.value or 0.0) > 0.0 and entry.consecutive_misses < 2:
                metrics["fieldsReused"] += 1
                entry.source = "held_empty_pending"
                self._record_amount_debug(metrics, key, entry, changed, "held_empty_pending")
                return float(entry.value or 0.0), min(float(entry.confidence or 0.0), 0.62), str(entry.raw or "")
            if changed or not entry.known or float(entry.value or 0.0) != 0.0:
                entry.value = 0.0
                entry.confidence = 0.92
                entry.raw = ""
                entry.source = "empty"
                entry.reject_reason = ""
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
        should_refresh = changed or not entry.known or retry_due or stale_known_due or candidate_confirmation_due
        hash_observation_consumed = False
        if should_refresh:
            fast_started_at = time.perf_counter()
            amount, confidence, raw = read_amount_fast(crop)
            metrics["ocrMs"] += round((time.perf_counter() - fast_started_at) * 1000, 2)
            pot_decimal_candidate = bool(
                key == "pot"
                and amount > 0
                and confidence >= 0.68
                and re.search(r"\d[.,]\d", str(raw or ""))
            )
            fast_accept_confidence = 0.80 if key == "pot" else (0.74 if "-bet" in key else 0.88)
            if amount > 0 and (confidence >= fast_accept_confidence or pot_decimal_candidate):
                accepted = self._apply_amount_candidate(entry, key, amount, confidence, raw, "fast_amount", now)
                if accepted:
                    metrics["fieldsUpdated"] += 1
                else:
                    metrics["fieldsReused"] += 1
                hash_observation_consumed = bool(
                    accepted
                    or entry.candidate_value is not None
                    or entry.reject_reason in {
                        "winner-text-not-live-bet",
                        "unlabeled-bet",
                        "suspicious-stack-unlabeled-buyin",
                        "suspicious-pot-jackpot",
                    }
                )
            elif (
                "-stack" in key
                and amount == 0
                and confidence >= 0.80
                and re.fullmatch(r"0(?:[.]0+)?BB?", str(raw or "").upper())
            ):
                entry.value = 0.0
                entry.confidence = float(confidence)
                entry.raw = str(raw or "")
                entry.source = "fast_zero_stack"
                entry.reject_reason = ""
                entry.known = True
                entry.completed_at = now
                entry.candidate_value = None
                entry.candidate_raw = ""
                entry.candidate_confidence = 0.0
                metrics["fieldsUpdated"] += 1
                hash_observation_consumed = True
            elif empty_is_zero and signal < 0.020:
                # Weak decorative cyan/white pixels inside a broad bet ROI are
                # not enough evidence to start a slow OCR job. Real live bet
                # labels in ClubGG are either decoded by the fast recognizer or
                # have a substantially stronger text signal. This keeps an
                # empty seat/side badge from blocking name and action OCR.
                entry.value = 0.0
                entry.confidence = 0.88
                entry.raw = ""
                entry.source = "low-signal-empty-bet"
                entry.reject_reason = ""
                entry.known = True
                entry.completed_at = now
                metrics["fieldsUpdated"] += 1
                hash_observation_consumed = True
            elif key != "pot" and signal >= 0.020 and not entry.known:
                if entry.future is None and self._can_queue_ocr(now, priority=True):
                    entry.future = self._executor.submit(_read_amount_source, crop.copy())
                    entry.requested_at = now
                    metrics["ocrQueued"] += 1
                    entry.source = "queued_tight_ocr"
                    entry.known = True
                    entry.completed_at = now
                    metrics["fieldsUpdated"] += 1
                    hash_observation_consumed = True
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
                    accepted = self._apply_amount_candidate(
                        entry,
                        key,
                        value,
                        tight_confidence,
                        tight_raw,
                        "tight_ocr",
                        now,
                    )
                    if accepted:
                        metrics["fieldsUpdated"] += 1
                    else:
                        metrics["fieldsReused"] += 1
                    hash_observation_consumed = bool(accepted or entry.candidate_value is not None)
                elif entry.future is None and self._can_queue_ocr(now, priority=True):
                    entry.future = self._executor.submit(_read_pot_amount_source, crop.copy())
                    entry.requested_at = now
                    entry.source = "queued_tight_ocr"
                    entry.known = True
                    entry.completed_at = now
                    metrics["ocrQueued"] += 1
                    metrics["fieldsUpdated"] += 1
                    hash_observation_consumed = True
                else:
                    metrics["fieldsReused"] += 1
            elif entry.future is None and self._can_queue_ocr(now, priority=True):
                reader = _read_pot_amount_source if key == "pot" else _read_amount_source
                entry.future = self._executor.submit(reader, crop.copy())
                entry.requested_at = now
                metrics["ocrQueued"] += 1
                if not entry.source or entry.source == "unknown":
                    entry.source = "queued_tight_ocr" if key == "pot" else "queued_tesseract"
                hash_observation_consumed = True
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
                    entry.reject_reason = "fast-amount-low-confidence"
                    hash_observation_consumed = True
                metrics["fieldsReused"] += 1
        else:
            metrics["fieldsReused"] += 1
        if hash_observation_consumed:
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
        suspicious_pot = (
            key == "pot"
            and float(value or 0.0) > 500
            and not re.search(r"(?i)BB", str(raw or ""))
        )
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
        elif suspicious_pot:
            entry.reject_reason = "suspicious-pot-jackpot"
        elif value <= 0:
            entry.reject_reason = "empty-or-zero-amount"
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
        field_is_bet = "-bet" in key
        field_is_pot = key == "pot"
        if value <= 0 or confidence <= 0:
            entry.reject_reason = "empty-or-zero-amount"
            return False
        if field_is_bet and "+" in str(raw or ""):
            entry.reject_reason = "winner-text-not-live-bet"
            return False
        if field_is_bet and not re.search(r"(?i)(?:BB|B)\s*$", str(raw or "").strip()):
            # A bare digit in a large bet ROI is usually an avatar badge, seat
            # number, or chip decoration.  Live ClubGG bet labels always carry
            # the B/BB suffix; requiring it eliminates persistent phantom bets.
            entry.reject_reason = "unlabeled-bet"
            return False
        if field_is_pot and value > 500 and not re.search(r"(?i)BB", raw or ""):
            entry.reject_reason = "suspicious-pot-jackpot"
            return False
        if field_is_stack and _looks_like_unlabeled_buyin_stack(value, raw, confidence):
            entry.reject_reason = "suspicious-stack-unlabeled-buyin"
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
                    entry.reject_reason = "suspicious-amount-jump"
                    return False
        entry.value = float(value)
        entry.confidence = float(confidence)
        entry.raw = str(raw or "")
        entry.source = str(source or "tesseract")
        entry.reject_reason = ""
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
        allow_slow_fallback: bool = True,
    ) -> tuple[str, float]:
        entry = self._fields.setdefault(key, _FieldCache(value=""))
        if key == "title/blinds":
            entry.kind = "title"
        self._consume_name_future(entry, metrics, min_confidence=min_confidence)
        new_hash = downscale_hash(crop)
        if key == "title/blinds" and not entry.known and entry.future is None:
            # This profile geometry is shared by multiple stakes.  A temporary
            # profile fallback can therefore double or halve every displayed
            # blind until background OCR happens to finish.  Read the tiny
            # title once during connection; all subsequent refreshes stay on
            # the normal background path, so steady-state frame cadence is
            # unaffected.
            value, confidence, raw, source, reject_reason = _read_table_title_source(crop.copy())
            cleaned = _clean_player_name(value)
            entry.raw = str(raw or value or "")
            entry.source = str(source or "tesseract_title")
            entry.reject_reason = str(reject_reason or "")
            entry.image_hash = new_hash
            entry.requested_at = now
            entry.completed_at = time.monotonic()
            valid_title = bool(
                cleaned
                and confidence >= min_confidence
                and self._parse_blinds_candidate(str(raw or value or "")) is not None
            )
            entry.known = valid_title
            if valid_title:
                entry.value = cleaned
                entry.confidence = float(confidence)
                entry.reject_reason = ""
                entry.consecutive_misses = 0
                metrics["fieldsUpdated"] += 1
            else:
                entry.value = ""
                entry.confidence = float(confidence or 0.0)
                entry.consecutive_misses += 1
                # A timeout or incomplete title is retryable.  Queue the
                # retry immediately, before numeric/name OCR can occupy the
                # bounded executor, while keeping the field unresolved.
                if self._can_queue_ocr(now, priority=True):
                    entry.future = self._executor.submit(_read_table_title_source, crop.copy())
                    entry.requested_at = now
                    entry.source = "queued_tesseract_title_retry"
                    metrics["ocrQueued"] += 1
            metrics["ocrCompleted"] += 1
            metrics["titleSynchronousBootstrap"] = True
            return str(entry.value or ""), float(entry.confidence or 0.0)
        diff = roi_mean_abs_diff(entry.image_hash, new_hash)
        changed = diff > TEXT_CHANGE_THRESHOLD if entry.image_hash is not None else True
        if changed:
            self._mark_changed(metrics, key)
            if entry.image_hash is not None:
                entry.consecutive_misses = 0
        retry_delay = min(30.0, 1.0 * (2 ** min(entry.consecutive_misses, 5)))
        missing_retry_due = bool(
            not entry.value
            and entry.consecutive_misses < MAX_NAME_RETRIES
            and now - float(entry.requested_at or 0.0) >= retry_delay
        )
        stale_known_due = bool(entry.value) and now - entry.completed_at >= stale_seconds
        should_refresh = changed or not entry.known or missing_retry_due or stale_known_due
        if should_refresh and entry.future is None and self._can_queue_ocr(
            now,
            # Player names are sparse, stable fields and must not be starved by
            # slow amount fallbacks.  The shared queue is deliberately small;
            # treating only the title as priority meant three pending stack/bet
            # jobs could prevent every later seat name from ever entering the
            # queue on an otherwise unchanged live frame.
            priority=(key == "title/blinds" or key.endswith("-name")),
        ):
            if key == "title/blinds":
                entry.future = self._executor.submit(_read_table_title_source, crop.copy())
            else:
                entry.future = self._executor.submit(_read_name_source, crop.copy(), allow_slow_fallback)
            entry.requested_at = now
            metrics["ocrQueued"] += 1
            entry.source = "queued_tesseract"
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
            result = future.result()
        except Exception:
            result = ("", 0.0, "", "tesseract_error", "ocr-error")
        entry.future = None
        if isinstance(result, tuple) and len(result) >= 5:
            value, confidence, raw, source, reject_reason = result[:5]
        else:
            value, confidence = result[:2]
            raw = value
            source = "tesseract"
            reject_reason = ""
        cleaned = _clean_player_name(value)
        entry.raw = str(raw or value or "")
        entry.source = str(source or "tesseract")
        entry.reject_reason = str(reject_reason or "")
        valid_value = bool(cleaned and confidence >= min_confidence)
        if entry.kind == "title":
            valid_value = bool(valid_value and self._parse_blinds_candidate(str(raw or value or "")) is not None)
        if valid_value:
            entry.value = cleaned
            entry.confidence = float(confidence)
            entry.known = True
            entry.completed_at = time.monotonic()
            entry.reject_reason = ""
            entry.consecutive_misses = 0
            metrics["fieldsUpdated"] += 1
        else:
            entry.confidence = float(confidence or 0.0)
            entry.completed_at = time.monotonic()
            entry.consecutive_misses += 1
            if not entry.reject_reason:
                entry.reject_reason = "low-confidence-or-empty-name"
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
        if should_refresh and entry.future is None and self._can_queue_ocr(now, priority=True):
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
        # A strong profile-local button signal is more specific than the
        # full-table yellow search, which can otherwise mistake a gold avatar
        # rim for the dealer puck. We keep geometry for layouts whose small
        # button falls outside the legacy ROIs.
        roi_scores = [
            (seat.index, _dealer_signal(crop_norm(frame, seat.dealer)))
            for seat in self.profile.seats
        ]
        best_roi_index, best_roi_score = max(roi_scores, key=lambda item: item[1], default=(None, 0.0))
        if best_roi_index is not None and best_roi_score >= 0.25:
            self._last_dealer_index = int(best_roi_index)
            self._last_dealer_at = now
            metrics["dealerConfidence"] = round(float(best_roi_score), 4)
            metrics["dealerSource"] = "roi_strong"
            return int(best_roi_index)

        if self.profile.table_type in {"6max", "7max", "8max"}:
            visual_index, visual_score = _detect_dealer_by_geometry(frame, self.profile, seats)
            min_visual_score = 0.72 if self.profile.table_type == "8max" else 0.08
            if visual_index is not None and visual_score >= min_visual_score:
                self._last_dealer_index = int(visual_index)
                self._last_dealer_at = now
                metrics["dealerConfidence"] = round(float(visual_score), 4)
                metrics["dealerSource"] = "visual_geometry"
                return int(visual_index)

        if best_roi_index is not None and best_roi_score >= 0.10:
            self._last_dealer_index = int(best_roi_index)
            self._last_dealer_at = now
            metrics["dealerConfidence"] = round(float(best_roi_score), 4)
            metrics["dealerSource"] = "roi"
            return int(best_roi_index)

        active_indexes = [seat.physicalSeatIndex for seat in seats if seat.active]
        if now - self._last_dealer_at <= DEALER_HOLD_SECONDS and self._last_dealer_index in active_indexes:
            metrics["dealerHeld"] = True
            return self._last_dealer_index
        return active_indexes[0] if active_indexes else self._last_dealer_index

    def _apply_positions(self, seats: list[GgSeat], dealer_index: int) -> None:
        order = list(getattr(self.profile, "seat_order_clockwise", ()) or [seat.index for seat in self.profile.seats])
        active_by_index = {int(seat.physicalSeatIndex): seat for seat in seats if seat.active}
        active_order = [index for index in order if index in active_by_index]
        for seat in seats:
            seat.isDealer = bool(seat.active and int(seat.physicalSeatIndex) == int(dealer_index))
            seat.position = None
        if not active_order:
            return
        if dealer_index not in active_order:
            dealer_position = 0
            for offset, seat_index in enumerate(order):
                if seat_index == dealer_index:
                    following = order[offset:] + order[:offset]
                    dealer_position = next(
                        (active_order.index(candidate) for candidate in following if candidate in active_by_index),
                        0,
                    )
                    break
        else:
            dealer_position = active_order.index(dealer_index)
        rotated = active_order[dealer_position:] + active_order[:dealer_position]
        labels = _position_labels(len(rotated))
        for seat_index, label in zip(rotated, labels):
            active_by_index[seat_index].position = label

    def _field_known(self, key: str) -> bool:
        entry = self._fields.get(key)
        if entry is None:
            return False
        if entry.future is not None:
            return True
        if key.endswith("-action") and str(entry.value or "none") == "none" and float(entry.confidence or 0.0) <= 0.0:
            return False
        return bool(entry.known and (entry.value not in (None, "", 0.0) or float(entry.confidence or 0.0) > 0.0))

    def _parse_blinds_candidate(self, title_text: str) -> tuple[float, float] | None:
        value = title_text or ""
        slash_matches = re.findall(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", value)
        for small, big in reversed(slash_matches):
            small_value, big_value = float(small), float(big)
            if 0 < small_value <= big_value <= 100:
                return small_value, big_value
        dash_matches = re.findall(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", value)
        for small, big in reversed(dash_matches):
            small_value, big_value = float(small), float(big)
            if 0 < small_value <= big_value <= 100:
                return small_value, big_value
        return None

    def _parse_blinds(self, title_text: str) -> tuple[float, float]:
        """Compatibility helper for diagnostics and focused unit tests."""

        return self._parse_blinds_candidate(title_text) or (
            self.profile.small_blind,
            self.profile.big_blind,
        )

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
        del now
        pending = self._pending_ocr_count()
        if pending >= MAX_PENDING_OCR:
            return False
        # Reserve half the bounded queue for pot/stack/bet recovery. Names and
        # action labels must never starve numeric state, regardless of poll FPS.
        return bool(priority or pending < MAX_BACKGROUND_OCR)

    def _pending_ocr_count(self) -> int:
        return sum(1 for entry in self._fields.values() if entry.future is not None)

    def _pending_stack_ocr_count(self) -> int:
        return sum(1 for key, entry in self._fields.items() if "-stack" in key and entry.future is not None)

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


def _yellow_win_text_signal(image: np.ndarray) -> float:
    if image.size == 0 or image.ndim < 3:
        return 0.0
    channels = image[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    mask = (red > 150) & (green > 110) & (blue < 95) & ((red - blue) > 70) & ((green - blue) > 45)
    return float(mask.mean())


def _read_amount_source(image: np.ndarray) -> tuple[float, float, str, str]:
    fast_amount, fast_confidence, fast_raw = read_amount_fast(image)
    rapid_amount, rapid_confidence, rapid_raw = read_amount_rapidocr(image)
    # RapidOCR occasionally renders the decimal point in a clear cyan stack
    # such as ``157.2BB`` as a colon (``157:2BB``).  Its normalizer then keeps
    # only the suffix and reports 2BB with high confidence.  Let the tight
    # digit recognizer arbitrate these structurally ambiguous results instead
    # of allowing them to overwrite a complete fast reading.
    rapid_has_ambiguous_decimal = bool(re.search(r"\d\s*[:;]\s*\d", str(rapid_raw or "")))
    fast_has_decimal_bb = bool(
        fast_amount > 0
        and fast_confidence >= 0.84
        and re.search(r"(?i)\d[.,]\d+\s*BB?\s*$", str(fast_raw or "").strip())
    )
    fast_is_more_complete = (
        sum(character.isdigit() for character in str(fast_raw or ""))
        >= sum(character.isdigit() for character in str(rapid_raw or "")) + 2
    )
    if fast_has_decimal_bb and (
        rapid_amount <= 0
        or rapid_has_ambiguous_decimal
        or fast_is_more_complete
        or rapid_amount < fast_amount * 0.35
        or rapid_amount > fast_amount * 2.8
    ):
        return fast_amount, fast_confidence, fast_raw, "fast_amount_decimal_guard"
    if rapid_amount > 0 and rapid_confidence >= 0.70 and not rapid_has_ambiguous_decimal:
        return rapid_amount, rapid_confidence, rapid_raw, "rapidocr_recognizer"
    amount, confidence, raw = read_amount_tight_ocr(image, squash_bb_suffix=True)
    combined_amount = _combine_amount_candidates(amount, raw, rapid_amount, rapid_raw)
    if combined_amount > 0:
        return combined_amount, max(confidence, rapid_confidence, 0.78), f"{rapid_raw}|{raw}", "rapidocr_tight_ocr"
    if amount > 0 and confidence > 0:
        return amount, confidence, raw, "tight_ocr"
    if rapid_amount > 0 and rapid_confidence >= 0.55:
        return rapid_amount, rapid_confidence, rapid_raw, "rapidocr_recognizer"
    amount, confidence, raw = read_amount(image)
    return amount, confidence, raw, "tesseract"


def _read_name_source(image: np.ndarray, allow_slow_fallback: bool = True) -> tuple[str, float, str, str, str]:
    result = read_name_detailed(image, allow_slow_fallback=allow_slow_fallback)
    cleaned = str(result.get("cleaned") or "")
    confidence = float(result.get("confidence") or 0.0)
    raw = str(result.get("raw") or "")
    source = str(result.get("source") or "tesseract")
    reject_reason = str(result.get("rejectReason") or "")
    return cleaned, confidence, raw, source, reject_reason


def _read_table_title_source(image: np.ndarray) -> tuple[str, float, str, str, str]:
    raw, confidence, reject_reason = read_table_title(image)
    return raw, confidence, raw, "tesseract_title", reject_reason


def _read_pot_amount_source(image: np.ndarray) -> tuple[float, float, str, str]:
    amount, confidence, raw = read_amount_tight_ocr(image, squash_bb_suffix=True)
    if amount > 0 and confidence > 0:
        return amount, confidence, raw, "tight_ocr"
    amount, confidence, raw = read_amount(image)
    return amount, confidence, raw, "tesseract"


def _looks_like_unlabeled_buyin_stack(value: float, raw: str, confidence: float) -> bool:
    if float(value or 0.0) < 700:
        return False
    text = str(raw or "").strip().upper().replace(" ", "")
    if re.search(r"(?i)(?:BB|B)$", text) or "." in text:
        return False
    digits = re.sub(r"\D+", "", text)
    return digits in {"1000", "10000"} or bool(digits and float(value or 0.0) >= 900)


def _combine_amount_candidates(tight_amount: float, tight_raw: str, rapid_amount: float, rapid_raw: str) -> float:
    if tight_amount <= 0 or rapid_amount <= 0:
        return 0.0
    tight_text = str(tight_raw or "").upper().replace(" ", "")
    rapid_text = str(rapid_raw or "").upper().replace(" ", "")
    rapid_prefix = re.search(r"^(\d+)[.,]$", rapid_text)
    tight_decimal = re.search(r"[.,](\d)", tight_text)
    if rapid_prefix and tight_decimal:
        return float(f"{rapid_prefix.group(1)}.{tight_decimal.group(1)}")
    return 0.0


def _active_signal(image: np.ndarray) -> float:
    if image.size == 0 or image.ndim < 3:
        return 0.0
    channels = image[:, :, :3]
    gray = np.mean(channels, axis=2)
    bright = float((gray > 120).mean())
    cyan = _cyan_signal(image)
    return min(1.0, bright * 1.5 + cyan * 8)


def _name_text_signal(image: np.ndarray) -> float:
    if image.size == 0 or image.ndim < 3:
        return 0.0
    channels = image[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    white = (red > 145) & (green > 145) & (blue > 145)
    cyan = (blue > 90) & (green > 90) & (red < 150) & ((blue - red) > 20) & ((green - red) > 20)
    return float(np.logical_or(white, cyan).mean())


def _panel_signal(image: np.ndarray) -> float:
    if image.size == 0 or image.ndim < 3:
        return 0.0
    gray = np.mean(image[:, :, :3], axis=2)
    dark = float((gray < 85).mean())
    text = _name_text_signal(image)
    cyan = _cyan_signal(image)
    return min(1.0, dark * 0.55 + text * 7.5 + cyan * 14.0)


def _looks_like_empty_take_seat(
    image: np.ndarray,
    *,
    has_two_hole_cards: bool,
    stack_signal: float,
    stack_text_signal: float,
    bet_text_signal: float,
) -> bool:
    # A live bet normally proves that a seat is occupied, except the compact
    # bottom-seat ROI overlaps the central pot label.  The caller combines this
    # visual with independent card/stack evidence before declaring the seat
    # empty, so an overlapping pot amount must not veto Take Seat detection.
    del bet_text_signal
    if has_two_hole_cards or stack_signal >= 0.025 or stack_text_signal >= 0.025:
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


def _looks_like_winner_overlay(
    bet_crop: np.ndarray,
    action_crop: np.ndarray,
    *,
    bet_text_signal: float,
    bet_yellow_signal: float,
    action_yellow_signal: float,
) -> bool:
    """Identify the large white/gold WIN decoration crossing a bet ROI.

    Reuse the existing signal boundaries: a normal yellow action pill is much
    stronger, while a dealer button does not have enough text in the broader
    action crop.  Requiring all signals keeps legitimate Call + bet labels and
    the dealer button untouched.
    """

    if bet_crop.size == 0 or action_crop.size == 0:
        return False
    return bool(
        0.0 < bet_yellow_signal < 0.010
        and 0.006 <= action_yellow_signal < 0.010
        and bet_text_signal >= 0.020
        and _name_text_signal(action_crop) >= 0.025
    )


def _looks_like_winner_label_overlay(image: np.ndarray, action_pill: str) -> bool:
    """Recognize WIN after precise wager ROIs no longer overlap the banner.

    On the left seat the large gold WIN word occupies the action-label band,
    while the corrected wager ROI sits to its right.  WIN has considerably
    more white lettering but a weaker compact-yellow text signal than a real
    Call/Check pill, which keeps this fallback independent of seat geometry.
    """

    if action_pill != "yellow" or image.size == 0 or image.ndim < 3:
        return False
    channels = image[:, :, :3]
    white_ratio = float(
        (
            (channels[:, :, 0] > 160)
            & (channels[:, :, 1] > 160)
            & (channels[:, :, 2] > 160)
        ).mean()
    )
    return bool(
        white_ratio >= 0.125
        and _name_text_signal(image) >= 0.160
        and _yellow_win_text_signal(image) < 0.015
    )


def _action_label_roi(name_roi: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Return the compact ClubGG action-pill band immediately above a name."""

    x, y, width, _height = name_roi
    top = max(0.0, float(y) - 0.052)
    return float(x), top, float(width), min(0.060, 1.0 - top)


def _pad_hole_card_roi_left(roi: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x, y, width, height = roi
    pad = min(0.012, float(x))
    return float(x) - pad, float(y), min(1.0 - (float(x) - pad), float(width) + pad), float(height)


def _detect_action_pill(image: np.ndarray) -> tuple[str, float]:
    """Detect the colored compact action pill without blocking on OCR.

    ClubGG uses a blue pill for Bet/Raise, a yellow pill for Call/Check and a
    red pill for Fold. The amount channel disambiguates Call from Check; later
    state inference disambiguates Bet from Raise.
    """

    if image.size == 0 or image.ndim < 3:
        return "none", 0.0
    channels = image[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    red_ratio = float(((red > 130) & (red > green * 1.25) & (red > blue * 1.50)).mean())
    yellow_ratio = float(((red > 130) & (green > 90) & (blue < 120) & ((red - blue) > 35)).mean())
    blue_ratio = float(((blue > 90) & (green > 60) & (blue > red * 1.30)).mean())
    cyan_ratio = float(((blue > 100) & (green > 100) & (red < 120)).mean())
    if red_ratio >= 0.045 and yellow_ratio < 0.012:
        return "fold", min(0.96, 0.76 + red_ratio * 3.0)
    if yellow_ratio >= 0.045:
        return "yellow", min(0.94, 0.72 + yellow_ratio * 2.5)
    if blue_ratio >= 0.080 and cyan_ratio >= 0.080:
        return "blue", min(0.94, 0.70 + max(blue_ratio, cyan_ratio) * 1.6)
    return "none", 0.0


def _detect_dealer_by_geometry(
    frame: np.ndarray,
    profile: FixedGgProfile | FittedGgProfile,
    seats: list[GgSeat],
) -> tuple[int | None, float]:
    try:
        import cv2
    except Exception:
        return None, 0.0
    if frame.size == 0 or frame.ndim < 3:
        return None, 0.0
    channels = frame[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    yellow = (red > 135) & (green > 95) & (blue < 120) & ((red - blue) > 35)
    # Exclude the Bad Beat banner/title bar and the board cards. The dealer
    # button lives around the table ring, not in the top chrome or board strip.
    height, width = yellow.shape[:2]
    yellow[: int(height * 0.22), :] = False
    yellow[int(height * 0.38): int(height * 0.60), int(width * 0.28): int(width * 0.72)] = False
    mask = yellow.astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[tuple[float, tuple[float, float]]] = []
    for contour in contours:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        area = float(cv2.contourArea(contour))
        if area < max(14.0, width * height * 0.00004):
            continue
        if area > width * height * 0.004:
            continue
        aspect = box_width / max(1, box_height)
        if not 0.45 <= aspect <= 1.95:
            continue
        center = (x + box_width / 2.0, y + box_height / 2.0)
        ring_score = 1.0 - min(1.0, abs((center[1] / max(1, height)) - 0.66) / 0.50)
        candidates.append((float(area) * max(0.2, ring_score), center))
    if not candidates:
        return None, 0.0
    _score, point = max(candidates, key=lambda item: item[0])
    active_indexes = {int(seat.physicalSeatIndex) for seat in seats if seat.active}
    centers: dict[int, tuple[float, float]] = {}
    for seat in profile.seats:
        roi = seat.active
        centers[int(seat.index)] = ((roi[0] + roi[2] / 2) * width, (roi[1] + roi[3] / 2) * height)
    candidate_indexes = active_indexes or set(centers)
    if not candidate_indexes:
        return None, 0.0
    best_index = min(candidate_indexes, key=lambda index: _distance(point, centers.get(index, point)))
    best_distance = _distance(point, centers.get(best_index, point))
    confidence = max(0.0, min(1.0, 1.0 - best_distance / max(width, height)))
    return int(best_index), confidence


def _distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return ((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2) ** 0.5


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
    cleaned = re.sub(r"[^0-9A-Za-z\u0590-\u05ff_. \[\](){}-]+", " ", cleaned)
    cleaned = " ".join(cleaned.split())
    cleaned = cleaned.strip(" -_{}[]()\\/")
    cleaned = re.sub(r"([A-Za-z])O(?=\d)", r"\g<1>0", cleaned)
    cleaned = re.sub(r"lS$", "IS", cleaned)
    cleaned = re.sub(r"^a(?=[A-Z]{2}\d)", "", cleaned)
    canonical = {
        "cedarkoi": "CedarKoi",
        "joeyis": "joeyIS",
        "jetstreamv": "JetStreamV",
    }.get(cleaned.lower())
    if canonical:
        cleaned = canonical
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


def _position_labels(active_count: int) -> list[str]:
    if active_count <= 0:
        return []
    if active_count == 1:
        return ["BTN"]
    if active_count == 2:
        return ["BTN/SB", "BB"]
    middle_by_count = {
        3: [],
        4: ["UTG"],
        5: ["UTG", "CO"],
        6: ["UTG", "HJ", "CO"],
        7: ["UTG", "UTG+1", "HJ", "CO"],
        8: ["UTG", "UTG+1", "MP", "HJ", "CO"],
        9: ["UTG", "UTG+1", "MP", "LJ", "HJ", "CO"],
    }
    middle = middle_by_count.get(active_count)
    if middle is None:
        middle = ["UTG", *[f"UTG+{index}" for index in range(1, max(1, active_count - 4))], "HJ", "CO"]
        middle = middle[-max(0, active_count - 3):]
    return ["BTN", "SB", "BB", *middle[: max(0, active_count - 3)]]


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
