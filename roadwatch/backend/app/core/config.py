"""Application configuration loaded from environment / .env file."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents: core(0) app(1) backend(2) roadwatch(3)
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_prefix="ROADWATCH_",
        extra="ignore",
    )

    app_name: str = "RoadWatch API"
    environment: str = "local"

    # Paths
    data_dir: Path = REPO_ROOT / "data"
    uploads_dir: Path = REPO_ROOT / "data" / "uploads"
    processed_dir: Path = REPO_ROOT / "data" / "processed"
    demo_dir: Path = REPO_ROOT / "data" / "demo"
    database_dir: Path = REPO_ROOT / "data" / "database"
    models_dir: Path = REPO_ROOT / "models"

    database_filename: str = "roadwatch.db"
    model_path: str = ""  # explicit override; otherwise auto-discovered

    # Upload validation
    max_upload_mb: int = 512
    allowed_video_extensions: str = ".mp4,.avi,.mov,.mkv,.webm"
    allowed_gps_extensions: str = ".csv,.gpx"

    # Inference defaults
    default_sample_rate_fps: float = 1.0
    default_confidence_threshold: float = 0.4
    default_image_size: int = 640

    # GPS matching
    gps_max_tolerance_seconds: float = 5.0

    # Aggregation
    aggregation_radius_m: float = 15.0

    # Route simulation alerts
    sim_corridor_angle_deg: float = 60.0  # forward half-angle of the alert corridor

    # CORS
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    # Worker
    max_concurrent_jobs: int = 1

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.database_dir / self.database_filename).as_posix()}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def video_extension_list(self) -> list[str]:
        return [e.strip().lower() for e in self.allowed_video_extensions.split(",") if e.strip()]

    @property
    def gps_extension_list(self) -> list[str]:
        return [e.strip().lower() for e in self.allowed_gps_extensions.split(",") if e.strip()]

    def ensure_directories(self) -> None:
        for d in (
            self.data_dir,
            self.uploads_dir,
            self.processed_dir,
            self.demo_dir,
            self.database_dir,
            self.models_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
