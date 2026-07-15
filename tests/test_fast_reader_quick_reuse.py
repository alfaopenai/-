from __future__ import annotations

import sys
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from threading import Lock
from typing import Any
from unittest.mock import patch

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.gg_reader.fast_reader import (  # noqa: E402
    QUICK_REUSE_OCR_FULL_PASS_FRAMES,
    FastGgReader,
    _FieldCache,
)
from backend.gg_reader.models import GgSeat  # noqa: E402


class _ControlledReader(FastGgReader):
    """Small deterministic reader that exercises the real parse/reuse loop."""

    def _warm_fast_paths(self) -> None:
        return

    def _looks_like_fixed_gg_frame(self, frame: np.ndarray) -> bool:
        return True

    def _select_profile(self, frame: np.ndarray) -> None:
        return

    def _read_name_cached(self, key: str, crop: np.ndarray, **kwargs: Any) -> tuple[str, float]:
        if key == "title/blinds":
            return "NLH 1/2", 0.98
        return super()._read_name_cached(key, crop, **kwargs)

    def _read_board(
        self,
        frame: np.ndarray,
        visible_ids: set[str],
        metrics: dict[str, Any],
    ) -> list[Any]:
        return []

    def _read_amount_cached(self, key: str, crop: np.ndarray, **kwargs: Any) -> tuple[float, float, str]:
        return 1.5, 0.98, "1.5BB"

    def _read_seats(
        self,
        frame: np.ndarray,
        visible_ids: set[str],
        now: float,
        metrics: dict[str, Any],
    ) -> list[GgSeat]:
        if int(frame[1, 1, 0]) == 255:
            return []
        entry = self._fields.setdefault(
            "seat-0-name",
            _FieldCache(value="StablePlayer", confidence=0.98, known=True, requested_at=now),
        )
        self._consume_name_future(entry, metrics, min_confidence=0.18)
        return [
            GgSeat(
                physicalSeatIndex=0,
                active=True,
                name=str(entry.value or ""),
                nameConfidence=float(entry.confidence or 0.0),
                stack=100.0,
                stackConfidence=0.98,
                confidence=0.92,
            ),
            GgSeat(
                physicalSeatIndex=1,
                active=True,
                name="KnownPlayer",
                nameConfidence=0.98,
                stack=100.0,
                stackConfidence=0.98,
                confidence=0.92,
            ),
        ]

    def _detect_dealer(
        self,
        frame: np.ndarray,
        seats: list[GgSeat],
        now: float,
        metrics: dict[str, Any],
    ) -> int:
        return 0

    def _apply_positions(self, seats: list[GgSeat], dealer_index: int) -> None:
        return


class _RetryingTitleReader(_ControlledReader):
    """Use the real title cache while keeping every other field deterministic."""

    def _read_name_cached(self, key: str, crop: np.ndarray, **kwargs: Any) -> tuple[str, float]:
        if key == "title/blinds":
            return FastGgReader._read_name_cached(self, key, crop, **kwargs)
        return super()._read_name_cached(key, crop, **kwargs)


class PendingOcrQuickReuseTest(unittest.TestCase):
    def _primed_reader(self) -> tuple[_ControlledReader, np.ndarray]:
        reader = _ControlledReader(ocr_workers=1)
        self.addCleanup(reader.close)
        frame = np.zeros((96, 128, 3), dtype=np.uint8)
        self.assertIsNotNone(reader.parse(frame))
        self.assertIsNotNone(reader.parse(frame))
        self.assertGreaterEqual(reader._actual_fps(), 2.5)
        reader._quick_reuses_since_full_pass = 0
        reader._last_full_pass_at = time.monotonic()
        return reader, frame

    def test_failed_title_bootstrap_never_publishes_profile_default_stakes(self) -> None:
        calls = 0
        calls_lock = Lock()

        def title_source(_crop: np.ndarray) -> tuple[str, float, str, str, str]:
            nonlocal calls
            with calls_lock:
                calls += 1
                attempt = calls
            if attempt == 1:
                return "", 0.0, "", "tesseract_error", "ocr-timeout"
            return "NLH 1-2 - 1/2", 0.92, "NLH 1-2 - 1/2", "tesseract_title", ""

        frame = np.zeros((96, 128, 3), dtype=np.uint8)
        with patch("backend.gg_reader.fast_reader._read_table_title_source", side_effect=title_source):
            reader = _RetryingTitleReader(ocr_workers=1)
            self.addCleanup(reader.close)

            first = reader.parse(frame)
            self.assertIsNone(first, "2/4 profile defaults must not escape while 1/2 title OCR is pending")

            resolved = None
            deadline = time.perf_counter() + 2.0
            while resolved is None and time.perf_counter() < deadline:
                time.sleep(0.01)
                resolved = reader.parse(frame)

        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual((resolved.smallBlind, resolved.bigBlind), (1.0, 2.0))
        self.assertFalse(resolved.metrics.get("stakesPending"))
        self.assertEqual(resolved.metrics.get("stakesSource"), "title")
        self.assertGreaterEqual(calls, 2)

    def test_never_completing_future_allows_reuse_but_forces_periodic_full_pass(self) -> None:
        reader, frame = self._primed_reader()
        never_done: Future[Any] = Future()
        entry = reader._fields["seat-0-name"]
        entry.future = never_done
        entry.requested_at = time.monotonic()

        quick_flags: list[bool] = []
        bypass_reasons: list[str] = []
        for _index in range(QUICK_REUSE_OCR_FULL_PASS_FRAMES + 2):
            snapshot = reader.parse(frame)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            quick_flags.append(bool(snapshot.metrics.get("quickReuse")))
            bypass_reasons.append(str(snapshot.metrics.get("quickReuseBypass") or ""))

        self.assertTrue(any(quick_flags), "a pending OCR task must not disable fast reuse")
        self.assertIn(False, quick_flags, "pending OCR still needs a bounded full field pass")
        self.assertIn("ocr-cadence", bypass_reasons)
        self.assertIs(entry.future, never_done)

        # This pixel is intentionally outside the sparse 24-pixel hash grid.
        # Exact equality must still prevent a stale reuse.
        changed = frame.copy()
        changed[1, 1, 0] = 1
        self.assertTrue(np.array_equal(reader._quick_frame_hash(changed), reader._last_reuse_hash))
        changed_snapshot = reader.parse(changed)
        self.assertIsNotNone(changed_snapshot)
        assert changed_snapshot is not None
        self.assertFalse(changed_snapshot.metrics.get("quickReuse", False))

    def test_completed_future_is_consumed_within_the_full_pass_frame_bound(self) -> None:
        reader, frame = self._primed_reader()
        completed: Future[Any] = Future()
        completed.set_result(("RecoveredName", 0.97, "RecoveredName", "test", ""))
        entry = reader._fields["seat-0-name"]
        entry.future = completed
        entry.requested_at = time.monotonic()

        consumed_after = None
        for frame_number in range(1, QUICK_REUSE_OCR_FULL_PASS_FRAMES + 2):
            snapshot = reader.parse(frame)
            self.assertIsNotNone(snapshot)
            if entry.future is None:
                consumed_after = frame_number
                break

        self.assertIsNotNone(consumed_after)
        assert consumed_after is not None
        self.assertLessEqual(consumed_after, QUICK_REUSE_OCR_FULL_PASS_FRAMES + 1)
        self.assertEqual(entry.value, "RecoveredName")
        self.assertAlmostEqual(entry.confidence, 0.97)

    def test_rejected_frame_cannot_reuse_the_previous_accepted_snapshot(self) -> None:
        reader, accepted_frame = self._primed_reader()
        self.assertTrue(np.array_equal(reader._last_reuse_frame, accepted_frame))

        rejected_frame = accepted_frame.copy()
        rejected_frame[1, 1, 0] = 255
        first_rejected = reader.parse(rejected_frame)
        self.assertIsNotNone(first_rejected)
        assert first_rejected is not None
        self.assertFalse(first_rejected.metrics.get("quickReuse", False))
        self.assertEqual(first_rejected.activePlayerCount, 2, "stabilizer should hold the prior visible state")
        self.assertTrue(np.array_equal(reader._last_frame, rejected_frame))
        self.assertTrue(np.array_equal(reader._last_reuse_frame, accepted_frame))

        second_rejected = reader.parse(rejected_frame)
        self.assertIsNotNone(second_rejected)
        assert second_rejected is not None
        self.assertFalse(
            second_rejected.metrics.get("quickReuse", False),
            "a rejected frame must not refresh an older accepted snapshot through reuse",
        )


if __name__ == "__main__":
    unittest.main()
