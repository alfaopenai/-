from __future__ import annotations

import math
import re

import numpy as np

from .fast_amount import read_amount_rapidocr


EquityOcrResult = tuple[float | None, float, str]

RAPIDOCR_PERCENT_SOURCE = "rapidocr_percent"
NO_EQUITY_RESULT: EquityOcrResult = (None, 0.0, "none")

_PERCENT_VALUE = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d+)?)\s*%")


def read_displayed_equity(image: np.ndarray) -> EquityOcrResult:
    """Read a ClubGG displayed equity percentage from one seat label ROI.

    ClubGG replaces a player's name with a percentage while hole cards are
    exposed.  Requiring the percent sign prevents an ordinary stack, player
    name, or blind amount from being accepted as equity.  The immutable tuple
    result is intentionally stateless so the live reader can cache it by its
    existing ROI hash without this helper maintaining a second cache.
    """

    value, confidence, raw = read_amount_rapidocr(image)
    raw_text = str(raw or "").strip()
    if "%" not in raw_text:
        return NO_EQUITY_RESULT

    match = _PERCENT_VALUE.search(raw_text)
    if match is None:
        return NO_EQUITY_RESULT

    try:
        parsed_value = float(match.group(1).replace(",", "."))
        recognized_value = float(value)
    except (TypeError, ValueError):
        return NO_EQUITY_RESULT

    if not math.isfinite(parsed_value) or not math.isfinite(recognized_value):
        return NO_EQUITY_RESULT
    if not 0.0 <= parsed_value <= 100.0 or not 0.0 <= recognized_value <= 100.0:
        return NO_EQUITY_RESULT

    # The recognizer already normalizes the numeric value.  Checking it against
    # the percent-bearing raw text prevents a malformed OCR payload such as
    # ``raw='18.12%'`` with ``value=181.2`` from reaching table state.
    if abs(parsed_value - recognized_value) > 0.005:
        return NO_EQUITY_RESULT

    normalized_confidence = float(confidence or 0.0)
    if not math.isfinite(normalized_confidence):
        normalized_confidence = 0.0
    normalized_confidence = min(1.0, max(0.0, normalized_confidence))
    return (parsed_value, normalized_confidence, RAPIDOCR_PERCENT_SOURCE)
