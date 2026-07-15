from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from backend.gg_reader.equity_ocr import (
    NO_EQUITY_RESULT,
    RAPIDOCR_PERCENT_SOURCE,
    read_displayed_equity,
)
from backend.gg_reader.fixed_profile import CLUBGG_COMPACT_8MAX
from backend.gg_reader.roi import crop_norm


FIXTURES = ROOT / "tests" / "fixtures"
LIVE_EQUITY_FRAMES = (
    (
        FIXTURES / "gg_allin_equity_flop.png",
        {2: 18.12, 6: 81.86},
    ),
    (
        FIXTURES / "gg_allin_equity_run1_turn.png",
        {2: 6.81, 6: 93.18},
    ),
    (
        FIXTURES / "gg_allin_equity_run2_turn.png",
        {2: 14.28, 6: 85.71},
    ),
)


class DisplayedEquityValidationTest(unittest.TestCase):
    def test_requires_percent_sign(self) -> None:
        with patch(
            "backend.gg_reader.equity_ocr.read_amount_rapidocr",
            return_value=(81.86, 0.91, "81.86"),
        ):
            self.assertEqual(read_displayed_equity(_empty_image()), NO_EQUITY_RESULT)

    def test_rejects_out_of_range_and_mismatched_values(self) -> None:
        cases = (
            (101.0, 0.9, "101%"),
            (-1.0, 0.9, "-1%"),
            (18.12, 0.9, "181.2%"),
        )
        for rapid_result in cases:
            with self.subTest(rapid_result=rapid_result), patch(
                "backend.gg_reader.equity_ocr.read_amount_rapidocr",
                return_value=rapid_result,
            ):
                self.assertEqual(read_displayed_equity(_empty_image()), NO_EQUITY_RESULT)

    def test_accepts_zero_and_one_hundred_inclusively(self) -> None:
        for value in (0.0, 100.0):
            with self.subTest(value=value), patch(
                "backend.gg_reader.equity_ocr.read_amount_rapidocr",
                return_value=(value, 0.88, f"{value:.1f}%"),
            ):
                self.assertEqual(
                    read_displayed_equity(_empty_image()),
                    (value, 0.88, RAPIDOCR_PERCENT_SOURCE),
                )


@unittest.skipIf(cv2 is None, "OpenCV is unavailable")
class DisplayedEquityLiveFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        missing = [str(path) for path, _expected in LIVE_EQUITY_FRAMES if not path.exists()]
        if missing:
            raise unittest.SkipTest(f"Live all-in equity fixtures are unavailable: {missing}")

    def test_reads_clubgg_percentages_from_name_rois(self) -> None:
        for frame_path, expected_by_seat in LIVE_EQUITY_FRAMES:
            frame = cv2.imread(str(frame_path))
            self.assertIsNotNone(frame, str(frame_path))
            for seat_index, expected in expected_by_seat.items():
                with self.subTest(frame=frame_path.name, seat=seat_index):
                    name_roi = crop_norm(frame, CLUBGG_COMPACT_8MAX.seats[seat_index].name)
                    value, confidence, source = read_displayed_equity(name_roi)
                    self.assertEqual(value, expected)
                    self.assertGreaterEqual(confidence, 0.65)
                    self.assertEqual(source, RAPIDOCR_PERCENT_SOURCE)


def _empty_image():
    import numpy as np

    return np.zeros((8, 8, 3), dtype=np.uint8)


if __name__ == "__main__":
    unittest.main()
