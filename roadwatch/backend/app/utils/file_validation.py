"""Upload validation: extensions, size caps, safe storage names."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.core.config import settings

_SAFE_STEM = re.compile(r"[^A-Za-z0-9._-]+")


def validate_extension(filename: str, allowed: list[str]) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{ext or '?'}'. Allowed: {', '.join(allowed)}",
        )
    return ext


async def save_upload(upload: UploadFile, dest_dir: Path, allowed: list[str]) -> Path:
    """Stream an upload to disk with extension + size validation.

    Stored name is a generated UUID — the client filename never influences the
    storage path (no path traversal possible).
    """
    ext = validate_extension(upload.filename or "", allowed)
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest = dest_dir / f"{uuid.uuid4().hex}{ext}"
    max_bytes = settings.max_upload_mb * 1024 * 1024
    written = 0

    try:
        with dest.open("wb") as out:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the {settings.max_upload_mb} MB limit.",
                    )
                out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Failed to store uploaded file.") from exc

    if written == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    return dest


def safe_preview_name(original: str) -> str:
    """Sanitized display name for UI (never used as a path)."""
    stem = Path(original).stem
    return _SAFE_STEM.sub("_", stem)[:80] or "video"
