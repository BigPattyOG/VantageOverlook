"""Embed rendering helpers for VError public and internal error displays."""

from __future__ import annotations

import discord

from .models import ErrorKind, InternalErrorRecord
from .registry import PublicErrorInfo
from .utils import (
    fixable_error_reply,
    internal_error_embed,
    internal_lookup_embed,
    not_found_embed,
    public_error_embed,
    public_registry_for_bot,
)

__all__ = [
    "ErrorKind",
    "InternalErrorRecord",
    "PublicErrorInfo",
    "fixable_error_reply",
    "internal_error_embed",
    "internal_lookup_embed",
    "not_found_embed",
    "public_error_embed",
    "public_registry_for_bot",
    "owner_notification_embed",
]


def owner_notification_embed(record: dict) -> discord.Embed:
    """Build a rich embed for the bot-owner DM notification of an internal error."""
    embed = discord.Embed(
        title=f"🔴 Internal Error — {record.get('code', 'UNKNOWN')}",
        color=discord.Color.red(),
    )
    embed.add_field(name="🖥️ System", value=f"`{record.get('system') or 'Unknown'}`", inline=True)
    embed.add_field(name="🏷️ Kind", value=f"`{record.get('kind') or 'Unknown'}`", inline=True)
    embed.add_field(name="⌨️ Command", value=f"`{record.get('command_name') or 'Unknown'}`", inline=True)
    embed.add_field(name="📋 Summary", value=(record.get("summary") or "Unknown")[:1024], inline=False)
    location_parts = []
    if record.get("guild_id"):
        location_parts.append(f"Guild: `{record['guild_id']}`")
    if record.get("channel_id"):
        location_parts.append(f"Channel: `{record['channel_id']}`")
    if record.get("user_id"):
        location_parts.append(f"User: `{record['user_id']}`")
    if location_parts:
        embed.add_field(name="📍 Context", value="\n".join(location_parts), inline=False)
    tb = (record.get("traceback_text") or "")[:900]
    if tb:
        embed.add_field(name="🐍 Traceback (partial)", value=f"```py\n{tb}\n```", inline=False)
    embed.set_footer(text=f"Use ?errors show {record.get('code', '')} for full details")
    return embed
