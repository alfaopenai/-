from __future__ import annotations

import os
import re
from functools import lru_cache
from threading import Lock
from typing import Any

import numpy as np


_RAPIDOCR_LOCK = Lock()


def normalize_amount(raw: str | None) -> float:
    if not raw:
        return 0.0
    value = raw.strip()
    value = re.sub(r"(?i)(?<=\d)B[856S](?![A-Za-z0-9])", "BB", value)
    value = re.sub(r"(?i)(?<=\d)[856S]B(?![A-Za-z0-9])", "BB", value)
    numeric_tokens = re.findall(r"(?i)(?:\d|[Oo])[\dOoIl.,]*(?:\s*(?:BB|B|K|M))?", value)
    if numeric_tokens:
        value = numeric_tokens[-1]
    value = value.replace("O", "0").replace("o", "0").replace("I", "1").replace("l", "1")
    value = re.sub(r"(?i)(?<=\d)B[856S]$", "BB", value)
    value = re.sub(r"(?i)(?<=\d)[856S]B$", "BB", value)
    value_upper = value.upper()
    is_big_blind_value = "BB" in value_upper or bool(re.search(r"\d\s*B", value_upper))
    if is_big_blind_value and "," in value and "." not in value:
        value = re.sub(r"(\d+),(\d{1,2})(?=\s*B+\s*$)", r"\1.\2", value, flags=re.IGNORECASE)
    else:
        value = value.replace(",", "")
    if is_big_blind_value:
        value = re.sub(r"(?i)\s*B+\s*", "", value)
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


def read_name_detailed(image: np.ndarray, *, allow_slow_fallback: bool = True) -> dict[str, object]:
    import cv2

    if image.size == 0:
        return {
            "raw": "",
            "cleaned": "",
            "confidence": 0.0,
            "source": "tesseract",
            "rejectReason": "empty-crop",
        }
    candidates: list[tuple[str, float, str, str]] = []

    if image.ndim == 3 and image.shape[2] >= 3:
        channels = image[:, :, :3].astype(np.int16)
        blue = channels[:, :, 0]
        green = channels[:, :, 1]
        red = channels[:, :, 2]
        white = ((red > 145) & (green > 145) & (blue > 145)).astype(np.uint8) * 255
        cyan = ((blue > 90) & (green > 90) & (red < 145)).astype(np.uint8) * 255
        whitelist = "-c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_.-"
        masks = [(white, "white-mask")]
        if int((white > 0).sum()) < 4:
            masks.append((cyan, "cyan-mask"))
        for mask, mask_name in masks:
            if int((mask > 0).sum()) < 4:
                continue
            tight = _tight_mask(mask)
            if tight is None:
                continue
            variants = (
                cv2.resize(tight, None, fx=8, fy=8, interpolation=cv2.INTER_CUBIC),
                255 - cv2.resize(tight, None, fx=8, fy=8, interpolation=cv2.INTER_CUBIC),
            )
            for variant_index, variant in enumerate(variants):
                for psm in (7, 8):
                    raw = _run_tesseract_string(variant, f"--psm {psm} {whitelist}")
                    if raw:
                        candidates.append((raw, 0.72, "tesseract", f"{mask_name}:{variant_index}:psm-{psm}"))

    if not candidates:
        processed = preprocess_for_text(image)
        raw, confidence = _run_tesseract(processed, "--psm 7")
        if raw:
            candidates.append((raw, confidence, "tesseract", "psm-7"))

    if allow_slow_fallback and os.environ.get("GG_READER_NAME_RAPIDOCR", "1").lower() not in {"0", "false", "no"}:
        rapidocr_result = _read_name_rapidocr(image)
        if rapidocr_result:
            raw, confidence = rapidocr_result
            candidates.append((raw, confidence, "rapidocr", "rapidocr"))

    if allow_slow_fallback and os.environ.get("GG_READER_NAME_EASYOCR", "").lower() in {"1", "true", "yes"}:
        easyocr_result = _read_name_easyocr(image)
        if easyocr_result:
            raw, confidence = easyocr_result
            candidates.append((raw, confidence, "easyocr", "easyocr"))

    cleaned_candidates = [
        (_clean_ocr_name_candidate(text), confidence, text, source, variant)
        for text, confidence, source, variant in candidates
        if text and _clean_ocr_name_candidate(text)
    ]
    if not cleaned_candidates:
        return {
            "raw": max((text for text, _confidence, _source, _variant in candidates), key=len, default=""),
            "cleaned": "",
            "confidence": 0.0,
            "source": "tesseract",
            "rejectReason": "no-clean-name-candidate",
        }
    cleaned, confidence, raw, source, variant = max(
        cleaned_candidates,
        key=lambda item: (item[1], _name_quality_score(item[0]), len(item[0])),
    )
    if _looks_like_amount_text(cleaned):
        return {
            "raw": raw,
            "cleaned": "",
            "confidence": 0.0,
            "source": source,
            "variant": variant,
            "rejectReason": "amount-text-not-name",
        }
    if _looks_like_take_seat_text(cleaned):
        return {
            "raw": raw,
            "cleaned": "",
            "confidence": 0.0,
            "source": source,
            "variant": variant,
            "rejectReason": "take-seat-placeholder",
        }
    return {
        "raw": raw,
        "cleaned": cleaned,
        "confidence": float(confidence),
        "source": source,
        "variant": variant,
        "rejectReason": "" if cleaned and confidence > 0 else "low-confidence",
    }


def read_name(image: np.ndarray) -> tuple[str, float]:
    result = read_name_detailed(image)
    return str(result.get("cleaned") or ""), float(result.get("confidence") or 0.0)


def read_text(image: np.ndarray, *, mode: str = "name") -> tuple[str, float]:
    if mode == "amount":
        amount, confidence, raw = read_amount(image)
        return (raw or str(amount)), confidence
    return read_name(image)


def _tight_mask(mask: np.ndarray) -> np.ndarray | None:
    rows, cols = np.where(mask > 0)
    if len(cols) == 0:
        return None
    top = max(0, int(rows.min()) - 2)
    bottom = min(mask.shape[0], int(rows.max()) + 3)
    left = max(0, int(cols.min()) - 2)
    right = min(mask.shape[1], int(cols.max()) + 3)
    tight = mask[top:bottom, left:right]
    return tight if tight.size else None


def _clean_ocr_name_candidate(text: str) -> str:
    value = str(text or "").strip()
    value = value.replace("!", "I").replace("|", "I").replace("—", " ")
    value = re.sub(r"[^0-9A-Za-z\u0590-\u05ff_. -]+", " ", value)
    value = " ".join(value.split())
    value = value.strip(" -_{}[]()\\/")
    value = re.sub(r"([A-Za-z])O(?=\d)", r"\g<1>0", value)
    value = re.sub(r"lS$", "IS", value)
    value = re.sub(r"^a(?=[A-Z]{2}\d)", "", value)
    compact = re.sub(r"[^0-9a-z]+", "", value.lower())
    canonical = {
        "cedarkoi": "CedarKoi",
        "joeyis": "joeyIS",
        "joeyls": "joeyIS",
        "joey1s": "joeyIS",
    }.get(compact)
    if canonical:
        value = canonical
    return value


def _name_quality_score(value: str) -> float:
    if not value:
        return 0.0
    score = 0.0
    if re.search(r"[A-Za-z]", value):
        score += 0.35
    if re.search(r"\d", value):
        score += 0.12
    if 2 <= len(value) <= 18:
        score += 0.25
    if value.lower().startswith("gg seat"):
        score -= 0.75
    if _looks_like_amount_text(value):
        score -= 0.80
    if len(value.split()) > 3:
        score -= 0.18
    return score


def _looks_like_amount_text(value: str) -> bool:
    text = str(value or "").strip()
    return bool(re.fullmatch(r"(?i)\d+(?:[.,]\d+)?\s*B?B?", text))


def _looks_like_take_seat_text(value: str) -> bool:
    text = re.sub(r"[^a-z]+", "", str(value or "").lower())
    return text in {"takeseat", "cakeseat"} or text.endswith("takeseat") or text.endswith("cakeseat")


@lru_cache(maxsize=1)
def _easyocr_reader() -> object | None:
    try:
        import easyocr

        return easyocr.Reader(["en"], gpu=False, verbose=False)
    except Exception:
        return None


def _read_name_easyocr(image: np.ndarray) -> tuple[str, float] | None:
    reader = _easyocr_reader()
    if reader is None:
        return None
    try:
        results = reader.readtext(image[:, :, :3] if image.ndim == 3 else image, detail=1, paragraph=False)
    except Exception:
        return None
    candidates: list[tuple[str, float]] = []
    for item in results:
        if len(item) >= 3:
            candidates.append((str(item[1] or ""), float(item[2] or 0.0)))
    return max(candidates, key=lambda item: item[1], default=None)


@lru_cache(maxsize=1)
def _rapidocr_reader() -> object | None:
    try:
        from rapidocr_onnxruntime import RapidOCR

        return RapidOCR()
    except Exception:
        return None


def _read_name_rapidocr(image: np.ndarray) -> tuple[str, float] | None:
    reader = _rapidocr_reader()
    if reader is None:
        return None
    try:
        with _RAPIDOCR_LOCK:
            result, _elapsed = reader(image[:, :, :3] if image.ndim == 3 else image)
    except Exception:
        return None
    candidates: list[tuple[str, float]] = []
    for item in result or []:
        if len(item) >= 3:
            try:
                confidence = float(item[2] or 0.0)
            except Exception:
                confidence = 0.0
            candidates.append((str(item[1] or ""), confidence))
    return max(candidates, key=lambda item: item[1], default=None)


def read_card(image: np.ndarray) -> dict[str, object]:
    if image.size == 0:
        return {"hidden": False, "visible": False, "confidence": 0.0}

    channels = image[:, :, :3] if image.ndim == 3 else np.stack([image, image, image], axis=2)
    blue = float(np.mean(channels[:, :, 0]))
    green = float(np.mean(channels[:, :, 1]))
    red = float(np.mean(channels[:, :, 2]))
    brightness = (blue + green + red) / 3
    bright_ratio = _bright_ratio(channels)
    white_ratio = _white_card_ratio(channels)

    if white_ratio < 0.35 and blue > red * 1.12 and blue > green * 1.05 and brightness > 35:
        return {"hidden": True, "display": "X", "visible": False, "confidence": 0.78}
    if bright_ratio < 0.12:
        return {"hidden": False, "visible": False, "confidence": 0.0}
    if _looks_like_card_back(channels):
        return {"hidden": True, "display": "X", "visible": False, "confidence": 0.82}
    if bright_ratio < 0.30:
        return {"hidden": False, "visible": False, "confidence": 0.0}
    if white_ratio < 0.62:
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
    if _white_card_ratio(channels) > 0.45:
        return False
    edges = cv2.Canny(gray, 80, 160)
    edge_ratio = float((edges > 0).mean())
    color_std = float(np.std(channels[:, :, :3]))
    return edge_ratio > 0.08 or color_std < 42


def _white_card_ratio(channels: np.ndarray) -> float:
    if channels.size == 0:
        return 0.0
    white = (channels[:, :, 0] > 210) & (channels[:, :, 1] > 210) & (channels[:, :, 2] > 210)
    return float(white.mean())


def _bright_ratio(channels: np.ndarray) -> float:
    import cv2

    if channels.size == 0:
        return 0.0
    gray = cv2.cvtColor(channels, cv2.COLOR_BGR2GRAY)
    return float((gray > 135).mean())
