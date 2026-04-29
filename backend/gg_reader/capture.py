from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class ScreenCapture:
    monitor_index: int = 2
    debug: bool = False

    def grab(self) -> np.ndarray:
        import mss

        with mss.mss() as sct:
            monitors: list[dict[str, Any]] = sct.monitors
            if self.monitor_index >= len(monitors):
                raise ValueError(f"Monitor {self.monitor_index} is not available. Found {len(monitors) - 1} monitors.")
            shot = sct.grab(monitors[self.monitor_index])
            return np.array(shot)
