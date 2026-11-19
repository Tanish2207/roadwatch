from huggingface_hub import hf_hub_download

weights_path = hf_hub_download(
    repo_id="Samdutse/pothole-yolov8",
    filename="best.pt"
)

print(weights_path)