"""Shared constants, translator helpers, and user-facing help text for VMod."""

from __future__ import annotations

import logging

from redbot.core import i18n

log = logging.getLogger("red.vmod")
_ = i18n.Translator("VMod", __file__)

# Action keys used by the role-based permission system.
# Matches the modulus (modplus) permission key set.
ACTION_KEYS: tuple[str, ...] = (
    "kick",
    "ban",
    "mute",
    "warn",
    "channelperms",
    "editchannel",
    "deletemessages",
)

# Notification event keys that users/channels can subscribe to.
NOTIF_KEYS: tuple[str, ...] = (
    "kick",
    "ban",
    "mute",
    "warn",
    "channelperms",
    "editchannel",
    "deletemessages",
    "ratelimit",
    "adminrole",
    "bot",
)

# Custom case types that are useful for this cog but may not already exist.
# Registering them is harmless if another cog already did it.
CASE_TYPES: list[dict[str, object]] = [
    {"name": "warning", "default_setting": True, "image": "⚠️", "case_str": "Warning"},
    {"name": "tempban", "default_setting": True, "image": "⏳", "case_str": "Tempban"},
    {"name": "softban", "default_setting": True, "image": "🧹", "case_str": "Softban"},
    {"name": "mute", "default_setting": True, "image": "🔇", "case_str": "Mute"},
    {"name": "unmute", "default_setting": True, "image": "🔊", "case_str": "Unmute"},
]

PERM_SYS_INFO = """
**__VMod Permission System__**
**Kick:** Can kick members. Default rate limit: 5 per hour.
**Ban:** Can ban, tempban, softban, massban, and unban members. Default rate limit: 3 per hour.
**Mute:** Can timeout/mute members.
**Warn:** Can warn members.
**ChannelPerms:** Can add/remove members from channels.
**EditChannel:** Can create, rename, enable slowmode, and move channels.
**DeleteMessages:** Can purge and pin messages. Default rate limit: 50 per hour.

Admins and bot owners always bypass VMod's permission checks.
""".strip()

NOTIF_SYS_INFO = """
**__VMod Notification System__**
Subscribe to receive DMs or channel alerts when moderation events occur:

**Kick:** When a member is kicked.
**Ban:** When a member is banned.
**Mute:** When a member is muted or timed out.
**Warn:** When a member is warned.
**ChannelPerms:** When channel permissions are modified.
**EditChannel:** When a channel is created, moved, or renamed.
**DeleteMessages:** When messages are bulk-deleted (may be frequent).
**RateLimit:** When a moderator hits a rate limit — *recommended*.
**AdminRole:** When a role or member gains administrator permissions — *recommended*.
**Bot:** When a new bot joins the server — *recommended*.
""".strip()
