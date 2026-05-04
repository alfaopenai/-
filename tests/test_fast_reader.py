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


FIXTURE = ROOT / "tests" / "fixtures" / "gg_table_preflop.png"


@unittest.skipIf(cv2 is None, "OpenCV is unavailable")
class FastGgReaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not FIXTURE.exists():
            raise unittest.SkipTest(f"Fixture is unavailable: {FIXTURE}")
        cls.frame = cv2.imread(str(FIXTURE), cv2.IMREAD_UNCHANGED)
        if cls.frame is None:
            raise unittest.SkipTest("Could not load GG debug frame")

    def test_static_fixture_snapshot_is_structured(self) -> None:
        reader = FastGgReader()
        snapshot = self._parse_until(reader, lambda item: item.pot > 0)
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

    def _parse_until(self, reader: FastGgReader, predicate) -> object:
        snapshot = None
        deadline = time.perf_counter() + 4.0
        while time.perf_counter() < deadline:
            snapshot = reader.parse(self.frame)
            if snapshot is not None and predicate(snapshot):
                return snapshot
            time.sleep(0.1)
        return snapshot


if __name__ == "__main__":
    unittest.main()
