"""Centralised embed helpers for Vantage.

All Discord embeds produced by the bot should be built through these helpers
so that branding (colour, footer, thumbnail, timestamp) stays consistent
everywhere — commands, error handlers, and system messages.

Usage
-----
::

    from core.embeds import VantageEmbed

    # Informational (teal)
    embed = VantageEmbed.info("Server Info", "Here are the details…", bot=ctx.bot)

    # Success (green)
    embed = VantageEmbed.ok("Extension loaded successfully.")

    # Error (red)
    embed = VantageEmbed.error("Load Failed", "Extension was not found.")

    # Warning / neutral (gold)
    embed = VantageEmbed.warn("Maintenance Mode", "The bot is under maintenance.")
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from discord.ext import commands

# ── Brand colours ─────────────────────────────────────────────────────────────

TEAL    = discord.Color.from_str("#2DC5C5")   # Vantage primary
GREEN   = discord.Color.from_str("#57F287")   # success
RED     = discord.Color.from_str("#ED4245")   # error
GOLD    = discord.Color.from_str("#FEE75C")   # warning / neutral
BLURPLE = discord.Color.blurple()             # informational accent

# Public alias for imports that only need the primary colour
EMBED_COLOUR = TEAL

# Version is read lazily from the VERSION file so it is always up to date.
_VERSION: Optional[str] = None


def get_version() -> str:
    """Return the current bot version from the ``VERSION`` file."""
    global _VERSION
    if _VERSION is not None:
        return _VERSION
    from pathlib import Path
    version_file = Path(__file__).resolve().parents[1] / "VERSION"
    if version_file.exists():
        _VERSION = version_file.read_text(encoding="utf-8").strip()
    else:
        _VERSION = "0.0.0"
    return _VERSION


# ── Core builder ──────────────────────────────────────────────────────────────

class VantageEmbed:
    """Factory class with static methods for each embed type."""

    @staticmethod
    def _base(
        title: str = "",
        description: str = "",
        color: discord.Color = TEAL,
        *,
        bot: Optional["commands.Bot"] = None,
        footer_extra: str = "",
        thumbnail: bool = False,
    ) -> discord.Embed:
        """Build a consistently styled base embed.

        Parameters
        ----------
        title:
            Embed title text (may be empty).
        description:
            Embed body text (may be empty).
        color:
            Embed accent colour.
        bot:
            When provided the bot's avatar is used as the thumbnail and the
            bot's name appears in the footer.
        footer_extra:
            Extra text appended after the version in the footer, separated
            by ``·``.  Useful for per-command context (e.g. ``"Command: ping"``).
        thumbnail:
            Whether to include the bot avatar as a thumbnail (requires *bot*).
        """
        version = get_version()
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        bot_name = "Vantage"
        if bot is not None and bot.user:
            bot_name = bot.user.display_name
            if thumbnail:
                embed.set_thumbnail(url=bot.user.display_avatar.url)

        footer_parts = [f"Vantage v{version}"]
        if footer_extra:
            footer_parts.append(footer_extra)
        embed.set_footer(text="  ·  ".join(footer_parts))
        return embed

    # ── Convenience factories ──────────────────────────────────────────────────

    @staticmethod
    def info(
        title: str,
        description: str = "",
        *,
        bot: Optional["commands.Bot"] = None,
        footer_extra: str = "",
        thumbnail: bool = False,
    ) -> discord.Embed:
        """Teal (primary brand) embed — use for neutral information."""
        return VantageEmbed._base(
            title, description, TEAL,
            bot=bot, footer_extra=footer_extra, thumbnail=thumbnail,
        )

    @staticmethod
    def ok(description: str, *, bot: Optional["commands.Bot"] = None) -> discord.Embed:
        """Green embed — use for successful actions."""
        return VantageEmbed._base(
            "", f"✅  {description}", GREEN, bot=bot,
        )

    @staticmethod
    def error(
        title: str,
        description: str = "",
        *,
        bot: Optional["commands.Bot"] = None,
        footer_extra: str = "",
    ) -> discord.Embed:
        """Red embed — use for errors and failures."""
        return VantageEmbed._base(
            f"❌  {title}", description, RED,
            bot=bot, footer_extra=footer_extra,
        )

    @staticmethod
    def warn(
        title: str,
        description: str = "",
        *,
        bot: Optional["commands.Bot"] = None,
    ) -> discord.Embed:
        """Gold embed — use for warnings, maintenance notices, and caution."""
        return VantageEmbed._base(title, description, GOLD, bot=bot)

    @staticmethod
    def maintenance(bot: Optional["commands.Bot"] = None, message: str = "") -> discord.Embed:
        """Styled maintenance-mode notice embed."""
        description = (
            message
            or "🔧  The bot is currently undergoing maintenance.\n"
               "Please check back soon — we'll be back online shortly!"
        )
        embed = VantageEmbed._base(
            "🔧  Maintenance Mode",
            description,
            GOLD,
            bot=bot,
            thumbnail=True,
        )
        return embed
