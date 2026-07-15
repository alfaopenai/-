from __future__ import annotations

import re
from functools import lru_cache

import numpy as np

from .ocr import TESSERACT_TIMEOUT_SECONDS, _RAPIDOCR_LOCK, _configure_tesseract, _rapidocr_reader, normalize_amount


FAST_AMOUNT_MIN_CONFIDENCE = 0.74


def read_amount_fast(image: np.ndarray) -> tuple[float, float, str]:
    candidates: list[tuple[float, float, str]] = []
    zero_candidates: list[tuple[float, float, str]] = []
    for mask in _text_masks(image):
        mask = _remove_amount_noise(mask)
        chars = _segment_chars(mask)
        if not chars:
            continue

        raw_parts: list[str] = []
        raw_masks: list[np.ndarray] = []
        confidences: list[float] = []
        for char_mask in chars:
            value, confidence = _match_char(char_mask)
            if not value:
                continue
            # At the smallest white wager size an 8 can rank just below the 6
            # template.  Both glyphs sometimes acquire two contours after
            # antialiasing, so count alone is not enough: a real 8 also has a
            # substantial upper counter.  This recovers 108.3BB without
            # changing real stacks such as 168.5, 126.3, and 261.7.
            if value == "6" and _has_substantial_upper_counter(char_mask):
                value = "8"
            raw_parts.append(value)
            raw_masks.append(char_mask)
            if value != ".":
                confidences.append(confidence)

        # A real 8 and the condensed ``B`` suffix both have two enclosed
        # counters and can share the same best font template.  Position makes
        # the ambiguity deterministic: the final two glyphs are the checksum
        # suffix; an earlier B-shaped two-counter glyph is the digit 8.
        suffix_start = max(0, len(raw_parts) - 2)
        for index in range(suffix_start):
            if raw_parts[index] == "B" and _glyph_hole_count(raw_masks[index]) >= 2:
                raw_parts[index] = "8"

        raw = _sanitize_amount_text("".join(raw_parts))
        if not raw or not re.search(r"\d", raw):
            continue
        confidence = float(sum(confidences) / len(confidences)) if confidences else 0.0
        # Every numeric ClubGG table label ends in BB.  Requiring that visual
        # checksum prevents names/action labels inside a broad ROI from being
        # accepted as money, while still returning a low-confidence candidate
        # for the bounded OCR fallback on unusual skins.
        if re.search(r"BB$", raw):
            confidence += 0.10
        elif re.search(r"B$", raw):
            confidence += 0.04
        else:
            confidence = min(confidence, 0.69)
        if "." in raw:
            confidence += 0.025
        amount = normalize_amount(raw)
        if amount <= 0:
            # A rendered ``0 BB`` is positive evidence for an all-in stack, not
            # an empty OCR result.  Preserve its glyph confidence/raw checksum;
            # the caller decides whether zero is meaningful for that field.
            if re.fullmatch(r"0(?:[.]0+)?BB?", raw):
                zero_candidates.append((0.0, max(0.0, min(0.97, confidence)), raw))
            continue
        if amount >= 1_000:
            confidence -= 0.18
        candidates.append((amount, max(0.0, min(0.97, confidence)), raw))

    if not candidates:
        return max(zero_candidates, key=lambda item: item[1], default=(0.0, 0.0, ""))
    amount, confidence, raw = max(
        candidates,
        key=lambda item: (
            item[1] + (0.08 if re.search(r"BB$", item[2]) else 0.0),
            -abs(item[0] - 100.0),
        ),
    )
    if confidence < FAST_AMOUNT_MIN_CONFIDENCE:
        return amount, min(confidence, 0.69), raw
    return amount, confidence, raw


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
        try:
            raw = pytesseract.image_to_string(
                processed,
                config=f"--psm {psm} -c tessedit_char_whitelist=0123456789.,KMBBO",
                timeout=TESSERACT_TIMEOUT_SECONDS,
            ).strip()
        except Exception:
            continue
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


def read_amount_rapidocr(image: np.ndarray) -> tuple[float, float, str]:
    """Read a short amount line with RapidOCR's recognizer only.

    The full RapidOCR detector is too slow for live table polling. Stack/bet
    ROIs are already tightly cropped, so feeding the crop directly to the text
    recognizer is both faster and much more reliable for ClubGG's cyan BB font.
    """
    if image.size == 0 or image.ndim < 2:
        return 0.0, 0.0, ""
    reader = _rapidocr_reader()
    recognizer = getattr(reader, "text_recognizer", None) if reader is not None else None
    if recognizer is None:
        return 0.0, 0.0, ""
    try:
        import cv2

        source = image[:, :, :3] if image.ndim == 3 else np.stack([image, image, image], axis=2)
        variants = [
            cv2.resize(source, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC),
            cv2.resize(source, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST),
        ]
        with _RAPIDOCR_LOCK:
            batch_results, _elapsed = recognizer(variants)
    except Exception:
        return 0.0, 0.0, ""
    candidates: list[tuple[float, float, str]] = []
    for text, confidence in batch_results or []:
        try:
            score = float(confidence or 0.0)
        except Exception:
            score = 0.0
        original_raw = str(text or "")
        if _looks_like_overlay_text(original_raw):
            continue
        raw = _normalize_ocr_amount_raw(original_raw)
        amount = _squash_bb_noise(raw, normalize_amount(raw))
        if amount > 0:
            candidates.append((amount, min(0.93, max(0.0, score)), raw))
    return max(candidates, key=_rapid_amount_candidate_score, default=(0.0, 0.0, ""))


def _rapid_amount_candidate_score(candidate: tuple[float, float, str]) -> float:
    amount, confidence, raw = candidate
    text = str(raw or "")
    score = float(confidence or 0.0)
    if "." in text or "," in text:
        score += 0.04
    if len(re.sub(r"\D+", "", text)) >= 2:
        score += 0.02
    if 1.0 <= float(amount or 0.0) < 700:
        score += 0.02
    return score


def _best_text_mask(image: np.ndarray) -> np.ndarray | None:
    masks = _text_masks(image)
    return max(masks, key=lambda mask: int((mask > 0).sum()), default=None)


def _text_masks(image: np.ndarray) -> list[np.ndarray]:
    """Return separate color masks without joining neighboring glyphs.

    The old 2x2 close operation connected digits at native ClubGG sizes
    (for example, ``45`` became one contour).  That made the supposedly fast
    path reject virtually every stack and pushed all work into serialized
    RapidOCR jobs.  Keeping colors separate and glyphs disconnected makes the
    local template reader both deterministic and sub-millisecond after warmup.
    """

    if image.size == 0 or image.ndim < 3:
        return []
    channels = image[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    raw_masks = (
        (blue > 88) & (green > 88) & (red < 150) & ((blue - red) > 20) & ((green - red) > 20),
        (red > 112) & (green > 92) & (blue < 155) & ((red - blue) > 18),
        (red > 145) & (green > 145) & (blue > 145),
    )
    return [mask.astype(np.uint8) * 255 for mask in raw_masks if int(mask.sum()) >= 4]


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
    all_boxes: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        # At the native 850x630 ClubGG size the decimal point in a blind such
        # as ``0.5BB`` is literally one illuminated pixel.  Keep that pixel;
        # the later baseline/size checks are strict enough to discard isolated
        # noise that is not positioned like a decimal marker.
        if w < 1 or h < 1:
            continue
        all_boxes.append((x, y, w, h))
    expanded_boxes: list[tuple[int, int, int, int, bool]] = []
    for x, y, w, h in all_boxes:
        component = mask[y:y + h, x:x + w]
        decimal_split = _attached_decimal_split(component)
        if decimal_split is not None:
            glyph_width = decimal_split
            expanded_boxes.append((x, y, glyph_width, h, False))
            expanded_boxes.append((x + glyph_width, y, w - glyph_width, h, True))
            continue
        # At native ClubGG resolution adjacent glyphs can touch by one
        # antialiased pixel ("44", "04", and the tiny "BB" suffix are common).
        # Their combined contour is much wider than any single condensed glyph.
        if h >= 4 and w / max(1, h) >= 1.15:
            parts = max(2, min(3, int(round(w / max(1.0, h * 0.70)))))
            for part in range(parts):
                left = int(round(part * w / parts))
                right = int(round((part + 1) * w / parts))
                if right > left:
                    expanded_boxes.append((x + left, y, right - left, h, False))
            continue
        expanded_boxes.append((x, y, w, h, False))

    glyph_height_floor = max(4, height * 0.14)
    main_boxes = [
        box for box in expanded_boxes
        if not box[4] and box[3] >= glyph_height_floor and box[2] * box[3] >= 4
    ]
    if not main_boxes:
        return []

    line_bottom = float(np.median([box[1] + box[3] for box in main_boxes]))
    initial_median_height = float(np.median([box[3] for box in main_boxes]))
    main_boxes = [
        box for box in main_boxes
        if abs((box[1] + box[3]) - line_bottom) <= max(3.0, initial_median_height * 0.60)
    ]
    if not main_boxes:
        return []
    median_height = float(np.median([box[3] for box in main_boxes]))
    line_top = float(np.median([box[1] for box in main_boxes]))
    boxes: list[tuple[int, int, int, int, bool]] = []
    for x, y, w, h, forced_decimal in expanded_boxes:
        is_decimal = bool(forced_decimal or (
            h <= max(3.0, median_height * 0.38)
            and w <= max(4.0, median_height * 0.42)
            and y >= line_top + median_height * 0.55
        ))
        is_glyph = bool(
            h >= glyph_height_floor
            and w * h >= 4
            and abs((y + h) - line_bottom) <= max(3.0, median_height * 0.60)
        )
        if is_decimal or is_glyph:
            boxes.append((x, y, w, h, is_decimal))

    chars: list[np.ndarray] = []
    for x, y, w, h, is_decimal in sorted(boxes, key=lambda item: item[0])[:12]:
        if is_decimal:
            chars.append(np.full((1, 1), 255, dtype=np.uint8))
            continue
        pad = 1
        left = max(0, x - pad)
        top = max(0, y - pad)
        right = min(width, x + w + pad)
        bottom = min(height, y + h + pad)
        chars.append(mask[top:bottom, left:right])
    return chars


def _attached_decimal_split(component: np.ndarray) -> int | None:
    """Find a decimal dot joined to a digit's baseline by antialiasing."""

    if component.size == 0:
        return None
    source = component > 0
    height, width = source.shape[:2]
    if height < 6 or not (0.86 <= width / max(1, height) <= 1.18):
        return None
    tail_start = width
    for column in range(width - 1, -1, -1):
        rows = np.flatnonzero(source[:, column])
        if not len(rows):
            if tail_start < width:
                tail_start = column
            continue
        if int(rows.min()) >= int(round(height * 0.64)):
            tail_start = column
            continue
        break
    tail_width = width - tail_start
    if 2 <= tail_width <= max(4, int(round(height * 0.45))) and tail_start >= max(4, int(height * 0.45)):
        return tail_start
    return None


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
def _char_templates() -> tuple[tuple[str, ...], np.ndarray, np.ndarray]:
    import os

    from PIL import Image, ImageDraw, ImageFont

    glyphs = "0123456789B"
    font_paths = (
        r"C:\Windows\Fonts\bahnschrift.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\tahomabd.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\calibrib.ttf",
        r"C:\Windows\Fonts\verdanab.ttf",
    )
    labels: list[str] = []
    masks: list[np.ndarray] = []
    aspects: list[float] = []
    seen: set[tuple[str, bytes]] = set()
    for font_path in font_paths:
        if not os.path.exists(font_path):
            continue
        for size in (20, 24, 28, 32):
            font = ImageFont.truetype(font_path, size)
            for glyph in glyphs:
                canvas = Image.new("L", (64, 64), 0)
                ImageDraw.Draw(canvas).text((4, 3), glyph, font=font, fill=255)
                array = np.asarray(canvas)
                rows, cols = np.where(array > 80)
                if len(cols) == 0:
                    continue
                tight = (array[rows.min(): rows.max() + 1, cols.min(): cols.max() + 1] > 80).astype(np.uint8)
                normalized = _normalize_glyph(tight)
                dedupe_key = (glyph, normalized.tobytes())
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                labels.append(glyph)
                masks.append(normalized.astype(bool))
                aspects.append(float(tight.shape[1] / max(1, tight.shape[0])))
    if not masks:
        return (), np.zeros((0, 32, 24), dtype=bool), np.zeros((0,), dtype=np.float32)
    return tuple(labels), np.stack(masks), np.asarray(aspects, dtype=np.float32)


def _normalize_glyph(mask: np.ndarray, *, target_height: int = 32, target_width: int = 24) -> np.ndarray:
    import cv2

    source = (mask > 0).astype(np.uint8)
    rows, cols = np.where(source > 0)
    if not len(cols):
        return np.zeros((target_height, target_width), dtype=np.uint8)
    source = source[rows.min(): rows.max() + 1, cols.min(): cols.max() + 1]
    scale = min((target_height - 4) / max(1, source.shape[0]), (target_width - 4) / max(1, source.shape[1]))
    resized_width = max(1, int(round(source.shape[1] * scale)))
    resized_height = max(1, int(round(source.shape[0] * scale)))
    resized = cv2.resize(source, (resized_width, resized_height), interpolation=cv2.INTER_NEAREST)
    output = np.zeros((target_height, target_width), dtype=np.uint8)
    left = (target_width - resized_width) // 2
    top = (target_height - resized_height) // 2
    output[top: top + resized_height, left: left + resized_width] = resized
    return output


def _match_char(mask: np.ndarray) -> tuple[str, float]:
    if mask.size == 0:
        return "", 0.0
    if mask.shape == (1, 1):
        return ".", 0.96
    source = (mask > 0).astype(np.uint8)
    rows, cols = np.where(source > 0)
    if not len(cols):
        return "", 0.0
    tight = source[rows.min(): rows.max() + 1, cols.min(): cols.max() + 1]
    source_aspect = float(tight.shape[1] / max(1, tight.shape[0]))
    normalized = _normalize_glyph(tight).astype(bool)
    labels, templates, aspects = _char_templates()
    if not labels or templates.size == 0:
        return "", 0.0
    intersection = np.logical_and(templates, normalized).sum(axis=(1, 2)).astype(np.float32)
    union = np.logical_or(templates, normalized).sum(axis=(1, 2)).astype(np.float32)
    scores = np.divide(intersection, np.maximum(1.0, union))
    scores -= np.minimum(0.30, np.abs(aspects - source_aspect) * 0.12)
    best_index = int(np.argmax(scores))
    best_label = labels[best_index]
    hole_count = _glyph_hole_count(tight)

    def best_index_for(label: str) -> int | None:
        indexes = [index for index, candidate in enumerate(labels) if candidate == label]
        return max(indexes, key=lambda index: float(scores[index])) if indexes else None

    # 8 has two enclosed counters while 0 has one. This invariant is more
    # reliable than a one-pixel outer-edge difference at tiny bet/stack sizes.
    if best_label == "0" and hole_count >= 2:
        eight_index = best_index_for("8")
        if eight_index is not None:
            best_index = int(eight_index)
            best_label = "8"

    # A tiny 3 occasionally has no surviving counter and lands only a few
    # thousandths above the 8 template.  A true 8 retains enclosed counters in
    # this cyan ClubGG font, so topology safely breaks that near tie.
    if best_label == "8" and hole_count == 0:
        three_index = best_index_for("3")
        if three_index is not None and float(scores[three_index]) >= float(scores[best_index]) - 0.03:
            best_index = int(three_index)
            best_label = "3"

    # 4 and 9 can each contain one counter.  The rendered 4 has a full-width
    # crossbar, whereas 9 does not; use that invariant only for a close
    # template tie so normal high-confidence fours remain unchanged.
    if best_label == "4" and hole_count == 1:
        nine_index = best_index_for("9")
        widest_row = float((tight > 0).mean(axis=1).max()) if tight.size else 1.0
        if (
            nine_index is not None
            and widest_row < 0.85
            and float(scores[nine_index]) >= float(scores[best_index]) - 0.03
        ):
            best_index = int(nine_index)
            best_label = "9"
    return best_label, max(0.0, float(scores[best_index]))


def _glyph_hole_count(mask: np.ndarray) -> int:
    import cv2

    if mask.size == 0 or mask.shape == (1, 1):
        return 0
    source = (mask > 0).astype(np.uint8)
    contours, hierarchy = cv2.findContours(source * 255, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    return sum(
        1
        for index in range(len(contours))
        if hierarchy is not None and hierarchy[0][index][3] >= 0
    )


def _has_substantial_upper_counter(mask: np.ndarray) -> bool:
    """Return true only for a closed, non-antialias upper counter.

    Native ClubGG sixes can contain a tiny two-pixel cavity near their open
    upper curl.  Treating every second cavity as proof of an eight changed 6s
    into 8s throughout stacks.  Counter area relative to the tight glyph is
    stable across the cyan stack font and the smaller white wager font.
    """

    import cv2

    if mask.size == 0 or mask.shape == (1, 1):
        return False
    source = (mask > 0).astype(np.uint8)
    rows, cols = np.where(source > 0)
    if not len(cols):
        return False
    tight = source[rows.min(): rows.max() + 1, cols.min(): cols.max() + 1]
    contours, hierarchy = cv2.findContours(tight * 255, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return False
    glyph_area = float(max(1, tight.shape[0] * tight.shape[1]))
    for index, contour in enumerate(contours):
        if hierarchy[0][index][3] < 0:
            continue
        _x, y, _width, height = cv2.boundingRect(contour)
        center_y = (float(y) + float(height) / 2.0) / max(1.0, float(tight.shape[0]))
        if center_y <= 0.50 and float(cv2.contourArea(contour)) / glyph_area >= 0.04:
            return True
    return False


def _looks_like_overlay_text(raw: str) -> bool:
    """Reject word-dominated status overlays before amount normalization.

    OCR may turn letters inside a disconnect/status banner into 0/1 and then
    normalize the result into a plausible tiny stack.  Genuine noisy amount
    crops can contain a short ``Total`` fragment, so reject only when letters
    clearly outnumber digits and there is no visual amount suffix.
    """

    compact = re.sub(r"\s+", "", str(raw or "").upper())
    if re.search(r"(?:BB|[KM])$", compact):
        return False
    digit_count = sum(char.isdigit() for char in compact)
    letter_count = sum(char.isalpha() for char in compact)
    return letter_count >= 3 and letter_count > digit_count


def _sanitize_amount_text(raw: str) -> str:
    value = raw.upper().replace(" ", "")
    value = value.replace("O", "0").replace("I", "1").replace("L", "1")
    value = re.sub(r"[^0-9.,KMB]", "", value)
    value = re.sub(r"(?<=\d)B[0856]$", "BB", value)
    value = re.sub(r"(?<=\d)[0856]B$", "BB", value)
    if value.endswith("B") and not value.endswith("BB"):
        value += "B"
    if value.endswith("BB"):
        # In this font a tiny zero and B differ mainly at the right edge.  B is
        # only legal in the two-character suffix, so an interior match is an
        # unambiguous zero correction (e.g. 1B4.1BB -> 104.1BB).
        prefix = re.sub(r"B$", "8", value[:-2])
        value = prefix.replace("B", "0") + "BB"
    return value


def _squash_bb_noise(raw: str, amount: float) -> float:
    value = (raw or "").replace(" ", "").upper()
    if "," in value and "." not in value:
        value = re.sub(r"(\d+),(\d{1,2})(?=B*$)", r"\1.\2", value)
    else:
        value = value.replace(",", "")
    long_decimal = re.search(r"^(\d+)[.](\d{3,})(?:B*)$", value)
    if long_decimal and 0 < amount < 1000:
        return float(f"{long_decimal.group(1)}.{long_decimal.group(2)[0]}")
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
