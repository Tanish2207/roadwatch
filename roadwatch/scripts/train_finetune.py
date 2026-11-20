from __future__ import annotations

import json
from pathlib import Path

import torch
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "training" / "pothole_120" / "data.yaml"
START = ROOT / "models" / "best.pt"
RUNS = ROOT / "runs" / "finetune"


def main() -> None:
    if not DATA.is_file() or not START.is_file():
        raise FileNotFoundError("Need the prepared pothole_120 data.yaml and models/best.pt checkpoint.")

    # Keep the run reproducible and modest for the available CPU-only PyTorch environment.
    torch.manual_seed(20261119)
    torch.set_num_threads(min(8, torch.get_num_threads()))
    model = YOLO(str(START))
    print(f"Starting from {START.name}; classes={model.names}; torch={torch.__version__}; cuda={torch.cuda.is_available()}")

    train_result = model.train(
        data=str(DATA),
        epochs=8,
        patience=3,
        imgsz=416,
        batch=4,
        device="cpu",
        workers=0,
        seed=20261119,
        deterministic=True,
        amp=False,
        close_mosaic=2,
        project=str(RUNS),
        name="andrewmvd-120",
        exist_ok=True,
        plots=True,
        save=True,
        verbose=True,
    )
    best = Path(train_result.save_dir) / "weights" / "best.pt"
    last = Path(train_result.save_dir) / "weights" / "last.pt"
    if not best.is_file():
        raise RuntimeError(f"Training did not produce {best}")

    summary = {
        "starting_checkpoint": str(START),
        "dataset": str(DATA),
        "sample_images": 120,
        "train_images": 90,
        "validation_images": 15,
        "test_images": 15,
        "epochs_requested": 8,
        "image_size": 416,
        "batch_size": 4,
        "device": "cpu",
        "best_weights": str(best),
        "last_weights": str(last),
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
    }
    (Path(train_result.save_dir) / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Measure both checkpoints on the same held-out subset.
    metrics = {}
    for label, weights in (("original", START), ("finetuned", best)):
        candidate = YOLO(str(weights))
        scores = candidate.val(
            data=str(DATA),
            split="test",
            imgsz=416,
            batch=4,
            device="cpu",
            workers=0,
            plots=True,
            project=str(RUNS),
            name=f"test_{label}",
            exist_ok=True,
            verbose=False,
        )
        box = scores.box
        metrics[label] = {
            "precision": float(box.mp),
            "recall": float(box.mr),
            "mAP50": float(box.map50),
            "mAP50_95": float(box.map),
        }
    (Path(train_result.save_dir) / "test_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print("TEST METRICS", json.dumps(metrics, indent=2))
    print(f"BEST_WEIGHTS={best}")


if __name__ == "__main__":
    main()
