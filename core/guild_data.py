"""Per-guild JSON data storage for VantageBot.

Each guild gets its own file at ``<data_dir>/guilds/{guild_id}.json``.
Use :func:`load_guild` and :func:`save_guild` to read/write guild-specific
settings and state without touching the global ``config.json``.

The data directory is resolved via :func:`core.config.resolve_data_dir`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .config import resolve_data_dir

GUILDS_DIR = resolve_data_dir() / "guilds"

DEFAULT_GUILD: Dict[str, Any] = {}


def load_guild(guild_id: int) -> Dict[str, Any]:
    """Load the JSON data file for *guild_id*, returning an empty dict if absent."""
    path = GUILDS_DIR / f"{guild_id}.json"
    if not path.exists():
        return DEFAULT_GUILD.copy()
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_guild(guild_id: int, data: Dict[str, Any]) -> None:
    """Persist *data* to ``data/guilds/{guild_id}.json``."""
    GUILDS_DIR.mkdir(parents=True, exist_ok=True)
    path = GUILDS_DIR / f"{guild_id}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def get_guild_value(guild_id: int, key: str, default: Any = None) -> Any:
    """Return a single key from a guild's data file."""
    return load_guild(guild_id).get(key, default)


def set_guild_value(guild_id: int, key: str, value: Any) -> None:
    """Set a single key in a guild's data file and save immediately."""
    data = load_guild(guild_id)
    data[key] = value
    save_guild(guild_id, data)
