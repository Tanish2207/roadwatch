"""Local settings and model readiness."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings
from app.ml.model_registry import model_status

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def get_settings() -> dict:
    return {
        "app": {"name": "RoadWatch", "environment": settings.environment},
        "model": model_status(),
        "defaults": {
            "sample_rate_fps": settings.default_sample_rate_fps,
            "confidence_threshold": settings.default_confidence_threshold,
            "image_size": settings.default_image_size,
            "gps_max_tolerance_seconds": settings.gps_max_tolerance_seconds,
            "aggregation_radius_m": settings.aggregation_radius_m,
            "sim_corridor_angle_deg": settings.sim_corridor_angle_deg,
        },
        "limits": {
            "max_upload_mb": settings.max_upload_mb,
            "allowed_video_extensions": settings.video_extension_list,
            "allowed_gps_extensions": settings.gps_extension_list,
        },
        "storage": {
            "uploads_dir": "data/uploads",
            "processed_dir": "data/processed",
        },
        "privacy": {
            "local_inference": True,
            "statement": "LOCAL INFERENCE · VIDEO STAYS ON THIS MACHINE",
            "tile_provider": "Esri World Imagery satellite (default) or OpenStreetMap street — map viewport is revealed to the selected tile provider",
        },
    }
