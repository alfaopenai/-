from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Any

import numpy as np


def list_monitors() -> list[dict[str, int]]:
    import mss

    with mss.mss() as sct:
        monitors: list[dict[str, Any]] = sct.monitors
        return [
            {
                "index": index,
                "left": int(monitor["left"]),
                "top": int(monitor["top"]),
                "width": int(monitor["width"]),
                "height": int(monitor["height"]),
            }
            for index, monitor in enumerate(monitors[1:], start=1)
        ]


def resolve_monitor_index(requested: int) -> tuple[int, str | None]:
    monitors = list_monitors()
    if not monitors:
        raise ValueError("No monitors are available for capture.")

    available = {monitor["index"] for monitor in monitors}
    if requested in available:
        return requested, None

    fallback = monitors[0]["index"]
    return fallback, f"Monitor {requested} not found, using Monitor {fallback}."


def list_gg_windows() -> list[dict[str, Any]]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    enum_windows_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    windows: list[dict[str, Any]] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        title_length = user32.GetWindowTextLengthW(hwnd)
        if title_length <= 0:
            return True

        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)
        title = title_buffer.value.strip()
        title_lower = title.lower()
        if not any(token in title_lower for token in ("nlh", "plo", "clubgg", "club gg")):
            return True

        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width < 320 or height < 240:
            return True

        score = 0
        if "nlh" in title_lower or "plo" in title_lower:
            score += 100
        if "clubgg" in title_lower or "club gg" in title_lower:
            score += 20
        score += min(width * height // 10000, 40)
        windows.append({
            "hwnd": int(hwnd),
            "title": title,
            "left": int(rect.left),
            "top": int(rect.top),
            "width": width,
            "height": height,
            "score": score,
        })
        return True

    user32.EnumWindows(enum_windows_proc(callback), 0)
    return sorted(windows, key=lambda item: int(item["score"]), reverse=True)


def get_best_gg_window() -> dict[str, Any] | None:
    windows = list_gg_windows()
    return windows[0] if windows else None


@dataclass
class ScreenCapture:
    monitor_index: int = 2
    debug: bool = False
    capture_mode: str = "auto"
    last_source: str = "monitor"
    last_window: dict[str, Any] | None = None
    _sct: Any = field(default=None, init=False, repr=False)
    _cached_window: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _window_checked_at: float = field(default=0.0, init=False, repr=False)
    _resolved_monitor_index: int | None = field(default=None, init=False, repr=False)
    _wgc_hwnd: int | None = field(default=None, init=False, repr=False)
    _wgc_capture: Any = field(default=None, init=False, repr=False)
    _wgc_control: Any = field(default=None, init=False, repr=False)
    _wgc_frame: np.ndarray | None = field(default=None, init=False, repr=False)
    _wgc_frame_event: Event = field(default_factory=Event, init=False, repr=False)
    _wgc_lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _wgc_closed: bool = field(default=False, init=False, repr=False)

    def _get_sct(self) -> Any:
        if self._sct is None:
            import mss

            self._sct = mss.mss()
        return self._sct

    def _get_cached_window(self) -> dict[str, Any] | None:
        now = time.monotonic()
        if now - self._window_checked_at > 1.0:
            self._cached_window = get_best_gg_window()
            self._window_checked_at = now
        return self._cached_window

    def get_monitor_index(self) -> int:
        if self._resolved_monitor_index is None:
            resolved, _message = resolve_monitor_index(self.monitor_index)
            self._resolved_monitor_index = resolved
        return self._resolved_monitor_index

    def grab(self) -> np.ndarray:
        if self.capture_mode in {"auto", "window"}:
            window = self._get_cached_window()
            if window:
                wgc_error: Exception | None = None
                try:
                    return self._grab_window_with_wgc(window)
                except Exception as exc:
                    wgc_error = exc
                try:
                    sct = self._get_sct()
                    shot = sct.grab({
                        "left": int(window["left"]),
                        "top": int(window["top"]),
                        "width": int(window["width"]),
                        "height": int(window["height"]),
                    })
                except Exception as exc:
                    raise RuntimeError(
                        "ClubGG table window was found, but Windows blocked the screen capture. "
                        "Make sure the GG table is visible in the same Windows session and not minimized. "
                        f"Windows Graphics Capture error: {wgc_error}. GDI error: {exc}"
                    )
                self.last_source = "window"
                self.last_window = window
                return np.array(shot)
            if self.capture_mode == "window":
                raise ValueError("No visible ClubGG table window was found.")

        resolved = self.get_monitor_index()
        sct = self._get_sct()
        monitors: list[dict[str, Any]] = sct.monitors
        shot = sct.grab(monitors[resolved])
        self.last_source = "monitor"
        self.last_window = None
        return np.array(shot)

    def _grab_window_with_wgc(self, window: dict[str, Any]) -> np.ndarray:
        hwnd = int(window["hwnd"])
        if self._wgc_hwnd != hwnd or self._wgc_capture is None or self._wgc_closed:
            self._start_window_capture(hwnd)
        wait_timeout = 5.0 if self._wgc_frame is None else 0.5
        if not self._wgc_frame_event.wait(timeout=wait_timeout):
            raise TimeoutError("Timed out waiting for Windows Graphics Capture frame.")
        with self._wgc_lock:
            if self._wgc_frame is None:
                raise TimeoutError("Windows Graphics Capture did not provide a frame.")
            frame = self._wgc_frame.copy()
        self.last_source = "window"
        self.last_window = window
        return frame

    def _start_window_capture(self, hwnd: int) -> None:
        self.close_window_capture()

        from windows_capture import WindowsCapture

        self._wgc_hwnd = hwnd
        self._wgc_frame = None
        self._wgc_closed = False
        self._wgc_frame_event.clear()

        capture = WindowsCapture(
            cursor_capture=False,
            draw_border=False,
            window_hwnd=hwnd,
            minimum_update_interval=16,
        )

        @capture.event
        def on_frame_arrived(frame: Any, _control: Any) -> None:
            with self._wgc_lock:
                self._wgc_frame = frame.frame_buffer.copy()
            self._wgc_frame_event.set()

        @capture.event
        def on_closed() -> None:
            self._wgc_closed = True

        self._wgc_capture = capture
        self._wgc_control = capture.start_free_threaded()

    def close_window_capture(self) -> None:
        if self._wgc_control is not None:
            try:
                self._wgc_control.stop()
            except Exception:
                pass
        self._wgc_control = None
        self._wgc_capture = None
        self._wgc_hwnd = None
        self._wgc_frame = None
        self._wgc_frame_event.clear()

    def close(self) -> None:
        self.close_window_capture()
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
        self._sct = None
