"""Model registry: discovery and status of local YOLO weights."""
from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# Filenames we accept as pothole weights, in discovery order.
_CANDIDATE_NAMES = ("best.pt", "pothole.pt", "yolo.pt")


def discover_model_path() -> Path | None:
    """Find usable local weights: explicit setting -> models/ dir -> bundled ml/weights."""
    if settings.model_path:
        p = Path(settings.model_path).expanduser()
        if p.is_file():
            return p
        log.warning("Configured ROADWATCH_MODEL_PATH does not exist: %s", p)

    for directory in (settings.models_dir, Path(__file__).resolve().parent / "weights"):
        if not directory.is_dir():
            continue
        for name in _CANDIDATE_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
        # Any .pt the developer dropped in (but ignore partial downloads).
        for candidate in sorted(directory.glob("*.pt")):
            if not candidate.name.endswith(".part"):
                return candidate
    return None


def model_status() -> dict:
    path = discover_model_path()
    return {
        "ready": path is not None,
        "filename": path.name if path else None,
        "source": _describe_source(path),
        "classes": None,  # populated once the predictor loads class names
        "hint": None
        if path
        else (
            "No weights found. Place best.pt in models/ or set "
            "ROADWATCH_MODEL_PATH in .env — see README 'Model weight setup'."
        ),
    }


def _describe_source(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        path.relative_to(settings.models_dir)
        return "models_dir"
    except ValueError:
        pass
    try:
        path.relative_to(Path(__file__).resolve().parent)
        return "bundled"
    except ValueError:
        return "configured"
