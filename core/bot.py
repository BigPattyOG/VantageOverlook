"""VantageBot — main bot class.

Extends ``discord.ext.commands.Bot`` with:
* CogManager integration (sys.path setup + autoload at startup).
* Graceful error handling with embed responses.
* Dynamic prefix from config.
* Built-in ``cogs.admin`` always loaded.
"""

from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any, Dict, List

import discord
from discord.ext import commands

from .cog_manager import CogManager
from .help_command import VantageHelp

log = logging.getLogger("vantage")

BUILTIN_EXTENSIONS = ["cogs.admin"]


class VantageBot(commands.Bot):
    """The main Vantage bot instance."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.cog_manager = CogManager()

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=commands.when_mentioned_or(config.get("prefix", "!")),
            intents=intents,
            owner_ids=set(config.get("owner_ids", [])),
            description=config.get("description", "Vantage Discord Bot"),
            help_command=VantageHelp(),
        )

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def setup_hook(self) -> None:
        """Called once before the bot connects. Load extensions here."""
        # Make all repos importable
        self.cog_manager.setup_paths()

        # Always load built-in extensions
        for ext in BUILTIN_EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info("Loaded built-in extension: %s", ext)
            except Exception:
                log.exception("Failed to load built-in extension: %s", ext)

        # Load user-configured autoload cogs
        for cog_path in self.cog_manager.get_autoload():
            try:
                await self.load_extension(cog_path)
                log.info("Autoloaded cog: %s", cog_path)
            except Exception:
                log.exception("Failed to autoload cog: %s", cog_path)

    async def on_ready(self) -> None:
        prefix = self.config.get("prefix", "!")
        activity_text = self.config.get("activity", "{prefix}help for commands").replace(
            "{prefix}", prefix
        )
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening, name=activity_text
            )
        )
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        log.info("Prefix: %s | Guilds: %d", prefix, len(self.guilds))

    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        """Global error handler — sends a user-friendly embed for common errors."""

        if isinstance(error, commands.CommandNotFound):
            return  # Silently ignore unknown commands

        if isinstance(error, commands.MissingRequiredArgument):
            await self._send_error(
                ctx,
                "Missing Argument",
                f"**`{error.param.name}`** is required.\n\n"
                f"Usage: `{ctx.clean_prefix}{ctx.command.qualified_name} {ctx.command.signature}`",
            )
            return

        if isinstance(error, commands.BadArgument):
            await self._send_error(ctx, "Bad Argument", str(error))
            return

        if isinstance(error, commands.MissingPermissions):
            perms = ", ".join(error.missing_permissions)
            await self._send_error(
                ctx, "Missing Permissions", f"You need **{perms}** to use this command."
            )
            return

        if isinstance(error, commands.BotMissingPermissions):
            perms = ", ".join(error.missing_permissions)
            await self._send_error(
                ctx, "Bot Missing Permissions", f"I need **{perms}** to do that."
            )
            return

        if isinstance(error, commands.NotOwner):
            await self._send_error(ctx, "Owner Only", "This command is restricted to bot owners.")
            return

        if isinstance(error, commands.CheckFailure):
            await self._send_error(ctx, "Access Denied", "You don't have permission to run this command.")
            return

        if isinstance(error, commands.CommandOnCooldown):
            await self._send_error(
                ctx,
                "On Cooldown",
                f"Try again in **{error.retry_after:.1f}s**.",
            )
            return

        # Unexpected error — log full traceback
        log.error(
            "Unhandled error in command '%s': %s",
            ctx.command,
            "".join(traceback.format_exception(type(error), error, error.__traceback__)),
        )
        await self._send_error(
            ctx,
            "Unexpected Error",
            "An unexpected error occurred. Please try again later.",
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _send_error(self, ctx: commands.Context, title: str, desc: str) -> None:
        embed = discord.Embed(title=f"❌ {title}", description=desc, color=discord.Color.red())
        await ctx.send(embed=embed)
