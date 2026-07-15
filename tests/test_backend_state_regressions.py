from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend import main as backend_main
from backend.gg_reader import history_store
from backend.gg_reader.data_paths import DATA_DIR_ENV, get_data_dir
from backend.gg_reader.models import GgCard, GgReaderStartRequest, GgReaderStatus, GgSeat, GgTableSnapshot
from backend.gg_reader.table_state import TableStateStabilizer


def _card(code: str) -> GgCard:
    return GgCard(rank=code[:-1], suit=code[-1], confidence=0.88)


def _snapshot(
    timestamp: int,
    *,
    dealer: int = 0,
    dealer_confidence: float = 0.9,
    street: str = "preflop",
    board: list[GgCard] | None = None,
    pot: float = 1.5,
    seats: list[GgSeat] | None = None,
    hand_id: str | None = None,
    small_blind: float = 0.5,
    big_blind: float = 1.0,
    table_type: str = "9max",
) -> GgTableSnapshot:
    return GgTableSnapshot(
        timestamp=timestamp,
        handId=hand_id,
        tableType=table_type,
        street=street,
        pot=pot,
        smallBlind=small_blind,
        bigBlind=big_blind,
        dealerSeatIndex=dealer,
        board=board or [],
        seats=seats or [],
        metrics={
            "dealerConfidence": dealer_confidence,
            "amountFields": [{"key": "pot", "confidence": 0.9}],
        },
    )


def _seat(
    index: int,
    bet: float,
    *,
    action: str = "none",
    status: str = "active",
    with_cards: bool = False,
) -> GgSeat:
    cards = [_card("AH"), _card("KC")] if with_cards else []
    return GgSeat(
        physicalSeatIndex=index,
        active=True,
        name=f"player-{index}",
        nameConfidence=0.9,
        stack=100.0 - bet,
        stackConfidence=0.9,
        currentBet=bet,
        betConfidence=0.9,
        action=action,
        actionAmount=bet if action in {"bet", "call", "raise", "all-in"} else 0.0,
        actionConfidence=0.9 if action != "none" else 0.0,
        actionSource="label_ocr" if action != "none" else "none",
        status=status,
        holeCards=cards,
    )


class _BodyRequest:
    def __init__(self, body: bytes = b"frame") -> None:
        self._body = body

    async def body(self) -> bytes:
        return self._body


class TableStateRegressionTest(unittest.TestCase):
    def test_repeated_half_confidence_dealer_move_resets_but_single_noise_does_not(self) -> None:
        stabilizer = TableStateStabilizer()
        stabilizer.stabilize(_snapshot(1), now=0.0)

        once = stabilizer.stabilize(_snapshot(2, dealer=1, dealer_confidence=0.50), now=0.2)
        self.assertEqual(once.dealerSeatIndex, 0)
        self.assertFalse(once.metrics["stabilizer"]["handReset"])

        noise_cleared = stabilizer.stabilize(_snapshot(3, dealer=0, dealer_confidence=0.50), now=0.4)
        self.assertEqual(noise_cleared.dealerSeatIndex, 0)
        restarted = stabilizer.stabilize(_snapshot(4, dealer=1, dealer_confidence=0.50), now=0.6)
        self.assertEqual(restarted.dealerSeatIndex, 0)
        self.assertFalse(restarted.metrics["stabilizer"]["handReset"])

        confirmed = stabilizer.stabilize(_snapshot(5, dealer=1, dealer_confidence=0.50), now=0.8)
        self.assertEqual(confirmed.dealerSeatIndex, 1)
        self.assertTrue(confirmed.metrics["stabilizer"]["handReset"])

    def test_duplicate_board_frame_holds_verified_board_and_database(self) -> None:
        stabilizer = TableStateStabilizer()
        verified = [_card("AS"), _card("6D"), _card("3D")]
        first = stabilizer.stabilize(_snapshot(1, street="flop", board=verified), now=0.0)
        self.assertEqual([f"{card.rank}{card.suit}" for card in first.board], ["AS", "6D", "3D"])

        duplicate = [_card("AS"), _card("6D"), _card("6D")]
        held = stabilizer.stabilize(_snapshot(2, street="flop", board=duplicate), now=0.2)
        self.assertEqual([f"{card.rank}{card.suit}" for card in held.board], ["AS", "6D", "3D"])
        self.assertIn("board-invalid", held.metrics["stabilizer"]["fieldsHeld"])
        self.assertEqual(
            [row["card"] for row in held.metrics["stabilizer"]["boardDatabase"]],
            ["AS", "6D", "3D"],
        )

    def test_new_hand_without_dealer_signal_resets_after_consistent_blind_frames(self) -> None:
        stabilizer = TableStateStabilizer()
        river = stabilizer.stabilize(_snapshot(
            1,
            dealer=4,
            dealer_confidence=0.92,
            street="river",
            board=[_card(code) for code in ("AS", "6D", "3D", "TC", "2H")],
            pot=48.0,
            seats=[
                _seat(0, 12.0, action="raise", with_cards=True),
                _seat(4, 12.0, action="fold", status="folded"),
                _seat(7, 12.0, action="call", with_cards=True),
            ],
        ), now=0.0)
        self.assertEqual(river.street, "river")

        blind_frame = lambda timestamp: _snapshot(
            timestamp,
            dealer=4,
            dealer_confidence=0.20,
            street="preflop",
            board=[],
            pot=1.5,
            seats=[_seat(0, 0.5), _seat(4, 1.0), _seat(7, 0.0)],
        )
        first = stabilizer.stabilize(blind_frame(2), now=0.2)
        self.assertFalse(first.metrics["stabilizer"]["handReset"])
        # The first missing-card observation deliberately holds both exposed
        # hands, so terminal inference promotes this held frame to showdown.
        self.assertEqual(first.street, "showdown")
        self.assertEqual(len(first.board), 5)

        reset = stabilizer.stabilize(blind_frame(3), now=0.4)
        self.assertTrue(reset.metrics["stabilizer"]["handReset"])
        self.assertEqual(reset.street, "preflop")
        self.assertEqual(reset.board, [])
        self.assertAlmostEqual(reset.pot, 1.5)
        self.assertEqual([seat.currentBet for seat in reset.seats], [0.5, 1.0, 0.0])
        self.assertTrue(all(seat.action == "none" for seat in reset.seats))
        self.assertTrue(all(seat.status == "active" for seat in reset.seats))
        self.assertEqual(reset.metrics["stabilizer"]["boardDatabase"], [])


class HistoryStoreConcurrencyTest(unittest.TestCase):
    def test_fresh_database_initialization_is_thread_safe(self) -> None:
        original_paths = (history_store.DATA_DIR, history_store.DB_PATH, history_store.HISTORY_PATH)
        original_initialized = set(history_store._INITIALIZED_DATABASES)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                data_dir = Path(temp_dir)
                history_store.DATA_DIR = data_dir
                history_store.DB_PATH = data_dir / "fresh.sqlite"
                history_store.HISTORY_PATH = data_dir / "fresh.jsonl"
                history_store._INITIALIZED_DATABASES.clear()
                barrier = threading.Barrier(6)

                def connect_and_inspect() -> set[str]:
                    barrier.wait(timeout=5)
                    connection = history_store._connect()
                    try:
                        rows = connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        ).fetchall()
                    finally:
                        connection.close()
                    return {str(row[0]) for row in rows}

                with ThreadPoolExecutor(max_workers=6) as executor:
                    results = list(executor.map(lambda _index: connect_and_inspect(), range(6)))

                for tables in results:
                    self.assertTrue({"gg_hands", "gg_snapshots", "gg_events"}.issubset(tables))
        finally:
            history_store.DATA_DIR, history_store.DB_PATH, history_store.HISTORY_PATH = original_paths
            history_store._INITIALIZED_DATABASES.clear()
            history_store._INITIALIZED_DATABASES.update(original_initialized)

    def test_blind_only_change_persists_latest_snapshot(self) -> None:
        original_paths = (history_store.DATA_DIR, history_store.DB_PATH, history_store.HISTORY_PATH)
        original_initialized = set(history_store._INITIALIZED_DATABASES)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                data_dir = Path(temp_dir)
                history_store.DATA_DIR = data_dir
                history_store.DB_PATH = data_dir / "blind-change.sqlite"
                history_store.HISTORY_PATH = data_dir / "blind-change.jsonl"
                history_store._INITIALIZED_DATABASES.clear()

                first = _snapshot(1, hand_id="hand-1", small_blind=0.5, big_blind=1.0)
                corrected = _snapshot(2, hand_id="hand-1", small_blind=1.0, big_blind=2.0)
                history_store.record_snapshot(first, None)
                events = history_store.record_snapshot(corrected, first)

                self.assertEqual(events, [])
                hands = history_store.read_hands(1)
                self.assertEqual(hands[0]["updatedAt"], 2)
                self.assertEqual(hands[0]["latestSnapshot"]["smallBlind"], 1.0)
                self.assertEqual(hands[0]["latestSnapshot"]["bigBlind"], 2.0)
                with history_store._managed_connection() as connection:
                    snapshot_count = connection.execute("SELECT COUNT(*) FROM gg_snapshots").fetchone()[0]
                self.assertEqual(snapshot_count, 2)
        finally:
            history_store.DATA_DIR, history_store.DB_PATH, history_store.HISTORY_PATH = original_paths
            history_store._INITIALIZED_DATABASES.clear()
            history_store._INITIALIZED_DATABASES.update(original_initialized)


class DataPathRegressionTest(unittest.TestCase):
    def test_environment_override_selects_packaged_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {DATA_DIR_ENV: temp_dir},
        ):
            self.assertEqual(get_data_dir(), Path(temp_dir))


class _NativeSocketStub:
    def __init__(self, disconnect_after: int) -> None:
        self.disconnect_after = disconnect_after
        self.accepted = asyncio.Event()
        self.messages: list[dict[str, object]] = []

    async def accept(self) -> None:
        self.accepted.set()

    async def send_json(self, data: dict[str, object]) -> None:
        self.messages.append(data)
        if len(self.messages) >= self.disconnect_after:
            raise backend_main.WebSocketDisconnect()


class _NativeCaptureStub:
    instances: list["_NativeCaptureStub"] = []

    def __init__(self, **_kwargs: object) -> None:
        self.last_source = "window-wgc"
        self.last_window = {"title": "NLH test"}
        self.closed = False
        self.__class__.instances.append(self)

    def close(self) -> None:
        self.closed = True


class NativeWebsocketFanoutRegressionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._originals = {
            "reader_state": backend_main.reader_state,
            "reader_config": backend_main.reader_config,
            "generation": backend_main._reader_session_generation,
            "pipeline": backend_main._reader_pipeline_task,
            "subscriber_counter": backend_main._native_subscriber_counter,
            "capture_owner": backend_main._native_capture_owner,
            "subscribers": dict(backend_main._native_subscribers),
            "latest_payload": backend_main._native_latest_payload,
        }
        backend_main.reader_state = GgReaderStatus(
            running=True,
            monitorIndex=2,
            fps=10,
            profile="ggclub_9max",
            message="running",
        )
        backend_main.reader_config = GgReaderStartRequest(
            monitorIndex=2,
            fps=10,
            captureMode="window",
        )
        backend_main._reader_session_generation = 700
        backend_main._reader_pipeline_task = None
        backend_main._native_subscriber_counter = 0
        backend_main._native_capture_owner = None
        backend_main._native_subscribers.clear()
        backend_main._native_latest_payload = None
        _NativeCaptureStub.instances.clear()

    async def asyncTearDown(self) -> None:
        task = backend_main._reader_pipeline_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        backend_main.reader_state = self._originals["reader_state"]
        backend_main.reader_config = self._originals["reader_config"]
        backend_main._reader_session_generation = self._originals["generation"]
        backend_main._reader_pipeline_task = self._originals["pipeline"]
        backend_main._native_subscriber_counter = self._originals["subscriber_counter"]
        backend_main._native_capture_owner = self._originals["capture_owner"]
        backend_main._native_subscribers.clear()
        backend_main._native_subscribers.update(self._originals["subscribers"])
        backend_main._native_latest_payload = self._originals["latest_payload"]

    async def test_latest_payload_fans_out_and_generation_reset_discards_stale_data(self) -> None:
        first_id, first_queue = backend_main._register_native_subscriber()
        second_id, second_queue = backend_main._register_native_subscriber()
        self.assertEqual(backend_main._native_capture_owner, first_id)

        self.assertTrue(backend_main._publish_native_payload(700, {"frame": 1}))
        self.assertEqual(
            await backend_main._receive_native_payload(first_queue, timeout=0.05),
            {"frame": 1},
        )
        self.assertEqual(
            await backend_main._receive_native_payload(second_queue, timeout=0.05),
            {"frame": 1},
        )

        backend_main._unregister_native_subscriber(first_id)
        self.assertEqual(backend_main._native_capture_owner, second_id)
        old_generation = backend_main._reader_session_generation
        backend_main._publish_native_payload(old_generation, {"frame": "stale"})
        backend_main._invalidate_reader_session()

        self.assertIsNone(backend_main._native_latest_payload)
        self.assertIsNone(await backend_main._receive_native_payload(second_queue, timeout=0.01))
        self.assertFalse(backend_main._publish_native_payload(old_generation, {"frame": "late"}))
        self.assertEqual(backend_main.reader_state.framesDropped, 0)

    async def test_one_owner_captures_for_two_clients_then_successor_takes_over(self) -> None:
        first_socket = _NativeSocketStub(disconnect_after=1)
        second_socket = _NativeSocketStub(disconnect_after=2)
        first_capture_started = asyncio.Event()
        release_first_capture = asyncio.Event()
        capture_calls = 0

        async def capture_once(
            _capture: _NativeCaptureStub,
            _calibration: dict[str, object],
        ) -> GgTableSnapshot:
            nonlocal capture_calls
            capture_calls += 1
            if capture_calls == 1:
                first_capture_started.set()
                await release_first_capture.wait()
            return _snapshot(capture_calls, hand_id="fanout-hand")

        with (
            patch.object(backend_main, "ScreenCapture", _NativeCaptureStub),
            patch.object(backend_main, "_capture_reader_pipeline", new=capture_once),
            patch.object(backend_main, "get_cached_calibration", return_value={}),
            patch.object(backend_main, "enrich_snapshot", side_effect=lambda snapshot: (snapshot, [])),
            patch.object(backend_main.FAST_GG_READER, "get_metrics", return_value={}),
        ):
            first_task = asyncio.create_task(backend_main.gg_reader_socket(first_socket))
            await asyncio.wait_for(first_capture_started.wait(), timeout=1)
            second_task = asyncio.create_task(backend_main.gg_reader_socket(second_socket))
            await asyncio.wait_for(second_socket.accepted.wait(), timeout=1)
            while len(backend_main._native_subscribers) < 2:
                await asyncio.sleep(0)
            release_first_capture.set()
            await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=2)

        self.assertEqual(capture_calls, 2)
        self.assertEqual([message["timestamp"] for message in first_socket.messages], [1])
        self.assertEqual([message["timestamp"] for message in second_socket.messages], [1, 2])
        self.assertEqual(backend_main.reader_state.framesRead, 2)
        self.assertEqual(backend_main.reader_state.framesDropped, 0)
        self.assertEqual(backend_main._native_subscribers, {})
        self.assertIsNone(backend_main._native_capture_owner)
        self.assertEqual(len(_NativeCaptureStub.instances), 2)
        self.assertTrue(all(capture.closed for capture in _NativeCaptureStub.instances))


class BrowserSessionRegressionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._originals = {
            "reader_state": backend_main.reader_state,
            "reader_config": backend_main.reader_config,
            "last_snapshot": backend_main.last_snapshot,
            "current_hand_id": backend_main.current_hand_id,
            "generation": backend_main._reader_session_generation,
            "last_seq": backend_main._last_browser_frame_seq,
            "pipeline": backend_main._reader_pipeline_task,
            "crop_metrics": dict(backend_main.last_crop_metrics),
        }
        backend_main.reader_state = GgReaderStatus(
            running=True,
            monitorIndex=2,
            profile="ggclub_9max",
            message="browser capture ready",
        )
        backend_main.reader_config = GgReaderStartRequest(
            monitorIndex=2,
            captureMode="browser",
        )
        backend_main.last_snapshot = None
        backend_main.current_hand_id = None
        backend_main._reader_session_generation = 100
        backend_main._last_browser_frame_seq = None
        backend_main._reader_pipeline_task = None
        backend_main.last_crop_metrics.clear()

    async def asyncTearDown(self) -> None:
        task = backend_main._reader_pipeline_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        backend_main.reader_state = self._originals["reader_state"]
        backend_main.reader_config = self._originals["reader_config"]
        backend_main.last_snapshot = self._originals["last_snapshot"]
        backend_main.current_hand_id = self._originals["current_hand_id"]
        backend_main._reader_session_generation = self._originals["generation"]
        backend_main._last_browser_frame_seq = self._originals["last_seq"]
        backend_main._reader_pipeline_task = self._originals["pipeline"]
        backend_main.last_crop_metrics.clear()
        backend_main.last_crop_metrics.update(self._originals["crop_metrics"])

    async def test_stop_invalidates_inflight(self) -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked_pipeline(_body: bytes) -> dict[str, object]:
            entered.set()
            await release.wait()
            return self._pipeline_result(_snapshot(10))

        with (
            patch.object(backend_main, "_process_browser_pipeline", new=blocked_pipeline),
            patch.object(backend_main, "_reset_reader_runtime", new=AsyncMock()),
            patch.object(backend_main, "append_event"),
            patch.object(backend_main, "enrich_snapshot") as enrich,
        ):
            parse_task = asyncio.create_task(backend_main.parse_browser_frame(_BodyRequest(), seq=1))
            await asyncio.wait_for(entered.wait(), timeout=1)
            prior_generation = backend_main._reader_session_generation

            await backend_main.stop_reader()
            self.assertEqual(backend_main._reader_session_generation, prior_generation + 1)
            self.assertFalse(backend_main.reader_state.running)
            release.set()
            response = await asyncio.wait_for(parse_task, timeout=1)

        enrich.assert_not_called()
        self.assertEqual(response["dropReason"], "session-stale")
        self.assertFalse(response["observationAccepted"])
        self.assertEqual(backend_main.reader_state.framesRead, 0)
        self.assertIsNone(backend_main.last_snapshot)

    async def test_restart_invalidates_old_generation(self) -> None:
        parse_entered = asyncio.Event()
        release_parse = asyncio.Event()
        reset_entered = asyncio.Event()
        release_reset = asyncio.Event()

        async def blocked_pipeline(_body: bytes) -> dict[str, object]:
            parse_entered.set()
            await release_parse.wait()
            return self._pipeline_result(_snapshot(20))

        async def blocked_reset() -> None:
            reset_entered.set()
            await release_reset.wait()

        with (
            patch.object(backend_main, "_process_browser_pipeline", new=blocked_pipeline),
            patch.object(backend_main, "_reset_reader_runtime", new=blocked_reset),
            patch.object(backend_main, "resolve_monitor_index", return_value=(2, None)),
            patch.object(backend_main, "append_event"),
            patch.object(backend_main, "enrich_snapshot") as enrich,
        ):
            parse_task = asyncio.create_task(backend_main.parse_browser_frame(_BodyRequest(), seq=5))
            await asyncio.wait_for(parse_entered.wait(), timeout=1)
            old_generation = backend_main._reader_session_generation
            start_task = asyncio.create_task(backend_main.start_reader(GgReaderStartRequest(
                monitorIndex=2,
                captureMode="browser",
            )))
            await asyncio.wait_for(reset_entered.wait(), timeout=1)
            self.assertEqual(backend_main._reader_session_generation, old_generation + 1)
            self.assertFalse(backend_main.reader_state.running)

            release_parse.set()
            stale_response = await asyncio.wait_for(parse_task, timeout=1)
            release_reset.set()
            await asyncio.wait_for(start_task, timeout=1)

        enrich.assert_not_called()
        self.assertEqual(stale_response["dropReason"], "session-stale")
        self.assertTrue(backend_main.reader_state.running)
        self.assertEqual(backend_main.reader_state.framesRead, 0)
        self.assertIsNone(backend_main.last_snapshot)

    async def test_out_of_order_and_duplicate_seq_are_stale(self) -> None:
        pipeline_calls = 0

        async def successful_pipeline(_body: bytes) -> dict[str, object]:
            nonlocal pipeline_calls
            pipeline_calls += 1
            return self._pipeline_result(None)

        with (
            patch.object(backend_main, "_process_browser_pipeline", new=successful_pipeline),
            patch.object(backend_main.FAST_GG_READER, "get_metrics", return_value={}),
        ):
            accepted = await backend_main.parse_browser_frame(_BodyRequest(), seq=10)
            duplicate = await backend_main.parse_browser_frame(_BodyRequest(), seq=10)
            out_of_order = await backend_main.parse_browser_frame(_BodyRequest(), seq=9)

        self.assertTrue(accepted["observationAccepted"])
        self.assertEqual(duplicate["dropReason"], "duplicate-seq")
        self.assertEqual(out_of_order["dropReason"], "out-of-order-seq")
        self.assertFalse(duplicate["observationAccepted"])
        self.assertFalse(out_of_order["observationAccepted"])
        self.assertEqual(pipeline_calls, 1)
        self.assertEqual(backend_main.reader_state.framesRead, 1)

    async def test_dropped_response_has_no_unparsed_observation(self) -> None:
        backend_main.last_snapshot = _snapshot(30, hand_id="old-hand")
        with patch.object(backend_main, "_reader_pipeline_busy", return_value=True):
            response = await backend_main.parse_browser_frame(_BodyRequest(), seq=20)

        self.assertEqual(response["type"], "status")
        self.assertEqual(response["dropReason"], "reader-busy")
        self.assertTrue(response["frameDropped"])
        self.assertFalse(response["observationAccepted"])
        self.assertNotIn("handId", response)
        self.assertNotIn("normalizedState", response)
        self.assertEqual(response["events"], [])
        self.assertEqual(backend_main.reader_state.framesRead, 0)

    async def test_arbitrary_browser_frame_uses_visual_crop_before_geometry_rejection(self) -> None:
        fixture = Path(__file__).resolve().parent / "fixtures" / "gg_table_user_flop_desktop.png"
        frame = backend_main.decode_browser_frame(fixture.read_bytes())
        window, monitor = self._mismatched_local_geometry()

        with (
            patch.object(backend_main, "get_cached_gg_windows", return_value=[window]),
            patch.object(backend_main, "get_cached_monitors", return_value=[monitor]),
        ):
            cropped, metrics = backend_main.crop_browser_frame_to_gg_window_with_metrics(frame)

        self.assertEqual(cropped.shape[:2], (789, 1063))
        self.assertEqual(metrics["cropRect"], {"left": 117, "top": 61, "width": 1063, "height": 789})
        self.assertTrue(metrics["isRealClubGg"], metrics)
        self.assertTrue(metrics["browserFrameGeometryFallback"])
        self.assertIn("image-detected-table", metrics["cropSource"])
        self.assertIn("browser-frame-not-full-monitor", metrics["cropWarnings"])
        self.assertFalse(metrics.get("rejectedLocalhostTable"))

    async def test_arbitrary_browser_frame_does_not_trust_local_window_title_for_fake_table(self) -> None:
        from tests.test_amount_and_state import _synthetic_localhost_table

        frame = _synthetic_localhost_table(width=1238, height=892)
        window, monitor = self._mismatched_local_geometry()
        with (
            patch.object(backend_main, "get_cached_gg_windows", return_value=[window]),
            patch.object(backend_main, "get_cached_monitors", return_value=[monitor]),
        ):
            _cropped, metrics = backend_main.crop_browser_frame_to_gg_window_with_metrics(frame)

        self.assertFalse(metrics["isRealClubGg"], metrics)
        self.assertTrue(metrics["browserFrameGeometryFallback"])
        self.assertNotEqual(metrics.get("rejectedReason"), "browser-frame-not-full-monitor")

    async def test_parse_frame_route_converges_user_fixture_with_mismatched_local_geometry(self) -> None:
        fixture = Path(__file__).resolve().parent / "fixtures" / "gg_table_user_flop_desktop.png"
        body = fixture.read_bytes()
        window, monitor = self._mismatched_local_geometry()
        exact_response: dict[str, object] | None = None

        try:
            with (
                patch.object(backend_main, "resolve_monitor_index", return_value=(2, None)),
                patch.object(backend_main, "append_event"),
            ):
                started = await backend_main.start_reader(GgReaderStartRequest(
                    monitorIndex=2,
                    captureMode="browser",
                ))
            self.assertTrue(started.running)
            self.assertEqual(backend_main.reader_config.captureMode, "browser")
            with (
                patch.object(backend_main, "get_cached_gg_windows", return_value=[window]),
                patch.object(backend_main, "get_cached_monitors", return_value=[monitor]),
                patch.object(backend_main, "get_cached_calibration", return_value={}),
                patch.object(backend_main, "schedule_cropped_debug_frame_save"),
                patch.object(backend_main, "enrich_snapshot", side_effect=lambda snapshot: (snapshot, [])),
            ):
                for seq in range(1, 46):
                    response = await backend_main.parse_browser_frame(_BodyRequest(body), seq=seq)
                    self.assertTrue(response.get("observationAccepted"), response)
                    if self._is_exact_user_response(response):
                        exact_response = response
                        break
                    await asyncio.sleep(0.05)
        finally:
            backend_main.FAST_GG_READER.reset()

        self.assertIsNotNone(exact_response)
        assert exact_response is not None
        self.assertEqual(exact_response["cropRect"], {"left": 117, "top": 61, "width": 1063, "height": 789})
        self.assertTrue(exact_response["browserFrameGeometryFallback"])
        self.assertIn("image-detected-table", str(exact_response["cropSource"]))
        self.assertEqual(exact_response.get("rejectedReason"), "")

    @staticmethod
    def _mismatched_local_geometry() -> tuple[dict[str, object], dict[str, int]]:
        return (
            {
                "title": "NLH 1-2 - 1/2",
                "processName": "ClubGG.exe",
                "left": 310,
                "top": 28,
                "width": 850,
                "height": 630,
            },
            {"left": 0, "top": 0, "width": 1326, "height": 695},
        )

    @staticmethod
    def _is_exact_user_response(response: dict[str, object]) -> bool:
        if response.get("street") != "flop" or response.get("pot") != 11.5:
            return False
        if response.get("smallBlind") != 1.0 or response.get("bigBlind") != 2.0:
            return False
        if response.get("dealerSeatIndex") != 5 or response.get("activePlayerCount") != 6:
            return False
        board = [
            f"{card.get('rank')}{card.get('suit')}"
            for card in response.get("board", [])
            if isinstance(card, dict) and card.get("visible") and not card.get("hidden")
        ]
        if board != ["6S", "AS", "9D"]:
            return False
        seats = {
            int(seat["physicalSeatIndex"]): seat
            for seat in response.get("seats", [])
            if isinstance(seat, dict)
        }
        expected = {
            0: ("Cyberster", 30.9, 0.0),
            3: ("yarkat1965", 38.0, 1.0),
            # 9.5 BB is the central prior-street subtotal, not seat 4's bet.
            4: ("HolyRiver88", 101.2, 0.0),
            5: ("itzik77733", 94.5, 1.0),
            6: ("NoobMaster69", 198.1, 0.0),
            7: ("natke", 126.8, 0.0),
        }
        return all(
            index in seats
            and seats[index].get("name") == name
            and seats[index].get("stack") == stack
            and seats[index].get("currentBet") == bet
            for index, (name, stack, bet) in expected.items()
        ) and seats.get(3, {}).get("action") == "call"

    @staticmethod
    def _pipeline_result(snapshot: GgTableSnapshot | None) -> dict[str, object]:
        return {
            "snapshot": snapshot,
            "cropMetrics": {},
            "decodeMs": 1.0,
            "cropMs": 1.0,
            "parseMs": 1.0,
        }


if __name__ == "__main__":
    unittest.main()
