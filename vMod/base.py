"""Shared config, helpers, and background tasks for VMod.

This file intentionally holds the boring but important plumbing:
- persistent Red config registration (global, guild, member, user)
- in-memory caches for live checks and rate limits
- modlog helper methods
- notification system (modulus-style DM/channel alerts)
- warn/timeout helpers
- tempban expiry background task
- shared permission helpers with role-removal on rate-limit breach
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

from .constants import ACTION_KEYS, CASE_TYPES, NOTIF_KEYS, _

log = logging.getLogger("red.vmod")

# ---------------------------------------------------------------------------
# Default config values
# ---------------------------------------------------------------------------

_DEFAULT_ACTION_RATE_LIMITS = {
    "kick": {"limit": 5, "window": 3600},
    "ban": {"limit": 3, "window": 3600},
    "deletemessages": {"limit": 50, "window": 3600},
}


class VModBase(commands.Cog):
    """Base class that owns config, caches, helper methods, and background tasks."""

    default_global_settings: dict[str, Any] = {
        "version": "4.0.0",
        "track_all_names": True,
        # Notification subscriptions — global so any mod in any guild can opt in.
        # Structure: notifkey -> list of user IDs
        "notif_users": {key: [] for key in NOTIF_KEYS},
        # Structure: notifkey -> list of [guild_id, channel_id]
        "notif_channels": {key: [] for key in NOTIF_KEYS},
    }

    default_guild_settings: dict[str, Any] = {
        "mention_spam": {"ban": None, "kick": None, "warn": None, "strict": False},
        "delete_repeats": -1,
        "respect_hierarchy": True,
        "reinvite_on_unban": False,
        "current_tempbans": [],
        "dm_on_kickban": False,
        "default_days": 0,
        "default_tempban_duration": 60 * 60 * 24,  # 24 hours
        "track_nicknames": True,
        "action_roles": {key: [] for key in ACTION_KEYS},
        "action_rate_limits": _DEFAULT_ACTION_RATE_LIMITS,
        # Roles awarded at warning milestones (matching the modplus rolekeys)
        "warning_roles": {
            "warning1": None,   # role ID for first warning
            "warning2": None,   # role ID for second warning
            "warning3+": None,  # role ID for three or more warnings
        },
        # Role used for manual mute when Discord timeouts cannot be applied
        "muted_role": None,
    }

    default_member_settings: dict[str, Any] = {
        "past_nicks": [],
        "banned_until": None,
        # Each entry: {"reason": str, "moderator_id": int, "timestamp": str}
        "warnings": [],
    }

    default_user_settings: dict[str, Any] = {
        "past_names": [],
    }

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=4961522000, force_registration=True)
        self.config.register_global(**self.default_global_settings)
        self.config.register_guild(**self.default_guild_settings)
        self.config.register_member(**self.default_member_settings)
        self.config.register_user(**self.default_user_settings)

        # In-memory cache for repeat-message detection.
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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def cog_load(self) -> None:
        """Register custom modlog case types when the cog is loaded."""
        for case in CASE_TYPES:
            with suppress(RuntimeError):
                await modlog.register_casetype(**case)

    async def initialize(self) -> None:
        """Perform lightweight startup work and then unlock command usage."""
        self._ready.set()

    async def cog_before_invoke(self, ctx: commands.Context) -> None:
        """Wait for startup initialization before commands run."""
        await self._ready.wait()

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        """Route VMod command errors through VErrors when available, with a graceful fallback."""
        original = getattr(error, "original", error)

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
                    with suppress(discord.HTTPException):
                        await ctx.send(embed=embed)
                    return

            system = verrors.get_system_prefix(ctx) if hasattr(verrors, "get_system_prefix") else "VM"
            await verrors.reporter.report_command_exception(ctx, original, system)
            return

        log.exception("Internal VMod error in %s", ctx.command, exc_info=original)
        cmd_display = f"{ctx.clean_prefix}{ctx.command.qualified_name}" if ctx.command else _("that command")
        with suppress(discord.HTTPException):
            await ctx.send(
                _("Something went wrong while running **{cmd}**. Please try again.").format(cmd=cmd_display)
            )

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

        # Remove from notification subscriptions
        global_data = await self.config.all()
        notif_users = global_data.get("notif_users", {})
        changed = False
        for key, uid_list in notif_users.items():
            if user_id in uid_list:
                uid_list.remove(user_id)
                changed = True
        if changed:
            await self.config.notif_users.set(notif_users)

    # ------------------------------------------------------------------
    # Notification system  (modulus-style)
    # ------------------------------------------------------------------

    async def notify(self, notif_key: str, embed: discord.Embed) -> None:
        """Send *embed* to all users and channels subscribed to *notif_key*.

        This mirrors the ``notify()`` method from the modplus (modulus) cog but
        uses an embed instead of a plain-text payload for a polished look.
        """
        if notif_key not in NOTIF_KEYS:
            return

        global_data = await self.config.all()

        # DM subscribers
        for user_id in global_data.get("notif_users", {}).get(notif_key, []):
            try:
                user = await self.bot.fetch_user(user_id)
                await user.send(embed=embed)
            except Exception:
                pass

        # Channel subscribers
        for guild_id, channel_id in global_data.get("notif_channels", {}).get(notif_key, []):
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            channel = guild.get_channel(channel_id)
            if channel is None:
                continue
            with suppress(discord.HTTPException, discord.Forbidden):
                await channel.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions.none(),
                )

    # ------------------------------------------------------------------
    # Permission & hierarchy helpers
    # ------------------------------------------------------------------

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

    async def _rate_limit_exceeded_handler(
        self, ctx: commands.Context, action_key: str
    ) -> None:
        """Called when a moderator exceeds their rate limit.

        Mirrors the modplus ``rate_limit_exceeded()`` behaviour:
        - Strips all moderation roles from the offending moderator.
        - Notifies all ratelimit subscribers with an embed.
        """
        all_action_roles: dict[str, list[int]] = await self.config.guild(ctx.guild).action_roles()
        all_mod_role_ids: set[int] = set()
        for role_ids in all_action_roles.values():
            all_mod_role_ids.update(role_ids)

        removed: list[str] = []
        broken: list[str] = []

        for role in ctx.author.roles:
            if role.id in all_mod_role_ids:
                try:
                    await ctx.author.remove_roles(role, reason=_("VMod rate limit exceeded."))
                    removed.append(f"{role.mention} (`{role.id}`)")
                except Exception:
                    broken.append(f"{role.mention} (`{role.id}`)")

        description_lines = [
            f"**Moderator:** {ctx.author.mention} (`{ctx.author.id}`)",
            f"**Action:** `{action_key}`",
            f"**Server:** {ctx.guild.name} (`{ctx.guild.id}`)",
        ]
        if removed:
            description_lines.append(f"**Roles removed:** {', '.join(removed)}")
        if broken:
            description_lines.append(
                f"⚠️ **Could not remove:** {', '.join(broken)} — bot role may be too low."
            )

        embed = discord.Embed(
            title="⚡ Moderator Rate Limit Exceeded",
            description="\n".join(description_lines),
            colour=discord.Colour.dark_orange(),
        )
        embed.timestamp = datetime.now(tz=timezone.utc)

        await self.notify("ratelimit", embed)

        # Also log to modlog channel
        await self.send_modlog_note(
            ctx.guild,
            title=_("Moderator rate limit exceeded"),
            description=_("{member} hit the `{action}` rate limit. Moderation roles removed.").format(
                member=ctx.author.mention,
                action=action_key,
            ),
        )

    async def _check_action_rate_limit(
        self, ctx: commands.Context, action_key: str
    ) -> tuple[bool, str | None]:
        """Enforce an in-memory rate limit for non-admin moderators."""
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
        """Return ``True`` when the caller may perform the requested action.

        Admin users and bot owners always bypass the check.
        Regular moderators must have a configured role, and are subject
        to the per-action rate limit.  Exceeding the rate limit triggers
        the modulus-style handler that strips their mod roles and notifies
        all ratelimit subscribers.
        """
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
                _("You do not have the VMod permission for `{action}`.").format(action=action_key)
            )
            return False

        allowed, message = await self._check_action_rate_limit(ctx, action_key)
        if not allowed:
            await ctx.send(message)
            await self._rate_limit_exceeded_handler(ctx, action_key)
            return False

        return True

    # ------------------------------------------------------------------
    # DM helpers
    # ------------------------------------------------------------------

    async def maybe_dm_before_action(
        self,
        member: discord.Member | discord.User,
        *,
        action: str,
        guild: discord.Guild,
        reason: str | None,
        embed: discord.Embed | None = None,
    ) -> None:
        """Optionally DM a user before a kick/ban/mute action is applied.

        If an *embed* is provided it is sent instead of the plain-text fallback.
        """
        if not await self.config.guild(guild).dm_on_kickban():
            return

        with suppress(discord.HTTPException, discord.Forbidden):
            if embed is not None:
                await member.send(embed=embed)
            else:
                msg = _("You are being {action} from **{guild}**.").format(
                    action=action, guild=guild.name
                )
                if reason:
                    msg += _("\n**Reason:** {reason}").format(reason=reason)
                await member.send(msg)

    # ------------------------------------------------------------------
    # Name / nick history
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Warning helpers
    # ------------------------------------------------------------------

    async def add_warning(
        self,
        member: discord.Member,
        *,
        reason: str | None,
        moderator: discord.Member,
    ) -> int:
        """Append a warning entry and return the new total warning count."""
        entry = {
            "reason": reason or _("No reason provided."),
            "moderator_id": moderator.id,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
        async with self.config.member(member).warnings() as warnings:
            warnings.append(entry)
            count = len(warnings)

        # Apply warning roles (modplus-style)
        await self._apply_warning_role(member, count)
        return count

    async def _apply_warning_role(self, member: discord.Member, warn_count: int) -> None:
        """Add the appropriate warning milestone role based on total warning count."""
        guild = member.guild
        warning_roles = await self.config.guild(guild).warning_roles()

        if warn_count == 1:
            role_id = warning_roles.get("warning1")
        elif warn_count == 2:
            role_id = warning_roles.get("warning2")
        else:
            role_id = warning_roles.get("warning3+")

        if role_id is None:
            return
        role = guild.get_role(role_id)
        if role is None:
            return
        with suppress(discord.HTTPException, discord.Forbidden):
            await member.add_roles(role, reason=_("VMod warning milestone role."))

    async def get_warnings(self, member: discord.Member) -> list[dict]:
        """Return all stored warning entries for *member*."""
        return [w for w in await self.config.member(member).warnings() if w]

    async def clear_warnings(self, member: discord.Member) -> int:
        """Clear all warnings for *member* and return how many were removed."""
        warnings = await self.config.member(member).warnings()
        count = len(warnings)
        await self.config.member(member).warnings.set([])
        return count

    # ------------------------------------------------------------------
    # Invite helper
    # ------------------------------------------------------------------

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
                        reason=_("VMod reinvite-on-unban invite."),
                    )
        return None

    # ------------------------------------------------------------------
    # Modlog helpers
    # ------------------------------------------------------------------

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
        """Send a plain embed note to Red's configured modlog channel."""
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

    # ------------------------------------------------------------------
    # Settings snapshot helper
    # ------------------------------------------------------------------

    async def build_settings_snapshot(self, guild: discord.Guild) -> dict[str, Any]:
        """Return a normalized snapshot used by both commands and the UI panel."""
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
            "warning_roles": guild_data["warning_roles"],
            "muted_role": guild_data["muted_role"],
        }

    # ------------------------------------------------------------------
    # Tempban expiry background task
    # ------------------------------------------------------------------

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
                        except (ValueError, TypeError):
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
                pass

            await asyncio.sleep(60)

