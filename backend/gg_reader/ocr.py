from __future__ import annotations

import os
import re
from typing import Any

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


def preprocess_for_text(image: np.ndarray) -> np.ndarray:
    import cv2

    if image.ndim == 3 and image.shape[2] >= 3:
        gray = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    scaled = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    denoised = cv2.medianBlur(scaled, 3)
    return cv2.adaptiveThreshold(
        denoised,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        7,
    )


def _configure_tesseract(pytesseract: Any) -> None:
    configured = os.environ.get("TESSERACT_CMD")
    default_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if configured:
        pytesseract.pytesseract.tesseract_cmd = configured
    elif os.path.exists(default_path):
        pytesseract.pytesseract.tesseract_cmd = default_path


def _run_tesseract(image: np.ndarray, config: str) -> tuple[str, float]:
    try:
        import pytesseract

        _configure_tesseract(pytesseract)
        data = pytesseract.image_to_data(
            image,
            output_type=pytesseract.Output.DICT,
            config=config,
        )
    except Exception:
        return "", 0.0

    words: list[str] = []
    confidences: list[float] = []
    for text, confidence in zip(data.get("text", []), data.get("conf", [])):
        cleaned = str(text or "").strip()
        try:
            numeric_confidence = float(confidence)
        except (TypeError, ValueError):
            numeric_confidence = -1
        if cleaned and numeric_confidence >= 0:
            words.append(cleaned)
            confidences.append(numeric_confidence / 100)

    return " ".join(words).strip(), (sum(confidences) / len(confidences) if confidences else 0.0)


def read_amount(image: np.ndarray) -> tuple[float, float, str]:
    processed = preprocess_for_text(image)
    config = "--psm 7 -c tessedit_char_whitelist=0123456789.,KMB"
    text, confidence = _run_tesseract(processed, config)
    return normalize_amount(text), confidence, text


def read_name(image: np.ndarray) -> tuple[str, float]:
    processed = preprocess_for_text(image)
    return _run_tesseract(processed, "--psm 7")


def read_text(image: np.ndarray, *, mode: str = "name") -> tuple[str, float]:
    if mode == "amount":
        amount, confidence, raw = read_amount(image)
        return (raw or str(amount)), confidence
    return read_name(image)


def read_card(image: np.ndarray) -> dict[str, object]:
    if image.size == 0:
        return {"hidden": False, "visible": False, "confidence": 0.0}

    channels = image[:, :, :3] if image.ndim == 3 else np.stack([image, image, image], axis=2)
    blue = float(np.mean(channels[:, :, 0]))
    green = float(np.mean(channels[:, :, 1]))
    red = float(np.mean(channels[:, :, 2]))
    brightness = (blue + green + red) / 3

    # Temporary card-back detector. Real visible-card recognition belongs in template matching.
    if blue > red * 1.12 and blue > green * 1.05 and brightness > 35:
        return {"hidden": True, "display": "X", "visible": False, "confidence": 0.78}

    return {"hidden": False, "visible": False, "confidence": 0.0}
