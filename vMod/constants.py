"""Shared constants, translator helpers, and user-facing help text for VMod."""

from __future__ import annotations

import logging

from redbot.core import i18n

log = logging.getLogger("red.vmod")
_ = i18n.Translator("VMod", __file__)

# Action keys used by the role-based permission system.
ACTION_KEYS: tuple[str, ...] = ("kick", "ban", "editchannel")

# Custom case types that are useful for this cog but may not already exist.
# Registering them is harmless if another cog already did it.
CASE_TYPES: list[dict[str, object]] = [
    {
        "name": "warning",
        "default_setting": True,
        "image": "⚠️",
        "case_str": "Warning",
    },
    {
        "name": "tempban",
        "default_setting": True,
        "image": "⏳",
        "case_str": "Tempban",
    },
    {
        "name": "softban",
        "default_setting": True,
        "image": "🧹",
        "case_str": "Softban",
    },
]

PERM_SYS_INFO = """
**__VMod Action Permission System__**
**Kick:** Can use VMod's `kick` command. Default rate limit: 5/hour.
**Ban:** Can use VMod's `ban`, `tempban`, `softban`, `massban`, and `unban` commands. Default rate limit: 3/hour.
**EditChannel:** Can use VMod's `slowmode` command.

Admins and bot owners always bypass VMod's role-based action checks.
""".strip()
