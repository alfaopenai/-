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
from backend.gg_reader.parser import parse_frame
from backend.gg_reader.profile_matcher import choose_and_fit_profile
from backend.gg_reader.table_crop import detect_clubgg_table_crop, validate_real_clubgg_crop
from backend.gg_reader.table_state import TableStateStabilizer
from backend.main import build_normalized_state, infer_actions

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
            "192,1B": 192.1,
            "195,17B": 195.17,
            "46.9BB": 46.9,
            "122BB": 122.0,
            "194.2BB": 194.2,
            "131.1BB": 131.1,
            "54BB": 54.0,
            "196.5BB": 196.5,
            "100B8": 100.0,
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

    def test_seat_database_holds_last_verified_name_and_stack_by_position(self) -> None:
        stabilizer = TableStateStabilizer()
        first = _snapshot(seats=[_seat(6, name="loftyodb", name_confidence=0.72, stack=116.9, stack_confidence=0.82)])
        stabilizer.stabilize(first, now=time.monotonic())

        missing = _snapshot(seats=[_seat(6, name="", name_confidence=0.0, stack=0.0, stack_confidence=0.0)])
        held = stabilizer.stabilize(missing, now=time.monotonic() + 1.1)
        self.assertEqual(held.seats[0].name, "loftyodb")
        self.assertAlmostEqual(held.seats[0].stack, 116.9)
        database = held.metrics["stabilizer"]["seatDatabase"]
        seat_record = next(record for record in database if record["seatIndex"] == 6)
        self.assertEqual(seat_record["name"], "loftyodb")
        self.assertAlmostEqual(seat_record["stack"], 116.9)
        normalized = build_normalized_state(held, held.metrics)
        normalized_record = next(record for record in normalized["seat_database"] if record["seat_index"] == 6)
        self.assertEqual(normalized_record["player_name"], "loftyodb")
        self.assertAlmostEqual(normalized_record["stack_bb"], 116.9)

    def test_seat_database_rejects_single_frame_wrong_name_for_same_position(self) -> None:
        stabilizer = TableStateStabilizer()
        first = _snapshot(seats=[_seat(4, name="barak_wit", name_confidence=0.72, stack=198.0, stack_confidence=0.82)])
        stabilizer.stabilize(first, now=time.monotonic())

        bad_read = _snapshot(seats=[_seat(4, name="P6743-5812", name_confidence=0.72, stack=1980.0, stack_confidence=0.82)])
        held = stabilizer.stabilize(bad_read, now=time.monotonic() + 1.1)
        self.assertEqual(held.seats[0].name, "barak_wit")
        self.assertAlmostEqual(held.seats[0].stack, 198.0)
        self.assertIn("seat-4-database-name", held.metrics["stabilizer"]["fieldsHeld"])

    def test_seat_database_updates_repeated_new_name_after_confirmation(self) -> None:
        stabilizer = TableStateStabilizer()
        first = _snapshot(seats=[_seat(3, name="old_player", name_confidence=0.72, stack=150.0, stack_confidence=0.82)])
        stabilizer.stabilize(first, now=time.monotonic())

        changed = _snapshot(seats=[_seat(3, name="new_player", name_confidence=0.72, stack=151.0, stack_confidence=0.82)])
        once = stabilizer.stabilize(changed, now=time.monotonic() + 1.1)
        self.assertEqual(once.seats[0].name, "old_player")

        twice = stabilizer.stabilize(changed, now=time.monotonic() + 2.2)
        self.assertEqual(twice.seats[0].name, "new_player")
        self.assertAlmostEqual(twice.seats[0].stack, 151.0)

    def test_seat_database_clears_after_confirmed_empty_position(self) -> None:
        stabilizer = TableStateStabilizer()
        first = _snapshot(seats=[_seat(5, name="Neegaa", name_confidence=0.72, stack=167.7, stack_confidence=0.82)])
        stabilizer.stabilize(first, now=time.monotonic())

        empty = _snapshot(seats=[_empty_seat(5)])
        once = stabilizer.stabilize(empty, now=time.monotonic() + 0.4)
        self.assertTrue(once.seats[0].active)
        self.assertEqual(once.seats[0].name, "Neegaa")

        twice = stabilizer.stabilize(empty, now=time.monotonic() + 1.4)
        self.assertFalse(twice.seats[0].active)
        self.assertEqual(twice.seats[0].name, "")
        self.assertEqual(twice.seats[0].stack, 0.0)
        database = twice.metrics["stabilizer"]["seatDatabase"]
        seat_record = next(record for record in database if record["seatIndex"] == 5)
        self.assertFalse(seat_record["active"])
        self.assertEqual(seat_record["name"], "")
        self.assertEqual(seat_record["stack"], 0.0)

    def test_board_database_rejects_single_frame_wrong_card_for_same_slot(self) -> None:
        stabilizer = TableStateStabilizer()
        first = _snapshot(
            street="flop",
            board=[_card("AS"), _card("6D"), _card("3D")],
            seats=[_seat(0)],
        )
        stabilizer.stabilize(first, now=time.monotonic())

        bad_read = _snapshot(
            street="flop",
            board=[_card("AC"), _card("6D"), _card("3D")],
            seats=[_seat(0)],
        )
        held = stabilizer.stabilize(bad_read, now=time.monotonic() + 1.1)
        self.assertEqual(_card_codes(held.board), ["AS", "6D", "3D"])
        self.assertIn("board-0-database-card", held.metrics["stabilizer"]["fieldsHeld"])
        normalized = build_normalized_state(held, held.metrics)
        self.assertEqual(normalized["board_database"][0]["card"], "AS")

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
        validation = validate_real_clubgg_crop(frame)
        if not validation.is_real_clubgg:
            raise unittest.SkipTest(validation.rejected_reason or "latest debug crop is not a visible ClubGG table")
        profile = choose_and_fit_profile(frame)
        self.assertGreaterEqual(profile.fit_score, 0.25)
        self.assertIn(profile.name, {"clubgg_fixed_8max", "clubgg_compact_6max", "clubgg_compact_7max", "clubgg_compact_8max"})

    def test_pot_parsing_from_fixture_still_works(self) -> None:
        from backend.gg_reader.fast_reader import FastGgReader

        frame = _load_optional_image(ROOT / "tests" / "fixtures" / "gg_table_preflop.png")
        reader = FastGgReader()
        self.addCleanup(reader.close)
        snapshot = reader.parse(frame)
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertAlmostEqual(snapshot.pot, 1.5, delta=0.2)
        self.assertGreaterEqual(snapshot.activePlayerCount, 2)

    def test_reject_localhost_app_table_source(self) -> None:
        frame = _synthetic_localhost_table()
        result = validate_real_clubgg_crop(frame, {
            "title": "localhost:7000 - Google Chrome",
            "processName": "chrome.exe",
            "processExe": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "className": "Chrome_WidgetWin_1",
        })
        self.assertFalse(result.is_real_clubgg)
        diagnostics = result.as_diagnostics()
        self.assertTrue(diagnostics["rejectedLocalhostTable"])
        self.assertTrue(diagnostics["rejectedBrowserChrome"])

    def test_select_real_clubgg_when_two_tables_visible(self) -> None:
        frame = _load_two_table_fixture_or_synthetic()
        crop = detect_clubgg_table_crop(frame)
        self.assertTrue(crop.diagnostics.get("isRealClubGg"), crop.diagnostics)
        self.assertEqual(crop.source, "image-detected-table")
        self.assertGreater(crop.crop_rect["left"], frame.shape[1] * 0.50)
        self.assertLess(crop.crop_rect["width"], frame.shape[1] * 0.40)
        self.assertFalse(crop.diagnostics.get("rejectedLocalhostTable"))

    def test_current_two_tables_live_selects_real_clubgg(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "current_two_tables_live.png"
        frame = _load_optional_image(fixture)
        crop = detect_clubgg_table_crop(frame)
        self.assertTrue(crop.diagnostics.get("isRealClubGg"), crop.diagnostics)
        self.assertEqual(crop.source, "image-detected-table")
        self.assertGreater(crop.crop_rect["left"], frame.shape[1] * 0.55)
        self.assertLess(crop.crop_rect["left"], frame.shape[1] * 0.98)
        self.assertFalse(crop.diagnostics.get("rejectedLocalhostTable"))
        candidates = crop.diagnostics.get("cropCandidates") or []
        self.assertGreaterEqual(len(candidates), 2)
        selected = candidates[0]
        self.assertTrue(selected.get("isRealClubGg"))
        self.assertGreater(int(selected.get("left") or 0), frame.shape[1] * 0.55)
        profile = choose_and_fit_profile(crop.cropped_frame)
        self.assertEqual(profile.name, "clubgg_compact_7max")
        self.assertGreaterEqual(profile.fit_score, 0.75)

    def test_padded_desktop_clubgg_frame_is_cropped_before_roi_reading(self) -> None:
        clubgg = _load_optional_image(ROOT / "tests" / "fixtures" / "current_clubgg_compact_live.png")
        canvas = np.zeros((768, 1024, 3), dtype=np.uint8)
        canvas[:] = (210, 140, 30)
        cv2.circle(canvas, (850, 740), 300, (255, 80, 20), -1)
        top = 52
        left = 101
        canvas[top:top + clubgg.shape[0], left:left + clubgg.shape[1]] = clubgg[:, :, :3]

        crop = detect_clubgg_table_crop(canvas)
        self.assertTrue(crop.diagnostics.get("isRealClubGg"), crop.diagnostics)
        self.assertEqual(crop.source, "image-detected-table")
        self.assertGreater(crop.crop_rect["left"], 40)
        self.assertGreater(crop.crop_rect["top"], 20)
        self.assertLess(crop.crop_rect["width"], canvas.shape[1] * 0.95)
        self.assertLess(crop.crop_rect["height"], canvas.shape[0] * 0.95)
        profile = choose_and_fit_profile(crop.cropped_frame)
        self.assertEqual(profile.name, "clubgg_compact_7max")
        self.assertGreaterEqual(profile.fit_score, 0.70)

    def test_no_snapshot_from_wrong_source(self) -> None:
        from backend.gg_reader.fast_reader import FastGgReader

        frame = _synthetic_localhost_table()
        reader = FastGgReader()
        self.addCleanup(reader.close)
        snapshot = parse_frame(
            frame,
            {},
            reader,
            {
                "title": "localhost:7000 - Google Chrome",
                "processName": "chrome.exe",
                "className": "Chrome_WidgetWin_1",
            },
        )
        self.assertIsNone(snapshot)

    def test_do_not_stabilize_wrong_source_after_good_snapshot(self) -> None:
        from backend.gg_reader.fast_reader import FastGgReader

        reader = FastGgReader()
        self.addCleanup(reader.close)
        good_frame = _load_optional_image(ROOT / "tests" / "fixtures" / "gg_table_preflop.png")
        good = parse_frame(good_frame, {}, reader, {"title": "NLH 2-4 - 2/4"})
        self.assertIsNotNone(good)

        bad = parse_frame(
            _synthetic_localhost_table(),
            {},
            reader,
            {
                "title": "localhost:7000 - Google Chrome",
                "processName": "chrome.exe",
                "className": "Chrome_WidgetWin_1",
            },
        )
        self.assertIsNone(bad)


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
    street: str = "preflop",
    board: list[GgCard] | None = None,
) -> GgTableSnapshot:
    return GgTableSnapshot(
        timestamp=int(time.time() * 1000),
        tableType="8max",
        street=street,
        pot=pot,
        activePlayerCount=len([seat for seat in seats or [] if seat.active]),
        dealerSeatIndex=0,
        board=board or [],
        seats=seats or [],
        confidence=0.86,
        metrics={
            "amountFields": [
                {"key": "pot", "value": pot, "confidence": pot_confidence, "source": "test"}
            ]
        },
    )


def _card(code: str, confidence: float = 0.84) -> GgCard:
    value = code.upper()
    return GgCard(rank=value[:-1], suit=value[-1], visible=True, hidden=False, confidence=confidence)


def _card_codes(cards: list[GgCard]) -> list[str]:
    return [f"{card.rank}{card.suit}" for card in cards if card.visible and not card.hidden]


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


def _empty_seat(index: int) -> GgSeat:
    return GgSeat(
        physicalSeatIndex=index,
        active=False,
        name="",
        nameConfidence=0.0,
        stack=0.0,
        stackConfidence=0.0,
        currentBet=0.0,
        betConfidence=0.0,
        action="none",
        actionSource="empty",
        status="empty",
        holeCards=[],
        confidence=0.92,
    )


def _load_optional_image(path: Path) -> np.ndarray:
    if not path.exists():
        raise unittest.SkipTest(f"Debug image unavailable: {path}")
    frame = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if frame is None:
        raise unittest.SkipTest(f"Could not load image: {path}")
    return frame


def _load_two_table_fixture_or_synthetic() -> np.ndarray:
    fixture = ROOT / "tests" / "fixtures" / "two_tables_localhost_and_clubgg.png"
    if fixture.exists():
        return _load_optional_image(fixture)
    return _synthetic_two_tables()


def _synthetic_two_tables() -> np.ndarray:
    clubgg = _load_optional_image(ROOT / "tests" / "fixtures" / "gg_table_preflop.png")
    if clubgg.ndim == 3 and clubgg.shape[2] >= 4:
        clubgg = clubgg[:, :, :3]
    canvas = np.zeros((550, 2048, 3), dtype=np.uint8) + 30
    local = _synthetic_localhost_table(width=1180, height=450)
    canvas[70:520, 90:1270] = local
    resized = cv2.resize(clubgg, (460, 340), interpolation=cv2.INTER_AREA)
    canvas[130:470, 1345:1805] = resized
    return canvas


def _synthetic_localhost_table(*, width: int = 1140, height: int = 450) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8) + 22
    frame[:, :] = (18, 95, 38)
    center = (width // 2, int(height * 0.62))
    cv2.ellipse(frame, center, (int(width * 0.36), int(height * 0.24)), 0, 0, 360, (8, 24, 22), -1)
    cv2.ellipse(frame, center, (int(width * 0.30), int(height * 0.17)), 0, 0, 360, (25, 118, 48), -1)
    cv2.putText(frame, "localhost:7000", (34, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (230, 230, 230), 2)
    cv2.rectangle(frame, (int(width * 0.43), int(height * 0.48)), (int(width * 0.57), int(height * 0.56)), (15, 35, 25), -1)
    cv2.putText(frame, "Pot 1.50", (int(width * 0.45), int(height * 0.535)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (235, 220, 80), 2)
    for x_ratio, y_ratio in ((0.50, 0.18), (0.76, 0.35), (0.84, 0.62), (0.50, 0.86), (0.18, 0.62), (0.24, 0.35)):
        x = int(width * x_ratio)
        y = int(height * y_ratio)
        cv2.rectangle(frame, (x - 62, y - 38), (x + 62, y + 38), (10, 18, 18), -1)
        cv2.putText(frame, "GG Seat", (x - 48, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (240, 240, 240), 1)
        cv2.putText(frame, "1000", (x - 32, y + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 235, 0), 2)
    return frame


if __name__ == "__main__":
    unittest.main()
