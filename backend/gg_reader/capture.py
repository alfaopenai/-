from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Any

import numpy as np


WGC_INITIAL_FRAME_TIMEOUT_SECONDS = 1.5
WGC_SUBSEQUENT_FRAME_TIMEOUT_SECONDS = 0.35
WINDOW_CAPTURE_RETRY_BACKOFF_SECONDS = 5.0


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


BAD_WINDOW_PROCESS_NAMES = {
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
    "mremoteng.exe",
}
BAD_WINDOW_TITLE_TOKENS = (
    "localhost",
    "127.0.0.1",
    "ask gemini",
    "google translate",
    "mremoteng",
)


def list_gg_windows(*, include_rejected: bool = False, allow_browser_fallback: bool = False) -> list[dict[str, Any]]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    enum_windows_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    windows: list[dict[str, Any]] = []
    psutil_module = _load_psutil()

    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

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

        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width < 320 or height < 240:
            return True

        class_buffer = ctypes.create_unicode_buffer(256)
        try:
            user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        except Exception:
            pass
        class_name = class_buffer.value.strip()

        pid = wintypes.DWORD()
        try:
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        except Exception:
            pid.value = 0
        process_info = _process_info(int(pid.value), psutil_module)

        client_rect = wintypes.RECT()
        client_payload: dict[str, int] | None = None
        try:
            if user32.GetClientRect(hwnd, ctypes.byref(client_rect)):
                point = POINT(0, 0)
                user32.ClientToScreen(hwnd, ctypes.byref(point))
                client_payload = {
                    "left": int(point.x),
                    "top": int(point.y),
                    "width": int(client_rect.right - client_rect.left),
                    "height": int(client_rect.bottom - client_rect.top),
                }
        except Exception:
            client_payload = None

        has_table_title = any(token in title_lower for token in ("nlh", "plo", "clubgg", "club gg"))
        reject_reason = _reject_window_reason(
            title=title,
            process_name=str(process_info.get("processName") or ""),
            process_exe=str(process_info.get("processExe") or ""),
            class_name=class_name,
            allow_browser_fallback=allow_browser_fallback,
        )
        if not has_table_title:
            reject_reason = reject_reason or "not-gg-table-title"
        if not has_table_title and not include_rejected:
            return True
        if reject_reason and not include_rejected:
            return True

        score = 0
        if "nlh" in title_lower or "plo" in title_lower:
            score += 100
        if re.search(r"\b\d+(?:\.\d+)?\s*[-/]\s*\d+(?:\.\d+)?\b", title_lower):
            score += 35
        if "clubgg" in title_lower or "club gg" in title_lower:
            score += 20
        process_name = str(process_info.get("processName") or "").lower()
        process_exe = str(process_info.get("processExe") or "").lower()
        if "clubgg" in process_name or "clubgg" in process_exe:
            score += 35
        if any(token in process_name or token in process_exe for token in ("hd-player", "nox", "bluestacks", "ldplayer")):
            score += 18
        if reject_reason:
            score -= 500
        score += min(width * height // 10000, 40)
        windows.append({
            "hwnd": int(hwnd),
            "title": title,
            "className": class_name,
            "pid": int(pid.value),
            **process_info,
            "left": int(rect.left),
            "top": int(rect.top),
            "width": width,
            "height": height,
            "rect": {
                "left": int(rect.left),
                "top": int(rect.top),
                "width": width,
                "height": height,
            },
            "clientRect": client_payload,
            "score": score,
            "rejected": bool(reject_reason),
            "rejectReason": reject_reason,
        })
        return True

    user32.EnumWindows(enum_windows_proc(callback), 0)
    return sorted(windows, key=lambda item: int(item["score"]), reverse=True)


def get_best_gg_window() -> dict[str, Any] | None:
    windows = list_gg_windows()
    return windows[0] if windows else None


def _load_psutil() -> Any | None:
    try:
        import psutil

        return psutil
    except Exception:
        return None


def _process_info(pid: int, psutil_module: Any | None) -> dict[str, Any]:
    if pid <= 0 or psutil_module is None:
        return {"processName": "", "processExe": ""}
    try:
        process = psutil_module.Process(pid)
        return {
            "processName": str(process.name() or ""),
            "processExe": str(process.exe() or ""),
        }
    except Exception:
        return {"processName": "", "processExe": ""}


def _reject_window_reason(
    *,
    title: str,
    process_name: str,
    process_exe: str,
    class_name: str,
    allow_browser_fallback: bool,
) -> str:
    title_lower = title.lower()
    process_lower = process_name.lower()
    exe_lower = process_exe.lower()
    class_lower = class_name.lower()
    if any(token in title_lower for token in ("localhost", "127.0.0.1")):
        return "localhost-title"
    if any(token in title_lower for token in ("ask gemini", "google translate")):
        return "browser-title"
    if "mremoteng" in title_lower or "mremoteng" in process_lower or "mremoteng" in exe_lower or "mremoteng" in class_lower:
        return "remote-control-process"
    if not allow_browser_fallback and (process_lower in BAD_WINDOW_PROCESS_NAMES or any(item in exe_lower for item in BAD_WINDOW_PROCESS_NAMES)):
        return "browser-process"
    return ""


@dataclass
class ScreenCapture:
    monitor_index: int = 2
    debug: bool = False
    capture_mode: str = "auto"
    last_source: str = "monitor"
    last_window: dict[str, Any] | None = None
    last_capture_warning: str | None = None
    last_capture_diagnostics: dict[str, Any] = field(default_factory=dict)
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
    _wgc_retry_after: float = field(default=0.0, init=False, repr=False)
    _window_retry_after: float = field(default=0.0, init=False, repr=False)
    _last_window_failure: str = field(default="", init=False, repr=False)

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
        self.last_capture_warning = None
        self.last_capture_diagnostics = {"requestedMode": self.capture_mode}
        monitor_fallback_reason = ""
        if self.capture_mode in {"auto", "window"}:
            window = self._get_cached_window()
            if window:
                now = time.monotonic()
                if self.capture_mode == "auto" and now < self._window_retry_after:
                    monitor_fallback_reason = self._last_window_failure or "window capture retry backoff"
                else:
                    wgc_error: Exception | None = None
                    if self.capture_mode == "window" or now >= self._wgc_retry_after:
                        try:
                            frame = self._grab_window_with_wgc(window)
                            self._window_retry_after = 0.0
                            self._last_window_failure = ""
                            self.last_capture_diagnostics.update({
                                "captureMethod": "windows-graphics-capture",
                                "windowFallback": False,
                            })
                            return frame
                        except Exception as exc:
                            wgc_error = exc
                            self._wgc_retry_after = now + WINDOW_CAPTURE_RETRY_BACKOFF_SECONDS
                    else:
                        wgc_error = RuntimeError("Windows Graphics Capture retry is in backoff.")
                    try:
                        sct = self._get_sct()
                        shot = sct.grab({
                            "left": int(window["left"]),
                            "top": int(window["top"]),
                            "width": int(window["width"]),
                            "height": int(window["height"]),
                        })
                    except Exception as exc:
                        error_message = (
                            "ClubGG table window was found, but Windows blocked the window capture. "
                            "Make sure the GG table is visible in the same Windows session and not minimized. "
                            f"Windows Graphics Capture error: {wgc_error}. GDI error: {exc}"
                        )
                        self.last_source = "window"
                        self.last_window = window
                        self.last_capture_warning = error_message
                        self.last_capture_diagnostics.update({
                            "captureMethod": "window-failed",
                            "windowFallback": self.capture_mode == "auto",
                            "wgcError": str(wgc_error or ""),
                            "gdiError": str(exc),
                        })
                        if self.capture_mode == "window":
                            raise RuntimeError(error_message) from exc
                        self._window_retry_after = now + WINDOW_CAPTURE_RETRY_BACKOFF_SECONDS
                        self._last_window_failure = error_message
                        monitor_fallback_reason = error_message
                    else:
                        self._window_retry_after = 0.0
                        self._last_window_failure = ""
                        self.last_source = "window"
                        self.last_window = window
                        if wgc_error is not None:
                            self.last_capture_warning = (
                                "Windows Graphics Capture failed; using the GDI window-region fallback. "
                                f"{wgc_error}"
                            )
                        self.last_capture_diagnostics.update({
                            "captureMethod": "mss-window-region",
                            "windowFallback": True,
                            "wgcError": str(wgc_error or ""),
                        })
                        return np.array(shot)
            if self.capture_mode == "window":
                self.last_source = "window"
                self.last_window = None
                self.last_capture_diagnostics.update({
                    "captureMethod": "window-not-found",
                    "windowFallback": False,
                })
                raise ValueError("No visible ClubGG table window was found.")
            if not window:
                monitor_fallback_reason = "No visible ClubGG table window was found; using monitor capture."

        resolved = self.get_monitor_index()
        sct = self._get_sct()
        monitors: list[dict[str, Any]] = sct.monitors
        try:
            shot = sct.grab(monitors[resolved])
        except Exception as exc:
            self.last_source = "monitor"
            self.last_window = None
            prefix = f"{monitor_fallback_reason} " if monitor_fallback_reason else ""
            error_message = (
                f"{prefix}Monitor capture also failed: {exc}"
            ).strip()
            self.last_capture_warning = error_message
            self.last_capture_diagnostics.update({
                "captureMethod": "monitor-failed",
                "windowFallback": bool(monitor_fallback_reason),
                "monitorIndex": int(resolved),
                "monitorError": str(exc),
            })
            raise RuntimeError(error_message) from exc
        self.last_source = "monitor"
        self.last_window = None
        self.last_capture_warning = monitor_fallback_reason or None
        self.last_capture_diagnostics.update({
            "captureMethod": "mss-monitor",
            "windowFallback": bool(monitor_fallback_reason),
            "monitorIndex": int(resolved),
        })
        return np.array(shot)

    def _grab_window_with_wgc(self, window: dict[str, Any]) -> np.ndarray:
        hwnd = int(window["hwnd"])
        if self._wgc_hwnd != hwnd or self._wgc_capture is None or self._wgc_closed:
            self._start_window_capture(hwnd)
        wait_timeout = (
            WGC_INITIAL_FRAME_TIMEOUT_SECONDS
            if self._wgc_frame is None
            else WGC_SUBSEQUENT_FRAME_TIMEOUT_SECONDS
        )
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
        self._wgc_retry_after = 0.0
        self._window_retry_after = 0.0
        self._last_window_failure = ""
