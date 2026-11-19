"""Video decoding, frame sampling and annotated-video encoding (OpenCV)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from app.core.logging import get_logger

log = get_logger(__name__)

# Colors in BGR for annotation drawing (neo-brutalist palette)
_COLOR_YELLOW = (66, 230, 245)   # #F5E642
_COLOR_CORAL = (94, 107, 255)     # #FF6B5E
_COLOR_INK = (17, 17, 17)


class VideoOpenError(ValueError):
    """Raised when a video cannot be opened/decoded (safe for users)."""


@dataclass
class VideoInfo:
    path: Path
    width: int
    height: int
    fps: float
    frame_count: int
    duration_s: float


@dataclass
class FrameSample:
    index: int            # original frame index
    timestamp_s: float    # seconds from video start
    frame: np.ndarray     # BGR


def open_video(path: Path) -> VideoInfo:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise VideoOpenError(
            "Could not open the video file. It may be corrupted or use an "
            "unsupported codec."
        )
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        duration = frame_count / fps if fps > 0 else 0.0
        if width <= 0 or height <= 0:
            raise VideoOpenError("Video reports invalid dimensions.")
        return VideoInfo(path, width, height, fps, frame_count, duration)
    finally:
        cap.release()


def iter_samples(
    path: Path,
    sample_rate_fps: float,
    should_cancel: Callable[[], bool] | None = None,
):
    """Yield FrameSample at the requested rate (default 1 fps).

    Yields nothing if cancelled mid-decode. Corrupted frames are skipped.
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise VideoOpenError("Could not open the video file.")

    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
        step = max(1, int(round(fps / max(sample_rate_fps, 0.1))))
        index = 0
        while True:
            if should_cancel is not None and should_cancel():
                return
            ok, frame = cap.read()
            if not ok:
                return
            if index % step == 0:
                yield FrameSample(index=index, timestamp_s=index / fps, frame=frame)
            index += 1
    finally:
        cap.release()


def draw_detections(
    frame: np.ndarray, detections: list[dict], timestamp_s: float
) -> np.ndarray:
    """Draw boxes/labels onto a copy of the frame (original-frame coords)."""
    out = frame.copy()
    for det in detections:
        x1, y1, x2, y2 = (int(round(v)) for v in det["bbox_xyxy"])
        conf = det["confidence"]
        label = f"{det['class_name'].upper()} {conf:.2f}"

        cv2.rectangle(out, (x1, y1), (x2, y2), _COLOR_INK, 5)
        cv2.rectangle(out, (x1, y1), (x2, y2), _COLOR_YELLOW, 2)

        # Label plate
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        ty = max(y1 - th - 12, 0)
        cv2.rectangle(out, (x1, ty), (x1 + tw + 10, ty + th + 10), _COLOR_INK, -1)
        cv2.putText(
            out, label, (x1 + 5, ty + th + 2),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA,
        )

        # Optional segmentation outline
        if det.get("mask"):
            pts = np.array(det["mask"], dtype=np.int32).reshape(-1, 1, 2)
            cv2.polylines(out, [pts], True, _COLOR_CORAL, 3)

    # Timestamp HUD (bottom-left)
    hud = f"T+{timestamp_s:07.2f}s"
    cv2.rectangle(out, (8, out.shape[0] - 34), (170, out.shape[0] - 8), _COLOR_INK, -1)
    cv2.putText(
        out, hud, (16, out.shape[0] - 12),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA,
    )
    return out


def annotate_video(
    source: Path,
    dest: Path,
    detections_by_index: dict[int, list[dict]],
    progress_cb: Callable[[int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> Path:
    """Re-encode the video, overlaying detections on their sampled frames.

    Frames without detections pass through unmodified. Progress is reported as
    (frames_done, frames_total).

    Uses FFmpeg (libx264) when available for compact output; falls back to
    OpenCV's mp4v writer otherwise.
    """
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise VideoOpenError("Could not open the video file for annotation.")

    ffmpeg = _find_ffmpeg()
    writer = None
    writer_proc = None

    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

        dest.parent.mkdir(parents=True, exist_ok=True)

        if ffmpeg:
            # Pipe raw frames into FFmpeg for H.264 encoding (~10x smaller
            # than OpenCV's default mp4v at high resolutions).
            import subprocess

            writer_proc = subprocess.Popen(
                [
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "rawvideo", "-pix_fmt", "bgr24",
                    "-s", f"{width}x{height}", "-r", f"{fps}",
                    "-i", "-",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    str(dest),
                ],
                stdin=subprocess.PIPE,
            )
        else:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(dest), fourcc, fps, (width, height))
            if not writer.isOpened():
                raise VideoOpenError("Could not create the output video file.")

        index = 0
        try:
            while True:
                if should_cancel is not None and should_cancel():
                    break
                ok, frame = cap.read()
                if not ok:
                    break
                dets = detections_by_index.get(index)
                if dets:
                    frame = draw_detections(frame, dets, index / fps)
                if writer_proc is not None:
                    writer_proc.stdin.write(frame.tobytes())
                else:
                    writer.write(frame)
                index += 1
                if progress_cb and total:
                    progress_cb(index, total)
        finally:
            if writer_proc is not None:
                writer_proc.stdin.close()
                writer_proc.wait()
                if writer_proc.returncode != 0 and dest.exists() and dest.stat().st_size == 0:
                    dest.unlink(missing_ok=True)
                    raise VideoOpenError("FFmpeg failed to encode the output video.")
            if writer is not None:
                writer.release()
        return dest
    finally:
        cap.release()


def _find_ffmpeg() -> str | None:
    """Locate an ffmpeg executable (bundled opencv build ships its own dll, not a CLI)."""
    import shutil

    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    # Common Windows locations
    for candidate in (
        Path(os.environ.get("PROGRAMFILES", "")) / "ffmpeg" / "bin" / "ffmpeg.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "ffmpeg" / "bin" / "ffmpeg.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def save_preview_frame(
    frame: np.ndarray, detections: list[dict], timestamp_s: float, dest: Path
) -> Path:
    """Save one annotated frame as JPEG for the UI preview."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    annotated = draw_detections(frame, detections, timestamp_s)
    cv2.imwrite(str(dest), annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return dest


@dataclass
class DetectionAccumulator:
    """Collects per-frame detections while streaming."""

    by_index: dict[int, list[dict]] = field(default_factory=dict)
    total: int = 0
    confidence_max: float = 0.0

    def add(self, index: int, dets: list[dict]) -> None:
        if not dets:
            return
        self.by_index[index] = dets
        self.total += len(dets)
        self.confidence_max = max(self.confidence_max, max(d["confidence"] for d in dets))
