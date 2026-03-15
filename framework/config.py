"""vprod Bot configuration management.

Config is stored in the resolved data directory (see :func:`resolve_data_dir`).
The bot token is read exclusively from the ``DISCORD_TOKEN`` environment
variable (or from a ``.env`` file in the project root via python-dotenv).

Data directory resolution order
--------------------------------
1. ``VPROD_DATA_DIR`` environment variable (explicit override).
2. ``/var/lib/<name>/`` when the code lives under ``/opt/<name>/`` (e.g. ``/opt/vprod/`` or ``/opt/vdev/``).
3. Local ``data/`` directory (development fallback).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


def resolve_data_dir() -> Path:
    """Return the data directory to use for this bot instance.

    Resolution order:

    1. ``VPROD_DATA_DIR`` environment variable — explicit override.
    2. ``/var/lib/<install-dir-name>/`` when this file is located under
       ``/opt/<install-dir-name>/`` (production layout — works for both
       ``/opt/vprod/`` and ``/opt/vdev/`` installs).
    3. ``data/`` relative to the project root (development fallback).
    """
    # 1 — explicit env var
    env_dir = os.environ.get("VPROD_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir)

    # 2 — production layout: code lives under /opt/<name>/
    # Use the install directory name so both /opt/vprod → /var/lib/vprod
    # and /opt/vdev → /var/lib/vdev work without extra configuration.
    this_file = Path(__file__).resolve()
    try:
        install_dir = this_file.parents[1]  # e.g. /opt/vprod or /opt/vdev
        if install_dir.parent == Path("/opt"):
            candidate = Path("/var/lib") / install_dir.name
            if candidate.exists():
                return candidate
    except Exception:
        pass

    # 3 — development fallback: data/ next to the project root
    return Path(__file__).resolve().parents[1] / "data"


DATA_DIR = resolve_data_dir()
CONFIG_PATH = DATA_DIR / "config.json"


def _load_dotenv() -> None:
    """Load .env files using python-dotenv if available.

    Resolution order (first match wins — ``override=False`` means an
    already-set env var is never overwritten):

    1. ``<DATA_DIR>/.env``   — production location written by install-vprod.sh;
                               lives outside the git directory so ``git pull``
                               can never wipe the token.
    2. Project-root ``.env`` — development / legacy location.
    """
    try:
        from dotenv import load_dotenv
        # 1 — production token location (outside git directory)
        data_env = DATA_DIR / ".env"
        if data_env.exists():
            load_dotenv(dotenv_path=data_env, override=False)
        # 2 — project-root .env (dev / legacy)
        root_env = Path(__file__).resolve().parents[1] / ".env"
        if root_env.exists():
            load_dotenv(dotenv_path=root_env, override=False)
    except ImportError:
        pass


_load_dotenv()


def resolve_ext_plugins_dir(config: Optional[Dict[str, Any]] = None) -> Path:
    """Return the external plugins directory.

    Resolution order:
    1. ``VPROD_PLUGINS_DIR`` environment variable.
    2. ``ext_plugins_dir`` key in *config* (absolute or relative to DATA_DIR).
    3. ``<data_dir>/ext_plugins/`` (default).
    """
    env_dir = os.environ.get("VPROD_PLUGINS_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    if config:
        cfg_dir = str(config.get("ext_plugins_dir", "")).strip()
        if cfg_dir:
            p = Path(cfg_dir)
            return p if p.is_absolute() else DATA_DIR / p
    return DATA_DIR / "ext_plugins"

DEFAULT_CONFIG: Dict[str, Any] = {
    "name": "vprod",
    "service_name": "vprod",
    "prefix": "!",
    "owner_ids": [],
    "description": "vprod — Vantage Discord Bot",
    "status": "online",
    "activity": "{prefix}help for commands",
    # Health-check endpoint — set health_port to 0 to disable.
    # health_host defaults to 127.0.0.1 (localhost); set to 0.0.0.0
    # to expose to external interfaces (e.g. a remote monitoring service).
    "health_port": 8080,
    "health_host": "0.0.0.0",
    # Maintenance mode — when True, non-owner commands are blocked.
    "maintenance": False,
    "maintenance_message": "",
    # External plugins directory — where your own custom plugins live.
    # Defaults to <data_dir>/ext_plugins/. Override with VPROD_PLUGINS_DIR
    # or set this key to an absolute path.
    "ext_plugins_dir": "",
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
