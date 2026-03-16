"""vprod — main bot class.

Extends ``discord.ext.commands.Bot`` with:
* PluginManager integration (sys.path setup + autoload at startup).
* Graceful error handling with branded embed responses.
* Dynamic prefix from config.
* Built-in ``plugins.admin`` always loaded.
* Owners resolved automatically from the Discord application/team.
* Global maintenance mode — non-owners receive a maintenance notice.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import discord
from discord.ext import commands

from .embeds import VantageEmbed, GOLD
from .health import HealthServer
from .help_command import VantageHelp
from .plugin_loader import PluginLoader
from .plugin_manager import PluginManager

log = logging.getLogger("vprod")

BUILTIN_EXTENSIONS = ["plugins.admin"]


class VantageBot(commands.Bot):
    """The main vprod bot instance."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.plugin_manager = PluginManager()
        self.start_time: Optional[datetime] = None
        self._health_server: Optional[HealthServer] = None
        # External plugins that failed to load — shown in health endpoint.
        self.failed_ext_plugins: list = []

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

        # Register the global maintenance check.
        self.add_check(self._maintenance_check)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def setup_hook(self) -> None:
        """Called once before the bot connects. Load extensions here."""
        from .config import resolve_ext_plugins_dir

        # Fetch owner(s) from the Discord API and merge with config owner_ids.
        await self._sync_owner_ids()

        # Make all repos importable.
        self.plugin_manager.setup_paths()

        # Start health-check HTTP server if a port is configured.
        health_port = int(self.config.get("health_port", 8080))
        if health_port > 0:
            self._health_server = HealthServer(self, health_port)
            try:
                await self._health_server.start()
            except Exception:
                log.exception(
                    "Failed to start health server on port %d — continuing without it.",
                    health_port,
                )
                self._health_server = None

        # Always load built-in extensions.
        for ext in BUILTIN_EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info("Loaded built-in extension: %s", ext)
            except Exception:
                log.exception("Failed to load built-in extension: %s", ext)

        # Load user-configured autoload plugins (community/GitHub repos).
        for plugin_path in self.plugin_manager.get_autoload():
            try:
                await self.load_extension(plugin_path)
                log.info("Autoloaded plugin: %s", plugin_path)
            except Exception:
                log.exception("Failed to autoload plugin: %s", plugin_path)

        # Load external (local/private) plugins.
        ext_plugins_dir = resolve_ext_plugins_dir(self.config)
        if ext_plugins_dir.exists():
            loader = PluginLoader(ext_plugins_dir)
            registry = self.plugin_manager.get_ext_plugins()
            if registry:
                _, failed = await loader.load_all(self, registry)
                self.failed_ext_plugins = failed
                if failed:
                    log.warning(
                        "%d external plugin(s) failed to load: %s",
                        len(failed),
                        [f.name for f in failed],
                    )

    async def close(self) -> None:
        """Gracefully shut down the health server before disconnecting."""
        if self._health_server is not None:
            await self._health_server.stop()
        await super().close()

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
        """Global error handler — sends a branded embed for common errors."""

        # Unwrap CommandInvokeError so each branch below can match the real cause.
        if isinstance(error, commands.CommandInvokeError):
            error = error.original  # type: ignore[assignment]

        if isinstance(error, commands.CommandNotFound):
            return  # Silently ignore unknown commands

        if isinstance(error, commands.DisabledCommand):
            await self._send_error(
                ctx,
                "Command Disabled",
                "This command has been disabled and cannot be used right now.",
            )
            return

        if isinstance(error, commands.NoPrivateMessage):
            await self._send_error(
                ctx,
                "Server Only",
                "This command can only be used inside a server, not in DMs.",
            )
            return

        if isinstance(error, commands.MissingRequiredArgument):
            param = error.param.name
            sig = ctx.command.signature
            usage = f"`{ctx.clean_prefix}{ctx.command.qualified_name}" + (f" {sig}`" if sig else "`")
            await self._send_error(
                ctx,
                "Missing Argument",
                f"You forgot to provide **`{param}`**, which is required.\n\n"
                f"**Correct usage:**\n{usage}\n\n"
                f"Run `{ctx.clean_prefix}help {ctx.command.qualified_name}` for a full description.",
            )
            return

        if isinstance(error, commands.TooManyArguments):
            sig = ctx.command.signature
            usage = f"`{ctx.clean_prefix}{ctx.command.qualified_name}" + (f" {sig}`" if sig else "`")
            await self._send_error(
                ctx,
                "Too Many Arguments",
                f"You provided more arguments than this command expects.\n\n"
                f"**Correct usage:**\n{usage}\n\n"
                f"Run `{ctx.clean_prefix}help {ctx.command.qualified_name}` for details.",
            )
            return

        if isinstance(error, (commands.BadArgument, commands.BadUnionArgument)):
            sig = ctx.command.signature
            usage = f"`{ctx.clean_prefix}{ctx.command.qualified_name}" + (f" {sig}`" if sig else "`")
            await self._send_error(
                ctx,
                "Invalid Argument",
                f"{error}\n\n"
                f"**Correct usage:**\n{usage}\n\n"
                f"Run `{ctx.clean_prefix}help {ctx.command.qualified_name}` for details.",
            )
            return

        if isinstance(error, commands.MissingPermissions):
            perms = ", ".join(
                p.replace("_", " ").title() for p in error.missing_permissions
            )
            await self._send_error(
                ctx,
                "Permission Denied",
                f"You need the **{perms}** permission(s) to run this command.\n"
                "Ask a server administrator if you think you should have access.",
            )
            return

        if isinstance(error, commands.BotMissingPermissions):
            perms = ", ".join(
                p.replace("_", " ").title() for p in error.missing_permissions
            )
            await self._send_error(
                ctx,
                "Bot Missing Permissions",
                f"I need the **{perms}** permission(s) in this channel to do that.\n"
                "Ask a server administrator to grant me the missing permissions.",
            )
            return

        if isinstance(error, commands.NotOwner):
            await self._send_error(
                ctx,
                "Owner Only",
                "This command can only be used by the bot owner(s).",
            )
            return

        if isinstance(error, commands.MaxConcurrencyReached):
            per_name = error.per.name.replace("_", " ")
            await self._send_error(
                ctx,
                "Command Already Running",
                f"This command can only run **{error.number}** time(s) at once per {per_name}.\n"
                "Please wait for the current use to finish, then try again.",
            )
            return

        if isinstance(error, commands.CommandOnCooldown):
            retry = error.retry_after
            if retry < 60:
                wait = f"{retry:.1f} seconds"
            else:
                m, s = divmod(int(retry), 60)
                wait = f"{m}m {s}s"
            await self._send_error(
                ctx,
                "Slow Down",
                f"This command is on cooldown. Try again in **{wait}**.",
            )
            return

        if isinstance(error, commands.CheckFailure):
            # Maintenance check raises CheckFailure — send the maintenance embed.
            if self.config.get("maintenance", False):
                msg = self.config.get("maintenance_message", "")
                embed = VantageEmbed.maintenance(bot=self, message=msg)
                try:
                    await ctx.send(embed=embed)
                except discord.HTTPException:
                    pass
                return
            await self._send_error(
                ctx,
                "Access Denied",
                "You do not have permission to run this command.",
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
            "Something Went Wrong",
            "An unexpected error occurred while running that command.\n"
            "Please try again in a moment. If the problem continues, let the bot owner know.",
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _maintenance_check(self, ctx: commands.Context) -> bool:
        """Global check: block non-owner commands while maintenance is active."""
        if not self.config.get("maintenance", False):
            return True
        if await self.is_owner(ctx.author):
            return True
        # Raise CheckFailure — on_command_error handles the response.
        raise commands.CheckFailure("maintenance")

    async def _sync_owner_ids(self) -> None:
        """Fetch the application's owner(s) from Discord and update ``owner_ids``.

        Supports both single-owner and team-owned applications.  Any IDs
        already in the config are preserved so operators can add extra owners
        beyond the application owner.
        """
        try:
            app_info = await self.application_info()
            discord_owner_ids: set[int] = set()

            if app_info.team:
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

            self.owner_ids = discord_owner_ids | self.owner_ids
        except Exception:
            log.warning(
                "Could not fetch application info from Discord; "
                "falling back to config owner_ids: %s",
                self.owner_ids,
                exc_info=True,
            )

    async def _send_error(self, ctx: commands.Context, title: str, desc: str) -> None:
        embed = VantageEmbed.error(title, desc, footer_extra=f"Command: {ctx.invoked_with}")
        try:
            await ctx.send(embed=embed)
        except discord.HTTPException as exc:
            log.warning(
                "Could not send error embed for command '%s' (%s): %s",
                ctx.command,
                title,
                exc,
            )

