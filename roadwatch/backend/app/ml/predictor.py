"""YOLO predictor: loads local weights once and runs frame inference.

Kept behind a stable interface (load / predict_frame) so the model family can
be swapped without touching callers. All inference is local.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.ml.model_registry import discover_model_path

log = get_logger(__name__)


class ModelNotLoadedError(RuntimeError):
    """Raised when inference is requested but weights are unavailable."""


class Predictor:
    """Thread-safe singleton wrapper around an Ultralytics YOLO model."""

    def __init__(self) -> None:
        self._model: Any = None
        self._model_path: Path | None = None
        self._classes: dict[int, str] = {}
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------
    def load(self, model_path: str | Path | None = None) -> None:
        """Load weights from an explicit path, or auto-discover them."""
        with self._lock:
            path = Path(model_path) if model_path else discover_model_path()
            if path is None:
                raise ModelNotLoadedError(
                    "No model weights found. Place best.pt in models/ or set "
                    "ROADWATCH_MODEL_PATH in .env."
                )
            if self._model is not None and self._model_path == path:
                return  # already loaded

            from ultralytics import YOLO  # imported lazily: heavy import

            log.info("Loading model weights from %s", path.name)
            self._model = YOLO(str(path))
            self._model_path = path
            names = getattr(self._model, "names", {}) or {}
            self._classes = {int(k): str(v) for k, v in names.items()}
            log.info("Model loaded: %d class(es): %s", len(self._classes), self._classes)

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def classes(self) -> list[str]:
        return [self._classes[k] for k in sorted(self._classes)]

    @property
    def model_path(self) -> Path | None:
        return self._model_path

    def ensure_loaded(self) -> None:
        if self._model is None:
            self.load()

    # -- inference ---------------------------------------------------------
    def predict_frame(
        self,
        frame: Any,
        confidence: float = 0.4,
        image_size: int = 640,
    ) -> list[dict]:
        """Run detection on a BGR frame.

        Returns structured detections:
            class_id, class_name, confidence, bbox_xyxy, mask (optional)
        Bounding boxes are pixel coordinates in the ORIGINAL frame space.
        """
        self.ensure_loaded()
        assert self._model is not None

        results = self._model.predict(
            source=frame,
            conf=confidence,
            imgsz=image_size,
            verbose=False,
        )

        detections: list[dict] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            xyxy = boxes.xyxy.cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            clss = boxes.cls.cpu().numpy().astype(int)

            masks = None
            if result.masks is not None:
                # Polygon masks in original-frame pixel space.
                masks = [m.tolist() for m in result.masks.xy]

            for i in range(len(xyxy)):
                cid = int(clss[i])
                detections.append(
                    {
                        "class_id": cid,
                        "class_name": self._classes.get(cid, str(cid)),
                        "confidence": float(confs[i]),
                        "bbox_xyxy": [round(float(v), 2) for v in xyxy[i]],
                        "mask": masks[i] if masks else None,
                    }
                )
        return detections


# Process-wide singleton
predictor = Predictor()
