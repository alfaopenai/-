from __future__ import annotations

import statistics
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


FIXTURE = ROOT / "backend" / "data" / "debug_last_frame.png"


@unittest.skipIf(cv2 is None or not FIXTURE.exists(), "OpenCV or debug_last_frame.png fixture is unavailable")
class FastGgReaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.frame = cv2.imread(str(FIXTURE), cv2.IMREAD_UNCHANGED)
        if cls.frame is None:
            raise unittest.SkipTest("Could not load GG debug frame")

    def test_static_fixture_snapshot_is_structured(self) -> None:
        reader = FastGgReader()
        snapshot = reader.parse(self.frame)
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.source, "ggclub")
        self.assertEqual(snapshot.street, "preflop")
        self.assertEqual(snapshot.board, [])
        self.assertEqual(snapshot.smallBlind, 2)
        self.assertEqual(snapshot.bigBlind, 4)
        self.assertGreaterEqual(snapshot.activePlayerCount, 3)
        self.assertLess(snapshot.pot, 1_000)
        self.assertTrue(0 <= snapshot.dealerSeatIndex <= 7)
        self.assertIn("parseMs", snapshot.metrics)

        if self.frame.shape[1] == 850 and self.frame.shape[0] == 631:
            seat_zero = next(seat for seat in snapshot.seats if seat.physicalSeatIndex == 0)
            self.assertFalse(seat_zero.active, "The visible Take Seat circle should not become an active player")

    def test_static_fixture_benchmark_300_frames(self) -> None:
        reader = FastGgReader()
        times_ms: list[float] = []
        snapshot = None
        for _index in range(300):
            started_at = time.perf_counter()
            snapshot = reader.parse(self.frame)
            times_ms.append((time.perf_counter() - started_at) * 1000)

        ordered = sorted(times_ms)
        p95 = ordered[int(0.95 * (len(ordered) - 1))]
        self.assertIsNotNone(snapshot)
        self.assertLess(p95, 180, f"p95={p95:.2f}ms avg={statistics.mean(times_ms):.2f}ms")
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


if __name__ == "__main__":
    unittest.main()
