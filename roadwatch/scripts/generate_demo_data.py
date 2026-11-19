"""Generate demo GPS data: sidecar CSV + synthetic route for the simulation.

The route starts at a user-supplied anchor coordinate and walks forward at a
constant speed with small GPS-like jitter, so it can be matched against a
25-second dashcam clip.

Usage (from roadwatch/):
    python scripts/generate_demo_data.py
"""
from __future__ import annotations

import csv
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = REPO_ROOT / "data" / "demo"
ROUTES_DIR = DEMO_DIR / "routes"

# --- Route anchor ---------------------------------------------------------
# NOTE: user-provided longitude 215.425 is invalid (valid: -180..180);
# normalized to 21.5425 (see README/demo notes).
ANCHOR_LAT = -4.275000
ANCHOR_LON = 21.542500

START_TIME = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
DURATION_S = 26          # covers the 25.52 s clip
SPEED_MPS = 8.0          # typical urban driving speed
HEADING_DEG = 45.0       # north-east
JITTER_M = 1.2           # simulated GPS noise (~1 m, like a real receiver)

# metres per degree
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(ANCHOR_LAT))


def build_track() -> list[dict]:
    rng = random.Random(42)  # deterministic demo data
    rows: list[dict] = []
    heading = math.radians(HEADING_DEG)

    for t in range(DURATION_S):
        # ideal position at t seconds along the heading
        dist = SPEED_MPS * t
        d_north = dist * math.sin(heading)
        d_east = dist * math.cos(heading)

        # jitter in metres -> degrees
        j_north = rng.gauss(0, JITTER_M)
        j_east = rng.gauss(0, JITTER_M)

        lat = ANCHOR_LAT + (d_north + j_north) / M_PER_DEG_LAT
        lon = ANCHOR_LON + (d_east + j_east) / M_PER_DEG_LON

        speed = SPEED_MPS + rng.gauss(0, 0.3)
        heading_deg = (HEADING_DEG + rng.gauss(0, 2)) % 360

        rows.append(
            {
                "timestamp": (START_TIME + timedelta(seconds=t)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "latitude": round(lat, 6),
                "longitude": round(lon, 6),
                "speed_mps": round(speed, 2),
                "heading_deg": round(heading_deg, 1),
            }
        )
    return rows


def main() -> None:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    ROUTES_DIR.mkdir(parents=True, exist_ok=True)

    rows = build_track()

    # 1. GPS sidecar CSV for video association
    csv_path = DEMO_DIR / "potholedRoad_gps.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["timestamp", "latitude", "longitude", "speed_mps", "heading_deg"]
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {csv_path.relative_to(REPO_ROOT)} ({len(rows)} rows)")

    # 2. Demo route for the simulator (same track, stored as route JSON)
    total_m = SPEED_MPS * (DURATION_S - 1)
    route = {
        "id": "potholed-road",
        "name": "Potholed Road (synthetic)",
        "description": f"Synthetic {DURATION_S} s track near the demo anchor, {SPEED_MPS:.0f} m/s.",
        "is_synthetic": True,
        "distance_m": round(total_m, 1),
        "points": [
            {
                "lat": r["latitude"],
                "lon": r["longitude"],
                "timestamp_seconds": i,
            }
            for i, r in enumerate(rows)
        ],
    }
    route_path = ROUTES_DIR / "potholed_road.json"
    route_path.write_text(json.dumps(route, indent=2), encoding="utf-8")
    print(f"wrote {route_path.relative_to(REPO_ROOT)} ({len(route['points'])} points)")


if __name__ == "__main__":
    main()
