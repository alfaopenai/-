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

from backend.gg_reader.fast_amount import _looks_like_overlay_text, read_amount_fast
from backend.gg_reader.fast_reader import _clean_player_name
from backend.gg_reader.fixed_profile import CLUBGG_COMPACT_8MAX
from backend.gg_reader.roi import crop_norm
from backend.gg_reader.ocr import read_card, read_name_detailed


FIXTURES = ROOT / "tests" / "fixtures"


@unittest.skipIf(cv2 is None, "OpenCV is unavailable")
class LiveOcrRegressionTest(unittest.TestCase):
    def test_native_one_pixel_decimal_reads_small_blind(self) -> None:
        fixture = FIXTURES / "gg_live_small_blind_0_5.png"
        if not fixture.exists() or cv2 is None:
            self.skipTest("Live small-blind crop is unavailable")
        crop = cv2.imread(str(fixture))
        value, confidence, raw = read_amount_fast(crop)

        self.assertAlmostEqual(value, 0.5, places=2)
        self.assertGreaterEqual(confidence, 0.74)
        self.assertEqual(raw, "0.5BB")

    def _fixture(self, name: str):
        image = cv2.imread(str(FIXTURES / name), cv2.IMREAD_UNCHANGED)
        self.assertIsNotNone(image, name)
        return image

    def test_black_suit_concavity_distinguishes_live_club(self) -> None:
        club = read_card(self._fixture("ocr_new_live_card_6c.png"))
        self.assertEqual((club.get("rank"), club.get("suit")), ("6", "C"))

    def test_fresh_live_eight_of_hearts_is_not_four(self) -> None:
        heart = read_card(self._fixture("ocr_new_live_card_8h.png"))
        self.assertEqual((heart.get("rank"), heart.get("suit")), ("8", "H"))

    def test_live_names_keep_terminal_nine_case_and_underscores(self) -> None:
        expected = {
            "ocr_new_live_name_justdie9.png": "JustDie9",
            "ocr_new_live_name_gu1967.png": "GU1967",
            "ocr_new_live_name_otb_mixed_case.png": "OTB_OvErStayE_d",
        }
        for fixture, name in expected.items():
            with self.subTest(fixture=fixture):
                result = read_name_detailed(self._fixture(fixture))
                self.assertEqual(result.get("cleaned"), name, result)

    def test_live_name_preserves_interior_brackets(self) -> None:
        result = read_name_detailed(self._fixture("gg_live_name_brackets.png"))

        self.assertEqual(result.get("cleaned"), "Kn[u]ckles", result)
        self.assertEqual(_clean_player_name(str(result.get("cleaned"))), "Kn[u]ckles")

    def test_fast_amount_reads_live_eight_three_and_nine_glyphs(self) -> None:
        expected = {
            "ocr_new_live_stack_juono_80_5.png": 80.5,
            "ocr_new_live_pot_14_9.png": 14.9,
            "ocr_new_live_stack_justdie9_139_9.png": 139.9,
        }
        for fixture, amount in expected.items():
            with self.subTest(fixture=fixture):
                actual, confidence, raw = read_amount_fast(self._fixture(fixture))
                self.assertAlmostEqual(actual, amount, delta=0.01, msg=raw)
                self.assertGreaterEqual(confidence, 0.74, raw)
                self.assertTrue(raw.endswith("BB"), raw)

    def test_word_dominated_overlay_is_not_an_amount_candidate(self) -> None:
        self.assertTrue(_looks_like_overlay_text("EC0NECT1N."))
        self.assertFalse(_looks_like_overlay_text("T01A014.90"))
        self.assertFalse(_looks_like_overlay_text("80.5BB"))

    def test_visible_zero_stack_is_preserved_as_all_in_evidence(self) -> None:
        frame = self._fixture("gg_allin_equity_flop.png")
        seat = next(item for item in CLUBGG_COMPACT_8MAX.seats if item.index == 6)
        amount, confidence, raw = read_amount_fast(crop_norm(frame, seat.stack))

        self.assertEqual(amount, 0.0)
        self.assertGreaterEqual(confidence, 0.80)
        self.assertEqual(raw, "0BB")


if __name__ == "__main__":
    unittest.main()
