from __future__ import annotations

import re
from functools import lru_cache

import numpy as np

from .ocr import _configure_tesseract, normalize_amount


FAST_AMOUNT_MIN_CONFIDENCE = 0.74


def read_amount_fast(image: np.ndarray) -> tuple[float, float, str]:
    mask = _best_text_mask(image)
    if mask is None:
        return 0.0, 0.0, ""
    mask = _remove_amount_noise(mask)

    chars = _segment_chars(mask)
    if not chars:
        return 0.0, 0.0, ""

    raw_parts: list[str] = []
    confidences: list[float] = []
    for char_mask in chars:
        value, confidence = _match_char(char_mask)
        if not value:
            continue
        raw_parts.append(value)
        confidences.append(confidence)

    raw = _sanitize_amount_text("".join(raw_parts))
    if not raw:
        return 0.0, 0.0, ""

    confidence = float(sum(confidences) / len(confidences)) if confidences else 0.0
    amount = normalize_amount(raw)
    if amount <= 0 or confidence < FAST_AMOUNT_MIN_CONFIDENCE:
        return amount, min(confidence, 0.69), raw
    return amount, min(0.96, confidence), raw


def amount_text_signal(image: np.ndarray) -> float:
    mask = _best_text_mask(image)
    if mask is None or image.size == 0:
        return 0.0
    mask = _remove_amount_noise(mask)
    return float((mask > 0).sum() / max(1, image.shape[0] * image.shape[1]))


def read_amount_tight_ocr(
    image: np.ndarray,
    *,
    squash_bb_suffix: bool = False,
    quick: bool = False,
) -> tuple[float, float, str]:
    import cv2

    mask = _best_text_mask(image)
    if mask is None:
        return 0.0, 0.0, ""
    mask = _remove_amount_noise(mask)
    rows, cols = np.where(mask > 0)
    if len(cols) == 0:
        return 0.0, 0.0, ""
    left = max(0, int(cols.min()) - 3)
    top = max(0, int(rows.min()) - 3)
    right = min(mask.shape[1], int(cols.max()) + 4)
    bottom = min(mask.shape[0], int(rows.max()) + 4)
    tight = mask[top:bottom, left:right]
    if tight.size == 0:
        return 0.0, 0.0, ""
    has_decimal_marker = _has_decimal_marker(tight)
    try:
        import pytesseract

        _configure_tesseract(pytesseract)
    except Exception:
        return 0.0, 0.0, ""

    candidates: list[tuple[float, float, str]] = []
    variants = ((cv2.INTER_NEAREST, 7),) if quick else (
        (cv2.INTER_NEAREST, 7),
        (cv2.INTER_CUBIC, 7),
        (cv2.INTER_CUBIC, 8),
    )
    for interpolation, psm in variants:
        processed = cv2.resize(tight, None, fx=8, fy=8, interpolation=interpolation)
        raw = pytesseract.image_to_string(
            processed,
            config=f"--psm {psm} -c tessedit_char_whitelist=0123456789.,KMBBO",
        ).strip()
        if not raw:
            continue
        normalized_raw = _normalize_ocr_amount_raw(raw)
        if has_decimal_marker and re.fullmatch(r"\d{2,4}", normalized_raw or ""):
            normalized_raw = f"{normalized_raw[:-1]}.{normalized_raw[-1]}"
        amount = normalize_amount(normalized_raw)
        if squash_bb_suffix:
            amount = _squash_bb_noise(normalized_raw, amount)
        if amount > 0:
            candidates.append((amount, _tight_amount_score(normalized_raw, amount), normalized_raw))

    if not candidates:
        return 0.0, 0.0, ""
    best = max(candidates, key=lambda candidate: candidate[1] + _cluster_bonus(candidate[0], candidates))
    amount, score, raw = best
    confidence = max(0.55, min(0.90, score + _cluster_bonus(amount, candidates)))
    return amount, confidence, raw


def _best_text_mask(image: np.ndarray) -> np.ndarray | None:
    import cv2

    if image.size == 0 or image.ndim < 3:
        return None
    channels = image[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    masks = [
        (blue > 95) & (green > 95) & (red < 135) & ((blue - red) > 30) & ((green - red) > 30),
        (red > 115) & (green > 95) & (blue < 150) & ((red - blue) > 20),
        (red > 150) & (green > 150) & (blue > 150),
    ]
    best: np.ndarray | None = None
    best_pixels = 0
    for mask in masks:
        pixels = int(mask.sum())
        if pixels > best_pixels:
            best_pixels = pixels
            best = mask.astype(np.uint8) * 255
    if best is None or best_pixels < 4:
        return None
    kernel = np.ones((2, 2), np.uint8)
    return cv2.morphologyEx(best, cv2.MORPH_CLOSE, kernel, iterations=1)


def _remove_amount_noise(mask: np.ndarray) -> np.ndarray:
    import cv2

    if mask.size == 0:
        return mask
    cleaned = mask.copy()
    contours, _hierarchy = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    height, width = cleaned.shape[:2]
    for contour in contours:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        if box_height <= max(2, int(height * 0.12)) and box_width >= width * 0.35:
            cleaned[y:y + box_height, x:x + box_width] = 0
    return cleaned


def _normalize_ocr_amount_raw(raw: str) -> str:
    value = str(raw or "").strip().upper().replace(" ", "")
    value = value.replace("O", "0").replace("I", "1").replace("L", "1")
    value = re.sub(r"(?<=\d)B[856S]$", "BB", value)
    value = re.sub(r"(?<=\d)[856S]B$", "BB", value)
    return value


def _segment_chars(mask: np.ndarray) -> list[np.ndarray]:
    import cv2

    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    height, width = mask.shape[:2]
    boxes: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if h < max(3, height * 0.18) or w < 1:
            continue
        if w * h < 4:
            continue
        boxes.append((x, y, w, h))
    if not boxes:
        return []

    boxes = _merge_close_boxes(sorted(boxes), max_gap=0)
    chars: list[np.ndarray] = []
    for x, y, w, h in boxes[:12]:
        pad = 1
        left = max(0, x - pad)
        top = max(0, y - pad)
        right = min(width, x + w + pad)
        bottom = min(height, y + h + pad)
        chars.append(mask[top:bottom, left:right])
    return chars


def _merge_close_boxes(boxes: list[tuple[int, int, int, int]], *, max_gap: int) -> list[tuple[int, int, int, int]]:
    if not boxes:
        return []
    merged: list[tuple[int, int, int, int]] = []
    for x, y, width, height in boxes:
        if not merged:
            merged.append((x, y, width, height))
            continue
        prev_x, prev_y, prev_w, prev_h = merged[-1]
        prev_right = prev_x + prev_w
        vertical_overlap = min(prev_y + prev_h, y + height) - max(prev_y, y)
        overlap_ratio = vertical_overlap / max(1, min(prev_h, height))
        if x - prev_right <= max_gap and overlap_ratio > 0.35:
            left = min(prev_x, x)
            top = min(prev_y, y)
            right = max(prev_x + prev_w, x + width)
            bottom = max(prev_y + prev_h, y + height)
            merged[-1] = (left, top, right - left, bottom - top)
        else:
            merged.append((x, y, width, height))
    return merged


@lru_cache(maxsize=1)
def _char_templates() -> tuple[tuple[str, np.ndarray], ...]:
    import cv2

    glyphs = "0123456789.KMB"
    templates: list[tuple[str, np.ndarray]] = []
    for scale in (0.42, 0.50):
        for glyph in glyphs:
            canvas = np.zeros((34, 34), dtype=np.uint8)
            cv2.putText(canvas, glyph, (2, 24), cv2.FONT_HERSHEY_SIMPLEX, scale, 255, 1, cv2.LINE_AA)
            rows, cols = np.where(canvas > 0)
            if len(cols) == 0:
                continue
            templates.append((glyph, canvas[rows.min():rows.max() + 1, cols.min():cols.max() + 1]))
    return tuple(templates)


def _match_char(mask: np.ndarray) -> tuple[str, float]:
    import cv2

    templates = _char_templates()
    if not templates or mask.size == 0:
        return "", 0.0
    source = (mask > 0).astype(np.uint8)
    best_value = ""
    best_score = 0.0
    for value, template in templates:
        if source.shape[0] < 2 or source.shape[1] < 1:
            continue
        resized = cv2.resize(template, (source.shape[1], source.shape[0]), interpolation=cv2.INTER_NEAREST)
        target = resized > 0
        source_bool = source > 0
        intersection = np.logical_and(source_bool, target).sum()
        union = np.logical_or(source_bool, target).sum()
        score = float(intersection / union) if union else 0.0
        if score > best_score:
            best_value = value
            best_score = score
    return best_value, best_score


def _sanitize_amount_text(raw: str) -> str:
    value = raw.upper().replace(" ", "")
    value = value.replace("O", "0").replace("I", "1").replace("L", "1")
    value = re.sub(r"[^0-9.,KMB]", "", value)
    if value.endswith("B") and not value.endswith("BB"):
        value += "B"
    return value


def _squash_bb_noise(raw: str, amount: float) -> float:
    value = (raw or "").replace(" ", "").upper()
    if "," in value and "." not in value:
        value = re.sub(r"(\d+),(\d{1,2})(?=B*$)", r"\1.\2", value)
    else:
        value = value.replace(",", "")
    match = re.search(r"(\d+)\.(\d)(?:[568B]{1,3})$", value)
    if match:
        return float(f"{match.group(1)}.{match.group(2)}")
    if amount >= 1000 and re.fullmatch(r"\d{4,5}", value):
        digits = re.sub(r"\D+", "", value)
        if len(digits) >= 4:
            return float(f"{digits[:-1]}.{digits[-1]}")
    return amount


def _tight_amount_score(raw: str, amount: float) -> float:
    value = str(raw or "").upper()
    score = 0.52
    if "." in value or "," in value:
        score += 0.16
    if "B" in value:
        score += 0.08
    if 1.0 <= amount <= 999.9:
        score += 0.12
    elif amount > 999.9:
        score -= 0.34
    if 0 < amount < 2:
        score -= 0.08
    digits = re.sub(r"\D+", "", value)
    if len(digits) >= 5 and amount > 999.9:
        score -= 0.16
    decimal_match = re.search(r"[.,](\d+)", value)
    if decimal_match and len(decimal_match.group(1)) > 2:
        score -= 0.08
    return score


def _cluster_bonus(amount: float, candidates: list[tuple[float, float, str]]) -> float:
    tolerance = max(0.8, amount * 0.006)
    matches = sum(1 for other, _score, _raw in candidates if abs(float(other) - float(amount)) <= tolerance)
    return min(0.24, max(0, matches - 1) * 0.08)


def _has_decimal_marker(mask: np.ndarray) -> bool:
    import cv2

    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    height, width = mask.shape[:2]
    for contour in contours:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        if box_width <= max(3, width * 0.08) and box_height <= max(2, height * 0.25) and y > height * 0.45:
            return True
    return False
