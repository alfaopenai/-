from __future__ import annotations

import re

import numpy as np


def normalize_amount(raw: str | None) -> float:
    if not raw:
        return 0.0
    value = raw.strip().replace(",", "")
    multiplier = 1.0
    if value[-1:].upper() == "K":
        multiplier = 1_000
        value = value[:-1]
    elif value[-1:].upper() == "M":
        multiplier = 1_000_000
        value = value[:-1]
    elif value[-1:].upper() == "B":
        multiplier = 1_000_000_000
        value = value[:-1]
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    return float(match.group(0)) * multiplier if match else 0.0


def read_text(_image: np.ndarray, *, mode: str = "name") -> tuple[str, float]:
    # Real OCR is wired here after ROIs are calibrated.
    return "", 0.0


def read_card(_image: np.ndarray) -> dict[str, object]:
    # Prefer OpenCV template matching for ranks/suits/card backs in the next phase.
    return {"hidden": False, "visible": False, "confidence": 0.0}
