# RoadWatch

Local-first AI road-hazard detection and mapping platform. Processes dashcam
footage **on this machine only**, detects potholes with a locally loaded YOLO
model, associates detections with GPS, consolidates repeats into deduplicated
hazard records, and displays them on a browsable map with route simulation and
alerts.

> **Prototype status.** All data is local. Map tiles come from Esri World
> Imagery satellite by default, switchable to OpenStreetMap street view
> (loading a map reveals your viewport to the tile provider). Alerts are
> experimental and must not be the sole basis for driving decisions.

## Prerequisites

- Python 3.11+ (tested on 3.12)
- Node.js 18+ (tested on 24)
- FFmpeg optional but recommended (video export); already on this machine

## Setup

```powershell
# Backend — reuses the existing project venv (torch/ultralytics/opencv included)
# or create a fresh one:
cd roadwatch\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # Windows
pip install -r requirements.txt

# Frontend
cd ..\frontend
npm install
```

## Configuration

Copy `.env.example` to `.env` and adjust. Key variable:

| Variable | Purpose |
| --- | --- |
| `ROADWATCH_MODEL_PATH` | Absolute path to YOLO `.pt` weights. Empty ⇒ auto-discover `models/*.pt` |
| `ROADWATCH_MAX_UPLOAD_MB` | Upload size cap (default 512) |
| `ROADWATCH_DEFAULT_*` | Sampling rate, confidence threshold, image size defaults |

## Model weight setup

Weights are **not** committed to git. Provide them in either way:

1. Set `ROADWATCH_MODEL_PATH` in `.env`, or
2. Drop `best.pt` into `roadwatch/models/`.

This project uses the HuggingFace checkpoint
[`Samdutse/pothole-yolov8`](https://huggingface.co/Samdutse/pothole-yolov8)
(`best.pt`). **License: check the model card before redistribution** — the
checkpoint's license terms apply to derived deployments. The current `.env`
points at the locally cached snapshot.

Runtime inference is fully offline once weights are present.

## Run

```powershell
# Terminal 1 — backend (port 8000)
cd roadwatch\backend
& <venv>\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Terminal 2 — frontend (port 5173, proxies /api to :8000)
cd roadwatch\frontend
npm run dev
```

Open **http://localhost:5173**. API docs at **http://127.0.0.1:8000/docs**.

## Tests

```powershell
cd roadwatch\backend
python -m pytest        # 53 tests: units, smoke, hazard filters, simulation alerts
cd ..\frontend
npm test                # vitest: geo/marker-size utils, map filters/drawer, playback + alert feed
npm run build           # type-check + production build
```

## Reset the database

Empty every job, hazard, observation and status-history row. The schema is
kept, so the API starts up empty and works normally — data returns only when
you process a video again. Nothing re-seeds on startup.

```powershell
cd roadwatch
python scripts/clear_database.py              # timestamped backup, then clear
python scripts/clear_database.py --no-backup  # skip the backup
```

A backup is written to `data/database/backups/` first; stop the backend if it
is running (it can hold the database file).

## Hazard map (M6)

- Leaflet with switchable base layers — Esri World Imagery satellite (the
  default), the same satellite view with place/road labels, or OpenStreetMap
  street view; no API key — plus neo-brutalist marker/cluster styling and
  marker clustering on the map page.
- Markers keep one simple badge shape in **three size tiers** — small (16 px),
  medium (22 px), severe (30 px) — chosen from the YOLO bounding box: the
  backend stores each hazard's mean bbox area as a fraction of the source
  frame (`bbox_area_frac`, so hazards from different video resolutions stay
  comparable) and the frontend maps it to a tier (`src/utils/hazardSize.ts`:
  <3 % small, 3–12 % medium, ≥12 % severe, unknown ⇒ medium). Run
  `python scripts/backfill_pixel_area.py` (from `roadwatch/`) once to size
  hazards that were aggregated before area tracking existed.
- Filters: status, min confidence, min reports, time range — all evaluated by
  the backend `GET /api/hazards` query.
- Clicking a marker opens the detail drawer: observation summaries (capped at
  50 embedded, full count shown), status history (latest 20), approximate
  location uncertainty, and resolve/reopen controls with an optional note
  (`PATCH /api/hazards/{id}`, audited into status history).

## Route simulation (M7)

- The simulated vehicle interpolates its position locally along a demo route
  (play/pause/reset, configurable speed and warning radius); it is clearly
  labeled **simulated** — no live vehicle telemetry.
- Each playback tick asks the backend (`POST /api/simulation/alerts`) which
  hazards just became eligible: Haversine distance ≤ warning radius, inside an
  approximate forward corridor (heading-angle threshold,
  `ROADWATCH_SIM_CORRIDOR_ANGLE_DEG`, default ±60°), resolved hazards skipped,
  and per-session dedup so a hazard alerts **at most once per run**
  (`POST /api/simulation/start` resets the dedup set).
- The alert feed shows distance, report count, status and bearing, and labels
  the corridor filter as approximate.
- Demo routes live in `data/demo/routes/*.json` (currently `potholed-road`,
  `east-run`, `return-pass`). Drop in another JSON file with the same shape
  and it appears in the route picker without restarting the backend.

## API overview

| Method & route | Purpose |
| --- | --- |
| `GET /api/health` | Backend, DB, model readiness |
| `GET /api/settings` | Model status, inference defaults, limits, privacy |
| `GET /api/jobs` / `GET /api/jobs/{id}` | Job list / detail |
| `GET /api/hazards` | Hazard map query (status, min confidence/reports, time range, bbox) |
| `GET /api/hazards/{id}` | Hazard detail (observations, status history) |
| `PATCH /api/hazards/{id}` | Update hazard status (resolve/reopen, note) |
| `GET /api/simulation/routes` / `GET /api/simulation/routes/{id}` | Demo routes (metadata / full points) |
| `POST /api/simulation/start` / `/stop` | Simulation session control (per-run alert dedup) |
| `POST /api/simulation/alerts` | Hazards eligible for an alert at the current vehicle pose |

## GPS sidecar CSV format

```csv
timestamp,latitude,longitude,speed_mps,heading_deg
2026-01-01T10:00:00Z,19.07610,72.87700,8.2,90
2026-01-01T10:00:01Z,19.07616,72.87708,8.4,90
```

`timestamp` ISO-8601 (or epoch seconds), `latitude`/`longitude` required;
`altitude`, `speed_mps`, `heading_deg` optional. Full format notes: see
`docs/gps-format.md` (arrives with the GPS milestone).

## Known limitations

- GPS association is approximate (nearest-timestamp ±5 s tolerance, interpolation
  between points); reported coordinates are vehicle position, not pothole position.
- No metric pothole dimensions or depth without camera calibration — pixel
  measurements only, labeled as such.
- False positives/negatives possible; confidence is always displayed.
- No dashcam hardware integration, cloud sync, accounts or mobile app (MVP scope).

## Privacy

Video, frames, GPS and inference stay on this machine. No third-party AI
services. Only external traffic: map tiles (Esri satellite or OpenStreetMap
street view) when a map is open.

## Fine-tuning

A small fine-tuning example using the Kaggle pothole dataset is documented in
[`docs/finetuning-run.md`](docs/finetuning-run.md). The preparation and training
scripts are in `scripts/download_kaggle_dataset.py`, `scripts/prepare_kaggle_subset.py`, and `scripts/train_finetune.py`.
