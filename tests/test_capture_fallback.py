from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from backend.gg_reader.capture import (
    WGC_INITIAL_FRAME_TIMEOUT_SECONDS,
    WGC_SUBSEQUENT_FRAME_TIMEOUT_SECONDS,
    ScreenCapture,
)


WINDOW = {
    "hwnd": 123,
    "title": "NLH 1-2 - 1/2",
    "left": 120,
    "top": 60,
    "width": 850,
    "height": 630,
}
MONITOR = {"left": 0, "top": 0, "width": 1326, "height": 695}


class ScreenCaptureFallbackTest(unittest.TestCase):
    def test_wgc_timeouts_stay_bounded_for_live_auto_fallback(self) -> None:
        self.assertLessEqual(WGC_INITIAL_FRAME_TIMEOUT_SECONDS, 1.5)
        self.assertLessEqual(WGC_SUBSEQUENT_FRAME_TIMEOUT_SECONDS, 0.5)

    def test_auto_falls_back_to_monitor_after_both_window_methods_fail(self) -> None:
        capture = ScreenCapture(monitor_index=1, capture_mode="auto")
        sct = MagicMock()
        sct.monitors = [{}, MONITOR]
        monitor_frame = np.full((4, 6, 4), 77, dtype=np.uint8)
        sct.grab.side_effect = [OSError("BitBlt access denied"), monitor_frame]

        with (
            patch.object(capture, "_get_cached_window", return_value=dict(WINDOW)),
            patch.object(capture, "_grab_window_with_wgc", side_effect=TimeoutError("WGC timeout")) as wgc,
            patch.object(capture, "_get_sct", return_value=sct),
            patch.object(capture, "get_monitor_index", return_value=1) as monitor_index,
        ):
            frame = capture.grab()

            self.assertTrue(np.array_equal(frame, monitor_frame))
            self.assertEqual(capture.last_source, "monitor")
            self.assertIsNone(capture.last_window)
            self.assertEqual(capture.last_capture_diagnostics["captureMethod"], "mss-monitor")
            self.assertTrue(capture.last_capture_diagnostics["windowFallback"])
            self.assertIn("WGC timeout", capture.last_capture_warning or "")
            self.assertIn("BitBlt access denied", capture.last_capture_warning or "")
            self.assertEqual(sct.grab.call_count, 2)
            monitor_index.assert_called_once()
            wgc.assert_called_once()

            # During the short retry backoff, auto mode must go directly to the
            # monitor instead of paying the WGC timeout on every frame.
            sct.grab.reset_mock()
            sct.grab.side_effect = None
            sct.grab.return_value = monitor_frame
            second = capture.grab()
            self.assertTrue(np.array_equal(second, monitor_frame))
            self.assertEqual(sct.grab.call_count, 1)
            wgc.assert_called_once()

    def test_window_mode_remains_strict_when_both_window_methods_fail(self) -> None:
        capture = ScreenCapture(monitor_index=1, capture_mode="window")
        sct = MagicMock()
        sct.monitors = [{}, MONITOR]
        sct.grab.side_effect = OSError("BitBlt access denied")

        with (
            patch.object(capture, "_get_cached_window", return_value=dict(WINDOW)),
            patch.object(capture, "_grab_window_with_wgc", side_effect=TimeoutError("WGC timeout")),
            patch.object(capture, "_get_sct", return_value=sct),
            patch.object(capture, "get_monitor_index", return_value=1) as monitor_index,
        ):
            with self.assertRaisesRegex(RuntimeError, "Windows blocked the window capture") as raised:
                capture.grab()

        self.assertIn("WGC timeout", str(raised.exception))
        self.assertIn("BitBlt access denied", str(raised.exception))
        self.assertEqual(capture.last_source, "window")
        self.assertEqual(capture.last_window, WINDOW)
        self.assertEqual(capture.last_capture_diagnostics["captureMethod"], "window-failed")
        self.assertFalse(capture.last_capture_diagnostics["windowFallback"])
        self.assertEqual(sct.grab.call_count, 1)
        monitor_index.assert_not_called()

    def test_wgc_failure_can_still_use_window_region_capture(self) -> None:
        capture = ScreenCapture(monitor_index=1, capture_mode="auto")
        sct = MagicMock()
        window_frame = np.full((3, 5, 4), 123, dtype=np.uint8)
        sct.grab.return_value = window_frame

        with (
            patch.object(capture, "_get_cached_window", return_value=dict(WINDOW)),
            patch.object(capture, "_grab_window_with_wgc", side_effect=TimeoutError("WGC timeout")),
            patch.object(capture, "_get_sct", return_value=sct),
            patch.object(capture, "get_monitor_index", return_value=1) as monitor_index,
        ):
            frame = capture.grab()

        self.assertTrue(np.array_equal(frame, window_frame))
        self.assertEqual(capture.last_source, "window")
        self.assertEqual(capture.last_window, WINDOW)
        self.assertEqual(capture.last_capture_diagnostics["captureMethod"], "mss-window-region")
        self.assertIn("WGC timeout", capture.last_capture_warning or "")
        monitor_index.assert_not_called()


if __name__ == "__main__":
    unittest.main()
