"""Generate two extra demo routes for the M7 simulation picker.

- east-run:   heading 90 deg from the demo anchor (hazards off to the side)
- return-pass: drives BACK along the potholed road (heading ~225 deg), so the
              same hazards are approached from the opposite direction.

Both: 26 points, 1 Hz, 8 m/s with small GPS-like jitter; distance_m computed
with Haversine over the emitted points.
"""
import json
import math
import random
from pathlib import Path

R = 6371000.0
OUT = Path(__file__).resolve().parents[1] / "data" / "demo" / "routes"
ANCHOR = (-4.275002, 21.542498)
SPEED_MPS = 8.0
POINTS = 26


def haversine(a, b):
    p1, l1 = math.radians(a[0]), math.radians(a[1])
    p2, l2 = math.radians(b[0]), math.radians(b[1])
    dp, dl = p2 - p1, l2 - l1
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def move(pt, bearing_deg, dist_m):
    d = dist_m / R
    b = math.radians(bearing_deg)
    p1, l1 = math.radians(pt[0]), math.radians(pt[1])
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(
        math.sin(b) * math.sin(d) * math.cos(p1),
        math.cos(d) - math.sin(p1) * math.sin(p2),
    )
    return (math.degrees(p2), math.degrees(l2))


def build(route_id, name, description, start, heading, seed):
    rng = random.Random(seed)
    cos_lat = math.cos(math.radians(start[0]))
    pts, cur = [], start
    total = 0.0
    for i in range(POINTS):
        jlat = rng.uniform(-0.35, 0.35) / 111194.0
        jlon = rng.uniform(-0.35, 0.35) / (111194.0 * cos_lat)
        pts.append({
            "lat": round(cur[0] + jlat, 6),
            "lon": round(cur[1] + jlon, 6),
            "timestamp_seconds": i,
        })
        if i > 0:
            total += haversine((pts[-2]["lat"], pts[-2]["lon"]), (pts[-1]["lat"], pts[-1]["lon"]))
        if i < POINTS - 1:
            cur = move(cur, heading, SPEED_MPS)
    return {
        "id": route_id,
        "name": name,
        "description": description,
        "is_synthetic": True,
        "distance_m": round(total, 1),
        "points": pts,
    }


# Return pass starts where the original potholed road ends, heading back.
original = json.loads((OUT / "potholed_road.json").read_text(encoding="utf-8"))
op = original["points"]
back_lat, back_lon = op[-1]["lat"], op[-1]["lon"]
fwd = math.degrees(math.atan2(
    math.radians(back_lon - op[-2]["lon"]) * math.cos(math.radians(back_lat)),
    math.radians(back_lat - op[-2]["lat"]),
))
return_heading = (fwd + 180.0) % 360.0

routes = [
    build(
        "east-run",
        "East Run (synthetic)",
        "Eastbound from the demo anchor at 8 m/s — hazards sit off to the side.",
        ANCHOR, 90.0, seed=7,
    ),
    build(
        "return-pass",
        "Return Pass (synthetic)",
        "Westbound return along the potholed road at 8 m/s, approaching the same hazards from behind.",
        (back_lat, back_lon), return_heading, seed=11,
    ),
]

for r in routes:
    path = OUT / f"{r['id']}.json"
    path.write_text(json.dumps(r, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.name}: {len(r['points'])} pts, {r['distance_m']} m, heading-ok")
