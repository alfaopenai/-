from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from backend.gg_reader.fast_reader import FastGgReader


PREFLOP_FIXTURE = ROOT / "tests" / "fixtures" / "gg_table_preflop.png"
COMPACT_FLOP_FIXTURE = ROOT / "tests" / "fixtures" / "gg_table_flop_compact.png"
COMPACT_RIVER_FIXTURE = ROOT / "tests" / "fixtures" / "gg_table_compact_river.png"


@unittest.skipIf(cv2 is None, "OpenCV is unavailable")
class FastGgReaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not PREFLOP_FIXTURE.exists():
            raise unittest.SkipTest(f"Fixture is unavailable: {PREFLOP_FIXTURE}")
        cls.frame = cv2.imread(str(PREFLOP_FIXTURE), cv2.IMREAD_UNCHANGED)
        if cls.frame is None:
            raise unittest.SkipTest("Could not load GG debug frame")

    def test_static_fixture_snapshot_is_structured(self) -> None:
        reader = FastGgReader()
        snapshot = self._parse_until(reader, self.frame, lambda item: item.pot > 0)
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.source, "ggclub")
        self.assertEqual(snapshot.street, "preflop")
        self.assertEqual(snapshot.board, [])
        self.assertEqual(snapshot.smallBlind, 2)
        self.assertEqual(snapshot.bigBlind, 4)
        self.assertAlmostEqual(snapshot.pot, 1.5, delta=0.15)
        self.assertLess(snapshot.pot, 1_000, "Bad Beat Jackpot must never be parsed as the table pot")
        self.assertEqual(snapshot.activePlayerCount, 7)
        self.assertEqual(snapshot.dealerSeatIndex, 0)
        self.assertIn("parseMs", snapshot.metrics)
        self.assertGreaterEqual(snapshot.metrics.get("emptyTakeSeats", 0), 1)

        active_indexes = {seat.physicalSeatIndex for seat in snapshot.seats if seat.active}
        self.assertEqual(active_indexes, {0, 1, 2, 3, 4, 5, 6})
        take_seat = next(seat for seat in snapshot.seats if seat.physicalSeatIndex == 7)
        self.assertFalse(take_seat.active, "The visible Take Seat circle should not become an active player")
        for seat in snapshot.seats:
            if seat.holeCards:
                self.assertEqual(len(seat.holeCards), 2)
                self.assertTrue(all(card.hidden and card.display == "X" for card in seat.holeCards))

    def test_static_fixture_benchmark_300_frames(self) -> None:
        reader = FastGgReader()
        for _index in range(30):
            reader.parse(self.frame)

        times_ms: list[float] = []
        snapshot = None
        for _index in range(300):
            started_at = time.perf_counter()
            snapshot = reader.parse(self.frame)
            times_ms.append((time.perf_counter() - started_at) * 1000)

        ordered = sorted(times_ms)
        p95 = ordered[int(0.95 * (len(ordered) - 1))]
        avg = sum(times_ms) / len(times_ms)
        self.assertIsNotNone(snapshot)
        self.assertLess(avg, 100, f"avg={avg:.2f}ms")
        self.assertLess(p95, 180, f"p95={p95:.2f}ms avg={avg:.2f}ms")
        self.assertLess(max(times_ms), 333, f"max={max(times_ms):.2f}ms")

    def test_bad_frame_does_not_clear_last_good_snapshot(self) -> None:
        reader = FastGgReader()
        good = reader.parse(self.frame)
        self.assertIsNotNone(good)
        assert good is not None

        bad_frame = np.zeros_like(self.frame)
        held = reader.parse(bad_frame)
        self.assertIsNotNone(held)
        assert held is not None
        self.assertEqual(held.activePlayerCount, good.activePlayerCount)
        self.assertEqual(held.dealerSeatIndex, good.dealerSeatIndex)
        self.assertTrue(held.metrics.get("heldSnapshot"))

    def test_compact_river_fixture_snapshot(self) -> None:
        frame = self._load_fixture(COMPACT_RIVER_FIXTURE)
        reader = FastGgReader()
        snapshot = self._parse_until(reader, frame, lambda item: item.pot > 0 and item.street == "river")
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.metrics.get("profile"), "clubgg_compact_8max")
        self.assertEqual(snapshot.street, "river")
        self.assertEqual(_card_codes(snapshot.board), ["9D", "JH", "7D", "5H", "KH"])
        self.assertAlmostEqual(snapshot.pot, 5.5, delta=0.20)
        self.assertLess(snapshot.pot, 1_000, "Bad Beat Jackpot must never be parsed as the table pot")
        self.assertEqual(snapshot.smallBlind, 2)
        self.assertEqual(snapshot.bigBlind, 4)
        self.assertEqual(snapshot.activePlayerCount, 8)
        self.assertEqual(snapshot.dealerSeatIndex, 7)
        amount_debug = snapshot.metrics.get("amountFields") or []
        pot_debug = next((item for item in amount_debug if item.get("key") == "pot"), None)
        self.assertIsNotNone(pot_debug)
        assert pot_debug is not None
        self.assertIn(pot_debug.get("source"), {"fast_amount", "tight_ocr", "cache"})

    def test_compact_flop_fixture_snapshot(self) -> None:
        if not COMPACT_FLOP_FIXTURE.exists():
            raise unittest.SkipTest(
                "Exact compact flop fixture is not available; place it at "
                f"{COMPACT_FLOP_FIXTURE}"
            )
        frame = self._load_fixture(COMPACT_FLOP_FIXTURE)
        reader = FastGgReader()
        snapshot = self._parse_until(reader, frame, lambda item: item.pot > 0 and item.street == "flop")
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.metrics.get("profile"), "clubgg_compact_8max")
        self.assertEqual(snapshot.street, "flop")
        self.assertEqual(_card_codes(snapshot.board), ["2H", "10C", "9C"])
        self.assertAlmostEqual(snapshot.pot, 6.5, delta=0.20)
        self.assertLess(snapshot.pot, 1_000, "Bad Beat Jackpot 72,272.87 must not be parsed as the pot")
        self.assertEqual(snapshot.smallBlind, 2)
        self.assertEqual(snapshot.bigBlind, 4)
        self.assertEqual(snapshot.activePlayerCount, 7)
        self.assertFalse(snapshot.seats[0].active, "The top Take Seat must be inactive")

        expected_stacks = {
            "A-Z777": 60.8,
            "Bendia1103": 85.7,
            "Dr Freud": 300.6,
            "I got the nuts!": 98.0,
            "ultraEGO": 76.1,
            "korch11": 77.2,
            "gons1472580": 127.3,
        }
        active_by_name = {seat.name or "": seat for seat in snapshot.seats if seat.active}
        for name, expected_stack in expected_stacks.items():
            self.assertIn(name, active_by_name)
            self.assertAlmostEqual(active_by_name[name].stack, expected_stack, delta=1.0)
            self.assertEqual(
                [card.display for card in active_by_name[name].holeCards],
                ["X", "X"],
                f"{name} hidden hole cards should be X/X",
            )
        self.assertNotEqual(snapshot.pot, 72_272.87)
        self.assertEqual(snapshot.dealerSeatIndex, active_by_name["A-Z777"].physicalSeatIndex)

    def _parse_until(self, reader: FastGgReader, frame: np.ndarray, predicate) -> object:
        snapshot = None
        deadline = time.perf_counter() + 4.0
        while time.perf_counter() < deadline:
            snapshot = reader.parse(frame)
            if snapshot is not None and predicate(snapshot):
                return snapshot
            time.sleep(0.1)
        return snapshot

    def _load_fixture(self, path: Path) -> np.ndarray:
        if not path.exists():
            raise unittest.SkipTest(f"Fixture is unavailable: {path}")
        frame = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if frame is None:
            raise unittest.SkipTest(f"Could not load fixture: {path}")
        return frame


def _card_codes(cards) -> list[str]:
    return [f"{card.rank}{card.suit}" for card in cards if card.visible and not card.hidden]


if __name__ == "__main__":
    unittest.main()
