from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import numpy as np


NormRoi = tuple[float, float, float, float]


def roi_to_bounds(frame_shape: tuple[int, ...], roi: NormRoi) -> tuple[int, int, int, int]:
    height, width = frame_shape[:2]
    x, y, roi_width, roi_height = roi
    left = int(round(float(x) * width))
    top = int(round(float(y) * height))
    right = int(round((float(x) + float(roi_width)) * width))
    bottom = int(round((float(y) + float(roi_height)) * height))

    left = max(0, min(width, left))
    top = max(0, min(height, top))
    right = max(left, min(width, right))
    bottom = max(top, min(height, bottom))
    return left, top, right, bottom


def crop_norm(frame: np.ndarray, roi: NormRoi) -> np.ndarray:
    if frame.size == 0:
        return frame[0:0, 0:0]
    left, top, right, bottom = roi_to_bounds(frame.shape, roi)
    return frame[top:bottom, left:right]


def crop_many(frame: np.ndarray, profile: Any) -> dict[str, np.ndarray]:
    crops: dict[str, np.ndarray] = {}
    for label, roi in _iter_profile_rois(profile):
        crops[label] = crop_norm(frame, roi)
    return crops


def downscale_hash(crop: np.ndarray, *, size: int = 12) -> np.ndarray:
    import cv2

    if crop.size == 0:
        return np.zeros((size, size), dtype=np.uint8)
    if crop.ndim == 3 and crop.shape[2] >= 3:
        gray = cv2.cvtColor(crop[:, :, :3], cv2.COLOR_BGR2GRAY)
    else:
        gray = crop.copy()
    return cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)


def roi_mean_abs_diff(previous_hash: np.ndarray | None, new_hash: np.ndarray | None) -> float:
    if previous_hash is None or new_hash is None:
        return 255.0
    if previous_hash.shape != new_hash.shape:
        return 255.0
    return float(np.mean(np.abs(previous_hash.astype(np.int16) - new_hash.astype(np.int16))))


def roi_changed(previous_hash: np.ndarray | None, new_hash: np.ndarray | None, threshold: float = 4.5) -> bool:
    return roi_mean_abs_diff(previous_hash, new_hash) > threshold


def draw_roi_overlay(frame: np.ndarray, profile: Any, output_path: str | Path) -> dict[str, Any]:
    import cv2

    overlay = frame.copy()
    if overlay.ndim == 3 and overlay.shape[2] == 4:
        overlay = overlay[:, :, :3].copy()
    colors = {
        "title": (255, 255, 255),
        "pot": (0, 230, 255),
        "board": (0, 200, 0),
        "name": (255, 160, 60),
        "stack": (255, 255, 0),
        "bet": (0, 180, 255),
        "dealer": (0, 140, 255),
        "card": (180, 180, 255),
        "active": (120, 120, 120),
    }
    for label, roi in _iter_profile_rois(profile):
        left, top, right, bottom = roi_to_bounds(overlay.shape, roi)
        kind = _label_kind(label)
        color = colors.get(kind, (210, 210, 210))
        cv2.rectangle(overlay, (left, top), (right, bottom), color, 1)
        if right - left >= 16 and bottom - top >= 10:
            text = label.replace("seat-", "s")
            cv2.putText(
                overlay,
                text[:32],
                (left + 2, max(10, top - 3)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.32,
                color,
                1,
                cv2.LINE_AA,
            )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), overlay)
    height, width = overlay.shape[:2]
    return {"path": str(output), "width": int(width), "height": int(height)}


def _iter_profile_rois(profile: Any) -> Iterable[tuple[str, NormRoi]]:
    if hasattr(profile, "all_rois"):
        yield from profile.all_rois()
        return
    if isinstance(profile, dict):
        for label, roi in profile.items():
            if _is_roi(roi):
                yield str(label), roi


def _is_roi(value: Any) -> bool:
    return isinstance(value, tuple) and len(value) == 4


def _label_kind(label: str) -> str:
    value = label.lower()
    if "title" in value:
        return "title"
    if "pot" in value:
        return "pot"
    if "board" in value:
        return "board"
    if "dealer" in value:
        return "dealer"
    if "card" in value:
        return "card"
    if "stack" in value:
        return "stack"
    if "bet" in value:
        return "bet"
    if "name" in value:
        return "name"
    if "active" in value:
        return "active"
    return "default"
