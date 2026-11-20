from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Keep KaggleHub's cache in the project data directory rather than the user profile.
os.environ.setdefault("KAGGLEHUB_CACHE", str(ROOT / "data" / "kagglehub_cache"))

import kagglehub  # noqa: E402


def main() -> None:
    path = Path(kagglehub.dataset_download("andrewmvd/pothole-detection"))
    print(f"Dataset available at: {path}")
    print("Next: python scripts/prepare_kaggle_subset.py")


if __name__ == "__main__":
    main()
