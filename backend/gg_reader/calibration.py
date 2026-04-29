from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CALIBRATION_PATH = DATA_DIR / "gg_calibration.json"


DEFAULT_CALIBRATION: dict[str, Any] = {
    "monitorIndex": 2,
    "profile": "ggclub_9max",
    "verified": False,
    "tableBox": {"x": 0, "y": 0, "width": 1920, "height": 1080},
    "seatRois": {},
    "boardRois": [],
    "potRoi": {"x": 0.44, "y": 0.34, "width": 0.12, "height": 0.06},
}


def load_calibration() -> dict[str, Any]:
    if not CALIBRATION_PATH.exists():
        return DEFAULT_CALIBRATION.copy()
    return json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))


def save_calibration(data: dict[str, Any]) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged = DEFAULT_CALIBRATION.copy()
    merged.update(data or {})
    CALIBRATION_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return merged
