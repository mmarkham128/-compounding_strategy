"""Configuration loader.

Reads config/config.yaml and overlays any secrets from environment variables so
API keys never live in the file or the repository.
"""

import os
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path) as f:
        cfg = yaml.safe_load(f)

    cfg.setdefault("blofin", {})
    cfg["blofin"]["api_key"] = os.environ.get("BLOFIN_API_KEY", cfg["blofin"].get("api_key"))
    cfg["blofin"]["api_secret"] = os.environ.get(
        "BLOFIN_API_SECRET", cfg["blofin"].get("api_secret")
    )
    cfg["blofin"]["api_passphrase"] = os.environ.get(
        "BLOFIN_API_PASSPHRASE", cfg["blofin"].get("api_passphrase")
    )
    return cfg
