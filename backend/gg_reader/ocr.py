from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any

import numpy as np


def normalize_amount(raw: str | None) -> float:
    if not raw:
        return 0.0
    value = raw.strip().replace(",", "")
    numeric_tokens = re.findall(r"(?i)(?:\d|[Oo])[\dOoIl.,]*(?:\s*(?:BB|B|K|M))?", value)
    if numeric_tokens:
        value = numeric_tokens[-1]
    value_upper = value.upper()
    is_big_blind_value = "BB" in value_upper or bool(re.search(r"\d\s*B", value_upper))
    if is_big_blind_value:
        value = re.sub(r"(?i)\s*B+\s*", "", value)
    value = value.replace("O", "0").replace("o", "0").replace("I", "1").replace("l", "1")
    if is_big_blind_value and value.count(".") > 1:
        parts = [part for part in value.split(".") if part]
        if len(parts) >= 2:
            value = "".join(parts[:-1]) + "." + parts[-1]
    if is_big_blind_value and "." not in value:
        digits = re.sub(r"\D+", "", value)
        if len(digits) >= 4:
            value = f"{digits[:-1]}.{digits[-1]}"
        elif digits:
            value = digits
    if not is_big_blind_value and re.search(r"\.\d88$", value):
        value = value[:-2]
    multiplier = 1.0
    if not is_big_blind_value and value[-1:].upper() == "K":
        multiplier = 1_000
        value = value[:-1]
    elif not is_big_blind_value and value[-1:].upper() == "M":
        multiplier = 1_000_000
        value = value[:-1]
    elif not is_big_blind_value and value[-1:].upper() == "B":
        if "." in value:
            value = value[:-1]
        else:
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


def _run_tesseract_string(image: np.ndarray, config: str) -> str:
    try:
        import pytesseract

        _configure_tesseract(pytesseract)
        return pytesseract.image_to_string(image, config=config).strip()
    except Exception:
        return ""


def _text_confidence(raw: str, confidence: float) -> float:
    if confidence > 0:
        return confidence
    return 0.82 if re.search(r"\d", raw or "") else 0.0


def _colored_text_mask(image: np.ndarray, color: str) -> np.ndarray | None:
    import cv2

    if image.size == 0 or image.ndim < 3:
        return None
    channels = image[:, :, :3]
    blue = channels[:, :, 0].astype(np.int16)
    green = channels[:, :, 1].astype(np.int16)
    red = channels[:, :, 2].astype(np.int16)
    if color == "cyan":
        mask = (blue > 95) & (green > 95) & (red < 125) & ((blue - red) > 35) & ((green - red) > 35)
    elif color == "yellow":
        mask = (red > 120) & (green > 105) & (blue < 130)
    else:
        mask = (red > 160) & (green > 160) & (blue > 160)
    if int(mask.sum()) < 4:
        return None
    mask_image = (mask.astype(np.uint8) * 255)
    mask_image = cv2.dilate(mask_image, np.ones((2, 2), np.uint8), iterations=1)
    return 255 - cv2.resize(mask_image, None, fx=5, fy=5, interpolation=cv2.INTER_NEAREST)


def read_amount(image: np.ndarray) -> tuple[float, float, str]:
    config = "--psm 7 -c tessedit_char_whitelist=0123456789.,KMBBO"
    candidates: list[tuple[float, float, str]] = []
    for processed in (
        _colored_text_mask(image, "cyan"),
        _colored_text_mask(image, "yellow"),
        _colored_text_mask(image, "white"),
        preprocess_for_text(image),
    ):
        if processed is None:
            continue
        text = _run_tesseract_string(processed, config)
        amount = normalize_amount(text)
        if not re.search(r"(?i)[KMB]", text or ""):
            if amount >= 10000 and amount < 1000000:
                amount = round(amount / 1000, 3)
            elif amount >= 1000 and amount < 10000:
                amount = round(amount / 10, 2)
        confidence = _text_confidence(text, 0) if amount > 0 else 0.0
        if amount > 0:
            candidates.append((amount, confidence, text))
    if not candidates:
        return 0.0, 0.0, ""
    return max(candidates, key=lambda candidate: (candidate[1], candidate[0]))


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
    bright_ratio = _bright_ratio(channels)

    if blue > red * 1.12 and blue > green * 1.05 and brightness > 35:
        return {"hidden": True, "display": "X", "visible": False, "confidence": 0.78}
    if bright_ratio < 0.12:
        return {"hidden": False, "visible": False, "confidence": 0.0}
    if _looks_like_card_back(channels):
        return {"hidden": True, "display": "X", "visible": False, "confidence": 0.82}
    if bright_ratio < 0.30:
        return {"hidden": False, "visible": False, "confidence": 0.0}

    visible = _read_visible_card(image)
    if visible:
        return visible

    return {"hidden": False, "visible": False, "confidence": 0.0}


def _read_visible_card(image: np.ndarray) -> dict[str, object] | None:
    rank = _recognize_rank(image)
    if not rank:
        return None
    suit = _recognize_suit(image)
    if not suit:
        return None
    confidence = min(float(rank["confidence"]), float(suit["confidence"]))
    if confidence < 0.72:
        return None
    return {
        "rank": rank["rank"],
        "suit": suit["suit"],
        "visible": True,
        "hidden": False,
        "confidence": confidence,
    }


def _card_symbol_mask(image: np.ndarray) -> np.ndarray:
    import cv2

    channels = image[:, :, :3] if image.ndim == 3 else np.stack([image, image, image], axis=2)
    rgb = cv2.cvtColor(channels, cv2.COLOR_BGR2RGB)
    distance_from_white = np.max(255 - rgb, axis=2)
    return (distance_from_white > 60).astype(np.uint8) * 255


def _component_mask(mask: np.ndarray, *, rank: bool) -> tuple[np.ndarray, tuple[int, int, int, int]] | None:
    import cv2

    height, width = mask.shape[:2]
    search = mask[: max(1, int(height * 0.65)), : max(1, int(width * 0.55))]
    component_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(search, 8)
    candidates: list[tuple[int, int, int, int, int, int]] = []
    for component_index in range(1, component_count):
        x, y, component_width, component_height, area = [int(value) for value in stats[component_index]]
        if area < max(10, int(width * height * 0.004)):
            continue
        center_y = y + component_height / 2
        if rank and center_y > height * 0.33:
            continue
        if not rank and center_y < height * 0.30:
            continue
        candidates.append((x, y, component_width, component_height, area, component_index))
    if not candidates:
        return None
    x, y, component_width, component_height, _area, component_index = max(candidates, key=lambda item: item[4])
    tight = (labels[y:y + component_height, x:x + component_width] == component_index).astype(np.uint8) * 255
    return tight, (x, y, component_width, component_height)


@lru_cache(maxsize=1)
def _rank_templates() -> tuple[tuple[str, np.ndarray], ...]:
    from PIL import Image, ImageDraw, ImageFont

    ranks = ("A", "K", "Q", "J", "10", "9", "8", "7", "6", "5", "4", "3", "2")
    font_paths = (
        r"C:\Windows\Fonts\bahnschrift.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\tahomabd.ttf",
    )
    templates: list[tuple[str, np.ndarray]] = []
    for font_path in font_paths:
        if not os.path.exists(font_path):
            continue
        for size in range(18, 36):
            font = ImageFont.truetype(font_path, size)
            for rank in ranks:
                canvas = Image.new("L", (72, 72), 0)
                draw = ImageDraw.Draw(canvas)
                draw.text((8, 8), rank, font=font, fill=255)
                array = np.array(canvas)
                rows, cols = np.where(array > 0)
                if len(cols) == 0:
                    continue
                templates.append((rank, array[rows.min():rows.max() + 1, cols.min():cols.max() + 1]))
    return tuple(templates)


def _match_template(component: np.ndarray, templates: tuple[tuple[str, np.ndarray], ...]) -> tuple[str, float]:
    import cv2

    best_value = ""
    best_score = 0.0
    for value, template in templates:
        if component.shape[0] < 4 or component.shape[1] < 4:
            continue
        resized = cv2.resize(template, (component.shape[1], component.shape[0]), interpolation=cv2.INTER_NEAREST)
        intersection = np.logical_and(component > 0, resized > 0).sum()
        union = np.logical_or(component > 0, resized > 0).sum()
        score = float(intersection / union) if union else 0.0
        if score > best_score:
            best_value = value
            best_score = score
    return best_value, best_score


def _recognize_rank(image: np.ndarray) -> dict[str, object] | None:
    mask = _card_symbol_mask(image)
    component = _component_mask(mask, rank=True)
    if not component:
        return None
    component_mask, _box = component
    rank, score = _match_template(component_mask, _rank_templates())
    if not rank or score < 0.55:
        return None
    return {"rank": rank, "confidence": min(0.98, max(0.72, score))}


def _recognize_suit(image: np.ndarray) -> dict[str, object] | None:
    import cv2

    channels = image[:, :, :3] if image.ndim == 3 else np.stack([image, image, image], axis=2)
    mask = _card_symbol_mask(image)
    component = _component_mask(mask, rank=False)
    if not component:
        return None
    component_mask, (x, y, width, height) = component
    roi = channels[y:y + height, x:x + width]
    if roi.size == 0:
        return None
    blue, green, red = [float(np.mean(roi[:, :, index])) for index in range(3)]
    density = float((component_mask > 0).sum() / max(1, width * height))

    if red > blue + 20 and red > green - 5:
        suit = "H" if density > 0.58 else "D"
        confidence = 0.84 if suit == "H" else 0.88
    else:
        rows = np.where(component_mask > 0)[0]
        top_half = component_mask[: max(1, component_mask.shape[0] // 2)]
        bottom_half = component_mask[max(1, component_mask.shape[0] // 2):]
        top_density = float((top_half > 0).sum() / max(1, top_half.size))
        bottom_density = float((bottom_half > 0).sum() / max(1, bottom_half.size))
        suit = "C" if top_density > bottom_density * 1.15 and rows.size else "S"
        confidence = 0.76

    return {"suit": suit, "confidence": confidence}


def _looks_like_card_back(channels: np.ndarray) -> bool:
    import cv2

    if channels.size == 0:
        return False
    gray = cv2.cvtColor(channels, cv2.COLOR_BGR2GRAY)
    bright_ratio = float((gray > 135).mean())
    if bright_ratio < 0.35:
        return False
    edges = cv2.Canny(gray, 80, 160)
    edge_ratio = float((edges > 0).mean())
    color_std = float(np.std(channels[:, :, :3]))
    return edge_ratio > 0.08 or color_std < 42


def _bright_ratio(channels: np.ndarray) -> float:
    import cv2

    if channels.size == 0:
        return 0.0
    gray = cv2.cvtColor(channels, cv2.COLOR_BGR2GRAY)
    return float((gray > 135).mean())
