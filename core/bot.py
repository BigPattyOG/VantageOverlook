"""vprod — main bot class.

Extends ``discord.ext.commands.Bot`` with:
* CogManager integration (sys.path setup + autoload at startup).
* Graceful error handling with embed responses.
* Dynamic prefix from config.
* Built-in ``cogs.admin`` always loaded.
* Owners resolved automatically from the Discord application/team.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import discord
from discord.ext import commands

from .cog_manager import CogManager
from .help_command import VantageHelp

log = logging.getLogger("vprod")

BUILTIN_EXTENSIONS = ["cogs.admin"]

# Colours used for embeds
TEAL = discord.Color.from_str("#2DC5C5")   # primary brand colour
RED = discord.Color.red()                   # errors


class VantageBot(commands.Bot):
    """The main vprod bot instance."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.cog_manager = CogManager()
        self.start_time: Optional[datetime] = None

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=commands.when_mentioned_or(config.get("prefix", "!")),
            intents=intents,
            owner_ids=set(config.get("owner_ids", [])),
            description=config.get("description", "vprod Discord Bot"),
            help_command=VantageHelp(),
        )

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def setup_hook(self) -> None:
        """Called once before the bot connects. Load extensions here."""
        # Fetch owner(s) from the Discord API and merge with config owner_ids.
        await self._sync_owner_ids()

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
        self.start_time = datetime.now(timezone.utc)
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

        # Unwrap CommandInvokeError so each branch below can match the real
        # cause and give users a specific, actionable error message.
        if isinstance(error, commands.CommandInvokeError):
            error = error.original  # type: ignore[assignment]

        if isinstance(error, commands.CommandNotFound):
            return  # Silently ignore unknown commands

        if isinstance(error, commands.DisabledCommand):
            await self._send_error(ctx, "Command Disabled", "This command is currently disabled.")
            return

        if isinstance(error, commands.NoPrivateMessage):
            await self._send_error(
                ctx, "Server Only", "This command can only be used inside a server."
            )
            return

        if isinstance(error, commands.MissingRequiredArgument):
            await self._send_error(
                ctx,
                "Missing Argument",
                f"**`{error.param.name}`** is required.\n\n"
                f"Usage: `{ctx.clean_prefix}{ctx.command.qualified_name} {ctx.command.signature}`",
            )
            return

        if isinstance(error, commands.TooManyArguments):
            await self._send_error(
                ctx,
                "Too Many Arguments",
                f"Usage: `{ctx.clean_prefix}{ctx.command.qualified_name} {ctx.command.signature}`",
            )
            return

        if isinstance(error, commands.BadArgument):
            await self._send_error(ctx, "Bad Argument", str(error))
            return

        if isinstance(error, commands.BadUnionArgument):
            await self._send_error(ctx, "Bad Argument", str(error))
            return

        if isinstance(error, commands.MissingPermissions):
            perms = ", ".join(
                p.replace("_", " ").title() for p in error.missing_permissions
            )
            await self._send_error(
                ctx, "Missing Permissions", f"You need the **{perms}** permission(s) to run this command."
            )
            return

        if isinstance(error, commands.BotMissingPermissions):
            perms = ", ".join(
                p.replace("_", " ").title() for p in error.missing_permissions
            )
            await self._send_error(
                ctx, "Bot Missing Permissions", f"I need the **{perms}** permission(s) to do that."
            )
            return

        if isinstance(error, commands.NotOwner):
            await self._send_error(
                ctx, "Owner Only", "This command is restricted to bot owners."
            )
            return

        if isinstance(error, commands.MaxConcurrencyReached):
            per_name = error.per.name.replace("_", " ")
            await self._send_error(
                ctx,
                "Too Many Active Uses",
                f"This command can only be run **{error.number}** time(s) at once per {per_name}. "
                "Please wait for it to finish.",
            )
            return

        if isinstance(error, commands.CommandOnCooldown):
            await self._send_error(
                ctx,
                "On Cooldown",
                f"You're using this command too fast. Try again in **{error.retry_after:.1f}s**.",
            )
            return

        if isinstance(error, commands.CheckFailure):
            await self._send_error(
                ctx, "Access Denied", "You don't have permission to run this command."
            )
            return

        # Unexpected error — log full traceback, send a generic response
        log.error(
            "Unhandled error in command '%s': %s",
            ctx.command,
            "".join(traceback.format_exception(type(error), error, error.__traceback__)),
        )
        await self._send_error(
            ctx,
            "Unexpected Error",
            "An unexpected error occurred. Please try again later.\n"
            "If this keeps happening, let the server owner know.",
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _sync_owner_ids(self) -> None:
        """Fetch the application's owner(s) from Discord and update ``owner_ids``.

        Supports both single-owner and team-owned applications.  Any IDs
        already present in the config are preserved so that the server
        operator can add extra owners beyond the application owner.
        """
        try:
            app_info = await self.application_info()
            discord_owner_ids: set[int] = set()

            if app_info.team:
                # Team-owned application — only accepted members count as owners.
                discord_owner_ids = {
                    m.id
                    for m in app_info.team.members
                    if m.membership_state == discord.TeamMembershipState.accepted
                }
                log.info(
                    "Fetched %d team owner(s) from Discord: %s",
                    len(discord_owner_ids),
                    discord_owner_ids,
                )
            elif app_info.owner:
                discord_owner_ids = {app_info.owner.id}
                log.info(
                    "Fetched bot owner from Discord: %s (ID: %d)",
                    app_info.owner,
                    app_info.owner.id,
                )
            else:
                log.warning("Discord application info returned no owner and no team.")

            # Merge Discord owners with any extra IDs already in owner_ids
            self.owner_ids = discord_owner_ids | self.owner_ids
        except Exception:
            log.warning(
                "Could not fetch application info from Discord; "
                "falling back to config owner_ids: %s",
                self.owner_ids,
                exc_info=True,
            )

    async def _send_error(self, ctx: commands.Context, title: str, desc: str) -> None:
        embed = discord.Embed(
            title=f"❌  {title}",
            description=desc,
            color=RED,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Command: {ctx.invoked_with}")
        try:
            await ctx.send(embed=embed)
        except discord.HTTPException:
            pass
