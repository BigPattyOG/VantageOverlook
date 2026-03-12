"""Shared config, helpers, and background tasks for VMod.

This file intentionally holds the boring but important plumbing:
- persistent Red config registration
- in-memory caches for live checks
- modlog helper methods
- tempban expiry handling
- shared permission helpers
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

import discord
from redbot.core import Config, commands, modlog
from redbot.core.bot import Red
from redbot.core.utils import AsyncIter

from .constants import ACTION_KEYS, CASE_TYPES, _

log = logging.getLogger("red.vmod")


class VModBase(commands.Cog):
    """Base class that owns config, caches, helper methods, and background tasks."""

    # These defaults are registered once and then available per-scope through Red's Config API.
    default_global_settings = {
        "version": "3.0.0",
        "track_all_names": True,
    }

    default_guild_settings = {
        "mention_spam": {"ban": None, "kick": None, "warn": None, "strict": False},
        "delete_repeats": -1,
        "respect_hierarchy": True,
        "reinvite_on_unban": False,
        "current_tempbans": [],
        "dm_on_kickban": False,
        "default_days": 0,
        "default_tempban_duration": 60 * 60 * 24,
        "track_nicknames": True,
        "action_roles": {key: [] for key in ACTION_KEYS},
        "action_rate_limits": {
            "kick": {"limit": 5, "window": 3600},
            "ban": {"limit": 3, "window": 3600},
            "editchannel": {"limit": 25, "window": 3600},
        },
    }

    default_member_settings = {
        "past_nicks": [],
        "banned_until": None,
    }

    default_user_settings = {
        "past_names": [],
    }

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=4961522000, force_registration=True)
        self.config.register_global(**self.default_global_settings)
        self.config.register_guild(**self.default_guild_settings)
        self.config.register_member(**self.default_member_settings)
        self.config.register_user(**self.default_user_settings)

        # In-memory cache for repeat message detection.
        # Structure: guild_id -> member_id -> deque([recent messages])
        self.repeat_cache: dict[int, defaultdict[int, deque[str]]] = {}

        # In-memory rate-limit history.
        # Structure: guild_id -> member_id -> action_key -> deque([timestamps])
        self.action_usage: dict[int, dict[int, dict[str, deque[float]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(deque))
        )

        self._ready = asyncio.Event()
        self.init_task = asyncio.create_task(self.initialize())
        self.tban_expiry_task = asyncio.create_task(self.check_tempban_expirations())

    async def cog_load(self) -> None:
        """Register custom modlog case types when the cog is loaded."""
        for case in CASE_TYPES:
            with suppress(RuntimeError):
                await modlog.register_casetype(**case)

    async def initialize(self) -> None:
        """Perform lightweight startup work and then unlock command usage."""
        # Reserved for future config migrations.
        self._ready.set()

    async def cog_before_invoke(self, ctx: commands.Context) -> None:
        """Wait for startup initialization before commands run."""
        await self._ready.wait()

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        """Route VMod command errors through VErrors when available, with a graceful fallback."""
        original = getattr(error, "original", error)

        # Let Red handle its own user-feedback check failures silently.
        if isinstance(original, commands.UserFeedbackCheckFailure):
            return

        verrors = self.bot.get_cog("VErrors")

        if verrors is not None:
            code = None
            if hasattr(verrors, "get_public_error_code"):
                code = verrors.get_public_error_code(ctx, original)

            if code is not None:
                embed = None
                if hasattr(verrors, "build_fixable_error_embed"):
                    embed = verrors.build_fixable_error_embed(ctx, original, code)
                if embed is not None:
                    try:
                        await ctx.send(embed=embed)
                    except discord.HTTPException:
                        pass
                    return

            system = verrors.get_system_prefix(ctx) if hasattr(verrors, "get_system_prefix") else "VM"
            await verrors.reporter.report_command_exception(ctx, original, system)
            return

        log.exception("Internal VMod error in %s", ctx.command, exc_info=original)
        cmd_display = f"{ctx.clean_prefix}{ctx.command.qualified_name}" if ctx.command else _("that command")
        try:
            await ctx.send(_("Something went wrong while running **{cmd_display}**. Please try again.").format(cmd_display=cmd_display))
        except discord.HTTPException:
            pass

    def cog_unload(self) -> None:
        """Cancel background tasks when the cog unloads."""
        for task in (self.init_task, self.tban_expiry_task):
            task.cancel()

    async def red_delete_data_for_user(self, *, requester: str, user_id: int) -> None:
        """Delete stored per-user data when Discord requests erasure."""
        if requester != "discord_deleted_user":
            return

        all_members = await self.config.all_members()
        async for guild_id, guild_data in AsyncIter(all_members.items(), steps=100):
            if user_id in guild_data:
                await self.config.member_from_ids(guild_id, user_id).clear()

        await self.config.user_from_id(user_id).clear()

        guild_data = await self.config.all_guilds()
        async for guild_id, settings in AsyncIter(guild_data.items(), steps=100):
            if user_id in settings.get("current_tempbans", []):
                async with self.config.guild_from_id(guild_id).current_tempbans() as tempbans:
                    with suppress(ValueError):
                        tempbans.remove(user_id)

    async def is_allowed_by_hierarchy(
        self,
        guild: discord.Guild,
        moderator: discord.Member,
        target: discord.Member,
    ) -> bool:
        """Respect Discord role hierarchy unless the guild disabled that safeguard."""
        if not await self.config.guild(guild).respect_hierarchy():
            return True
        if moderator == guild.owner or await self.bot.is_owner(moderator):
            return True
        return moderator.top_role > target.top_role

    async def _check_action_rate_limit(
        self, ctx: commands.Context, action_key: str
    ) -> tuple[bool, str | None]:
        """Enforce a lightweight in-memory rate limit for non-admin moderators."""
        limits = await self.config.guild(ctx.guild).action_rate_limits()
        settings = limits.get(action_key)
        if not settings:
            return True, None

        now = datetime.now(tz=timezone.utc).timestamp()
        usage = self.action_usage[ctx.guild.id][ctx.author.id][action_key]
        window = int(settings["window"])
        limit = int(settings["limit"])

        while usage and now - usage[0] > window:
            usage.popleft()

        if len(usage) >= limit:
            return False, _("You have hit VMod's rate limit for `{action}`.").format(action=action_key)

        usage.append(now)
        return True, None

    async def action_check(self, ctx: commands.Context, action_key: str) -> bool:
        """Return ``True`` when the caller can use the requested moderated action."""
        if action_key not in ACTION_KEYS:
            return False

        if await self.bot.is_owner(ctx.author) or await self.bot.is_admin(ctx.author):
            return True
        if ctx.author.guild_permissions.administrator:
            return True

        action_roles = await self.config.guild(ctx.guild).action_roles()
        allowed_role_ids = set(action_roles.get(action_key, []))
        has_role = any(role.id in allowed_role_ids for role in ctx.author.roles)
        if not has_role:
            await ctx.send(
                _("You do not have the configured VMod permission for `{action}`.").format(
                    action=action_key
                )
            )
            return False

        allowed, message = await self._check_action_rate_limit(ctx, action_key)
        if not allowed:
            await ctx.send(message)
            await self.send_modlog_note(
                ctx.guild,
                title=_("Moderator rate limit hit"),
                description=_("{member} hit the `{action}` rate limit.").format(
                    member=ctx.author.mention,
                    action=action_key,
                ),
            )
            return False
        return True

    async def maybe_dm_before_action(
        self,
        member: discord.Member | discord.User,
        *,
        action: str,
        guild: discord.Guild,
        reason: str | None,
    ) -> None:
        """Optionally DM a user before a kick or ban action is applied."""
        if not await self.config.guild(guild).dm_on_kickban():
            return

        msg = _("You are being {action} from **{guild}**.").format(action=action, guild=guild.name)
        if reason:
            msg += _("\nReason: {reason}").format(reason=reason)
        with suppress(discord.HTTPException, discord.Forbidden):
            await member.send(msg)

    async def append_name_history(self, user: discord.User, old_name: str) -> None:
        """Store a previous username while keeping the list de-duplicated and short."""
        async with self.config.user(user).past_names() as names:
            while None in names:
                names.remove(None)
            if old_name in names:
                names.remove(old_name)
            names.append(old_name)
            while len(names) > 20:
                names.pop(0)

    async def append_nick_history(self, member: discord.Member, old_nick: str) -> None:
        """Store a previous nickname while keeping the list de-duplicated and short."""
        async with self.config.member(member).past_nicks() as nicks:
            while None in nicks:
                nicks.remove(None)
            if old_nick in nicks:
                nicks.remove(old_nick)
            nicks.append(old_nick)
            while len(nicks) > 20:
                nicks.pop(0)

    async def get_names_and_nicks(
        self, member: discord.Member | discord.User
    ) -> tuple[list[str], list[str]]:
        """Fetch stored username and nickname history for display commands."""
        names = [n for n in await self.config.user(member).past_names() if n]
        nicks: list[str] = []
        if isinstance(member, discord.Member):
            nicks = [n for n in await self.config.member(member).past_nicks() if n]
        return names, nicks

    async def get_invite_for_reinvite(
        self, ctx: commands.Context, max_age: int = 86400
    ) -> discord.Invite | None:
        """Create a temporary invite to reuse on unban, when enabled and possible."""
        me = ctx.guild.me
        if me is None or not me.guild_permissions.create_instant_invite:
            return None

        target_channels: list[discord.abc.GuildChannel] = [ctx.channel, *ctx.guild.text_channels]
        for channel in target_channels:
            perms = channel.permissions_for(me)
            if getattr(perms, "create_instant_invite", False):
                with suppress(discord.HTTPException, discord.Forbidden):
                    return await channel.create_invite(
                        max_age=max_age,
                        max_uses=1,
                        unique=True,
                        reason=_("Invite created for VMod reinvite-on-unban."),
                    )
        return None

    async def create_modlog_case(
        self,
        guild: discord.Guild,
        *,
        action_type: str,
        user: discord.abc.User | discord.Object | int,
        moderator: discord.abc.User | discord.Object | int | None,
        reason: str | None,
        created_at: datetime | None = None,
        until: datetime | None = None,
        channel: discord.abc.GuildChannel | discord.Thread | None = None,
    ) -> None:
        """Wrapper around Red's modlog helper to keep call sites tidy."""
        with suppress(Exception):
            await modlog.create_case(
                self.bot,
                guild,
                created_at or datetime.now(tz=timezone.utc),
                action_type,
                user,
                moderator,
                reason,
                until=until,
                channel=channel,
            )

    async def send_modlog_note(
        self,
        guild: discord.Guild,
        *,
        title: str,
        description: str,
    ) -> None:
        """Send a plain embed note to Red's configured modlog channel.

        This is used for informational events that are useful to staff but do not
        naturally map to a real moderation case.
        """
        try:
            channel = await modlog.get_modlog_channel(guild)
        except RuntimeError:
            return
        if channel is None:
            return

        embed = discord.Embed(title=title, description=description, colour=discord.Colour.blurple())
        embed.timestamp = datetime.now(tz=timezone.utc)
        with suppress(discord.HTTPException, discord.Forbidden):
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    async def build_settings_snapshot(self, guild: discord.Guild) -> dict[str, Any]:
        """Return a small normalized snapshot used by both commands and the UI panel."""
        guild_data = await self.config.guild(guild).all()
        return {
            "delete_repeats": guild_data["delete_repeats"],
            "mention_spam": guild_data["mention_spam"],
            "respect_hierarchy": guild_data["respect_hierarchy"],
            "reinvite_on_unban": guild_data["reinvite_on_unban"],
            "dm_on_kickban": guild_data["dm_on_kickban"],
            "default_days": guild_data["default_days"],
            "default_tempban_duration": guild_data["default_tempban_duration"],
            "track_nicknames": guild_data["track_nicknames"],
            "action_roles": guild_data["action_roles"],
            "action_rate_limits": guild_data["action_rate_limits"],
        }

    async def check_tempban_expirations(self) -> None:
        """Background task that removes tempbans after their configured expiry time."""
        await self.bot.wait_until_red_ready()
        await self._ready.wait()

        while True:
            try:
                now = datetime.now(tz=timezone.utc)
                all_guilds = await self.config.all_guilds()
                async for guild_id, settings in AsyncIter(all_guilds.items(), steps=25):
                    guild = self.bot.get_guild(guild_id)
                    if guild is None:
                        continue

                    tempban_ids = list(settings.get("current_tempbans", []))
                    if not tempban_ids:
                        continue

                    for user_id in tempban_ids:
                        banned_until = await self.config.member_from_ids(guild_id, user_id).banned_until()
                        if not banned_until:
                            continue
                        try:
                            expiry = datetime.fromisoformat(banned_until)
                        except ValueError:
                            await self.config.member_from_ids(guild_id, user_id).banned_until.clear()
                            continue

                        if expiry.tzinfo is None:
                            expiry = expiry.replace(tzinfo=timezone.utc)

                        if expiry > now:
                            continue

                        try:
                            user = await self.bot.fetch_user(user_id)
                        except discord.HTTPException:
                            user = discord.Object(id=user_id)

                        with suppress(discord.HTTPException, discord.Forbidden):
                            await guild.unban(user, reason=_("Tempban expired."))

                        async with self.config.guild(guild).current_tempbans() as tempbans:
                            with suppress(ValueError):
                                tempbans.remove(user_id)
                        await self.config.member_from_ids(guild_id, user_id).banned_until.clear()
                        await self.create_modlog_case(
                            guild,
                            action_type="unban",
                            user=user,
                            moderator=guild.me or self.bot.user,
                            reason=_("Tempban expired."),
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                # Keep the task alive even if one guild fails unexpectedly.
                pass

            await asyncio.sleep(60)
