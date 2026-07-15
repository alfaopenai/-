from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from backend.gg_reader.fast_reader import FastGgReader
from backend.gg_reader.fixed_profile import CLUBGG_COMPACT_8MAX


FIXTURES = ROOT / "tests" / "fixtures"
RUNNING_RIVER = FIXTURES / "gg_table_running_river_user.png"
MOTION_FIXTURES = {
    "turn_idle": FIXTURES / "gg_table_motion_turn_idle.png",
    "turn_bet": FIXTURES / "gg_table_motion_turn_bet.png",
    "turn_call": FIXTURES / "gg_table_motion_turn_call.png",
    "river_check": FIXTURES / "gg_table_motion_river_check.png",
    "river_bet": FIXTURES / "gg_table_motion_river_bet.png",
    "river_fold": FIXTURES / "gg_table_motion_river_fold.png",
    "next_preflop": FIXTURES / "gg_table_motion_next_preflop.png",
}


def _card_codes(snapshot) -> list[str]:
    return [
        f"{card.rank}{card.suit}"
        for card in snapshot.board
        if card.visible and not card.hidden
    ]


@unittest.skipIf(cv2 is None, "OpenCV is unavailable")
class FastGgReaderMotionRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        required = [RUNNING_RIVER, *MOTION_FIXTURES.values()]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise unittest.SkipTest(f"Live GG fixtures are unavailable: {missing}")

    def test_running_river_user_fixture_reads_every_visible_value(self) -> None:
        frame = self._load(RUNNING_RIVER)
        reader = FastGgReader(CLUBGG_COMPACT_8MAX)
        self.addCleanup(reader.close)

        expected_players = {
            1: ("shira6765", 23.1),
            2: ("Juono", 80.5),
            3: ("ozoora", 102.1),
            4: ("GU1967", 149.0),
            6: ("OTB_OvErStayE_d", 199.5),
            7: ("JustDie9", 78.4),
        }

        snapshot = self._read_until(
            reader,
            frame,
            lambda item: self._matches_players(item, expected_players)
            and _card_codes(item) == ["KH", "KD", "9S", "5C", "7C"]
            and abs(item.pot - 64.5) <= 0.05
            and item.dealerSeatIndex == 1
            and self._seat(item, 1).currentBet == 21.5
            and self._seat(item, 1).action == "bet",
            deadline_seconds=45.0,
        )

        self.assertEqual(snapshot.metrics.get("profile"), "clubgg_compact_8max")
        self.assertEqual(snapshot.street, "river")
        self.assertEqual(_card_codes(snapshot), ["KH", "KD", "9S", "5C", "7C"])
        self.assertAlmostEqual(snapshot.pot, 64.5, delta=0.05)
        self.assertEqual((snapshot.smallBlind, snapshot.bigBlind), (1.0, 2.0))
        self.assertEqual(snapshot.dealerSeatIndex, 1)
        self.assertEqual(snapshot.activePlayerCount, 6)

        for index, (name, stack) in expected_players.items():
            seat = self._seat(snapshot, index)
            self.assertTrue(seat.active)
            self.assertEqual(seat.name, name)
            self.assertAlmostEqual(seat.stack, stack, delta=0.05)

        for index in (0, 5):
            seat = self._seat(snapshot, index)
            self.assertFalse(seat.active)
            self.assertEqual(seat.status, "empty")
            self.assertEqual(seat.name or "", "")
            self.assertEqual(seat.stack, 0.0)
            self.assertEqual(seat.currentBet, 0.0)

        bettor = self._seat(snapshot, 1)
        self.assertAlmostEqual(bettor.currentBet, 21.5, delta=0.05)
        self.assertEqual(bettor.action, "bet")
        self.assertEqual(bettor.status, "active")
        self._assert_hidden_cards(bettor, 2)

        caller = self._seat(snapshot, 7)
        self.assertEqual(caller.currentBet, 0.0)
        self.assertEqual(caller.action, "none")
        self.assertEqual(caller.status, "active")
        self._assert_hidden_cards(caller, 2)

        for index in (2, 3, 4, 6):
            seat = self._seat(snapshot, index)
            self.assertEqual(seat.currentBet, 0.0)
            self.assertEqual(seat.action, "none")
            self.assertEqual(seat.status, "folded")
            self.assertEqual(seat.holeCards, [])

    def test_live_motion_sequence_reads_actions_and_resets_the_next_hand(self) -> None:
        frames = {name: self._load(path) for name, path in MOTION_FIXTURES.items()}
        reader = FastGgReader(CLUBGG_COMPACT_8MAX)
        self.addCleanup(reader.close)

        turn_players = {
            0: ("Gai Lan", 254.5),
            1: ("eladmacca", 195.5),
            2: ("Juono", 79.0),
            3: ("ozoora", 101.6),
            4: ("GU1967", 149.5),
            5: ("ZugAce1", 261.7),
            6: ("OTB_OvErStayE_d", 202.0),
            7: ("JustDie9", 139.9),
        }

        idle = self._read_until(
            reader,
            frames["turn_idle"],
            lambda item: self._matches_players(item, turn_players)
            and self._matches_table(item, ["8H", "2S", "9S", "JH"], 7.4, 3),
            deadline_seconds=45.0,
        )
        self._assert_table(idle, "turn", ["8H", "2S", "9S", "JH"], 7.4, 3)
        self._assert_postflop_participants(idle, active=(1, 5), folded=(0, 2, 3, 4, 6, 7))
        self._assert_no_bets_or_actions(idle)

        bet_players = dict(turn_players)
        bet_players[1] = ("eladmacca", 191.7)
        bet = self._read_until(
            reader,
            frames["turn_bet"],
            lambda item: self._matches_players(item, bet_players)
            and self._matches_table(item, ["8H", "2S", "9S", "JH"], 11.2, 3)
            and self._matches_action(item, 1, 3.7, "bet"),
        )
        self._assert_table(bet, "turn", ["8H", "2S", "9S", "JH"], 11.2, 3)
        self._assert_only_bets(bet, {1: (3.7, "bet")})
        self._assert_postflop_participants(bet, active=(1, 5), folded=(0, 2, 3, 4, 6, 7))

        call_players = dict(bet_players)
        call_players[5] = ("ZugAce1", 257.9)
        call = self._read_until(
            reader,
            frames["turn_call"],
            lambda item: self._matches_players(item, call_players)
            and self._matches_table(item, ["8H", "2S", "9S", "JH"], 14.9, 3)
            and self._matches_action(item, 1, 3.7, "bet")
            and self._matches_action(item, 5, 3.7, "call"),
        )
        self._assert_table(call, "turn", ["8H", "2S", "9S", "JH"], 14.9, 3)
        self._assert_only_bets(call, {1: (3.7, "bet"), 5: (3.7, "call")})
        self._assert_postflop_participants(call, active=(1, 5), folded=(0, 2, 3, 4, 6, 7))

        river_players = dict(call_players)
        river_players[1] = ("eladmacca", 180.5)
        check = self._read_until(
            reader,
            frames["river_check"],
            lambda item: self._matches_players(item, river_players)
            and self._matches_table(item, ["8H", "2S", "9S", "JH", "3C"], 14.9, 3)
            and self._matches_action(item, 5, 0.0, "check")
            and all(seat.currentBet == 0.0 for seat in item.seats),
        )
        self._assert_table(check, "river", ["8H", "2S", "9S", "JH", "3C"], 14.9, 3)
        self._assert_only_bets(check, {5: (0.0, "check")})
        self._assert_postflop_participants(check, active=(1, 5), folded=(0, 2, 3, 4, 6, 7))

        river_bet = self._read_until(
            reader,
            frames["river_bet"],
            lambda item: self._matches_players(item, river_players)
            and self._matches_table(item, ["8H", "2S", "9S", "JH", "3C"], 26.1, 3)
            and self._matches_action(item, 1, 11.2, "bet")
            and self._seat(item, 5).action == "none",
        )
        self._assert_table(river_bet, "river", ["8H", "2S", "9S", "JH", "3C"], 26.1, 3)
        self._assert_only_bets(river_bet, {1: (11.2, "bet")})
        self._assert_postflop_participants(river_bet, active=(1, 5), folded=(0, 2, 3, 4, 6, 7))

        folded = self._read_until(
            reader,
            frames["river_fold"],
            lambda item: self._matches_players(item, river_players)
            and self._matches_table(item, ["8H", "2S", "9S", "JH", "3C"], 26.1, 3)
            and self._seat(item, 5).action == "fold"
            and self._seat(item, 5).status == "folded",
        )
        self._assert_table(folded, "river", ["8H", "2S", "9S", "JH", "3C"], 26.1, 3)
        self._assert_only_bets(folded, {1: (11.2, "bet"), 5: (0.0, "fold")})
        self._assert_postflop_participants(folded, active=(1,), folded=(0, 2, 3, 4, 5, 6, 7))

        preflop_players = {
            0: ("Gai Lan", 249.1),
            1: ("eladmacca", 207.5),
            2: ("Juono", 60.0),
            3: ("ozoora", 59.5),
            4: ("GU1967", 134.1),
            5: ("ZugAce1", 277.9),
            6: ("OTB_OVErStayE_d", 206.0),
            7: ("Ederson_3010", 222.6),
        }
        preflop = self._read_until(
            reader,
            frames["next_preflop"],
            lambda item: self._matches_players(item, preflop_players)
            and self._matches_table(item, [], 1.5, 2)
            and self._matches_action(item, 3, 0.5, "bet")
            and self._matches_action(item, 4, 1.0, "bet")
            and all(seat.status == "active" and len(seat.holeCards) == 2 for seat in item.seats),
        )
        self._assert_table(preflop, "preflop", [], 1.5, 2)
        self.assertEqual((preflop.smallBlind, preflop.bigBlind), (1.0, 2.0))
        self._assert_only_bets(preflop, {3: (0.5, "bet"), 4: (1.0, "bet")})
        for seat in preflop.seats:
            self.assertTrue(seat.active)
            self.assertEqual(seat.status, "active")
            self._assert_hidden_cards(seat, 2)

    def _load(self, path: Path):
        frame = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        self.assertIsNotNone(frame, f"Could not load fixture: {path}")
        return frame

    def _read_until(self, reader, frame, predicate, *, deadline_seconds: float = 15.0):
        snapshot = None
        deadline = time.perf_counter() + deadline_seconds
        while time.perf_counter() < deadline:
            snapshot = reader.parse(frame)
            if snapshot is not None and predicate(snapshot):
                return snapshot
            time.sleep(0.02)
        self.fail(f"Reader did not converge before timeout: {self._summary(snapshot)}")

    def _assert_table(self, snapshot, street, board, pot, dealer) -> None:
        self.assertEqual(snapshot.street, street)
        self.assertEqual(_card_codes(snapshot), board)
        self.assertAlmostEqual(snapshot.pot, pot, delta=0.05)
        self.assertEqual(snapshot.dealerSeatIndex, dealer)

    def _assert_postflop_participants(self, snapshot, *, active, folded) -> None:
        for index in active:
            seat = self._seat(snapshot, index)
            self.assertEqual(seat.status, "active")
            self._assert_hidden_cards(seat, 2)
        for index in folded:
            seat = self._seat(snapshot, index)
            self.assertEqual(seat.status, "folded")
            self.assertEqual(seat.holeCards, [])

    def _assert_no_bets_or_actions(self, snapshot) -> None:
        for seat in snapshot.seats:
            self.assertEqual(seat.currentBet, 0.0)
            self.assertEqual(seat.action, "none")

    def _assert_only_bets(self, snapshot, expected) -> None:
        for seat in snapshot.seats:
            amount, action = expected.get(seat.physicalSeatIndex, (0.0, "none"))
            self.assertAlmostEqual(seat.currentBet, amount, delta=0.05)
            self.assertEqual(seat.action, action)

    def _assert_hidden_cards(self, seat, count) -> None:
        self.assertEqual(len(seat.holeCards), count)
        self.assertTrue(all(card.hidden and card.display == "X" for card in seat.holeCards))

    def _matches_players(self, snapshot, expected) -> bool:
        by_index = {seat.physicalSeatIndex: seat for seat in snapshot.seats}
        return all(
            index in by_index
            and by_index[index].active
            and by_index[index].name == name
            and abs(by_index[index].stack - stack) <= 0.05
            for index, (name, stack) in expected.items()
        )

    def _matches_table(self, snapshot, board, pot, dealer) -> bool:
        return (
            _card_codes(snapshot) == board
            and abs(snapshot.pot - pot) <= 0.05
            and snapshot.dealerSeatIndex == dealer
        )

    def _matches_action(self, snapshot, index, amount, action) -> bool:
        seat = self._seat(snapshot, index)
        return abs(seat.currentBet - amount) <= 0.05 and seat.action == action

    @staticmethod
    def _seat(snapshot, index):
        return next(seat for seat in snapshot.seats if seat.physicalSeatIndex == index)

    @staticmethod
    def _summary(snapshot):
        if snapshot is None:
            return None
        return {
            "street": snapshot.street,
            "board": _card_codes(snapshot),
            "pot": snapshot.pot,
            "dealer": snapshot.dealerSeatIndex,
            "seats": [
                {
                    "index": seat.physicalSeatIndex,
                    "name": seat.name,
                    "stack": seat.stack,
                    "bet": seat.currentBet,
                    "action": seat.action,
                    "status": seat.status,
                    "cards": len(seat.holeCards),
                }
                for seat in snapshot.seats
            ],
        }


if __name__ == "__main__":
    unittest.main()
