"""GPS sidecar parsing and frame-timestamp association.

CSV format: timestamp,latitude,longitude[,altitude,speed_mps,heading_deg]
Timestamps: ISO-8601 (preferred) or epoch seconds; normalized to UTC.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.core.logging import get_logger
from app.utils.geometry import haversine_m, interpolate_lat_lon

log = get_logger(__name__)

MATCH_NEAREST = "nearest"
MATCH_INTERPOLATED = "interpolated"
MATCH_SIMULATED = "simulated"
MATCH_NONE = "none"

REQUIRED_COLUMNS = ("timestamp", "latitude", "longitude")


class GpsParseError(ValueError):
    """Raised for malformed GPS files (safe to show to the user)."""


@dataclass
class GpsPoint:
    time: datetime
    lat: float
    lon: float
    speed_mps: float | None = None
    heading_deg: float | None = None


@dataclass
class GpsMatch:
    lat: float | None
    lon: float | None
    method: str  # nearest | interpolated | simulated | none
    delta_seconds: float | None
    speed_mps: float | None = None
    heading_deg: float | None = None


def _parse_timestamp(value: object) -> datetime:
    # Epoch seconds (numeric) support
    if isinstance(value, (int, float)) and not pd.isna(value):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    ts = pd.to_datetime(value, utc=True, format="mixed")
    if pd.isna(ts):
        raise GpsParseError(f"Unparseable timestamp: {value!r}")
    return ts.to_pydatetime()


def load_gps_csv(path: Path) -> list[GpsPoint]:
    """Parse and validate a GPS sidecar CSV into sorted GpsPoints."""
    try:
        df = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001
        raise GpsParseError("GPS file is not a readable CSV.") from exc

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise GpsParseError(
            f"GPS CSV missing required column(s): {', '.join(missing)}. "
            "Expected header: timestamp,latitude,longitude[,speed_mps,heading_deg]"
        )

    points: list[GpsPoint] = []
    for idx, row in df.iterrows():
        try:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
        except (TypeError, ValueError) as exc:
            raise GpsParseError(f"Row {idx + 2}: latitude/longitude must be numeric.") from exc

        if not (-90.0 <= lat <= 90.0):
            raise GpsParseError(f"Row {idx + 2}: latitude {lat} out of range [-90, 90].")
        if not (-180.0 <= lon <= 180.0):
            raise GpsParseError(f"Row {idx + 2}: longitude {lon} out of range [-180, 180].")

        try:
            when = _parse_timestamp(row["timestamp"])
        except GpsParseError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GpsParseError(f"Row {idx + 2}: bad timestamp {row['timestamp']!r}.") from exc

        speed = _opt_float(row.get("speed_mps"))
        heading = _opt_float(row.get("heading_deg"))

        points.append(GpsPoint(time=when, lat=lat, lon=lon, speed_mps=speed, heading_deg=heading))

    if not points:
        raise GpsParseError("GPS CSV contains no data rows.")

    points.sort(key=lambda p: p.time)
    return points


def _opt_float(value: object) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def match_gps(
    frame_time: datetime,
    points: list[GpsPoint],
    max_tolerance_s: float = 5.0,
    video_start_offset_s: float = 0.0,
) -> GpsMatch:
    """Associate an absolute frame timestamp with GPS observations.

    - Exact/near match within tolerance -> nearest
    - Frame bracketed by two points and interpolation is possible -> interpolated
      (recording method + delta are still surfaced)
    - Otherwise -> none (never silently uses stale data)

    `video_start_offset_s` shifts frame_time backwards before matching when the
    GPS clock and video clock start at different epochs.
    """
    if not points:
        return GpsMatch(None, None, MATCH_NONE, None)

    target = frame_time
    if video_start_offset_s:
        from datetime import timedelta

        target = frame_time - timedelta(seconds=video_start_offset_s)

    # Binary search for the insertion point of target among sorted points.
    lo, hi = 0, len(points)
    while lo < hi:
        mid = (lo + hi) // 2
        if points[mid].time < target:
            lo = mid + 1
        else:
            hi = mid

    # lo is the first index with time >= target
    before = points[lo - 1] if lo > 0 else None
    after = points[lo] if lo < len(points) else None

    if before is None and after is None:
        return GpsMatch(None, None, MATCH_NONE, None)

    # Pick the closest point for a "nearest" candidate
    if before is None:
        cand, delta = after, abs((after.time - target).total_seconds())
    elif after is None:
        cand, delta = before, abs((before.time - target).total_seconds())
    else:
        d_before = abs((before.time - target).total_seconds())
        d_after = abs((after.time - target).total_seconds())
        if d_before <= d_after:
            cand, delta = before, d_before
        else:
            cand, delta = after, d_after

    # Strictly between two close fixes -> interpolate (exact hits stay "nearest")
    if (
        before is not None
        and after is not None
        and before.time < target < after.time
        and abs((before.time - target).total_seconds()) <= max_tolerance_s
        and abs((after.time - target).total_seconds()) <= max_tolerance_s
    ):
        span = (after.time - before.time).total_seconds()
        frac = 0.0 if span <= 0 else (target - before.time).total_seconds() / span
        lat, lon = interpolate_lat_lon(before.lat, before.lon, after.lat, after.lon, frac)
        return GpsMatch(
            lat=lat,
            lon=lon,
            method=MATCH_INTERPOLATED,
            delta_seconds=round(delta, 3),
            speed_mps=cand.speed_mps,
            heading_deg=cand.heading_deg,
        )

    if delta <= max_tolerance_s:
        return GpsMatch(
            lat=cand.lat,
            lon=cand.lon,
            method=MATCH_NEAREST,
            delta_seconds=round(delta, 3),
            speed_mps=cand.speed_mps,
            heading_deg=cand.heading_deg,
        )

    return GpsMatch(None, None, MATCH_NONE, round(delta, 3))


def simulate_route_match(
    frame_index: int, route_points: list[dict]
) -> GpsMatch:
    """Match a frame to a synthetic route by frame index (1 route point/sec)."""
    if not route_points:
        return GpsMatch(None, None, MATCH_NONE, None)
    idx = min(max(frame_index, 0), len(route_points) - 1)
    p = route_points[idx]
    return GpsMatch(
        lat=float(p["lat"]),
        lon=float(p["lon"]),
        method=MATCH_SIMULATED,
        delta_seconds=0.0,
    )


def route_points_near(
    lat: float, lon: float, route_points: list[dict], radius_m: float
) -> bool:
    return any(
        haversine_m(lat, lon, float(p["lat"]), float(p["lon"])) <= radius_m
        for p in route_points
    )
