from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.gg_reader.models import GgCard, GgSeat, GgTableSnapshot
from backend.gg_reader.ocr import normalize_amount
from backend.gg_reader.profile_matcher import choose_and_fit_profile
from backend.gg_reader.table_crop import detect_clubgg_table_crop
from backend.gg_reader.table_state import TableStateStabilizer
from backend.main import infer_actions

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


class AmountNormalizationTest(unittest.TestCase):
    def test_bb_amount_formats(self) -> None:
        cases = {
            "152.4BB": 152.4,
            "73.5": 73.5,
            "1BB": 1.0,
            "0.5BB": 0.5,
            "1.5BB": 1.5,
            "207.5bb": 207.5,
            "110.5 BB": 110.5,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertAlmostEqual(normalize_amount(raw), expected, delta=0.001)


class TableStateStabilizerTest(unittest.TestCase):
    def test_weak_frame_does_not_clear_name_stack_or_cards(self) -> None:
        stabilizer = TableStateStabilizer()
        first = _snapshot(
            pot=6.5,
            seats=[
                _seat(
                    0,
                    name="A-Z777",
                    name_confidence=0.8,
                    stack=60.8,
                    stack_confidence=0.82,
                    cards=True,
                )
            ],
            pot_confidence=0.82,
        )
        stable = stabilizer.stabilize(first, now=time.monotonic())
        self.assertEqual(stable.seats[0].name, "A-Z777")

        weak = _snapshot(
            pot=0.0,
            seats=[
                _seat(
                    0,
                    name="",
                    name_confidence=0.0,
                    stack=0.0,
                    stack_confidence=0.0,
                    cards=False,
                )
            ],
            pot_confidence=0.0,
        )
        held = stabilizer.stabilize(weak, now=time.monotonic() + 0.2)
        self.assertEqual(held.pot, 6.5)
        self.assertEqual(held.seats[0].name, "A-Z777")
        self.assertAlmostEqual(held.seats[0].stack, 60.8)
        self.assertEqual(len(held.seats[0].holeCards), 2)

    def test_placeholder_name_does_not_overwrite_known_name(self) -> None:
        stabilizer = TableStateStabilizer()
        first = _snapshot(seats=[_seat(0, name="RealName", name_confidence=0.82)])
        stabilizer.stabilize(first, now=time.monotonic())

        placeholder = _snapshot(seats=[_seat(0, name="GG Seat 1", name_confidence=0.0)])
        held = stabilizer.stabilize(placeholder, now=time.monotonic() + 1.1)
        self.assertEqual(held.seats[0].name, "RealName")
        self.assertNotEqual(held.seats[0].name, "GG Seat 1")

    def test_bet_resets_only_after_two_empty_hits(self) -> None:
        stabilizer = TableStateStabilizer()
        first = _snapshot(seats=[_seat(0, current_bet=4.0, bet_confidence=0.82)])
        stabilizer.stabilize(first, now=time.monotonic())

        empty_once = _snapshot(seats=[_seat(0, current_bet=0.0, bet_confidence=0.92)])
        held = stabilizer.stabilize(empty_once, now=time.monotonic() + 1.1)
        self.assertEqual(held.seats[0].currentBet, 4.0)

        cleared = stabilizer.stabilize(empty_once, now=time.monotonic() + 2.2)
        self.assertEqual(cleared.seats[0].currentBet, 0.0)

    def test_cards_disappearing_twice_marks_fold(self) -> None:
        stabilizer = TableStateStabilizer()
        first = _snapshot(seats=[_seat(0, cards=True)])
        stabilizer.stabilize(first, now=time.monotonic())

        no_cards_once = _snapshot(seats=[_seat(0, cards=False)])
        once = stabilizer.stabilize(no_cards_once, now=time.monotonic() + 0.2)
        self.assertEqual(len(once.seats[0].holeCards), 2)

        twice = stabilizer.stabilize(no_cards_once, now=time.monotonic() + 1.4)
        self.assertEqual(twice.seats[0].status, "folded")
        self.assertEqual(twice.seats[0].action, "fold")
        self.assertEqual(twice.seats[0].actionSource, "cards_disappeared")


@unittest.skipIf(cv2 is None, "OpenCV is unavailable")
class DebugFrameCropProfileTest(unittest.TestCase):
    def test_crop_detection_from_latest_debug_frame(self) -> None:
        frame = _load_optional_image(ROOT / "backend" / "data" / "debug_last_frame.png")
        crop = detect_clubgg_table_crop(frame)
        self.assertGreaterEqual(crop.confidence, 0.20)
        self.assertGreaterEqual(crop.cropped_frame.shape[1], 320)
        self.assertGreaterEqual(crop.cropped_frame.shape[0], 240)

    def test_profile_fitting_alignment_on_latest_cropped_frame(self) -> None:
        frame = _load_optional_image(ROOT / "backend" / "data" / "debug_last_cropped_frame.png")
        profile = choose_and_fit_profile(frame)
        self.assertGreaterEqual(profile.fit_score, 0.25)
        self.assertIn(profile.name, {"clubgg_fixed_8max", "clubgg_compact_8max"})

    def test_pot_parsing_from_fixture_still_works(self) -> None:
        from backend.gg_reader.fast_reader import FastGgReader

        frame = _load_optional_image(ROOT / "tests" / "fixtures" / "gg_table_preflop.png")
        snapshot = FastGgReader().parse(frame)
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertAlmostEqual(snapshot.pot, 1.5, delta=0.2)
        self.assertGreaterEqual(snapshot.activePlayerCount, 2)


class ActionInferenceTest(unittest.TestCase):
    def test_bet_call_raise_and_all_in_sources(self) -> None:
        previous = _snapshot(seats=[
            _seat(0, current_bet=0.0),
            _seat(1, current_bet=4.0),
            _seat(2, current_bet=2.0),
            _seat(3, stack=10.0, current_bet=0.0),
            _seat(4, stack=10.0, current_bet=0.0),
        ])
        current = _snapshot(seats=[
            _seat(0, current_bet=2.0),
            _seat(1, current_bet=4.0),
            _seat(2, current_bet=4.0),
            _seat(3, stack=10.0, current_bet=9.0),
            _seat(4, stack=0.0, current_bet=9.0),
        ])
        infer_actions(current, previous)
        by_index = {seat.physicalSeatIndex: seat for seat in current.seats}
        self.assertEqual(by_index[0].action, "bet")
        self.assertEqual(by_index[0].actionSource, "bet_delta")
        self.assertEqual(by_index[2].action, "call")
        self.assertEqual(by_index[2].actionSource, "bet_delta")
        self.assertEqual(by_index[3].action, "raise")
        self.assertEqual(by_index[3].actionSource, "bet_delta")
        self.assertEqual(by_index[4].action, "all-in")
        self.assertEqual(by_index[4].actionSource, "stack_zero")

        all_in = _snapshot(seats=[_seat(0, stack=0.0, current_bet=10.0)])
        infer_actions(all_in, _snapshot(seats=[_seat(0, stack=10.0, current_bet=10.0)]))
        self.assertEqual(all_in.seats[0].action, "all-in")
        self.assertEqual(all_in.seats[0].actionSource, "stack_zero")


def _snapshot(
    *,
    pot: float = 1.5,
    seats: list[GgSeat] | None = None,
    pot_confidence: float = 0.82,
) -> GgTableSnapshot:
    return GgTableSnapshot(
        timestamp=int(time.time() * 1000),
        tableType="8max",
        street="preflop",
        pot=pot,
        activePlayerCount=len([seat for seat in seats or [] if seat.active]),
        dealerSeatIndex=0,
        seats=seats or [],
        confidence=0.86,
        metrics={
            "amountFields": [
                {"key": "pot", "value": pot, "confidence": pot_confidence, "source": "test"}
            ]
        },
    )


def _seat(
    index: int,
    *,
    name: str = "Hero",
    name_confidence: float = 0.75,
    stack: float = 100.0,
    stack_confidence: float = 0.82,
    current_bet: float = 0.0,
    bet_confidence: float = 0.92,
    cards: bool = True,
) -> GgSeat:
    return GgSeat(
        physicalSeatIndex=index,
        active=True,
        name=name,
        nameConfidence=name_confidence,
        stack=stack,
        stackConfidence=stack_confidence,
        currentBet=current_bet,
        betConfidence=bet_confidence,
        action="none",
        status="active",
        holeCards=[
            GgCard(hidden=True, visible=False, display="X", confidence=0.82),
            GgCard(hidden=True, visible=False, display="X", confidence=0.82),
        ] if cards else [],
        confidence=0.82,
    )


def _load_optional_image(path: Path) -> np.ndarray:
    if not path.exists():
        raise unittest.SkipTest(f"Debug image unavailable: {path}")
    frame = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if frame is None:
        raise unittest.SkipTest(f"Could not load image: {path}")
    return frame


if __name__ == "__main__":
    unittest.main()
