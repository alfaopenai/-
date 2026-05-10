from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from backend.gg_reader.fast_reader import FastGgReader
from backend.gg_reader.parser import parse_frame


REFERENCE_PREFLOP = ROOT / "tests" / "fixtures" / "clubgg_reference_preflop.png"
REFERENCE_TURN = ROOT / "tests" / "fixtures" / "clubgg_reference_turn.png"


@unittest.skipIf(cv2 is None, "OpenCV is unavailable")
class ClubGgReferenceScreenshotTest(unittest.TestCase):
    def test_reference_preflop_screenshot_comparison(self) -> None:
        frame = _load_reference(REFERENCE_PREFLOP)
        expected = {
            "street": "preflop",
            "pot": 1.5,
            "players": {
                "razfri": 167.1,
                "8Bamba": 199.0,
                "AAmid": 199.5,
                "KaiWest7": 302.5,
                "batahat sheli": 204.9,
            },
            "bets": [0.5, 1.0],
            "emptySeatsAtLeast": 2,
        }
        snapshot = _parse_reference(frame)
        self.assertIsNotNone(snapshot)
        _print_comparison("reference preflop", expected, snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.street, "preflop")
        self.assertAlmostEqual(float(snapshot.pot or 0.0), 1.5, delta=0.35)
        self.assertGreaterEqual(_empty_count(snapshot), 2)
        self.assertGreaterEqual(_named_count(snapshot), 3)

    def test_reference_turn_screenshot_comparison(self) -> None:
        frame = _load_reference(REFERENCE_TURN)
        expected = {
            "street": "turn",
            "pot": 7.3,
            "board": ["4D", "KC", "2C", "7S"],
            "players": {
                "razfri": 167.1,
                "8Bamba": 197.5,
                "AAmid": 199.5,
                "KaiWest7": 298.2,
                "batahat sheli": 204.9,
            },
            "bets": [5.5, 1.8],
            "emptySeatsAtLeast": 2,
        }
        snapshot = _parse_reference(frame)
        self.assertIsNotNone(snapshot)
        _print_comparison("reference turn", expected, snapshot)
        assert snapshot is not None
        self.assertIn(snapshot.street, {"turn", "river"})
        self.assertAlmostEqual(float(snapshot.pot or 0.0), 7.3, delta=0.5)
        self.assertGreaterEqual(_empty_count(snapshot), 2)
        self.assertGreaterEqual(len(_card_codes(snapshot.board)), 4)


def _load_reference(path: Path) -> Any:
    if not path.exists():
        raise unittest.SkipTest(
            f"Reference screenshot is unavailable: {path}. "
            "Save the two attached screenshots as clubgg_reference_preflop.png "
            "and clubgg_reference_turn.png in tests/fixtures to run this comparison."
        )
    frame = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if frame is None:
        raise unittest.SkipTest(f"Could not load reference screenshot: {path}")
    return frame


def _parse_reference(frame: Any) -> Any:
    reader = FastGgReader()
    deadline = time.perf_counter() + 45.0
    snapshot = None
    try:
        while time.perf_counter() < deadline:
            snapshot = parse_frame(frame, {}, reader, {"title": "NLH 1-2 BP (7max) - 1/2"})
            if snapshot is not None and snapshot.pot > 0 and _stacked_count(snapshot) >= 3:
                return snapshot
            time.sleep(0.10)
        return snapshot
    finally:
        reader.close()


def _print_comparison(label: str, expected: dict[str, Any], snapshot: Any) -> None:
    if snapshot is None:
        print(f"\n[{label}] no snapshot detected")
        return
    seats = sorted(snapshot.seats, key=lambda seat: int(seat.physicalSeatIndex))
    detected_players = {
        seat.name or f"seat-{seat.physicalSeatIndex}": round(float(seat.stack or 0.0), 1)
        for seat in seats
        if seat.active
    }
    detected = {
        "profile": snapshot.metrics.get("profile"),
        "street": snapshot.street,
        "pot": round(float(snapshot.pot or 0.0), 2),
        "board": _card_codes(snapshot.board),
        "dealerSeat": snapshot.dealerSeatIndex,
        "emptySeats": [seat.physicalSeatIndex for seat in seats if not seat.active],
        "players": detected_players,
        "bets": [
            round(float(seat.currentBet or 0.0), 2)
            for seat in seats
            if seat.active and float(seat.currentBet or 0.0) > 0
        ],
        "confidence": round(float(snapshot.confidence or 0.0), 3),
    }
    print(f"\n[{label}] expected={expected}")
    print(f"[{label}] detected={detected}")


def _card_codes(cards: list[Any]) -> list[str]:
    return [
        f"{card.rank}{card.suit}"
        for card in cards
        if card.visible and not card.hidden and card.rank and card.suit
    ]


def _empty_count(snapshot: Any) -> int:
    return sum(1 for seat in snapshot.seats if not seat.active)


def _named_count(snapshot: Any) -> int:
    return sum(1 for seat in snapshot.seats if seat.active and seat.name)


def _stacked_count(snapshot: Any) -> int:
    return sum(1 for seat in snapshot.seats if seat.active and float(seat.stack or 0.0) > 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
