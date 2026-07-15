from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from backend.gg_reader.fast_amount import read_amount_fast
from backend.gg_reader.fixed_profile import CLUBGG_COMPACT_7MAX, CLUBGG_COMPACT_8MAX
from backend.gg_reader.roi import crop_norm


@unittest.skipIf(cv2 is None, "OpenCV is unavailable")
class FastAmountTopologyRegressionTest(unittest.TestCase):
    def _load(self, relative_path: str):
        image = cv2.imread(str(ROOT / relative_path), cv2.IMREAD_UNCHANGED)
        self.assertIsNotNone(image, relative_path)
        return image

    @staticmethod
    def _seat(profile, index: int):
        return next(seat for seat in profile.seats if seat.index == index)

    def test_real_sixes_are_not_changed_to_eights(self) -> None:
        cases = (
            ("tests/fixtures/current_clubgg_compact_live.png", CLUBGG_COMPACT_7MAX, 2, 168.5),
            ("tests/fixtures/gg_table_live_turn_20260714.png", CLUBGG_COMPACT_8MAX, 7, 126.3),
            ("tests/fixtures/gg_table_motion_turn_idle.png", CLUBGG_COMPACT_8MAX, 5, 261.7),
        )
        for relative_path, profile, seat_index, expected in cases:
            with self.subTest(relative_path=relative_path, seat=seat_index):
                frame = self._load(relative_path)
                value, confidence, raw = read_amount_fast(
                    crop_norm(frame, self._seat(profile, seat_index).stack)
                )
                self.assertAlmostEqual(value, expected, delta=0.01, msg=raw)
                self.assertGreaterEqual(confidence, 0.74, raw)

    def test_small_white_all_in_eight_is_recovered(self) -> None:
        relative_path = "output/live-allin-audit/raw_006_20260715-105653.578.png"
        if not (ROOT / relative_path).exists():
            self.skipTest("Live all-in source frame is unavailable")
        frame = self._load(relative_path)
        seat = self._seat(CLUBGG_COMPACT_8MAX, 2)
        value, confidence, raw = read_amount_fast(crop_norm(frame, seat.bet))

        self.assertAlmostEqual(value, 108.3, delta=0.01, msg=raw)
        self.assertGreaterEqual(confidence, 0.74, raw)
        self.assertEqual(raw, "108.3BB")


if __name__ == "__main__":
    unittest.main()
