"""vprod Bot configuration management.

Config is stored in the resolved data directory (see :func:`resolve_data_dir`).
The bot token is read exclusively from the ``DISCORD_TOKEN`` environment
variable (or from a ``.env`` file in the project root via python-dotenv).

Data directory resolution order
--------------------------------
1. ``VPROD_DATA_DIR`` environment variable (explicit override).
2. ``/var/lib/vprod/`` when the code lives under ``/opt/vprod/``.
3. Local ``data/`` directory (development fallback).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


def _load_dotenv() -> None:
    """Load a .env file from the project root if python-dotenv is available."""
    try:
        from dotenv import load_dotenv
        env_file = Path(__file__).resolve().parents[1] / ".env"
        load_dotenv(dotenv_path=env_file, override=False)
    except ImportError:
        pass


_load_dotenv()


def resolve_data_dir() -> Path:
    """Return the data directory to use for this bot instance.

    Resolution order:

    1. ``VPROD_DATA_DIR`` environment variable — explicit override.
    2. ``/var/lib/vprod/`` when this file is located under
       ``/opt/vprod/`` (production layout).
    3. ``data/`` relative to the project root (development fallback).
    """
    # 1 — explicit env var
    env_dir = os.environ.get("VPROD_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir)

    # 2 — production layout: code lives at /opt/vprod/
    this_file = Path(__file__).resolve()
    try:
        opt_vprod = Path("/opt/vprod")
        parts = this_file.parts
        opt_parts = opt_vprod.parts
        if parts[: len(opt_parts)] == opt_parts and len(parts) > len(opt_parts):
            return Path("/var/lib/vprod")
    except Exception:
        pass

    # 3 — development fallback: data/ next to the project root
    return Path(__file__).resolve().parents[1] / "data"


DATA_DIR = resolve_data_dir()
CONFIG_PATH = DATA_DIR / "config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "name": "vprod",
    "service_name": "vprod",
    "prefix": "!",
    "owner_ids": [],
    "description": "vprod — Vantage Discord Bot",
    "status": "online",
    "activity": "{prefix}help for commands",
}


def get_token() -> str:
    """Return the bot token from the environment.

    Reads ``DISCORD_TOKEN`` from the environment (populated from ``.env``
    at import time).  Raises :class:`RuntimeError` if the variable is unset
    or empty.
    """
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN is not set.  "
            "Add it to your .env file or export it in the shell before starting the bot."
        )
    return token


def load_config() -> Dict[str, Any]:
    """Load config from disk, merging with defaults."""
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG.copy()
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    return {**DEFAULT_CONFIG, **data}


def save_config(config: Dict[str, Any]) -> None:
    """Persist config to disk (token is never written to config.json)."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Strip the token field if someone accidentally put it in config — it lives
    # in .env only.
    safe = {k: v for k, v in config.items() if k != "token"}
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(safe, fh, indent=2)
