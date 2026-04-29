from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CALIBRATION_PATH = DATA_DIR / "gg_calibration.json"


def _rect(x: float, y: float, width: float, height: float) -> dict[str, float]:
    return {"x": x, "y": y, "width": width, "height": height}


def _seat_roi(x: float, y: float, *, card_y_offset: float = -0.085) -> dict[str, Any]:
    return {
        "name": _rect(x - 0.055, y + 0.025, 0.11, 0.032),
        "stack": _rect(x - 0.055, y + 0.055, 0.11, 0.036),
        "bet": _rect(x - 0.04, y - 0.095, 0.08, 0.05),
        "active": _rect(x - 0.07, y - 0.06, 0.14, 0.16),
        "cards": [
            _rect(x - 0.055, y + card_y_offset, 0.046, 0.082),
            _rect(x + 0.009, y + card_y_offset, 0.046, 0.082),
        ],
        "dealer": _rect(x - 0.075, y - 0.03, 0.035, 0.04),
    }


GGCLUB_9MAX_1920X1080 = {
    "monitorIndex": 2,
    "profile": "ggclub_9max_1920x1080",
    "verified": False,
    "tableBox": _rect(0, 0, 1920, 1080),
    "potRoi": _rect(0.45, 0.35, 0.1, 0.045),
    "dealerButtonRois": [
        _rect(0.485, 0.235, 0.03, 0.04),
        _rect(0.78, 0.52, 0.03, 0.04),
        _rect(0.5, 0.72, 0.03, 0.04),
        _rect(0.21, 0.52, 0.03, 0.04),
    ],
    "boardRois": [
        _rect(0.37, 0.41, 0.06, 0.1),
        _rect(0.44, 0.41, 0.06, 0.1),
        _rect(0.51, 0.41, 0.06, 0.1),
        _rect(0.58, 0.41, 0.06, 0.1),
        _rect(0.65, 0.41, 0.06, 0.1),
    ],
    "seatRois": {
        "0": _seat_roi(0.5, 0.16),
        "1": _seat_roi(0.77, 0.26),
        "2": _seat_roi(0.9, 0.45),
        "3": _seat_roi(0.86, 0.72),
        "4": _seat_roi(0.65, 0.84),
        "5": _seat_roi(0.35, 0.84),
        "6": _seat_roi(0.14, 0.72),
        "7": _seat_roi(0.1, 0.45),
        "8": _seat_roi(0.23, 0.26),
    },
}


GGCLUB_6MAX_1920X1080 = {
    **copy.deepcopy(GGCLUB_9MAX_1920X1080),
    "profile": "ggclub_6max_1920x1080",
    "seatRois": {
        "0": _seat_roi(0.5, 0.15),
        "1": _seat_roi(0.86, 0.35),
        "2": _seat_roi(0.82, 0.73),
        "3": _seat_roi(0.5, 0.86),
        "4": _seat_roi(0.18, 0.73),
        "5": _seat_roi(0.14, 0.35),
    },
}


DEFAULT_CALIBRATION: dict[str, Any] = {
    **copy.deepcopy(GGCLUB_9MAX_1920X1080),
    "profiles": {
        "ggclub_9max_1920x1080": GGCLUB_9MAX_1920X1080,
        "ggclub_6max_1920x1080": GGCLUB_6MAX_1920X1080,
    },
}


def load_calibration() -> dict[str, Any]:
    if not CALIBRATION_PATH.exists():
        return copy.deepcopy(DEFAULT_CALIBRATION)
    return json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))


def save_calibration(data: dict[str, Any]) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged = copy.deepcopy(DEFAULT_CALIBRATION)
    merged.update(data or {})
    CALIBRATION_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return merged
