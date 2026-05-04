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

from .fast_amount import amount_text_signal, read_amount_fast
from .fixed_profile import FixedGgProfile, FixedSeatProfile, get_fixed_profile
from .models import GgCard, GgSeat, GgTableSnapshot
from .ocr import normalize_amount, read_amount, read_card, read_name
from .roi import crop_norm, downscale_hash, draw_roi_overlay, roi_changed, roi_mean_abs_diff


MIN_FAST_CONFIDENCE = 0.58
CARD_CHANGE_THRESHOLD = 3.5
TEXT_CHANGE_THRESHOLD = 4.0
DEALER_HOLD_SECONDS = 1.5
BAD_FRAME_HOLD_SECONDS = 1.2
MAX_PENDING_OCR = 3


@dataclass
class _FieldCache:
    value: Any = None
    confidence: float = 0.0
    raw: str = ""
    image_hash: np.ndarray | None = None
    future: Future[Any] | None = None
    requested_at: float = 0.0
    completed_at: float = 0.0
    known: bool = False


class FastGgReader:
    def __init__(self, profile: FixedGgProfile | None = None, *, ocr_workers: int = 1) -> None:
        self.profile = profile or get_fixed_profile()
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
            metrics = self._new_metrics()
            if frame is None or frame.size == 0 or frame.ndim < 2:
                return self._held_snapshot(metrics, started_at)

            quick_hash = self._quick_frame_hash(frame)
            quick_reuse = self._quick_reuse_snapshot(quick_hash, metrics, started_at)
            if quick_reuse is not None:
                return quick_reuse

            self._last_frame = frame
            if not self._looks_like_fixed_gg_frame(frame):
                return self._held_snapshot(metrics, started_at)
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
            self._finish_metrics(metrics, started_at, confidence)
            snapshot.metrics = dict(metrics)

            if confidence >= MIN_FAST_CONFIDENCE and active_count >= 2:
                self._last_snapshot = snapshot.model_copy(deep=True)
                self._last_snapshot_at = now
            return snapshot if confidence >= MIN_FAST_CONFIDENCE else None

    def get_metrics(self) -> dict[str, Any]:
        with self._lock:
            pending = self._pending_ocr_count()
            metrics = dict(self._last_metrics)
            metrics["ocrPending"] = pending
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
        return {
            "reader": "fast_roi",
            "profile": self.profile.name,
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
        }

    def _finish_metrics(self, metrics: dict[str, Any], started_at: float, confidence: float) -> None:
        parse_ms = round((time.perf_counter() - started_at) * 1000, 2)
        now = time.monotonic()
        self._parse_timestamps.append(now)
        self._parse_durations_ms.append(parse_ms)
        metrics["parseMs"] = parse_ms
        metrics["actualReaderFps"] = self._actual_fps()
        metrics["ocrPending"] = self._pending_ocr_count()
        metrics["confidence"] = round(float(confidence), 4)
        self._last_metrics = dict(metrics)

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
        if self._actual_fps() <= 4.5:
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

        stack_crop = crop_norm(frame, seat_profile.stack)
        bet_crop = crop_norm(frame, seat_profile.bet)
        stack_signal = _cyan_signal(stack_crop)
        active_signal = _active_signal(crop_norm(frame, seat_profile.active))
        likely_active = bool(hole_cards or stack_signal > 0.012 or active_signal > 0.10)

        stack = 0.0
        stack_confidence = 0.0
        current_bet = 0.0
        bet_confidence = 0.0
        name = ""
        name_confidence = 0.0
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

        active = bool(
            likely_active
            or stack_confidence >= 0.55
            or bet_confidence >= 0.55
            or stack > 0
            or current_bet > 0
        )
        if active and not name:
            name = f"GG Seat {seat_profile.index + 1}"

        current_bet = current_bet if bet_confidence >= 0.50 else 0.0
        stack = stack if stack_confidence >= 0.50 else 0.0
        action = "bet" if current_bet > 0 else "none"
        confidence = _estimate_confidence([
            min(0.95, active_signal),
            min(0.90, stack_signal * 16),
            stack_confidence,
            bet_confidence,
            name_confidence,
            *[card.confidence for card in hole_cards],
        ])
        if active and confidence < 0.72:
            confidence = 0.72

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
        retry_window_due = (
            entry.future is None
            and float(entry.confidence or 0.0) < 0.50
            and now - float(entry.requested_at or 0.0) >= max(2.0, stale_seconds)
        )
        if not changed and entry.known and not retry_window_due:
            metrics["fieldsReused"] += 1
            entry.image_hash = new_hash
            return float(entry.value or 0.0), float(entry.confidence or 0.0), str(entry.raw or "")

        signal = amount_text_signal(crop)
        if empty_is_zero and signal < 0.008:
            if changed or not entry.known or float(entry.value or 0.0) != 0.0:
                entry.value = 0.0
                entry.confidence = 0.92
                entry.raw = ""
                entry.known = True
                entry.completed_at = now
                metrics["fieldsUpdated"] += 1
            else:
                metrics["fieldsReused"] += 1
            entry.image_hash = new_hash
            return 0.0, 0.92, ""

        retry_due = retry_window_due and signal >= 0.008
        should_refresh = changed or not entry.known or retry_due
        if should_refresh:
            use_template_reader = key == "pot"
            if use_template_reader:
                fast_started_at = time.perf_counter()
                amount, confidence, raw = read_amount_fast(crop)
                metrics["ocrMs"] += round((time.perf_counter() - fast_started_at) * 1000, 2)
            else:
                amount, confidence, raw = 0.0, 0.0, ""
            if amount > 0 and confidence >= 0.80:
                entry.value = amount
                entry.confidence = confidence
                entry.raw = raw
                entry.known = True
                entry.completed_at = now
                metrics["fieldsUpdated"] += 1
            elif entry.future is None and self._can_queue_ocr(now):
                entry.future = self._executor.submit(read_amount, crop.copy())
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
        else:
            metrics["fieldsReused"] += 1
        entry.image_hash = new_hash
        return float(entry.value or 0.0), float(entry.confidence or 0.0), str(entry.raw or "")

    def _consume_amount_future(self, key: str, entry: _FieldCache, metrics: dict[str, Any]) -> None:
        future = entry.future
        if future is None or not future.done():
            return
        try:
            value, confidence, raw = future.result()
        except Exception:
            value, confidence, raw = 0.0, 0.0, ""
        entry.future = None
        suspicious_pot = key == "pot" and float(value or 0.0) > 20 and not re.search(r"(?i)[.KMB]|BB", str(raw or ""))
        if value > 0 and confidence >= 0.40 and not suspicious_pot:
            entry.value = float(value)
            entry.confidence = float(confidence)
            entry.raw = str(raw or "")
            entry.known = True
            entry.completed_at = time.monotonic()
            metrics["fieldsUpdated"] += 1
        metrics["ocrCompleted"] += 1

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
        should_refresh = changed or not entry.known or (now - entry.completed_at >= stale_seconds and bool(entry.value))
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
        if len(self._parse_timestamps) < 2:
            return 0.0
        span = max(0.25, self._parse_timestamps[-1] - self._parse_timestamps[0])
        return round((len(self._parse_timestamps) - 1) / span, 3)

    def _can_queue_ocr(self, now: float) -> bool:
        if self._pending_ocr_count() >= MAX_PENDING_OCR:
            return False
        if not self._parse_timestamps:
            return False
        current_fps = self._actual_fps()
        if current_fps and current_fps > 4.5:
            return False
        return now - self._parse_timestamps[-1] >= 0.25

    def _pending_ocr_count(self) -> int:
        return sum(1 for entry in self._fields.values() if entry.future is not None)

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


def _active_signal(image: np.ndarray) -> float:
    if image.size == 0 or image.ndim < 3:
        return 0.0
    channels = image[:, :, :3]
    gray = np.mean(channels, axis=2)
    bright = float((gray > 120).mean())
    cyan = _cyan_signal(image)
    return min(1.0, bright * 1.5 + cyan * 8)


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


def _estimate_confidence(values: list[float]) -> float:
    usable = [float(value) for value in values if value and value > 0]
    if not usable:
        return 0.0
    return max(0.0, min(1.0, sum(usable) / len(usable)))
