"""Vantage Bot configuration management.

Config is stored in ``data/config.json``.  The file is created automatically
on first run by ``launcher.py setup``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

CONFIG_PATH = Path("data/config.json")

DEFAULT_CONFIG: Dict[str, Any] = {
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
