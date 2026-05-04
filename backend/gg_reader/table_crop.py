from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class TableCropResult:
    cropped_frame: np.ndarray
    crop_rect: dict[str, int]
    inner_table_rect: dict[str, int] | None
    source: str
    confidence: float
    diagnostics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def metrics(self) -> dict[str, Any]:
        height, width = self.cropped_frame.shape[:2]
        return {
            "croppedFrameWidth": int(width),
            "croppedFrameHeight": int(height),
            "cropSource": self.source,
            "cropConfidence": round(float(self.confidence), 4),
            "cropRect": dict(self.crop_rect),
            "innerTableRect": dict(self.inner_table_rect) if self.inner_table_rect else None,
            "cropWarnings": list(self.warnings),
            "cropDiagnostics": dict(self.diagnostics),
        }


def detect_clubgg_table_crop(
    frame: np.ndarray,
    window_metadata: dict[str, Any] | None = None,
) -> TableCropResult:
    """Find the visible ClubGG client/table surface before normalized ROIs run.

    Browser sharing may send a full desktop, a window with title/chrome, or the
    already-cropped table. This detector first validates the current frame and
    then falls back to locating the green felt region inside a larger image.
    """

    if frame is None or frame.size == 0:
        empty_rect = {"left": 0, "top": 0, "width": 0, "height": 0}
        return TableCropResult(frame, empty_rect, None, "empty-frame", 0.0, warnings=["empty-frame"])

    frame_height, frame_width = frame.shape[:2]
    full_rect = {"left": 0, "top": 0, "width": int(frame_width), "height": int(frame_height)}
    direct_confidence, direct_diag = validate_table_crop(frame)
    warnings: list[str] = []

    if direct_confidence >= 0.42:
        source = "window-client"
        if window_metadata and window_metadata.get("source"):
            source = str(window_metadata["source"])
        return TableCropResult(
            frame,
            full_rect,
            _green_inner_rect(frame),
            source,
            direct_confidence,
            diagnostics=direct_diag,
        )

    detected = _image_detected_table_crop(frame)
    if detected is not None:
        left, top, right, bottom, inner_rect, detected_diag = detected
        cropped = frame[top:bottom, left:right]
        detected_confidence, validation_diag = validate_table_crop(cropped)
        diagnostics = {**direct_diag, **detected_diag, **validation_diag}
        if detected_confidence >= 0.22:
            return TableCropResult(
                cropped,
                {
                    "left": int(left),
                    "top": int(top),
                    "width": int(right - left),
                    "height": int(bottom - top),
                },
                inner_rect,
                "image-detected-table",
                detected_confidence,
                diagnostics=diagnostics,
            )
        warnings.append("image-detected-crop-low-confidence")

    warnings.append("table-crop-validation-low")
    return TableCropResult(
        frame,
        full_rect,
        None,
        "uncropped-low-confidence",
        direct_confidence,
        diagnostics=direct_diag,
        warnings=warnings,
    )


def validate_table_crop(frame: np.ndarray) -> tuple[float, dict[str, Any]]:
    try:
        import cv2
    except Exception:
        return 0.0, {"cv2": False}

    if frame.size == 0 or frame.ndim < 3:
        return 0.0, {"empty": True}

    height, width = frame.shape[:2]
    sample = frame[:: max(1, height // 360), :: max(1, width // 640), :3]
    hsv = cv2.cvtColor(sample, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
    green_mask = cv2.inRange(hsv, np.array([35, 28, 24]), np.array([96, 255, 245]))
    dark_mask = gray < 70

    green_ratio = float((green_mask > 0).mean())
    dark_ratio = float(dark_mask.mean())
    center = sample[
        int(sample.shape[0] * 0.20): int(sample.shape[0] * 0.80),
        int(sample.shape[1] * 0.12): int(sample.shape[1] * 0.88),
    ]
    center_confidence = 0.0
    if center.size:
        center_hsv = cv2.cvtColor(center, cv2.COLOR_BGR2HSV)
        center_gray = cv2.cvtColor(center, cv2.COLOR_BGR2GRAY)
        center_green = cv2.inRange(center_hsv, np.array([35, 28, 24]), np.array([96, 255, 245]))
        center_dark = center_gray < 75
        center_green_ratio = float((center_green > 0).mean())
        center_dark_ratio = float(center_dark.mean())
        center_confidence = min(1.0, center_green_ratio * 2.8 + center_dark_ratio * 0.55)
    else:
        center_green_ratio = 0.0
        center_dark_ratio = 0.0

    aspect = width / max(1, height)
    aspect_score = 1.0 if 1.15 <= aspect <= 2.35 else max(0.0, 1.0 - abs(aspect - 1.65) / 1.65)
    confidence = min(1.0, (green_ratio * 2.4 + dark_ratio * 0.35 + center_confidence) * aspect_score)
    diagnostics = {
        "greenFeltRatio": round(green_ratio, 4),
        "darkTableRatio": round(dark_ratio, 4),
        "centerGreenRatio": round(center_green_ratio, 4),
        "centerDarkRatio": round(center_dark_ratio, 4),
        "aspect": round(aspect, 4),
        "aspectScore": round(aspect_score, 4),
    }
    return confidence, diagnostics


def _image_detected_table_crop(
    frame: np.ndarray,
) -> tuple[int, int, int, int, dict[str, int] | None, dict[str, Any]] | None:
    try:
        import cv2
    except Exception:
        return None

    if frame.size == 0 or frame.ndim < 3:
        return None

    height, width = frame.shape[:2]
    sample_step = max(1, min(height, width) // 900)
    sampled = frame[::sample_step, ::sample_step, :3]
    hsv = cv2.cvtColor(sampled, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([35, 35, 28]), np.array([96, 255, 245]))
    kernel = np.ones((9, 9), np.uint8)
    green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _hierarchy = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    candidates: list[tuple[float, tuple[int, int, int, int]]] = []
    for contour in contours:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        area = float(box_width * box_height)
        if area < max(1500, sampled.shape[0] * sampled.shape[1] * 0.015):
            continue
        aspect = box_width / max(1, box_height)
        if not (0.75 <= aspect <= 4.0):
            continue
        candidates.append((area, (x, y, box_width, box_height)))
    if not candidates:
        return None

    _area, (x, y, box_width, box_height) = max(candidates, key=lambda item: item[0])
    x *= sample_step
    y *= sample_step
    box_width *= sample_step
    box_height *= sample_step

    # The felt is the center of the table; seats, cards, and labels live around
    # it. Expand generously so fixed profile ROIs can align with the client area.
    pad_x = int(max(box_width * 0.42, width * 0.045))
    pad_top = int(max(box_height * 0.46, height * 0.055))
    pad_bottom = int(max(box_height * 0.78, height * 0.080))
    left = max(0, x - pad_x)
    top = max(0, y - pad_top)
    right = min(width, x + box_width + pad_x)
    bottom = min(height, y + box_height + pad_bottom)

    if right - left < 320 or bottom - top < 240:
        return None

    inner_rect = {
        "left": int(x - left),
        "top": int(y - top),
        "width": int(box_width),
        "height": int(box_height),
    }
    diagnostics = {
        "detectedFeltBox": {
            "left": int(x),
            "top": int(y),
            "width": int(box_width),
            "height": int(box_height),
        }
    }
    return int(left), int(top), int(right), int(bottom), inner_rect, diagnostics


def _green_inner_rect(frame: np.ndarray) -> dict[str, int] | None:
    detected = _image_detected_table_crop(frame)
    if detected is None:
        return None
    left, top, _right, _bottom, inner_rect, _diag = detected
    if inner_rect is None:
        return None
    return {
        "left": int(left + inner_rect["left"]),
        "top": int(top + inner_rect["top"]),
        "width": int(inner_rect["width"]),
        "height": int(inner_rect["height"]),
    }
