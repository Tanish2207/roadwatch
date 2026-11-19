"""Geometry helpers: Haversine distance, bearing, linear interpolation."""
from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2, in degrees [0, 360)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)

    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def interpolate_lat_lon(
    lat1: float, lon1: float, lat2: float, lon2: float, fraction: float
) -> tuple[float, float]:
    """Linear interpolation between two close points (fine for short spans)."""
    fraction = max(0.0, min(1.0, fraction))
    return (
        lat1 + (lat2 - lat1) * fraction,
        lon1 + (lon2 - lon1) * fraction,
    )


def offset_along_heading(
    lat: float, lon: float, heading_deg: float, distance_m: float
) -> tuple[float, float]:
    """Move a point forward along a compass heading by distance_m (flat-earth approx)."""
    heading = math.radians(heading_deg)
    d_north = distance_m * math.sin(heading)
    d_east = distance_m * math.cos(heading)

    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat))
    return (lat + d_north / m_per_deg_lat, lon + d_east / m_per_deg_lon)


def angle_between_headings(a: float, b: float) -> float:
    """Smallest absolute difference between two compass bearings, in degrees [0, 180]."""
    diff = abs((a - b) % 360)
    return min(diff, 360 - diff)
