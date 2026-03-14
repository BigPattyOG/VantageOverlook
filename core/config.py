"""Vantage Bot configuration management.

Config is stored in the resolved data directory (see :func:`resolve_data_dir`).
The file is created automatically on first run by ``launcher.py setup``.

Data directory resolution order
--------------------------------
1. ``VANTAGE_DATA_DIR`` environment variable (explicit override).
2. ``/var/lib/vantage/<name>/`` when the code lives under ``/opt/vantage/``.
3. Local ``data/`` directory (development fallback).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List


def resolve_data_dir() -> Path:
    """Return the data directory to use for this bot instance.

    Resolution order:

    1. ``VANTAGE_DATA_DIR`` environment variable — explicit override.
    2. ``/var/lib/vantage/<name>/`` when this file is located under
       ``/opt/vantage/<name>/`` (production layout).
    3. ``data/`` relative to the project root (development fallback).
    """
    # 1 — explicit env var
    env_dir = os.environ.get("VANTAGE_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir)

    # 2 — production layout: code lives at /opt/vantage/<BotName>/...
    this_file = Path(__file__).resolve()
    try:
        opt_vantage = Path("/opt/vantage")
        # Walk up until we find the direct child of /opt/vantage
        parts = this_file.parts
        opt_parts = opt_vantage.parts
        if parts[: len(opt_parts)] == opt_parts and len(parts) > len(opt_parts):
            bot_name = parts[len(opt_parts)]  # e.g. "MyBot"
            return Path("/var/lib/vantage") / bot_name
    except Exception:
        pass

    # 3 — development fallback: data/ next to the project root
    return Path(__file__).resolve().parents[1] / "data"


DATA_DIR = resolve_data_dir()
CONFIG_PATH = DATA_DIR / "config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "name": "Vantage",
    "service_name": "vantage",
    "token": "",
    "prefix": "!",
    "owner_ids": [],
    "description": "Vantage — a custom Discord bot framework",
    "status": "online",
    "activity": "{prefix}help for commands",
}


def load_config() -> Dict[str, Any]:
    """Load config from disk, merging with defaults."""
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG.copy()
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    return {**DEFAULT_CONFIG, **data}


def save_config(config: Dict[str, Any]) -> None:
    """Persist config to disk."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
