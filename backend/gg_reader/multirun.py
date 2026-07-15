from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .models import GgCard
from .ocr import read_card
from .roi import crop_norm


NormRoi = tuple[float, float, float, float]

# ClubGG keeps the shared flop in the normal board row.  When Run It Multiple
# Times is accepted, the two branch cards fan into two rows over the normal
# turn/river columns.  During the deal animation an individual upper card can
# settle either one full card-height above the normal row or roughly three
# quarters of a card-height above it.  The observed 850x630 client positions
# were y=174 and y=194 for a normal board y=263 and card height=91.
SHARED_LIFT_CARD_HEIGHTS = 0.215
UPPER_ROW_CARD_HEIGHTS = (0.98, 0.76)
SHARED_X_NUDGE_WIDTHS = (0.0, 0.03)
# The branch row is rendered a few pixels to the right of the legacy compact
# turn/river ROIs (about +2 px for turn and +5 px for river at 850 px width).
# Desired nudges come first so equal-coverage template matches favor the
# aligned branch crop instead of the neighboring/overlapping card.
SUFFIX_X_NUDGE_WIDTHS = (0.03, 0.07, 0.0)
# The first card of run two is already live for equity while it slides from
# the chip/deck area into the lower branch.  On the captured compact table its
# face is about half a card left and half a card down from the settled slot.
# Reading this single well-constrained transition crop lets the UI match the
# on-table 85.71/14.28 update instead of waiting for the river animation.
LOWER_TRANSITION_OFFSETS = ((-0.45, 0.45),)
MIN_VISIBLE_CARD_CONFIDENCE = 0.72
# A correctly aligned white or terminal-dimmed card fills roughly 69-80% of
# its ROI in the captured client.  Empty felt and transient chips stay well
# below this deliberately permissive cutoff, so they never reach the much
# more expensive rank/suit template matcher.
MIN_CARD_FACE_COVERAGE = 0.30


@dataclass(frozen=True)
class DetectedRunout:
    index: int
    cards: tuple[GgCard, ...]
    confidence: float = 0.0


@dataclass(frozen=True)
class MultiRunBoardDetection:
    """A board split into a shared flop and zero, one, or two suffixes.

    ``runouts`` contains two entries for the upper/lower ClubGG branch layout,
    including an empty lower entry while the second run is still being dealt.
    A normal single board has at most one runout.  ``primary_board`` preserves
    the legacy five-card representation expected by the current reader.
    """

    shared_flop: tuple[GgCard, ...]
    runouts: tuple[DetectedRunout, ...]
    is_multiple: bool
    layout: str
    confidence: float = 0.0

    def primary_board(self) -> list[GgCard]:
        suffix = self.runouts[0].cards if self.runouts else ()
        return [
            *(card.model_copy(deep=True) for card in self.shared_flop),
            *(card.model_copy(deep=True) for card in suffix),
        ]


@dataclass(frozen=True)
class _CardCandidate:
    card: GgCard
    coverage: float
    roi: NormRoi


def detect_multirun_board(
    frame: np.ndarray,
    board_rois: Sequence[NormRoi] | None = None,
    *,
    profile: object | None = None,
) -> MultiRunBoardDetection:
    """Detect the normal board or ClubGG's upper/lower multi-run layout.

    Callers may pass the five fitted/base ``profile.board`` ROIs directly, or
    pass the profile itself.  No state is retained here; the table stabilizer
    can later stabilize each ``(runout.index, card slot)`` independently.
    """

    rois = _resolve_board_rois(board_rois, profile)
    if frame is None or frame.size == 0 or len(rois) < 5:
        return MultiRunBoardDetection((), (), False, "none", 0.0)

    shared_candidates: list[list[_CardCandidate]] = []
    for roi in rois[:3]:
        x, y, width, height = roi
        alternatives = [
            (x + width * x_nudge, y + height * y_offset, width, height)
            for y_offset in (0.0, -SHARED_LIFT_CARD_HEIGHTS)
            for x_nudge in SHARED_X_NUDGE_WIDTHS
        ]
        shared_candidates.append(_read_candidates(frame, alternatives))

    shared, seen = _select_contiguous_unique(shared_candidates, set())
    if len(shared) != 3:
        return MultiRunBoardDetection(tuple(shared), (), False, "partial", _cards_confidence(shared))

    upper_candidates: list[list[_CardCandidate]] = []
    for roi in rois[3:5]:
        x, y, width, height = roi
        upper_alternatives = [
            (x + width * x_nudge, y - height * lift, width, height)
            for lift in UPPER_ROW_CARD_HEIGHTS
            for x_nudge in SUFFIX_X_NUDGE_WIDTHS
        ]
        upper_candidates.append(_read_candidates(frame, upper_alternatives))

    upper, upper_seen = _select_contiguous_unique(upper_candidates, set(seen))
    if upper:
        # Presence in the displaced upper row is the unambiguous layout switch.
        # The normal row is now run two, not the turn/river of a single board.
        lower_candidates: list[list[_CardCandidate]] = []
        for roi in rois[3:5]:
            x, y, width, height = roi
            alternatives = [
                (x + width * x_nudge, y, width, height)
                for x_nudge in SUFFIX_X_NUDGE_WIDTHS
            ]
            alternatives.extend(
                (x + width * x_nudge, y + height * y_nudge, width, height)
                for x_nudge, y_nudge in LOWER_TRANSITION_OFFSETS
            )
            lower_candidates.append(_read_candidates(frame, alternatives))
        lower, _lower_seen = _select_contiguous_unique(lower_candidates, set(upper_seen))
        runouts = (
            DetectedRunout(0, tuple(upper), _cards_confidence(upper)),
            DetectedRunout(1, tuple(lower), _cards_confidence(lower)),
        )
        all_cards = [*shared, *upper, *lower]
        return MultiRunBoardDetection(
            tuple(shared),
            runouts,
            True,
            "upper-lower",
            _cards_confidence(all_cards),
        )

    normal_candidates: list[list[_CardCandidate]] = []
    for roi in rois[3:5]:
        x, y, width, height = roi
        alternatives = [
            (x + width * x_nudge, y, width, height)
            for x_nudge in SHARED_X_NUDGE_WIDTHS
        ]
        normal_candidates.append(_read_candidates(frame, alternatives))
    normal, _normal_seen = _select_contiguous_unique(normal_candidates, set(seen))
    runouts = (
        (DetectedRunout(0, tuple(normal), _cards_confidence(normal)),)
        if normal
        else ()
    )
    return MultiRunBoardDetection(
        tuple(shared),
        runouts,
        False,
        "single",
        _cards_confidence([*shared, *normal]),
    )


def has_multirun_layout(
    frame: np.ndarray,
    board_rois: Sequence[NormRoi] | None = None,
    *,
    profile: object | None = None,
) -> bool:
    """Cheaply identify two settled cards in ClubGG's displaced upper row."""

    rois = _resolve_board_rois(board_rois, profile)
    if frame is None or frame.size == 0:
        return False
    covered_slots = 0
    for roi in rois[3:5]:
        x, y, width, height = roi
        best = 0.0
        for lift in UPPER_ROW_CARD_HEIGHTS:
            for x_nudge in SUFFIX_X_NUDGE_WIDTHS:
                candidate = _clip_roi((x + width * x_nudge, y - height * lift, width, height))
                best = max(best, _card_face_coverage(crop_norm(frame, candidate)))
        if best >= MIN_CARD_FACE_COVERAGE:
            covered_slots += 1
    return covered_slots == 2


def primary_board(detection: MultiRunBoardDetection) -> list[GgCard]:
    """Backward-compatible helper for consumers that still accept one board."""

    return detection.primary_board()


def card_codes(cards: Sequence[GgCard]) -> list[str]:
    """Small diagnostic helper used by regression tests and debug output."""

    return [_card_id(card) for card in cards if _card_id(card)]


def _resolve_board_rois(
    board_rois: Sequence[NormRoi] | None,
    profile: object | None,
) -> tuple[NormRoi, ...]:
    source = board_rois
    if source is None and profile is not None:
        source = getattr(profile, "board", None)
    if source is None:
        raise ValueError("five board ROIs or a profile with .board are required")
    resolved = tuple(tuple(float(value) for value in roi) for roi in source)
    if len(resolved) < 5 or any(len(roi) != 4 for roi in resolved):
        raise ValueError("five normalized board ROIs are required")
    return resolved  # type: ignore[return-value]


def _read_candidates(frame: np.ndarray, rois: Sequence[NormRoi]) -> list[_CardCandidate]:
    # Geometry is cheap to score and rank/suit recognition is comparatively
    # expensive.  Prefer the crop that contains the most card face, then stop
    # as soon as that aligned crop yields a valid card.  This turns a normal
    # flop from dozens of template passes into three.
    scored: list[tuple[float, int, NormRoi, np.ndarray]] = []
    for order, roi in enumerate(rois):
        clipped = _clip_roi(roi)
        crop = crop_norm(frame, clipped)
        coverage = _card_face_coverage(crop)
        if coverage >= MIN_CARD_FACE_COVERAGE:
            scored.append((coverage, order, clipped, crop))

    scored.sort(key=lambda item: (-item[0], item[1]))
    for coverage, _order, clipped, crop in scored:
        data = read_card(crop)
        confidence = float(data.get("confidence") or 0.0)
        rank = str(data.get("rank") or "").upper()
        suit = str(data.get("suit") or "").upper()
        if (
            confidence < MIN_VISIBLE_CARD_CONFIDENCE
            or bool(data.get("hidden"))
            or not bool(data.get("visible"))
            or rank not in {"2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"}
            or suit not in {"S", "H", "D", "C"}
        ):
            continue
        card = GgCard(rank=rank, suit=suit, visible=True, hidden=False, confidence=confidence)
        return [_CardCandidate(card, coverage, clipped)]
    return []


def _select_contiguous_unique(
    slot_candidates: Sequence[Sequence[_CardCandidate]],
    seen: set[str],
) -> tuple[list[GgCard], set[str]]:
    selected: list[GgCard] = []
    accepted_ids = set(seen)
    for candidates in slot_candidates:
        chosen = next(
            (candidate for candidate in candidates if _card_id(candidate.card) not in accepted_ids),
            None,
        )
        if chosen is None:
            break
        card = chosen.card.model_copy(deep=True)
        selected.append(card)
        accepted_ids.add(_card_id(card))
    return selected, accepted_ids


def _candidate_quality(candidate: _CardCandidate) -> tuple[float, float]:
    # Coverage is the important tie-breaker during the fan animation: a crop
    # starting at the old row can still produce a plausible template match but
    # contains only ~50% card face, whereas the aligned crop contains 69-80%.
    return candidate.coverage, float(candidate.card.confidence or 0.0)


def _card_face_coverage(image: np.ndarray) -> float:
    if image.size == 0 or image.ndim < 3:
        return 0.0
    import cv2

    channels = image[:, :, :3]
    hsv = cv2.cvtColor(channels, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(channels, cv2.COLOR_BGR2GRAY)
    # Includes both normal white faces and ClubGG's dimmed gray terminal frame,
    # while excluding the saturated green felt around a misaligned ROI.
    face = (hsv[:, :, 1] < 85) & (gray > 48)
    return float(face.mean())


def _cards_confidence(cards: Sequence[GgCard]) -> float:
    values = [float(card.confidence or 0.0) for card in cards]
    return sum(values) / len(values) if values else 0.0


def _card_id(card: GgCard | None) -> str:
    if not card or card.hidden or not card.rank or not card.suit:
        return ""
    return f"{card.rank}{card.suit}".upper()


def _clip_roi(roi: NormRoi) -> NormRoi:
    x, y, width, height = roi
    left = max(0.0, min(1.0, float(x)))
    top = max(0.0, min(1.0, float(y)))
    right = max(left, min(1.0, float(x + width)))
    bottom = max(top, min(1.0, float(y + height)))
    return left, top, right - left, bottom - top
