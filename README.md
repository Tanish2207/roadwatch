# RoadWatch

Local-first AI road-hazard detection and mapping platform. Processes dashcam
footage **on this machine only** with a locally loaded YOLO model, associates
detections with GPS, consolidates repeats into deduplicated hazard records,
renders them on a Leaflet map (satellite imagery by default, switchable to a
labelled satellite view or street view), and simulates driving a demo route to
raise non-repeating hazard alerts.

> **Prototype.** All ML inference, video, GPS and hazard data stay local.
> The only external traffic is map tiles — Esri satellite by default,
> switchable to OpenStreetMap street view (a loaded map reveals your viewport
> to the tile provider). Alerts are experimental and must not be the sole
> basis for driving decisions.

## Repository layout

| Path | Contents |
| --- | --- |
| [`roadwatch/backend/`](roadwatch/backend/) | FastAPI app: upload → local YOLO inference → GPS matching → aggregation → hazard map API → simulation alert API, plus test suite |
| [`roadwatch/frontend/`](roadwatch/frontend/) | React 19 + TypeScript + Vite dashboard: detection studio, hazard map (Leaflet + satellite tiles, clustering), route simulation, settings |
| [`roadwatch/data/demo/`](roadwatch/data/demo/) | Seeded demo GPS CSV + three synthetic simulation routes |
| [`roadwatch/scripts/`](roadwatch/scripts/) | Demo data generators (GPS CSV, routes) + `clear_database.py` to empty the app database |
| `main.py` / `main.ipynb` | Model training / exploration notebook |
| `RoadWatch_End_to_End_Developer_Brief.pdf` | Project specification |

## Quick start

```powershell
# Backend (port 8000)
cd roadwatch\backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Frontend (port 5173, proxies /api → :8000)
cd ..\frontend
npm install
npm run dev
```

Open **http://localhost:5173**. Full setup, model-weight provisioning, API
reference, GPS format and milestone details: **[roadwatch/README.md](roadwatch/README.md)**.

## Tests

```powershell
cd roadwatch\backend && python -m pytest   # unit + smoke + map/simulation API tests
cd ..\frontend && npm test                 # vitest: geo utils, map, simulation UI
```

## Local and shared artifacts

The starting YOLO checkpoint, fine-tuned checkpoint, and selected training/evaluation reports are included under `roadwatch/models/` and `roadwatch/runs/`. Dataset downloads, prepared training images, caches, uploads, `.env`, databases, and logs remain local and are git-ignored.