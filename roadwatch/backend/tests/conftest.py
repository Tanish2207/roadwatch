"""Test isolation: point the app at a throwaway database before import."""
from __future__ import annotations

import os
from pathlib import Path

# Must run before app.core.config is imported (settings are cached at import).
os.environ["ROADWATCH_DATABASE_FILENAME"] = "roadwatch_test.db"
os.environ["ROADWATCH_ENVIRONMENT"] = "test"

# Start each test session from a clean slate (assertions expect empty lists).
_test_db = Path(__file__).resolve().parents[2] / "data" / "database" / "roadwatch_test.db"
_test_db.parent.mkdir(parents=True, exist_ok=True)
if _test_db.exists():
    _test_db.unlink()
