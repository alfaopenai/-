from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np

from .fast_amount import amount_text_signal
from .fixed_profile import (
    CLUBGG_COMPACT_8MAX,
    CLUBGG_FIXED_8MAX,
    FixedGgProfile,
    FixedSeatProfile,
    NormRoi,
)
from .roi import crop_norm


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
    preferred_base = preferred.base if isinstance(preferred, FittedGgProfile) else preferred
    preferred_name = preferred_base.name if preferred_base is not None else ""
    bases = _candidate_bases(preferred)
    best: FittedGgProfile | None = None
    best_score = -1.0
    best_diagnostics: dict[str, Any] = {}

    search_points = (
        (0.0, 0.0, 1.0, 1.0),
        (0.0, -0.035, 1.0, 1.0),
        (0.0, 0.035, 1.0, 1.0),
        (-0.03, 0.0, 1.0, 1.0),
        (0.03, 0.0, 1.0, 1.0),
        (0.0, 0.0, 0.98, 0.98),
        (0.0, 0.0, 1.02, 1.02),
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
            adjusted_score = score - (abs(offset_x) + abs(offset_y)) * 0.12 - abs(scale_x - 1.0) * 0.35
            if base.name == preferred_name:
                adjusted_score += 0.02
            if adjusted_score > best_score:
                best_score = adjusted_score
                best = candidate
                best_diagnostics = {**diagnostics, "rawFitScore": round(score, 4)}

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
    }
    return float(score), diagnostics


def _candidate_bases(preferred: FixedGgProfile | FittedGgProfile | None) -> tuple[FixedGgProfile, ...]:
    if isinstance(preferred, FittedGgProfile):
        preferred = preferred.base
    candidates: list[FixedGgProfile] = []
    if preferred is not None:
        candidates.append(preferred)
    for profile in (CLUBGG_FIXED_8MAX, CLUBGG_COMPACT_8MAX):
        if all(item.name != profile.name for item in candidates):
            candidates.append(profile)
    return tuple(candidates)


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
