from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


NormRoi = tuple[float, float, float, float]


@dataclass(frozen=True)
class FixedSeatProfile:
    index: int
    label: str
    name: NormRoi
    stack: NormRoi
    bet: NormRoi
    cards: tuple[NormRoi, NormRoi]
    active: NormRoi
    dealer: NormRoi
    action: NormRoi | None = None


@dataclass(frozen=True)
class FixedGgProfile:
    name: str
    table_type: str
    title_blinds: NormRoi
    pot: NormRoi
    board: tuple[NormRoi, ...]
    seats: tuple[FixedSeatProfile, ...]
    small_blind: float = 2.0
    big_blind: float = 4.0
    hero_seat_index: int | None = 4

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


# The ClubGG table surface is fixed. These normalized ROIs intentionally cover
# only cards, player panels, bet chips, pot text, title text, and dealer-button
# candidates; the fast reader never needs board/card contour scans.
CLUBGG_FIXED_8MAX = FixedGgProfile(
    name="clubgg_fixed_8max",
    table_type="8max",
    title_blinds=(0.018, 0.004, 0.180, 0.032),
    pot=(0.435, 0.355, 0.155, 0.060),
    board=(
        (0.342, 0.385, 0.055, 0.125),
        (0.402, 0.385, 0.055, 0.125),
        (0.462, 0.385, 0.055, 0.125),
        (0.522, 0.385, 0.055, 0.125),
        (0.582, 0.385, 0.055, 0.125),
    ),
    seats=(
        FixedSeatProfile(
            index=0,
            label="top",
            name=(0.440, 0.195, 0.135, 0.040),
            stack=(0.452, 0.235, 0.125, 0.040),
            bet=(0.375, 0.270, 0.105, 0.070),
            cards=((0.450, 0.105, 0.050, 0.105), (0.497, 0.105, 0.050, 0.105)),
            active=(0.430, 0.100, 0.155, 0.185),
            dealer=(0.400, 0.265, 0.045, 0.055),
            action=(0.375, 0.255, 0.145, 0.095),
        ),
        FixedSeatProfile(
            index=1,
            label="upper-right",
            name=(0.765, 0.285, 0.130, 0.045),
            stack=(0.772, 0.320, 0.120, 0.045),
            bet=(0.718, 0.365, 0.090, 0.070),
            cards=((0.775, 0.190, 0.052, 0.110), (0.822, 0.190, 0.052, 0.110)),
            active=(0.755, 0.185, 0.150, 0.190),
            dealer=(0.720, 0.360, 0.050, 0.060),
            action=(0.700, 0.350, 0.140, 0.095),
        ),
        FixedSeatProfile(
            index=2,
            label="right",
            name=(0.855, 0.545, 0.145, 0.045),
            stack=(0.875, 0.580, 0.120, 0.045),
            bet=(0.785, 0.510, 0.070, 0.080),
            cards=((0.865, 0.445, 0.050, 0.100), (0.910, 0.445, 0.050, 0.100)),
            active=(0.850, 0.440, 0.150, 0.190),
            dealer=(0.790, 0.455, 0.055, 0.065),
            action=(0.760, 0.485, 0.125, 0.105),
        ),
        FixedSeatProfile(
            index=3,
            label="bottom-right",
            name=(0.728, 0.790, 0.150, 0.045),
            stack=(0.735, 0.825, 0.140, 0.050),
            bet=(0.665, 0.610, 0.100, 0.070),
            cards=((0.735, 0.675, 0.055, 0.115), (0.790, 0.675, 0.055, 0.115)),
            active=(0.720, 0.665, 0.165, 0.215),
            dealer=(0.720, 0.710, 0.055, 0.065),
            action=(0.640, 0.585, 0.155, 0.095),
        ),
        FixedSeatProfile(
            index=4,
            label="bottom",
            name=(0.430, 0.855, 0.170, 0.050),
            stack=(0.430, 0.900, 0.160, 0.050),
            bet=(0.455, 0.610, 0.100, 0.070),
            cards=((0.438, 0.700, 0.057, 0.118), (0.493, 0.700, 0.057, 0.118)),
            active=(0.420, 0.690, 0.185, 0.265),
            dealer=(0.410, 0.805, 0.060, 0.070),
            action=(0.435, 0.590, 0.150, 0.100),
        ),
        FixedSeatProfile(
            index=5,
            label="bottom-left",
            name=(0.168, 0.785, 0.170, 0.045),
            stack=(0.178, 0.825, 0.145, 0.050),
            bet=(0.240, 0.610, 0.100, 0.070),
            cards=((0.160, 0.675, 0.057, 0.115), (0.215, 0.675, 0.057, 0.115)),
            active=(0.150, 0.665, 0.190, 0.210),
            dealer=(0.245, 0.705, 0.060, 0.070),
            action=(0.215, 0.585, 0.155, 0.095),
        ),
        FixedSeatProfile(
            index=6,
            label="left",
            name=(0.035, 0.545, 0.150, 0.045),
            stack=(0.050, 0.580, 0.135, 0.050),
            bet=(0.140, 0.500, 0.100, 0.070),
            cards=((0.035, 0.445, 0.055, 0.110), (0.088, 0.445, 0.055, 0.110)),
            active=(0.030, 0.435, 0.165, 0.205),
            dealer=(0.170, 0.500, 0.060, 0.070),
            action=(0.115, 0.475, 0.150, 0.100),
        ),
        FixedSeatProfile(
            index=7,
            label="upper-left",
            name=(0.135, 0.285, 0.135, 0.045),
            stack=(0.135, 0.322, 0.130, 0.045),
            bet=(0.225, 0.350, 0.075, 0.080),
            cards=((0.125, 0.165, 0.052, 0.115), (0.170, 0.165, 0.052, 0.115)),
            active=(0.120, 0.160, 0.160, 0.215),
            dealer=(0.135, 0.385, 0.060, 0.070),
            action=(0.200, 0.325, 0.135, 0.105),
        ),
    ),
)


CLUBGG_COMPACT_8MAX = FixedGgProfile(
    name="clubgg_compact_8max",
    table_type="8max",
    title_blinds=(0.002, 0.000, 0.220, 0.050),
    pot=(0.435, 0.355, 0.155, 0.060),
    board=(
        (0.310, 0.418, 0.075, 0.145),
        (0.387, 0.418, 0.075, 0.145),
        (0.464, 0.418, 0.075, 0.145),
        (0.541, 0.418, 0.075, 0.145),
        (0.618, 0.418, 0.075, 0.145),
    ),
    seats=(
        FixedSeatProfile(
            index=0,
            label="top",
            name=(0.435, 0.218, 0.145, 0.040),
            stack=(0.445, 0.255, 0.125, 0.040),
            bet=(0.465, 0.285, 0.080, 0.065),
            cards=((0.448, 0.105, 0.052, 0.115), (0.498, 0.105, 0.052, 0.115)),
            active=(0.420, 0.090, 0.180, 0.220),
            dealer=(0.400, 0.270, 0.055, 0.065),
            action=(0.430, 0.270, 0.145, 0.095),
        ),
        FixedSeatProfile(
            index=1,
            label="upper-right",
            name=(0.770, 0.300, 0.130, 0.045),
            stack=(0.790, 0.337, 0.115, 0.045),
            bet=(0.720, 0.365, 0.090, 0.070),
            cards=((0.775, 0.185, 0.052, 0.115), (0.828, 0.185, 0.052, 0.115)),
            active=(0.760, 0.175, 0.160, 0.225),
            dealer=(0.720, 0.360, 0.050, 0.060),
            action=(0.700, 0.350, 0.140, 0.095),
        ),
        FixedSeatProfile(
            index=2,
            label="right",
            name=(0.862, 0.548, 0.135, 0.045),
            stack=(0.875, 0.585, 0.120, 0.045),
            bet=(0.785, 0.505, 0.080, 0.080),
            cards=((0.865, 0.445, 0.052, 0.110), (0.918, 0.445, 0.052, 0.110)),
            active=(0.850, 0.435, 0.150, 0.205),
            dealer=(0.805, 0.455, 0.055, 0.065),
            action=(0.760, 0.485, 0.130, 0.105),
        ),
        FixedSeatProfile(
            index=3,
            label="bottom-right",
            name=(0.728, 0.790, 0.150, 0.045),
            stack=(0.748, 0.828, 0.125, 0.050),
            bet=(0.665, 0.610, 0.100, 0.070),
            cards=((0.735, 0.675, 0.055, 0.115), (0.790, 0.675, 0.055, 0.115)),
            active=(0.720, 0.665, 0.165, 0.215),
            dealer=(0.700, 0.708, 0.055, 0.065),
            action=(0.640, 0.585, 0.155, 0.095),
        ),
        FixedSeatProfile(
            index=4,
            label="bottom",
            name=(0.430, 0.870, 0.170, 0.050),
            stack=(0.432, 0.915, 0.160, 0.050),
            bet=(0.455, 0.635, 0.100, 0.070),
            cards=((0.438, 0.735, 0.057, 0.118), (0.493, 0.735, 0.057, 0.118)),
            active=(0.420, 0.720, 0.185, 0.265),
            dealer=(0.410, 0.805, 0.060, 0.070),
            action=(0.435, 0.615, 0.150, 0.100),
        ),
        FixedSeatProfile(
            index=5,
            label="bottom-left",
            name=(0.168, 0.785, 0.170, 0.045),
            stack=(0.178, 0.825, 0.145, 0.050),
            bet=(0.240, 0.610, 0.100, 0.070),
            cards=((0.160, 0.675, 0.057, 0.115), (0.215, 0.675, 0.057, 0.115)),
            active=(0.150, 0.665, 0.190, 0.210),
            dealer=(0.245, 0.705, 0.060, 0.070),
            action=(0.215, 0.585, 0.155, 0.095),
        ),
        FixedSeatProfile(
            index=6,
            label="left",
            name=(0.035, 0.545, 0.150, 0.045),
            stack=(0.050, 0.585, 0.135, 0.050),
            bet=(0.140, 0.500, 0.100, 0.070),
            cards=((0.035, 0.445, 0.055, 0.110), (0.088, 0.445, 0.055, 0.110)),
            active=(0.030, 0.435, 0.165, 0.205),
            dealer=(0.150, 0.505, 0.060, 0.070),
            action=(0.115, 0.475, 0.150, 0.100),
        ),
        FixedSeatProfile(
            index=7,
            label="upper-left",
            name=(0.120, 0.300, 0.145, 0.045),
            stack=(0.130, 0.337, 0.130, 0.045),
            bet=(0.225, 0.350, 0.075, 0.080),
            cards=((0.125, 0.185, 0.052, 0.115), (0.178, 0.185, 0.052, 0.115)),
            active=(0.105, 0.175, 0.175, 0.225),
            dealer=(0.135, 0.385, 0.060, 0.070),
            action=(0.200, 0.325, 0.135, 0.105),
        ),
    ),
    small_blind=2.0,
    big_blind=4.0,
    hero_seat_index=4,
)


def get_fixed_profile(
    name: str | None = None,
    *,
    frame_shape: tuple[int, ...] | None = None,
) -> FixedGgProfile:
    normalized_name = (name or "").lower()
    if normalized_name in {"clubgg_compact", "clubgg_compact_8max", "ggclub_compact_8max"}:
        return CLUBGG_COMPACT_8MAX
    if normalized_name in {"clubgg_fixed", "clubgg_fixed_8max", "ggclub_8max", "ggclub_9max"}:
        return CLUBGG_FIXED_8MAX

    if frame_shape:
        height, width = frame_shape[:2]
        # Browser/window captures of the compact ClubGG table arrive as the
        # table window itself, or as a small cropped window from a desktop share.
        if 420 <= width <= 1000 and 300 <= height <= 800:
            return CLUBGG_COMPACT_8MAX
    return CLUBGG_FIXED_8MAX
