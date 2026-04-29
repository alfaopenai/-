from __future__ import annotations

from dataclasses import dataclass
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


@dataclass
class ScreenCapture:
    monitor_index: int = 2
    debug: bool = False

    def get_monitor_index(self) -> int:
        resolved, _message = resolve_monitor_index(self.monitor_index)
        return resolved

    def grab(self) -> np.ndarray:
        import mss

        # TODO: keep an mss instance alive for high-FPS parsing after OCR is wired.
        with mss.mss() as sct:
            resolved, _message = resolve_monitor_index(self.monitor_index)
            monitors: list[dict[str, Any]] = sct.monitors
            shot = sct.grab(monitors[resolved])
            return np.array(shot)
