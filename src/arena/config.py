"""Load params.yaml, the single file that holds every setting."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_params(path: Path | None = None) -> dict:
    with open(path or REPO_ROOT / "params.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)
