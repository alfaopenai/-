from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any, Iterable

import numpy as np

from .fast_amount import amount_text_signal
from .fixed_profile import (
    CLUBGG_COMPACT_6MAX,
    CLUBGG_COMPACT_7MAX,
    CLUBGG_COMPACT_8MAX,
    CLUBGG_FIXED_8MAX,
    FixedGgProfile,
    FixedSeatProfile,
    NormRoi,
)
from .roi import crop_norm
from .table_crop import validate_real_clubgg_crop


@dataclass(frozen=True)
class FittedGgProfile:
    base: FixedGgProfile
    offset_x: float = 0.0
    offset_y: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    fit_score: float = 0.0
    diagnostics: dict[str, Any] | None = None

    @property
    def name(self) -> str:
        return self.base.name

    @property
    def table_type(self) -> str:
        return self.base.table_type

    @property
    def seat_order_clockwise(self) -> tuple[int, ...]:
        return self.base.seat_order_clockwise

    @property
    def small_blind(self) -> float:
        return self.base.small_blind

    @property
    def big_blind(self) -> float:
        return self.base.big_blind

    @property
    def hero_seat_index(self) -> int | None:
        return self.base.hero_seat_index

    @property
    def title_blinds(self) -> NormRoi:
        return self.transform_roi(self.base.title_blinds)

    @property
    def pot(self) -> NormRoi:
        return self.transform_roi(self.base.pot)

    @property
    def board(self) -> tuple[NormRoi, ...]:
        return tuple(self.transform_roi(roi) for roi in self.base.board)

    @property
    def seats(self) -> tuple[FixedSeatProfile, ...]:
        fitted: list[FixedSeatProfile] = []
        for seat in self.base.seats:
            fitted.append(
                FixedSeatProfile(
                    index=seat.index,
                    label=seat.label,
                    name=self.transform_roi(seat.name),
                    stack=self.transform_roi(seat.stack),
                    bet=self.transform_roi(seat.bet),
                    cards=(self.transform_roi(seat.cards[0]), self.transform_roi(seat.cards[1])),
                    active=self.transform_roi(seat.active),
                    dealer=self.transform_roi(seat.dealer),
                    action=self.transform_roi(seat.action) if seat.action else self.transform_roi(seat.bet),
                )
            )
        return tuple(fitted)

    def transform_roi(self, roi: NormRoi) -> NormRoi:
        x, y, width, height = roi
        scaled_x = ((float(x) - 0.5) * self.scale_x) + 0.5 + self.offset_x
        scaled_y = ((float(y) - 0.5) * self.scale_y) + 0.5 + self.offset_y
        scaled_width = float(width) * self.scale_x
        scaled_height = float(height) * self.scale_y
        left = max(0.0, min(0.995, scaled_x))
        top = max(0.0, min(0.995, scaled_y))
        right = max(left, min(1.0, left + max(0.001, scaled_width)))
        bottom = max(top, min(1.0, top + max(0.001, scaled_height)))
        return left, top, right - left, bottom - top

    def all_rois(self) -> Iterable[tuple[str, NormRoi]]:
        yield "title/blinds", self.title_blinds
        yield "pot", self.pot
        for index, roi in enumerate(self.board):
            yield f"board-{index + 1}", roi
        for seat in self.seats:
            yield f"seat-{seat.index}:{seat.label}:active", seat.active
            yield f"seat-{seat.index}:{seat.label}:name", seat.name
            yield f"seat-{seat.index}:{seat.label}:stack", seat.stack
            yield f"seat-{seat.index}:{seat.label}:bet", seat.bet
            yield f"seat-{seat.index}:{seat.label}:action", seat.action or seat.bet
            yield f"seat-{seat.index}:{seat.label}:dealer", seat.dealer
            yield f"seat-{seat.index}:{seat.label}:card-1", seat.cards[0]
            yield f"seat-{seat.index}:{seat.label}:card-2", seat.cards[1]

    @property
    def fit_signature(self) -> tuple[str, float, float, float, float]:
        return (
            self.name,
            round(self.offset_x, 4),
            round(self.offset_y, 4),
            round(self.scale_x, 4),
            round(self.scale_y, 4),
        )


def choose_and_fit_profile(
    frame: np.ndarray,
    preferred: FixedGgProfile | FittedGgProfile | None = None,
) -> FittedGgProfile:
    source_validation = validate_real_clubgg_crop(frame)
    preferred_base = preferred.base if isinstance(preferred, FittedGgProfile) else preferred
    preferred_name = preferred_base.name if preferred_base is not None else ""
    bases = _candidate_bases(preferred)
    if not source_validation.is_real_clubgg:
        base = preferred_base or bases[0]
        return FittedGgProfile(
            base=base,
            fit_score=0.0,
            diagnostics={
                "fitError": "source-not-real-clubgg",
                **source_validation.as_diagnostics(),
            },
        )
    best: FittedGgProfile | None = None
    best_score = -1.0
    best_diagnostics: dict[str, Any] = {}
    title_layout_hint = _title_text_hint(frame)

    search_points = (
        (0.0, 0.0, 1.0, 1.0),
        (-0.025, 0.0, 1.0, 1.0),
        (0.025, 0.0, 1.0, 1.0),
        (0.0, -0.025, 1.0, 1.0),
        (0.0, 0.025, 1.0, 1.0),
        (-0.050, 0.0, 1.0, 1.0),
        (0.050, 0.0, 1.0, 1.0),
        (0.0, -0.050, 1.0, 1.0),
        (0.0, 0.050, 1.0, 1.0),
        (0.0, 0.0, 0.96, 0.96),
        (0.0, 0.0, 1.04, 1.04),
        (0.0, 0.0, 0.98, 1.02),
        (0.0, 0.0, 1.02, 0.98),
        (0.0, -0.010, 0.955, 0.930),
        (0.0, 0.010, 0.955, 0.930),
        (0.0, -0.015, 0.960, 0.940),
        (-0.025, -0.025, 0.98, 0.98),
        (0.025, 0.025, 0.98, 0.98),
        (-0.025, 0.025, 1.02, 1.02),
        (0.025, -0.025, 1.02, 1.02),
    )
    for base in bases:
        for offset_x, offset_y, scale_x, scale_y in search_points:
            candidate = FittedGgProfile(
                base=base,
                offset_x=offset_x,
                offset_y=offset_y,
                scale_x=scale_x,
                scale_y=scale_y,
            )
            score, diagnostics = score_profile_fit(frame, candidate)
            layout_bonus = _layout_title_bonus(frame, base, title_layout_hint)
            exact_window_bonus = (
                0.075
                if offset_x == 0.0
                and offset_y == 0.0
                and scale_x == 1.0
                and scale_y == 1.0
                and _looks_like_unpadded_compact_window(frame, base)
                else 0.0
            )
            padded_crop_bonus = _padded_compact_crop_bonus(
                frame,
                base,
                offset_x=offset_x,
                offset_y=offset_y,
                scale_x=scale_x,
                scale_y=scale_y,
            )
            adjusted_score = (
                score
                + layout_bonus
                + exact_window_bonus
                + padded_crop_bonus
                - (abs(offset_x) + abs(offset_y)) * 0.08
                - (abs(scale_x - 1.0) + abs(scale_y - 1.0)) * 0.05
            )
            if base.name == preferred_name:
                adjusted_score += 0.035
            elif base.name == "clubgg_fixed_8max" and preferred_name != "clubgg_fixed_8max":
                adjusted_score -= 0.035
            if adjusted_score > best_score:
                best_score = adjusted_score
                best = candidate
                best_diagnostics = {
                    **diagnostics,
                    **source_validation.as_diagnostics(),
                    "rawFitScore": round(score, 4),
                    "layoutTitleBonus": round(layout_bonus, 4),
                    "exactWindowBonus": round(exact_window_bonus, 4),
                    "paddedCropBonus": round(padded_crop_bonus, 4),
                    "titleLayoutHint": title_layout_hint,
                }

    if best is None:
        base = bases[0]
        return FittedGgProfile(base=base, diagnostics={"fitError": "no-candidates"})
    return FittedGgProfile(
        base=best.base,
        offset_x=best.offset_x,
        offset_y=best.offset_y,
        scale_x=best.scale_x,
        scale_y=best.scale_y,
        fit_score=best_score,
        diagnostics=best_diagnostics,
    )


def score_profile_fit(frame: np.ndarray, profile: FittedGgProfile) -> tuple[float, dict[str, Any]]:
    if frame is None or frame.size == 0:
        return 0.0, {}

    pot_score = min(1.0, amount_text_signal(crop_norm(frame, profile.pot)) * 35.0)
    stack_scores: list[float] = []
    bet_scores: list[float] = []
    card_scores: list[float] = []
    name_scores: list[float] = []
    dealer_scores: list[float] = []
    active_scores: list[float] = []

    for seat in profile.seats:
        stack_scores.append(min(1.0, _cyan_signal(crop_norm(frame, seat.stack)) * 24.0))
        bet_scores.append(min(1.0, amount_text_signal(crop_norm(frame, seat.bet)) * 30.0))
        name_scores.append(min(1.0, _white_text_signal(crop_norm(frame, seat.name)) * 18.0))
        active_scores.append(min(1.0, _panel_signal(crop_norm(frame, seat.active)) * 2.4))
        dealer_scores.append(_dealer_signal(crop_norm(frame, seat.dealer)))
        for card_roi in seat.cards:
            card_scores.append(_card_presence_signal(crop_norm(frame, card_roi)))

    board_scores = [_card_presence_signal(crop_norm(frame, roi)) for roi in profile.board]
    extra_layout_penalty = _extra_seat_penalty(frame, profile)
    top_stacks = sorted(stack_scores, reverse=True)[:5]
    top_cards = sorted(card_scores, reverse=True)[:8]
    top_names = sorted(name_scores, reverse=True)[:5]
    top_active = sorted(active_scores, reverse=True)[:6]
    top_bets = sorted(bet_scores, reverse=True)[:4]
    score = (
        pot_score * 0.12
        + _avg(top_stacks) * 0.24
        + _avg(top_cards) * 0.22
        + _avg(top_names) * 0.14
        + _avg(top_active) * 0.16
        + max(dealer_scores or [0.0]) * 0.06
        + _avg(board_scores) * 0.04
        + _avg(top_bets) * 0.02
        - extra_layout_penalty
    )
    diagnostics = {
        "profile": profile.name,
        "offsetX": round(profile.offset_x, 4),
        "offsetY": round(profile.offset_y, 4),
        "scaleX": round(profile.scale_x, 4),
        "scaleY": round(profile.scale_y, 4),
        "potSignalScore": round(pot_score, 4),
        "stackSignalScore": round(_avg(top_stacks), 4),
        "cardSignalScore": round(_avg(top_cards), 4),
        "nameSignalScore": round(_avg(top_names), 4),
        "activeSignalScore": round(_avg(top_active), 4),
        "dealerSignalScore": round(max(dealer_scores or [0.0]), 4),
        "boardSignalScore": round(_avg(board_scores), 4),
        "betSignalScore": round(_avg(top_bets), 4),
        "extraSeatPenalty": round(extra_layout_penalty, 4),
    }
    return float(score), diagnostics


def _candidate_bases(preferred: FixedGgProfile | FittedGgProfile | None) -> tuple[FixedGgProfile, ...]:
    if isinstance(preferred, FittedGgProfile):
        preferred = preferred.base
    candidates: list[FixedGgProfile] = []
    if preferred is not None:
        candidates.append(preferred)
    for profile in (CLUBGG_COMPACT_7MAX, CLUBGG_COMPACT_6MAX, CLUBGG_COMPACT_8MAX, CLUBGG_FIXED_8MAX):
        if all(item.name != profile.name for item in candidates):
            candidates.append(profile)
    return tuple(candidates)


def _layout_title_bonus(frame: np.ndarray, profile: FixedGgProfile, title_layout_hint: str = "") -> float:
    title = crop_norm(frame, profile.title_blinds)
    if title.size == 0 or title.ndim < 3:
        return 0.0
    # A cheap non-OCR hint: compact 6/7max titles often include "(6max)" or
    # "(7max)" in bright glyphs near the left title bar. We avoid blocking on
    # OCR and just score the visual title band plus the window aspect.
    height, width = frame.shape[:2]
    aspect = width / max(1, height)
    bonus = 0.0
    if profile.table_type in {"6max", "7max"} and aspect < 1.50:
        bonus += 0.035
    if profile.table_type == "8max" and aspect >= 1.50:
        bonus += 0.018
    normalized_hint = title_layout_hint.lower()
    hinted_table_type = ""
    if re.search(r"\b6\s*max\b", normalized_hint):
        hinted_table_type = "6max"
    elif re.search(r"\b7\s*max\b", normalized_hint):
        hinted_table_type = "7max"
    elif re.search(r"\b8\s*max\b", normalized_hint):
        hinted_table_type = "8max"
    if hinted_table_type:
        if profile.table_type == hinted_table_type:
            bonus += 0.22
        elif profile.table_type in {"6max", "7max", "8max"}:
            bonus -= 0.12
    return bonus


def _title_text_hint(frame: np.ndarray) -> str:
    if frame is None or frame.size == 0 or frame.ndim < 3:
        return ""
    try:
        import cv2
        import pytesseract
    except Exception:
        return ""

    try:
        tesseract_cmd = os.environ.get("TESSERACT_CMD")
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        height, width = frame.shape[:2]
        title = frame[: max(1, int(height * 0.075)), : max(1, int(width * 0.46)), :3]
        gray = cv2.cvtColor(title, cv2.COLOR_BGR2GRAY)
        scaled = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        _, threshold = cv2.threshold(scaled, 70, 255, cv2.THRESH_BINARY)
        config = (
            "--psm 7 "
            "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/-(). "
        )
        raw = pytesseract.image_to_string(threshold, config=config)
    except Exception:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9()/.\- ]+", " ", raw or "")
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def _extra_seat_penalty(frame: np.ndarray, profile: FittedGgProfile) -> float:
    if profile.base.name == "clubgg_compact_7max":
        extra_probe = FittedGgProfile(
            CLUBGG_COMPACT_8MAX,
            offset_x=profile.offset_x,
            offset_y=profile.offset_y,
            scale_x=profile.scale_x,
            scale_y=profile.scale_y,
        )
        upper_left = next(seat for seat in extra_probe.seats if seat.index == 7)
        upper_left_stack = crop_norm(frame, upper_left.stack)
        upper_left_name = crop_norm(frame, upper_left.name)
        signal = max(_cyan_signal(upper_left_stack) * 12.0, _white_text_signal(upper_left_name) * 10.0)
        if signal < 0.35:
            return 0.0
        return min(0.16, (signal - 0.35) * 0.20)
    if profile.base.name == "clubgg_compact_6max":
        seat_probe = FittedGgProfile(
            CLUBGG_COMPACT_7MAX,
            offset_x=profile.offset_x,
            offset_y=profile.offset_y,
            scale_x=profile.scale_x,
            scale_y=profile.scale_y,
        )
        top_seat = next(seat for seat in seat_probe.seats if seat.index == 0)
        top_take_seat = crop_norm(frame, top_seat.active)
        signal = _panel_signal(top_take_seat)
        if signal < 0.35:
            return 0.0
        return min(0.18, (signal - 0.35) * 0.24)
    return 0.0


def _looks_like_unpadded_compact_window(frame: np.ndarray, profile: FixedGgProfile) -> bool:
    if profile.table_type not in {"6max", "7max", "8max"}:
        return False
    if profile.name == "clubgg_fixed_8max":
        return False
    height, width = frame.shape[:2]
    return 800 <= width <= 870 and 590 <= height <= 650


def _padded_compact_crop_bonus(
    frame: np.ndarray,
    profile: FixedGgProfile,
    *,
    offset_x: float,
    offset_y: float,
    scale_x: float,
    scale_y: float,
) -> float:
    if profile.table_type not in {"6max", "7max", "8max"}:
        return 0.0
    height, width = frame.shape[:2]
    looks_like_padded_live_crop = 870 <= width <= 930 and 650 <= height <= 710 and width / max(1, height) < 1.36
    if not looks_like_padded_live_crop:
        return 0.0
    matches_content_inset = (
        abs(offset_x) <= 0.012
        and -0.025 <= offset_y <= 0.002
        and 0.945 <= scale_x <= 0.970
        and 0.920 <= scale_y <= 0.945
    )
    if not matches_content_inset:
        return 0.0
    return 0.04


def _avg(values: list[float]) -> float:
    usable = [float(value) for value in values if value and value > 0]
    return sum(usable) / len(usable) if usable else 0.0


def _cyan_signal(image: np.ndarray) -> float:
    if image.size == 0 or image.ndim < 3:
        return 0.0
    channels = image[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    mask = (blue > 90) & (green > 90) & (red < 145) & ((blue - red) > 25) & ((green - red) > 25)
    return float(mask.mean())


def _white_text_signal(image: np.ndarray) -> float:
    if image.size == 0 or image.ndim < 3:
        return 0.0
    channels = image[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    white = (red > 150) & (green > 150) & (blue > 150)
    cyan = (blue > 95) & (green > 95) & (red < 145)
    return float(np.logical_or(white, cyan).mean())


def _panel_signal(image: np.ndarray) -> float:
    if image.size == 0 or image.ndim < 3:
        return 0.0
    channels = image[:, :, :3]
    gray = np.mean(channels, axis=2)
    dark = float((gray < 85).mean())
    text = _white_text_signal(image)
    cyan = _cyan_signal(image)
    return min(1.0, dark * 0.65 + text * 10.0 + cyan * 16.0)


def _card_presence_signal(image: np.ndarray) -> float:
    if image.size == 0 or image.ndim < 3:
        return 0.0
    channels = image[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    gray = np.mean(channels, axis=2)
    bright_ratio = float((gray > 120).mean())
    white_ratio = float(((red > 205) & (green > 205) & (blue > 205)).mean())
    blue_back_ratio = float((blue > red * 1.08).mean())
    color_std = float(np.std(channels[:, :, :3]))
    return min(1.0, bright_ratio * 0.8 + white_ratio * 0.9 + blue_back_ratio * 0.18 + max(0.0, 55.0 - color_std) / 120.0)


def _dealer_signal(image: np.ndarray) -> float:
    if image.size == 0 or image.ndim < 3:
        return 0.0
    channels = image[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    mask = (red > 130) & (green > 90) & (blue < 145) & ((red - blue) > 25)
    return min(1.0, float(mask.mean()) * 5.0)
