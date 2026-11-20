"""Configuration shared by the HTTP app and the local worker."""
from pathlib import Path
import os

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_settings():
    path = Path(os.environ.get("ASSETGATE_CONFIG", ROOT / "configs/assetgate.yaml"))
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def storage_root(settings):
    folder = os.environ.get("ASSETGATE_STORAGE", settings["storage"])
    return (ROOT / folder).resolve()
