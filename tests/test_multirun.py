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

from backend.gg_reader.fixed_profile import CLUBGG_COMPACT_8MAX
from backend.gg_reader.multirun import (
    card_codes,
    detect_multirun_board,
    primary_board,
)


FIXTURES = ROOT / "tests" / "fixtures"
LIVE_FRAMES = {
    # raw_008_20260715-105657.827.png
    "shared_flop": FIXTURES / "gg_allin_equity_flop.png",
    # raw_011_20260715-105703.908.png
    "moving_first_run_turn": FIXTURES / "gg_allin_equity_run1_turn.png",
    # raw_012_20260715-105707.190.png
    "first_run_complete": FIXTURES / "gg_allin_equity_run2_turn.png",
    # raw_013_20260715-105709.213.png
    "both_runs_complete": FIXTURES / "gg_allin_two_runs_complete.png",
}


@unittest.skipIf(cv2 is None, "OpenCV is unavailable")
class MultiRunBoardDetectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        missing = [str(path) for path in LIVE_FRAMES.values() if not path.exists()]
        if missing:
            raise unittest.SkipTest(f"Live multi-run fixtures are unavailable: {missing}")

        cls.frames = {
            name: cls._load(path)
            for name, path in LIVE_FRAMES.items()
        }
        # Exercise both supported APIs: a fitted/base profile and explicit
        # normalized board geometry.
        cls.results = {
            "shared_flop": detect_multirun_board(
                cls.frames["shared_flop"],
                profile=CLUBGG_COMPACT_8MAX,
            ),
            "moving_first_run_turn": detect_multirun_board(
                cls.frames["moving_first_run_turn"],
                CLUBGG_COMPACT_8MAX.board,
            ),
            "first_run_complete": detect_multirun_board(
                cls.frames["first_run_complete"],
                profile=CLUBGG_COMPACT_8MAX,
            ),
            "both_runs_complete": detect_multirun_board(
                cls.frames["both_runs_complete"],
                CLUBGG_COMPACT_8MAX.board,
            ),
        }

    def test_normal_shared_flop_is_not_misclassified_as_multiple_runs(self) -> None:
        result = self.results["shared_flop"]

        self.assertEqual(card_codes(result.shared_flop), ["JC", "9S", "3H"])
        self.assertFalse(result.is_multiple)
        self.assertEqual(result.layout, "single")
        self.assertEqual(result.runouts, ())
        self.assertEqual(card_codes(primary_board(result)), ["JC", "9S", "3H"])

    def test_deal_animation_does_not_promote_a_moving_card_to_a_runout(self) -> None:
        result = self.results["moving_first_run_turn"]

        self.assertEqual(card_codes(result.shared_flop), ["JC", "9S", "3H"])
        self.assertFalse(result.is_multiple)
        self.assertEqual(result.layout, "single")
        self.assertEqual(result.runouts, ())
        self.assertEqual(card_codes(result.primary_board()), ["JC", "9S", "3H"])

    def test_settled_upper_run_and_live_second_run_turn_are_read(self) -> None:
        result = self.results["first_run_complete"]

        self.assertEqual(card_codes(result.shared_flop), ["JC", "9S", "3H"])
        self.assertTrue(result.is_multiple)
        self.assertEqual(result.layout, "upper-lower")
        self.assertEqual(len(result.runouts), 2)
        self.assertEqual(card_codes(result.runouts[0].cards), ["4C", "KC"])
        self.assertEqual(card_codes(result.runouts[1].cards), ["QS"])
        self.assertEqual(
            card_codes(primary_board(result)),
            ["JC", "9S", "3H", "4C", "KC"],
        )

    def test_complete_upper_and_lower_runs_are_read_independently(self) -> None:
        result = self.results["both_runs_complete"]

        self.assertEqual(card_codes(result.shared_flop), ["JC", "9S", "3H"])
        self.assertTrue(result.is_multiple)
        self.assertEqual(result.layout, "upper-lower")
        self.assertEqual(card_codes(result.runouts[0].cards), ["4C", "KC"])
        self.assertEqual(card_codes(result.runouts[1].cards), ["QS", "AD"])
        self.assertEqual(
            card_codes(result.primary_board()),
            ["JC", "9S", "3H", "4C", "KC"],
        )

    def test_complete_layout_has_seven_unique_visible_cards(self) -> None:
        result = self.results["both_runs_complete"]
        cards = [
            *result.shared_flop,
            *(card for runout in result.runouts for card in runout.cards),
        ]
        codes = card_codes(cards)

        self.assertEqual(len(codes), 7)
        self.assertEqual(len(set(codes)), 7)
        self.assertTrue(all(card.visible and not card.hidden for card in cards))

    @staticmethod
    def _load(path: Path):
        frame = cv2.imread(str(path))
        if frame is None:
            raise unittest.SkipTest(f"Could not load live multi-run fixture: {path}")
        return frame


if __name__ == "__main__":
    unittest.main(verbosity=2)
