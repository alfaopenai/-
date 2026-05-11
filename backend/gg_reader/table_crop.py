from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

import numpy as np

from .fast_amount import amount_text_signal


BAD_SOURCE_PROCESSES = {
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
    "mremoteng.exe",
}
BAD_SOURCE_TITLE_TOKENS = (
    "localhost",
    "127.0.0.1",
    "ask gemini",
    "google translate",
    "mremoteng",
    "chrome",
    "edge",
    "firefox",
)


@dataclass(frozen=True)
class ClubGgValidationResult:
    is_real_clubgg: bool
    score: float
    anchors_found: list[str] = field(default_factory=list)
    rejected_localhost_table: bool = False
    rejected_browser_chrome: bool = False
    rejected_reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def as_diagnostics(self) -> dict[str, Any]:
        return {
            "isRealClubGg": bool(self.is_real_clubgg),
            "realClubGgScore": round(float(self.score), 4),
            "clubggAnchorsFound": list(self.anchors_found),
            "rejectedLocalhostTable": bool(self.rejected_localhost_table),
            "rejectedBrowserChrome": bool(self.rejected_browser_chrome),
            "rejectedReason": self.rejected_reason,
            **dict(self.diagnostics),
        }


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
        metrics = {
            "croppedFrameWidth": int(width),
            "croppedFrameHeight": int(height),
            "cropSource": self.source,
            "cropConfidence": round(float(self.confidence), 4),
            "cropRect": dict(self.crop_rect),
            "innerTableRect": dict(self.inner_table_rect) if self.inner_table_rect else None,
            "cropWarnings": list(self.warnings),
            "cropDiagnostics": dict(self.diagnostics),
        }
        for key in (
            "isRealClubGg",
            "realClubGgScore",
            "clubggAnchorsFound",
            "rejectedLocalhostTable",
            "rejectedBrowserChrome",
            "rejectedReason",
            "selectedCropCandidate",
            "cropCandidates",
        ):
            if key in self.diagnostics:
                metrics[key] = self.diagnostics[key]
        return metrics


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
    direct_real = validate_real_clubgg_crop(frame, window_metadata)
    warnings: list[str] = []

    if direct_real.is_real_clubgg:
        if _trust_direct_window_capture(window_metadata):
            source = str((window_metadata or {}).get("source") or (window_metadata or {}).get("captureSource") or "window")
            return TableCropResult(
                frame,
                full_rect,
                None,
                source,
                min(1.0, max(direct_confidence, direct_real.score)),
                diagnostics={**direct_diag, **direct_real.as_diagnostics(), "selectedCropCandidate": "direct-window"},
            )
        detected = _image_detected_table_crop(frame, window_metadata)
        if detected is not None:
            left, top, right, bottom, inner_rect, detected_diag, real_validation = detected
            if _should_prefer_detected_crop(
                frame_width=frame_width,
                frame_height=frame_height,
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                direct_score=direct_real.score,
                detected_validation=real_validation,
            ):
                cropped = frame[top:bottom, left:right]
                detected_confidence, validation_diag = validate_table_crop(cropped)
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
                    min(1.0, max(detected_confidence, real_validation.score)),
                    diagnostics={
                        **direct_diag,
                        **detected_diag,
                        **validation_diag,
                        **real_validation.as_diagnostics(),
                    },
                )
        source = "window-client"
        if window_metadata and window_metadata.get("source"):
            source = str(window_metadata["source"])
        return TableCropResult(
            frame,
            full_rect,
            _green_inner_rect(frame),
            source,
            min(1.0, max(direct_confidence, direct_real.score)),
            diagnostics={**direct_diag, **direct_real.as_diagnostics(), "selectedCropCandidate": "direct-frame"},
        )

    detected = _image_detected_table_crop(frame, window_metadata)
    if detected is not None:
        left, top, right, bottom, inner_rect, detected_diag, real_validation = detected
        cropped = frame[top:bottom, left:right]
        detected_confidence, validation_diag = validate_table_crop(cropped)
        diagnostics = {
            **direct_diag,
            **detected_diag,
            **validation_diag,
            **real_validation.as_diagnostics(),
        }
        if real_validation.is_real_clubgg:
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
                min(1.0, max(detected_confidence, real_validation.score)),
                diagnostics=diagnostics,
            )
        warnings.append(real_validation.rejected_reason or "image-detected-crop-not-real-clubgg")

    warnings.append(direct_real.rejected_reason or "real-clubgg-validation-low")
    return TableCropResult(
        frame,
        full_rect,
        None,
        "crop-invalid",
        min(direct_confidence, direct_real.score),
        diagnostics={**direct_diag, **direct_real.as_diagnostics(), "selectedCropCandidate": "none"},
        warnings=warnings,
    )


def _trust_direct_window_capture(window_metadata: dict[str, Any] | None) -> bool:
    metadata = dict(window_metadata or {})
    source = str(metadata.get("source") or metadata.get("captureSource") or "").lower()
    if source != "window":
        return False
    process_text = f"{metadata.get('processName') or ''} {metadata.get('processExe') or ''}".lower()
    title = str(metadata.get("title") or metadata.get("selectedWindowTitle") or "").lower()
    class_name = str(metadata.get("className") or "").lower()
    return bool(
        "clubgg" in process_text
        or "unitywndclass" in class_name
        or "clubgg" in title
        or re.search(r"\b(?:nlh|plo)\b", title)
    )


def _should_prefer_detected_crop(
    *,
    frame_width: int,
    frame_height: int,
    left: int,
    top: int,
    right: int,
    bottom: int,
    direct_score: float,
    detected_validation: ClubGgValidationResult,
) -> bool:
    """Prefer the table client when a desktop/screen frame contains padding.

    Direct validation intentionally accepts real ClubGG pixels even when they
    are surrounded by desktop background. The ROI reader, however, needs the
    client/table area, not the whole monitor, so a smaller high-confidence crop
    should win when it clearly trims outside padding.
    """

    if not detected_validation.is_real_clubgg:
        return False
    frame_area = max(1, int(frame_width) * int(frame_height))
    crop_width = max(0, int(right) - int(left))
    crop_height = max(0, int(bottom) - int(top))
    crop_area = crop_width * crop_height
    if crop_width < 320 or crop_height < 240:
        return False
    trims_padding = crop_area < frame_area * 0.94 and (
        int(left) > max(8, frame_width * 0.01)
        or int(top) > max(8, frame_height * 0.01)
        or int(right) < frame_width - max(8, frame_width * 0.01)
        or int(bottom) < frame_height - max(8, frame_height * 0.01)
    )
    if not trims_padding:
        return False
    return detected_validation.score >= max(0.38, float(direct_score) + 0.045)


def validate_real_clubgg_crop(
    frame: np.ndarray,
    window_metadata: dict[str, Any] | None = None,
) -> ClubGgValidationResult:
    """Validate that a candidate is the real ClubGG table, not a generic table.

    The local app is also a green poker table. This guard therefore requires
    ClubGG-specific anchors and rejects known browser/remote-control sources
    before the OCR/profile reader can consume the frame.
    """

    generic_confidence, generic_diag = validate_table_crop(frame)
    diagnostics: dict[str, Any] = dict(generic_diag)
    metadata = dict(window_metadata or {})
    metadata_rejection = _metadata_rejection_reason(metadata)
    process_text = f"{metadata.get('processName') or ''} {metadata.get('processExe') or ''}".lower()
    metadata_browser_hint = metadata_rejection in {"browser-process", "browser-title"} or any(
        process in process_text for process in ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe")
    )

    if frame is None or frame.size == 0 or frame.ndim < 3:
        return ClubGgValidationResult(False, 0.0, rejected_reason="empty-frame", diagnostics=diagnostics)

    height, width = frame.shape[:2]
    anchors: list[str] = []
    title_meta_score = _title_metadata_score(metadata)
    if title_meta_score > 0:
        anchors.append("window-title-nlh-plo")

    title_visual = _title_bar_signal(frame)
    bad_beat = _bad_beat_signal(frame)
    pot = _pot_anchor_signal(frame)
    center_logo = _center_logo_signal(frame)
    join_waiting = _join_waiting_signal(frame)
    cyan_stacks = _cyan_stack_signal(frame)
    compact_panels = _compact_panel_signal(frame)
    browser_ui = _browser_chrome_visual_signal(frame)
    localhost_like = _localhost_app_table_signal(frame, bad_beat=bad_beat, title_visual=title_visual)

    if title_visual >= 0.18:
        anchors.append("clubgg-titlebar")
    if bad_beat >= 0.010:
        anchors.append("bad-beat-banner")
    if pot >= 0.035:
        anchors.append("total-pot-bb")
    if center_logo >= 0.006:
        anchors.append("clubgg-center-logo")
    if join_waiting >= 0.020:
        anchors.append("join-waiting")
    if cyan_stacks >= 0.010:
        anchors.append("cyan-bb-stacks")
    if compact_panels >= 0.22:
        anchors.append("compact-player-panels")

    score = (
        generic_confidence * 0.12
        + title_meta_score * 0.24
        + min(1.0, title_visual * 2.2) * 0.10
        + min(1.0, bad_beat * 30.0) * 0.18
        + min(1.0, pot * 16.0) * 0.18
        + min(1.0, center_logo * 25.0) * 0.06
        + min(1.0, cyan_stacks * 42.0) * 0.10
        + min(1.0, compact_panels * 2.8) * 0.09
        + min(1.0, join_waiting * 18.0) * 0.03
    )
    if browser_ui >= 0.62:
        score -= 0.32
    if localhost_like:
        score -= 0.45
    if metadata_rejection:
        # Window metadata is a hint, not a veto. Desktop/browser captures often
        # arrive through Chrome or mRemoteNG even when the pixels are the real
        # ClubGG client. Visual ClubGG anchors are allowed to override that.
        metadata_penalty = 0.14 if len(set(anchors)) >= 3 else 0.45
        if metadata_rejection in {"localhost-title", "browser-title"} and len(set(anchors)) < 3:
            metadata_penalty = 0.55
        score -= metadata_penalty

    diagnostics.update({
        **_metadata_debug(metadata),
        "metadataRejectHint": metadata_rejection,
        "clubggTitleVisualSignal": round(float(title_visual), 4),
        "clubggBadBeatSignal": round(float(bad_beat), 4),
        "clubggPotAnchorSignal": round(float(pot), 4),
        "clubggCenterLogoSignal": round(float(center_logo), 4),
        "clubggJoinWaitingSignal": round(float(join_waiting), 4),
        "clubggCyanStackSignal": round(float(cyan_stacks), 4),
        "clubggCompactPanelSignal": round(float(compact_panels), 4),
        "browserChromeVisualSignal": round(float(browser_ui), 4),
        "localhostLikeTableSignal": bool(localhost_like),
        "candidateWidth": int(width),
        "candidateHeight": int(height),
    })

    green_ratio = float(generic_diag.get("greenFeltRatio") or 0.0)
    center_green_ratio = float(generic_diag.get("centerGreenRatio") or 0.0)
    table_surface_visible = not (green_ratio < 0.25 and center_green_ratio < 0.45)
    if not table_surface_visible:
        score -= 0.35
    diagnostics["tableSurfaceVisible"] = bool(table_surface_visible)

    enough_anchors = len(set(anchors)) >= 3
    if title_meta_score >= 0.85 and len(set(anchors)) >= 2:
        enough_anchors = True
    is_real = bool(score >= 0.38 and enough_anchors and table_surface_visible and not localhost_like and browser_ui < 0.72)
    reason = ""
    if not is_real:
        if localhost_like:
            reason = "localhost-like-green-table"
        elif browser_ui >= 0.72:
            reason = "browser-frame-not-clubgg"
        elif metadata_rejection and len(set(anchors)) < 3:
            reason = metadata_rejection
        elif not table_surface_visible:
            reason = "clubgg-table-obscured-or-not-visible"
        elif not enough_anchors:
            reason = "missing-clubgg-anchors"
        else:
            reason = "real-clubgg-score-low"

    return ClubGgValidationResult(
        is_real_clubgg=is_real,
        score=max(0.0, min(1.0, score)),
        anchors_found=sorted(set(anchors)),
        rejected_localhost_table=bool(localhost_like or (metadata_rejection == "localhost-title" and not is_real)),
        rejected_browser_chrome=bool(browser_ui >= 0.72 or (metadata_browser_hint and not is_real)),
        rejected_reason=reason,
        diagnostics=diagnostics,
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
    window_metadata: dict[str, Any] | None = None,
) -> tuple[int, int, int, int, dict[str, int] | None, dict[str, Any], ClubGgValidationResult] | None:
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

    scored: list[tuple[float, tuple[int, int, int, int, dict[str, int], dict[str, Any], ClubGgValidationResult]]] = []
    candidate_debug: list[dict[str, Any]] = []
    for area, (x0, y0, box_width0, box_height0) in candidates:
        x = int(x0 * sample_step)
        y = int(y0 * sample_step)
        box_width = int(box_width0 * sample_step)
        box_height = int(box_height0 * sample_step)

        # The green contour may be either the whole compact ClubGG client or
        # just the inner felt. Try several expansions and let the ClubGG anchor
        # score pick the right one instead of choosing the largest table.
        for variant_name, pad_x_ratio, pad_top_ratio, pad_bottom_ratio in (
            ("compact-client", 0.025, 0.20, 0.06),
            ("client-area", 0.16, 0.30, 0.24),
            ("wide-felt", 0.42, 0.50, 0.78),
        ):
            pad_x = int(max(box_width * pad_x_ratio, width * 0.005))
            pad_top = int(max(box_height * pad_top_ratio, height * 0.010))
            pad_bottom = int(max(box_height * pad_bottom_ratio, height * 0.010))
            left = max(0, x - pad_x)
            top = max(0, y - pad_top)
            right = min(width, x + box_width + pad_x)
            bottom = min(height, y + box_height + pad_bottom)

            if right - left < 320 or bottom - top < 240:
                continue

            candidate = frame[top:bottom, left:right]
            real_validation = validate_real_clubgg_crop(candidate, window_metadata)
            inner_rect = {
                "left": int(x - left),
                "top": int(y - top),
                "width": int(box_width),
                "height": int(box_height),
            }
            diagnostics = {
                "selectedCropCandidate": {
                    "variant": variant_name,
                    "left": int(left),
                    "top": int(top),
                    "width": int(right - left),
                    "height": int(bottom - top),
                    "feltArea": int(area * sample_step * sample_step),
                },
                "detectedFeltBox": {
                    "left": int(x),
                    "top": int(y),
                    "width": int(box_width),
                    "height": int(box_height),
                },
            }
            score = real_validation.score
            if real_validation.is_real_clubgg:
                score += 0.25
            debug_item = {
                "variant": variant_name,
                "left": int(left),
                "top": int(top),
                "width": int(right - left),
                "height": int(bottom - top),
                "feltArea": int(area * sample_step * sample_step),
                "score": round(float(score), 4),
                "accepted": bool(real_validation.is_real_clubgg),
                "rejectReason": real_validation.rejected_reason,
                "anchors": list(real_validation.anchors_found),
                "isRealClubGg": bool(real_validation.is_real_clubgg),
                "rejectedLocalhostTable": bool(real_validation.rejected_localhost_table),
                "realClubGgScore": round(float(real_validation.score), 4),
            }
            candidate_debug.append(debug_item)
            scored.append((score, (int(left), int(top), int(right), int(bottom), inner_rect, diagnostics, real_validation)))

    if not scored:
        return None
    selected = max(scored, key=lambda item: item[0])[1]
    selected[5]["cropCandidates"] = sorted(candidate_debug, key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return selected


def _green_inner_rect(frame: np.ndarray) -> dict[str, int] | None:
    detected = _image_detected_table_crop(frame)
    if detected is None:
        return None
    left, top, _right, _bottom, inner_rect, _diag, _validation = detected
    if inner_rect is None:
        return None
    return {
        "left": int(left + inner_rect["left"]),
        "top": int(top + inner_rect["top"]),
        "width": int(inner_rect["width"]),
        "height": int(inner_rect["height"]),
    }


def _metadata_rejection_reason(metadata: dict[str, Any]) -> str:
    allow_browser = bool(metadata.get("allowBrowserFallback"))
    title = str(metadata.get("title") or metadata.get("selectedWindowTitle") or "").lower()
    process = str(metadata.get("processName") or metadata.get("process") or "").lower()
    exe = str(metadata.get("processExe") or "").lower()
    class_name = str(metadata.get("className") or "").lower()
    if any(token in title for token in ("localhost", "127.0.0.1")):
        return "localhost-title"
    if any(token in title for token in ("ask gemini", "google translate")):
        return "browser-title"
    if not allow_browser and process in {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}:
        return "browser-process"
    if not allow_browser and any(token in exe for token in ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe")):
        return "browser-process"
    if process == "mremoteng.exe" or "mremoteng" in exe or "mremoteng" in class_name or "mremoteng" in title:
        return "remote-control-process"
    return ""


def _metadata_debug(metadata: dict[str, Any]) -> dict[str, Any]:
    keys = ("title", "selectedWindowTitle", "processName", "processExe", "className", "hwnd", "source", "captureSource")
    return {f"window{key[0].upper()}{key[1:]}": metadata.get(key) for key in keys if metadata.get(key) is not None}


def _title_metadata_score(metadata: dict[str, Any]) -> float:
    title = str(metadata.get("title") or metadata.get("selectedWindowTitle") or "").lower()
    if not title:
        return 0.0
    score = 0.0
    if "nlh" in title or "plo" in title:
        score += 0.72
    if re.search(r"\b\d+(?:\.\d+)?\s*[-/]\s*\d+(?:\.\d+)?\b", title):
        score += 0.20
    if "clubgg" in title or "club gg" in title:
        score += 0.15
    return min(1.0, score)


def _roi(frame: np.ndarray, roi: tuple[float, float, float, float]) -> np.ndarray:
    height, width = frame.shape[:2]
    x, y, w, h = roi
    left = max(0, min(width, int(round(x * width))))
    top = max(0, min(height, int(round(y * height))))
    right = max(left, min(width, int(round((x + w) * width))))
    bottom = max(top, min(height, int(round((y + h) * height))))
    return frame[top:bottom, left:right]


def _title_bar_signal(frame: np.ndarray) -> float:
    image = _roi(frame, (0.0, 0.0, 0.42, 0.08))
    if image.size == 0 or image.ndim < 3:
        return 0.0
    gray = np.mean(image[:, :, :3], axis=2)
    dark = float((gray < 55).mean())
    bright = float((gray > 150).mean())
    orange = _orange_signal(_roi(frame, (0.0, 0.05, 0.30, 0.11)))
    return min(1.0, dark * 0.45 + bright * 2.2 + orange * 4.0)


def _bad_beat_signal(frame: np.ndarray) -> float:
    return _orange_signal(_roi(frame, (0.0, 0.045, 0.33, 0.105)))


def _pot_anchor_signal(frame: np.ndarray) -> float:
    crop = _roi(frame, (0.39, 0.315, 0.24, 0.085))
    if crop.size == 0:
        return 0.0
    return max(amount_text_signal(crop), _yellow_white_signal(crop) * 0.5)


def _center_logo_signal(frame: np.ndarray) -> float:
    crop = _roi(frame, (0.36, 0.36, 0.30, 0.20))
    if crop.size == 0 or crop.ndim < 3:
        return 0.0
    channels = crop[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    gray = np.mean(channels, axis=2)
    muted_logo = (gray > 65) & (gray < 175) & (np.abs(red - green) < 30) & (np.abs(blue - green) < 35)
    return float(muted_logo.mean())


def _join_waiting_signal(frame: np.ndarray) -> float:
    crop = _roi(frame, (0.77, 0.82, 0.22, 0.16))
    if crop.size == 0 or crop.ndim < 3:
        return 0.0
    gray = np.mean(crop[:, :, :3], axis=2)
    dark_button = float((gray < 70).mean())
    white_text = float((gray > 160).mean())
    return min(1.0, dark_button * white_text * 5.0)


def _cyan_stack_signal(frame: np.ndarray) -> float:
    # Score only the ring where ClubGG stack labels are normally rendered.
    masks = [
        _roi(frame, (0.39, 0.20, 0.22, 0.08)),
        _roi(frame, (0.73, 0.25, 0.23, 0.13)),
        _roi(frame, (0.78, 0.50, 0.22, 0.13)),
        _roi(frame, (0.67, 0.76, 0.25, 0.14)),
        _roi(frame, (0.37, 0.82, 0.27, 0.16)),
        _roi(frame, (0.12, 0.76, 0.25, 0.14)),
        _roi(frame, (0.00, 0.50, 0.23, 0.13)),
        _roi(frame, (0.08, 0.25, 0.25, 0.13)),
    ]
    values = [_cyan_signal(crop) for crop in masks if crop.size]
    return sum(values) / len(values) if values else 0.0


def _compact_panel_signal(frame: np.ndarray) -> float:
    rois = [
        (0.42, 0.10, 0.18, 0.22),
        (0.74, 0.17, 0.18, 0.24),
        (0.84, 0.43, 0.16, 0.24),
        (0.72, 0.66, 0.18, 0.24),
        (0.42, 0.70, 0.20, 0.26),
        (0.13, 0.66, 0.20, 0.24),
        (0.00, 0.43, 0.19, 0.24),
        (0.10, 0.17, 0.20, 0.24),
    ]
    scores = []
    for roi in rois:
        crop = _roi(frame, roi)
        if crop.size == 0 or crop.ndim < 3:
            continue
        gray = np.mean(crop[:, :, :3], axis=2)
        dark = float((gray < 80).mean())
        cyan = _cyan_signal(crop)
        white = float((gray > 150).mean())
        scores.append(min(1.0, dark * 0.60 + cyan * 18.0 + white * 0.25))
    scores = sorted(scores, reverse=True)[:5]
    return sum(scores) / len(scores) if scores else 0.0


def _browser_chrome_visual_signal(frame: np.ndarray) -> float:
    if frame.size == 0 or frame.ndim < 3:
        return 0.0
    height, width = frame.shape[:2]
    if width < 900 or height < 500:
        return 0.0
    top = _roi(frame, (0.0, 0.0, 1.0, 0.16))
    if top.size == 0:
        return 0.0
    channels = top[:, :, :3].astype(np.int16)
    gray = np.mean(channels, axis=2)
    neutral = float(((np.abs(channels[:, :, 0] - channels[:, :, 1]) < 12) & (np.abs(channels[:, :, 1] - channels[:, :, 2]) < 12)).mean())
    mid = float(((gray > 25) & (gray < 95)).mean())
    bright = float((gray > 185).mean())
    return min(1.0, neutral * 0.35 + mid * 0.45 + bright * 0.25)


def _localhost_app_table_signal(frame: np.ndarray, *, bad_beat: float, title_visual: float) -> bool:
    generic_confidence, _diag = validate_table_crop(frame)
    if generic_confidence < 0.38:
        return False
    # The app table has strong green felt but lacks the ClubGG bad-beat/title
    # anchors. A direct real ClubGG client almost always has one of them.
    return bool(bad_beat < 0.004 and title_visual < 0.12 and _pot_anchor_signal(frame) < 0.025)


def _cyan_signal(image: np.ndarray) -> float:
    if image.size == 0 or image.ndim < 3:
        return 0.0
    channels = image[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    mask = (blue > 90) & (green > 90) & (red < 150) & ((blue - red) > 20) & ((green - red) > 20)
    return float(mask.mean())


def _orange_signal(image: np.ndarray) -> float:
    if image.size == 0 or image.ndim < 3:
        return 0.0
    channels = image[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    mask = (red > 125) & (green > 55) & (blue < 115) & ((red - blue) > 35)
    return float(mask.mean())


def _yellow_white_signal(image: np.ndarray) -> float:
    if image.size == 0 or image.ndim < 3:
        return 0.0
    channels = image[:, :, :3].astype(np.int16)
    blue = channels[:, :, 0]
    green = channels[:, :, 1]
    red = channels[:, :, 2]
    yellow = (red > 120) & (green > 115) & (blue < 120)
    white = (red > 165) & (green > 165) & (blue > 165)
    return float(np.logical_or(yellow, white).mean())
