from __future__ import annotations

import csv
import random
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "kagglehub_cache" / "datasets" / "andrewmvd" / "pothole-detection" / "versions" / "1"
DEST = ROOT / "data" / "training" / "pothole_120"
SEED = 20261119
SPLIT_SIZES = {"train": 90, "val": 15, "test": 15}


def parse_annotation(xml_path: Path, width: int, height: int) -> list[str]:
    root = ET.parse(xml_path).getroot()
    rows: list[str] = []
    for obj in root.findall("object"):
        name = (obj.findtext("name") or "").strip().lower()
        if name != "pothole":
            continue
        box = obj.find("bndbox")
        if box is None:
            continue
        xmin, ymin, xmax, ymax = (float(box.findtext(k, "0")) for k in ("xmin", "ymin", "xmax", "ymax"))
        xmin, xmax = max(0.0, xmin), min(float(width), xmax)
        ymin, ymax = max(0.0, ymin), min(float(height), ymax)
        if xmax <= xmin or ymax <= ymin:
            continue
        xc, yc = (xmin + xmax) / 2 / width, (ymin + ymax) / 2 / height
        bw, bh = (xmax - xmin) / width, (ymax - ymin) / height
        rows.append(f"0 {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}")
    return rows


def main() -> None:
    images_dir, annotations_dir = SOURCE / "images", SOURCE / "annotations"
    pairs = []
    for image in images_dir.iterdir():
        if not image.is_file():
            continue
        xml = annotations_dir / f"{image.stem}.xml"
        if xml.is_file():
            root = ET.parse(xml).getroot()
            size = root.find("size")
            if size is None:
                continue
            width, height = int(size.findtext("width", "0")), int(size.findtext("height", "0"))
            labels = parse_annotation(xml, width, height) if width > 0 and height > 0 else []
            if labels:
                pairs.append((image, labels))
    random.Random(SEED).shuffle(pairs)
    requested = sum(SPLIT_SIZES.values())
    if len(pairs) < requested:
        raise RuntimeError(f"Found only {len(pairs)} labeled image/annotation pairs; need {requested}.")
    pairs = pairs[:requested]

    # Rebuild only this generated subset so repeated runs use the same fixed sample.
    if DEST.exists():
        shutil.rmtree(DEST)
    manifest = []
    offset = 0
    for split, count in SPLIT_SIZES.items():
        for image, labels in pairs[offset:offset + count]:
            target_images = DEST / "images" / split
            target_labels = DEST / "labels" / split
            target_images.mkdir(parents=True, exist_ok=True)
            target_labels.mkdir(parents=True, exist_ok=True)
            shutil.copy2(image, target_images / image.name)
            (target_labels / f"{image.stem}.txt").write_text("\n".join(labels) + "\n", encoding="utf-8")
            manifest.append({"split": split, "image": image.name, "boxes": len(labels)})
        offset += count

    data_yaml = DEST / "data.yaml"
    data_yaml.write_text(
        f"path: {DEST.as_posix()}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: pothole\n",
        encoding="utf-8",
    )
    with (DEST / "manifest.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=("split", "image", "boxes"))
        writer.writeheader()
        writer.writerows(manifest)
    print(f"Prepared {len(manifest)} images at {DEST}")
    for split, n in SPLIT_SIZES.items():
        subset = manifest[sum(list(SPLIT_SIZES.values())[:list(SPLIT_SIZES).index(split)]):][:n]
        print(f"{split}: {len(subset)} images, {sum(int(row['boxes']) for row in subset)} pothole boxes")


if __name__ == "__main__":
    main()
