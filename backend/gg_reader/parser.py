from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from .models import GgTableSnapshot


MOCK_SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "mock" / "gg_snapshot_example.json"


def load_mock_snapshot() -> GgTableSnapshot:
    data: dict[str, Any] = json.loads(MOCK_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    data["timestamp"] = int(time.time() * 1000)
    return GgTableSnapshot.model_validate(data)


def parse_frame(_frame: np.ndarray, _calibration: dict[str, Any]) -> GgTableSnapshot | None:
    # OCR/template matching will replace this once GG Club ROIs are calibrated.
    # Returning None is intentional: never emit fake GG data in normal reader mode.
    return None
