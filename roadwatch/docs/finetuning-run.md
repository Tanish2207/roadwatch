# RoadWatch fine-tuning run: Kaggle pothole sample

## Run details

- Dataset: [`andrewmvd/pothole-detection`](https://www.kaggle.com/datasets/andrewmvd/pothole-detection), fetched with KaggleHub. It contains 665 images paired with Pascal VOC XML bounding boxes.
- Sample: 120 images picked with seed `20261119`; 90 train, 15 validation, 15 test (341 labeled boxes).
- Starting checkpoint: `models/best.pt`, the YOLOv8s pothole checkpoint referenced in the project README and downloaded from [Hugging Face](https://huggingface.co/Samdutse/pothole-yolov8).
- Training: Ultralytics, 416 px, batch 4, CPU. Early stopping halted at epoch 4; best validation weights came from epoch 1.
- Output: `models/roadwatch-pothole-finetuned.pt` (22.5 MB). Run plots and metrics are saved in `runs/finetune/andrewmvd-120/`.

## Test subset comparison

| Weights | Precision | Recall | mAP50 | mAP50-95 |
|---|---:|---:|---:|---:|
| Original | 1.000 | 0.865 | 0.9522 | 0.6557 |
| Fine-tuned | 0.833 | 0.926 | 0.9495 | 0.6503 |

The new checkpoint found more labeled potholes but also produced more false detections. Its aggregate test metrics were slightly lower, so the original `models/best.pt` remains the default. To try the fine-tuned checkpoint, set `ROADWATCH_MODEL_PATH` to its absolute path.

This small run demonstrates the training pipeline; it does not establish improved performance on new dashcam footage. The checkpoint card says it was already fine-tuned on a pothole dataset from Roboflow Universe, so the Kaggle images may overlap with its training data. A reliable comparison needs fresh, labeled footage from the roads/camera RoadWatch will use. Check the dataset and model terms before redistributing images or weights.

## Reproduce

From the outer repository root:

```powershell
python -m pip install kagglehub
python roadwatch/scripts/download_kaggle_dataset.py
python roadwatch/scripts/prepare_kaggle_subset.py
python roadwatch/scripts/train_finetune.py
```

Ultralytics and PyTorch are already project dependencies. The checkpoints are included in `models/`; training metrics, curves, configuration, and summary files are included in `runs/finetune/`. Dataset downloads, prepared images, caches, duplicate run checkpoints, and image previews are git-ignored.
