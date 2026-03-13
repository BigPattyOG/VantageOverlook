"""User-facing moderation and information commands for VMod.

All embeds share a consistent colour scheme and layout:
  - 🔴 Red     — punitive permanent actions (kick, ban, softban, massban)
  - 🟠 Orange  — punitive temporary actions (tempban, warn)
  - 🟣 Purple  — reversible restrictions (mute / timeout)
  - 🟢 Green   — restorative actions (unban, unmute)
  - 🔵 Blue    — informational commands (userinfo, slowmode, rename)
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import cast

import discord
from redbot.core import checks, commands
from redbot.core.commands import Greedy
from redbot.core.utils.chat_formatting import humanize_timedelta
from redbot.core.utils.common_filters import escape_spoilers_and_mass_mentions
from redbot.core.utils.mod import get_audit_reason

from .base import VModBase
from .converters import RawUserIds
from .constants import _

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

_C_KICK      = discord.Color.from_rgb(237, 66,  69)   # Discord red
_C_BAN       = discord.Color.from_rgb(194, 33,  33)   # dark red
_C_SOFTBAN   = discord.Color.from_rgb(220, 80,  40)   # red-orange
_C_TEMPBAN   = discord.Color.from_rgb(230, 130, 30)   # amber
_C_WARN      = discord.Color.from_rgb(240, 173, 22)   # gold/yellow
_C_MUTE      = discord.Color.from_rgb(155, 89,  182)  # purple
_C_UNMUTE    = discord.Color.from_rgb(46,  204, 113)  # green
_C_UNBAN     = discord.Color.from_rgb(46,  204, 113)  # green
_C_INFO      = discord.Color.from_rgb(88,  101, 242)  # blurple
_C_CHANNEL   = discord.Color.from_rgb(52,  152, 219)  # sky blue
_C_DANGER    = discord.Color.from_rgb(237, 66,  69)   # same as kick

_MAX_FIELD = 950  # leave breathing room below Discord's 1024-char field limit


# ---------------------------------------------------------------------------
# Shared embed builders
# ---------------------------------------------------------------------------

def _base_embed(
    title: str,
    *,
    colour: discord.Color,
    description: str = "",
) -> discord.Embed:
    """Return a timestamped embed with a consistent structure."""
    embed = discord.Embed(title=title, description=description or None, colour=colour)
    embed.timestamp = datetime.now(tz=timezone.utc)
    return embed


def _action_embed(
    title: str,
    *,
    colour: discord.Color,
    target: discord.User | discord.Member,
    moderator: discord.abc.User,
    reason: str | None,
    extra_fields: list[tuple[str, str, bool]] | None = None,
) -> discord.Embed:
    """Build a fully-featured moderation action embed."""
    embed = _base_embed(title, colour=colour)
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="👤 Member", value=f"{target} (`{target.id}`)", inline=True)
    embed.add_field(name="🛡️ Moderator", value=moderator.mention, inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer
    embed.add_field(
        name="📋 Reason",
        value=reason or _("No reason provided."),
        inline=False,
    )
    for name, value, inline in (extra_fields or []):
        embed.add_field(name=name, value=value, inline=inline)
    return embed


def _format_id_list(ids: list[str]) -> str:
    """Join IDs as backtick-wrapped values, truncating with a count if too long."""
    entries = [f"`{uid}`" for uid in ids]
    result = ", ".join(entries)
    if len(result) <= _MAX_FIELD:
        return result
    shown: list[str] = []
    for entry in entries:
        candidate = ", ".join(shown + [entry])
        remaining = len(ids) - len(shown)
        suffix = _(", …and {count} more").format(count=remaining)
        if len(candidate) + len(suffix) > _MAX_FIELD:
            return (", ".join(shown) + suffix) if shown else _("…{count} IDs").format(count=remaining)
        shown.append(entry)
    return ", ".join(shown)


async def _guild_ban(
    guild: discord.Guild,
    user: discord.abc.Snowflake,
    *,
    reason: str | None,
    delete_days: int = 0,
) -> None:
    """Ban *user* from *guild*, handling both old and new discord.py parameter names.

    Older versions of discord.py use ``delete_message_days``; newer versions use
    ``delete_message_seconds``.  We try the seconds form first and fall back to
    the days form so the cog works across library versions without nested
    try-excepts at every call site.
    """
    seconds = delete_days * 86400
    try:
        await guild.ban(user, reason=reason, delete_message_seconds=seconds)
    except TypeError:
        await guild.ban(user, reason=reason, delete_message_days=delete_days)


# ---------------------------------------------------------------------------
# DM embed builders (sent to affected users when dm_on_kickban is enabled)
# ---------------------------------------------------------------------------

def _dm_embed(
    action: str,
    *,
    guild: discord.Guild,
    reason: str | None,
    colour: discord.Color,
    extra_fields: list[tuple[str, str, bool]] | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=_("You have been {action} from **{guild}**").format(action=action, guild=guild.name),
        colour=colour,
    )
    embed.add_field(name="📋 Reason", value=reason or _("No reason provided."), inline=False)
    for name, value, inline in (extra_fields or []):
        embed.add_field(name=name, value=value, inline=inline)
    embed.set_footer(text=guild.name, icon_url=guild.icon.url if guild.icon else None)
    embed.timestamp = datetime.now(tz=timezone.utc)
    return embed


# ---------------------------------------------------------------------------
# Cog class
# ---------------------------------------------------------------------------

class VModModeration(VModBase):
    """All user-facing moderation commands for VMod."""

    # ------------------------------------------------------------------ #
    # Slowmode                                                             #
    # ------------------------------------------------------------------ #

    @commands.command()
    @commands.guild_only()
    @commands.bot_has_permissions(manage_channels=True, embed_links=True)
    async def slowmode(
        self,
        ctx: commands.Context,
        *,
        interval: commands.TimedeltaConverter(
            minimum=timedelta(seconds=0),
            maximum=timedelta(hours=6),
            default_unit="seconds",
        ) = timedelta(seconds=0),
    ) -> None:
        """Set the current channel's slowmode interval.

        Set to `0` to disable slowmode.

        **Examples:**
        - `[p]slowmode 30s` — 30-second slowmode.
        - `[p]slowmode 2m` — 2-minute slowmode.
        - `[p]slowmode 0` — disable slowmode.
        """
        if not await self.action_check(ctx, "editchannel"):
            return

        seconds = int(interval.total_seconds())
        with suppress(discord.HTTPException, discord.Forbidden):
            await ctx.channel.edit(slowmode_delay=seconds)

        if seconds > 0:
            readable = humanize_timedelta(timedelta=interval)
            embed = _base_embed(_("🐢 Slowmode Enabled"), colour=_C_CHANNEL)
            embed.add_field(name="📌 Channel", value=ctx.channel.mention, inline=True)
            embed.add_field(name="⏱️ Interval", value=readable, inline=True)
            embed.set_footer(text=_("Set by {mod}").format(mod=ctx.author))
        else:
            embed = _base_embed(_("🚀 Slowmode Disabled"), colour=_C_CHANNEL)
            embed.add_field(name="📌 Channel", value=ctx.channel.mention, inline=True)
            embed.set_footer(text=_("Disabled by {mod}").format(mod=ctx.author))

        await ctx.send(embed=embed)
        await self.send_modlog_note(
            ctx.guild,
            title=_("Slowmode changed"),
            description=_("{mod} changed slowmode in {channel} to **{interval}**.").format(
                mod=ctx.author.mention,
                channel=ctx.channel.mention,
                interval=(humanize_timedelta(timedelta=interval) if seconds > 0 else _("off")),
            ),
        )

    # ------------------------------------------------------------------ #
    # Rename / nickname                                                    #
    # ------------------------------------------------------------------ #

    @commands.command()
    @commands.guild_only()
    @commands.bot_has_permissions(manage_nicknames=True, embed_links=True)
    @checks.admin_or_permissions(manage_nicknames=True)
    async def rename(
        self,
        ctx: commands.Context,
        user: discord.Member,
        *,
        nickname: str = "",
    ) -> None:
        """Change or clear a member's server nickname.

        Leave `nickname` blank to clear the nickname.

        **Examples:**
        - `[p]rename @User CoolNick`
        - `[p]rename @User` — clears their nickname.
        """
        nickname = nickname.strip() or None
        me = cast(discord.Member, ctx.me)

        if nickname is not None and not 2 <= len(nickname) <= 32:
            await ctx.send(_("Nicknames must be between 2 and 32 characters."))
            return
        if not (
            (me.guild_permissions.manage_nicknames or me.guild_permissions.administrator)
            and me.top_role > user.top_role
            and user != ctx.guild.owner
        ):
            await ctx.send(_("I do not have permission to rename that member."))
            return

        old_nick = user.nick
        try:
            await user.edit(nick=nickname, reason=get_audit_reason(ctx.author, None))
        except discord.Forbidden:
            await ctx.send(_("I do not have permission to rename that member."))
        except discord.HTTPException:
            await ctx.send(_("That nickname is invalid or Discord rejected it."))
        else:
            embed = _base_embed(_("✏️ Nickname Changed"), colour=_C_INFO)
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="👤 Member", value=user.mention, inline=True)
            embed.add_field(name="📛 Before", value=f"`{old_nick}`" if old_nick else _("*(none)*"), inline=True)
            embed.add_field(name="📛 After", value=f"`{nickname}`" if nickname else _("*(cleared)*"), inline=True)
            embed.set_footer(text=_("Changed by {mod}").format(mod=ctx.author))
            await ctx.send(embed=embed)
            await self.send_modlog_note(
                ctx.guild,
                title=_("Nickname changed"),
                description=_("{mod} renamed {member}.").format(
                    mod=ctx.author.mention,
                    member=user.mention,
                ),
            )

    # ------------------------------------------------------------------ #
    # Userinfo                                                             #
    # ------------------------------------------------------------------ #

    @commands.command(aliases=["ui", "memberinfo"])
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def userinfo(
        self, ctx: commands.Context, *, user: discord.Member | None = None
    ) -> None:
        """Show detailed information about a member.

        Includes account age, server join date, roles, and stored name history.
        """
        user = user or ctx.author
        names, nicks = await self.get_names_and_nicks(user)
        roles = user.roles[-1:0:-1]
        joined_at = user.joined_at or ctx.message.created_at

        status_emoji = {
            discord.Status.online: "🟢",
            discord.Status.idle: "🟡",
            discord.Status.dnd: "🔴",
            discord.Status.offline: "⚫",
        }.get(user.status, "⚫")

        embed = discord.Embed(
            colour=user.colour if user.colour.value else _C_INFO,
            timestamp=ctx.message.created_at,
        )
        embed.set_author(name=f"{user} {status_emoji}", icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)

        embed.add_field(
            name="🗓️ Account Created",
            value=f"<t:{int(user.created_at.timestamp())}:D>\n<t:{int(user.created_at.timestamp())}:R>",
            inline=True,
        )
        embed.add_field(
            name="📥 Joined Server",
            value=f"<t:{int(joined_at.timestamp())}:D>\n<t:{int(joined_at.timestamp())}:R>",
            inline=True,
        )
        embed.add_field(name="🆔 User ID", value=f"`{user.id}`", inline=True)

        if user.activity:
            activity_name = getattr(user.activity, "name", None) or str(user.activity)
            embed.add_field(name="🎮 Activity", value=activity_name, inline=True)

        if user.premium_since:
            embed.add_field(
                name="💎 Boosting Since",
                value=f"<t:{int(user.premium_since.timestamp())}:D>",
                inline=True,
            )

        warnings = await self.get_warnings(user)
        embed.add_field(name="⚠️ Warnings", value=str(len(warnings)), inline=True)

        if roles:
            role_text = " ".join(role.mention for role in roles)
            if len(role_text) > 1024:
                role_text = role_text[:1000] + "…"
            embed.add_field(
                name=_("🎭 Roles ({count})").format(count=len(roles)),
                value=role_text,
                inline=False,
            )

        if names:
            safe = [escape_spoilers_and_mass_mentions(n) for n in names]
            embed.add_field(name="📝 Past Usernames", value=", ".join(safe), inline=False)
        if nicks:
            safe = [escape_spoilers_and_mass_mentions(n) for n in nicks]
            embed.add_field(name="🏷️ Past Nicknames", value=", ".join(safe), inline=False)

        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------ #
    # Kick                                                                 #
    # ------------------------------------------------------------------ #

    @commands.command()
    @commands.guild_only()
    @commands.bot_has_permissions(kick_members=True, embed_links=True)
    async def kick(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: str | None = None,
    ) -> None:
        """Kick a member from the server.

        **Example:**
        - `[p]kick @User Spamming in general.`
        """
        if not await self.action_check(ctx, "kick"):
            return
        if not await self.is_allowed_by_hierarchy(ctx.guild, ctx.author, member):
            await ctx.send(_("You cannot kick that member due to role hierarchy."))
            return
        if ctx.guild.me.top_role <= member.top_role or member == ctx.guild.owner:
            await ctx.send(_("I cannot kick that member due to Discord's hierarchy rules."))
            return

        dm_embed = _dm_embed(
            _("kicked"),
            guild=ctx.guild,
            reason=reason,
            colour=_C_KICK,
        )
        await self.maybe_dm_before_action(
            member, action=_("kicked"), guild=ctx.guild, reason=reason, embed=dm_embed
        )

        try:
            await member.kick(reason=get_audit_reason(ctx.author, reason))
        except discord.HTTPException:
            await ctx.send(_("Discord rejected the kick request."))
            return

        await self.create_modlog_case(
            ctx.guild,
            action_type="kick",
            user=member,
            moderator=ctx.author,
            reason=reason,
        )

        embed = _action_embed(
            "👢 Member Kicked",
            colour=_C_KICK,
            target=member,
            moderator=ctx.author,
            reason=reason,
        )
        await ctx.send(embed=embed)

        notif_embed = _action_embed(
            f"👢 Member Kicked — {ctx.guild.name}",
            colour=_C_KICK,
            target=member,
            moderator=ctx.author,
            reason=reason,
        )
        await self.notify("kick", notif_embed)

    # ------------------------------------------------------------------ #
    # Ban                                                                  #
    # ------------------------------------------------------------------ #

    @commands.command()
    @commands.guild_only()
    @commands.bot_has_permissions(ban_members=True, embed_links=True)
    async def ban(
        self,
        ctx: commands.Context,
        member: discord.Member | discord.User,
        days: int | None = None,
        *,
        reason: str | None = None,
    ) -> None:
        """Ban a user from the server.

        `days` controls message history deletion (0–7).

        **Examples:**
        - `[p]ban @User 1 Spamming.`
        - `[p]ban 123456789 Hate speech.`
        """
        if not await self.action_check(ctx, "ban"):
            return
        if isinstance(member, discord.Member):
            if not await self.is_allowed_by_hierarchy(ctx.guild, ctx.author, member):
                await ctx.send(_("You cannot ban that member due to role hierarchy."))
                return
            if ctx.guild.me.top_role <= member.top_role or member == ctx.guild.owner:
                await ctx.send(_("I cannot ban that member due to Discord's hierarchy rules."))
                return

        if days is None:
            days = await self.config.guild(ctx.guild).default_days()
        if not 0 <= days <= 7:
            await ctx.send(_("Discord only allows 0–7 days of message deletion."))
            return

        dm_embed = _dm_embed(_("banned"), guild=ctx.guild, reason=reason, colour=_C_BAN)
        await self.maybe_dm_before_action(
            member, action=_("banned"), guild=ctx.guild, reason=reason, embed=dm_embed
        )

        try:
            await _guild_ban(ctx.guild, member, reason=get_audit_reason(ctx.author, reason), delete_days=days)
        except discord.HTTPException:
            await ctx.send(_("Discord rejected the ban request."))
            return

        await self.create_modlog_case(
            ctx.guild, action_type="ban", user=member, moderator=ctx.author, reason=reason
        )

        extra = []
        if days:
            extra.append(("🗑️ Messages Deleted", f"Last **{days}** day{'s' if days != 1 else ''}", True))

        embed = _action_embed(
            "🔨 Member Banned",
            colour=_C_BAN,
            target=member,
            moderator=ctx.author,
            reason=reason,
            extra_fields=extra,
        )
        await ctx.send(embed=embed)

        notif_embed = _action_embed(
            f"🔨 Member Banned — {ctx.guild.name}",
            colour=_C_BAN,
            target=member,
            moderator=ctx.author,
            reason=reason,
            extra_fields=extra,
        )
        await self.notify("ban", notif_embed)

    # ------------------------------------------------------------------ #
    # Softban                                                              #
    # ------------------------------------------------------------------ #

    @commands.command()
    @commands.guild_only()
    @commands.bot_has_permissions(ban_members=True, embed_links=True)
    async def softban(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: str | None = None,
    ) -> None:
        """Softban a member — ban then immediately unban to clear recent messages."""
        if not await self.action_check(ctx, "ban"):
            return
        if not await self.is_allowed_by_hierarchy(ctx.guild, ctx.author, member):
            await ctx.send(_("You cannot softban that member due to role hierarchy."))
            return

        dm_embed = _dm_embed(_("softbanned"), guild=ctx.guild, reason=reason, colour=_C_SOFTBAN)
        await self.maybe_dm_before_action(
            member, action=_("softbanned"), guild=ctx.guild, reason=reason, embed=dm_embed
        )

        try:
            await _guild_ban(ctx.guild, member, reason=get_audit_reason(ctx.author, reason), delete_days=1)
            await ctx.guild.unban(member, reason=_("Softban follow-up unban."))
        except discord.HTTPException:
            await ctx.send(_("Discord rejected the softban request."))
            return

        await self.create_modlog_case(
            ctx.guild, action_type="softban", user=member, moderator=ctx.author, reason=reason
        )

        embed = _action_embed(
            "💨 Member Softbanned",
            colour=_C_SOFTBAN,
            target=member,
            moderator=ctx.author,
            reason=reason,
            extra_fields=[("ℹ️ Note", "Banned then immediately unbanned — recent messages cleared.", False)],
        )
        await ctx.send(embed=embed)
        await self.notify("ban", embed)

    # ------------------------------------------------------------------ #
    # Tempban                                                              #
    # ------------------------------------------------------------------ #

    @commands.command()
    @commands.guild_only()
    @commands.bot_has_permissions(ban_members=True, embed_links=True)
    async def tempban(
        self,
        ctx: commands.Context,
        member: discord.Member | discord.User,
        duration: commands.TimedeltaConverter(
            minimum=timedelta(minutes=1),
            maximum=timedelta(days=365),
            default_unit="hours",
        ) = None,
        *,
        reason: str | None = None,
    ) -> None:
        """Temporarily ban a user until the expiry task lifts the ban.

        **Examples:**
        - `[p]tempban @User 24h Repeated offences.`
        - `[p]tempban @User 7d Continued harassment.`
        """
        if not await self.action_check(ctx, "ban"):
            return
        if isinstance(member, discord.Member):
            if not await self.is_allowed_by_hierarchy(ctx.guild, ctx.author, member):
                await ctx.send(_("You cannot tempban that member due to role hierarchy."))
                return

        if duration is None:
            default_seconds = await self.config.guild(ctx.guild).default_tempban_duration()
            duration = timedelta(seconds=default_seconds)

        expiry = datetime.now(tz=timezone.utc) + duration
        readable = humanize_timedelta(timedelta=duration)

        dm_embed = _dm_embed(
            _("temporarily banned"),
            guild=ctx.guild,
            reason=reason,
            colour=_C_TEMPBAN,
            extra_fields=[
                ("⏳ Duration", readable, True),
                ("📅 Expires", f"<t:{int(expiry.timestamp())}:F>", True),
            ],
        )
        await self.maybe_dm_before_action(
            member, action=_("tempbanned"), guild=ctx.guild, reason=reason, embed=dm_embed
        )

        try:
            await _guild_ban(ctx.guild, member, reason=get_audit_reason(ctx.author, reason), delete_days=0)
        except discord.HTTPException:
            await ctx.send(_("Discord rejected the tempban request."))
            return

        async with self.config.guild(ctx.guild).current_tempbans() as tempbans:
            if member.id not in tempbans:
                tempbans.append(member.id)
        await self.config.member_from_ids(ctx.guild.id, member.id).banned_until.set(expiry.isoformat())

        await self.create_modlog_case(
            ctx.guild,
            action_type="tempban",
            user=member,
            moderator=ctx.author,
            reason=reason,
            until=expiry,
        )

        embed = _action_embed(
            "⏳ Member Temporarily Banned",
            colour=_C_TEMPBAN,
            target=member,
            moderator=ctx.author,
            reason=reason,
            extra_fields=[
                ("⏳ Duration", readable, True),
                ("📅 Expires", f"<t:{int(expiry.timestamp())}:F>", True),
            ],
        )
        await ctx.send(embed=embed)
        await self.notify("ban", embed)

    # ------------------------------------------------------------------ #
    # Unban                                                                #
    # ------------------------------------------------------------------ #

    @commands.command()
    @commands.guild_only()
    @commands.bot_has_permissions(ban_members=True, embed_links=True)
    async def unban(
        self,
        ctx: commands.Context,
        user_id: RawUserIds,
        *,
        reason: str | None = None,
    ) -> None:
        """Unban a user by their ID.

        **Example:**
        - `[p]unban 123456789 Appeal accepted.`
        """
        if not await self.action_check(ctx, "ban"):
            return

        user = discord.Object(id=user_id)
        try:
            await ctx.guild.unban(user, reason=get_audit_reason(ctx.author, reason))
        except discord.HTTPException:
            await ctx.send(_("Could not unban that user — are they actually banned?"))
            return

        async with self.config.guild(ctx.guild).current_tempbans() as tempbans:
            with suppress(ValueError):
                tempbans.remove(user_id)
        await self.config.member_from_ids(ctx.guild.id, user_id).banned_until.clear()

        await self.create_modlog_case(
            ctx.guild, action_type="unban", user=user, moderator=ctx.author, reason=reason
        )

        embed = _base_embed("✅ User Unbanned", colour=_C_UNBAN)
        embed.add_field(name="🆔 User ID", value=f"`{user_id}`", inline=True)
        embed.add_field(name="🛡️ Moderator", value=ctx.author.mention, inline=True)
        embed.add_field(name="📋 Reason", value=reason or _("No reason provided."), inline=False)

        if await self.config.guild(ctx.guild).reinvite_on_unban():
            invite = await self.get_invite_for_reinvite(ctx)
            if invite is not None:
                try:
                    fetched = await self.bot.fetch_user(user_id)
                except discord.HTTPException:
                    fetched = None
                if fetched is not None:
                    reinvite_dm = discord.Embed(
                        title=_("You have been unbanned from {guild}").format(guild=ctx.guild.name),
                        description=_("Here is a fresh invite: {url}").format(url=invite.url),
                        colour=_C_UNBAN,
                    )
                    with suppress(discord.HTTPException, discord.Forbidden):
                        await fetched.send(embed=reinvite_dm)
                    embed.add_field(name="📨 Reinvite", value=_("A fresh invite was sent."), inline=False)

        await ctx.send(embed=embed)

    # ------------------------------------------------------------------ #
    # Massban                                                              #
    # ------------------------------------------------------------------ #

    @commands.command(aliases=["hackban"])
    @commands.guild_only()
    @commands.bot_has_permissions(ban_members=True, embed_links=True)
    async def massban(
        self,
        ctx: commands.Context,
        user_ids: Greedy[RawUserIds],
        *,
        reason: str | None = None,
    ) -> None:
        """Ban multiple users by ID in one command.

        **Example:**
        - `[p]massban 111 222 333 Mass botting accounts.`
        """
        if not await self.action_check(ctx, "ban"):
            return
        if not user_ids:
            await ctx.send(_("Provide one or more user IDs to ban."))
            return

        banned: list[str] = []
        failed: list[str] = []

        for user_id in user_ids:
            target = discord.Object(id=user_id)
            try:
                await _guild_ban(ctx.guild, target, reason=get_audit_reason(ctx.author, reason), delete_days=0)
                banned.append(str(user_id))
                await self.create_modlog_case(
                    ctx.guild, action_type="ban", user=target, moderator=ctx.author, reason=reason
                )
            except discord.HTTPException:
                failed.append(str(user_id))

        embed = _base_embed("🔨 Massban Results", colour=_C_BAN)
        embed.add_field(name="🛡️ Moderator", value=ctx.author.mention, inline=True)
        embed.add_field(name="✅ Banned", value=str(len(banned)), inline=True)
        embed.add_field(name="❌ Failed", value=str(len(failed)), inline=True)
        embed.add_field(name="📋 Reason", value=reason or _("No reason provided."), inline=False)
        if banned:
            embed.add_field(name="✅ Banned IDs", value=_format_id_list(banned), inline=False)
        if failed:
            embed.add_field(name="❌ Failed IDs", value=_format_id_list(failed), inline=False)

        await ctx.send(embed=embed)
        if banned:
            await self.notify("ban", embed)

    # ------------------------------------------------------------------ #
    # Timeout / Mute                                                       #
    # ------------------------------------------------------------------ #

    @commands.command(aliases=["mute"])
    @commands.guild_only()
    @commands.bot_has_permissions(moderate_members=True, embed_links=True)
    async def timeout(
        self,
        ctx: commands.Context,
        member: discord.Member,
        duration: commands.TimedeltaConverter(
            minimum=timedelta(seconds=1),
            maximum=timedelta(days=28),
            default_unit="minutes",
        ) = None,
        *,
        reason: str | None = None,
    ) -> None:
        """Timeout (mute) a member for a specified duration.

        Discord's native timeout prevents the member from sending messages,
        joining voice channels, or reacting for the specified period.
        Maximum duration is 28 days (Discord limit).

        **Examples:**
        - `[p]timeout @User 30m Heated argument.`
        - `[p]mute @User 2h Repeated rule violations.`
        """
        if not await self.action_check(ctx, "mute"):
            return
        if not await self.is_allowed_by_hierarchy(ctx.guild, ctx.author, member):
            await ctx.send(_("You cannot timeout that member due to role hierarchy."))
            return
        if ctx.guild.me.top_role <= member.top_role or member == ctx.guild.owner:
            await ctx.send(_("I cannot timeout that member due to Discord's hierarchy rules."))
            return

        if duration is None:
            duration = timedelta(minutes=10)

        expiry = datetime.now(tz=timezone.utc) + duration
        readable = humanize_timedelta(timedelta=duration)

        dm_embed = _dm_embed(
            _("timed out"),
            guild=ctx.guild,
            reason=reason,
            colour=_C_MUTE,
            extra_fields=[
                ("⏳ Duration", readable, True),
                ("📅 Expires", f"<t:{int(expiry.timestamp())}:F>", True),
            ],
        )
        await self.maybe_dm_before_action(
            member, action=_("timed out"), guild=ctx.guild, reason=reason, embed=dm_embed
        )

        try:
            await member.timeout(duration, reason=get_audit_reason(ctx.author, reason))
        except discord.Forbidden:
            await ctx.send(_("I do not have permission to timeout that member."))
            return
        except discord.HTTPException:
            await ctx.send(_("Discord rejected the timeout request."))
            return

        await self.create_modlog_case(
            ctx.guild,
            action_type="mute",
            user=member,
            moderator=ctx.author,
            reason=reason,
            until=expiry,
        )

        embed = _action_embed(
            "🔇 Member Timed Out",
            colour=_C_MUTE,
            target=member,
            moderator=ctx.author,
            reason=reason,
            extra_fields=[
                ("⏳ Duration", readable, True),
                ("📅 Expires", f"<t:{int(expiry.timestamp())}:F>", True),
            ],
        )
        await ctx.send(embed=embed)

        notif_embed = _action_embed(
            f"🔇 Member Timed Out — {ctx.guild.name}",
            colour=_C_MUTE,
            target=member,
            moderator=ctx.author,
            reason=reason,
            extra_fields=[("⏳ Duration", readable, True)],
        )
        await self.notify("mute", notif_embed)

    @commands.command(aliases=["unmute"])
    @commands.guild_only()
    @commands.bot_has_permissions(moderate_members=True, embed_links=True)
    async def untimeout(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: str | None = None,
    ) -> None:
        """Remove a timeout from a member early.

        **Example:**
        - `[p]untimeout @User Calmed down.`
        """
        if not await self.action_check(ctx, "mute"):
            return

        if member.timed_out_until is None:
            await ctx.send(_("That member is not currently timed out."))
            return

        try:
            await member.timeout(None, reason=get_audit_reason(ctx.author, reason))
        except discord.Forbidden:
            await ctx.send(_("I do not have permission to remove that timeout."))
            return
        except discord.HTTPException:
            await ctx.send(_("Discord rejected the untimeout request."))
            return

        await self.create_modlog_case(
            ctx.guild, action_type="unmute", user=member, moderator=ctx.author, reason=reason
        )

        embed = _action_embed(
            "🔊 Timeout Removed",
            colour=_C_UNMUTE,
            target=member,
            moderator=ctx.author,
            reason=reason,
        )
        await ctx.send(embed=embed)
        await self.notify("mute", embed)

    # ------------------------------------------------------------------ #
    # Warn system                                                          #
    # ------------------------------------------------------------------ #

    @commands.command()
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def warn(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: str | None = None,
    ) -> None:
        """Issue a formal warning to a member.

        Warnings are stored and can be reviewed with `[p]warnings`.
        Warning milestone roles are applied automatically if configured.

        **Example:**
        - `[p]warn @User Stop spamming in #general.`
        """
        if not await self.action_check(ctx, "warn"):
            return
        if not await self.is_allowed_by_hierarchy(ctx.guild, ctx.author, member):
            await ctx.send(_("You cannot warn that member due to role hierarchy."))
            return

        count = await self.add_warning(member, reason=reason, moderator=ctx.author)

        dm_embed = discord.Embed(
            title=_("⚠️ You have received a warning in **{guild}**").format(guild=ctx.guild.name),
            colour=_C_WARN,
        )
        dm_embed.add_field(name="📋 Reason", value=reason or _("No reason provided."), inline=False)
        dm_embed.add_field(name="⚠️ Total Warnings", value=str(count), inline=True)
        dm_embed.set_footer(text=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        dm_embed.timestamp = datetime.now(tz=timezone.utc)

        await self.maybe_dm_before_action(
            member, action=_("warned"), guild=ctx.guild, reason=reason, embed=dm_embed
        )

        await self.create_modlog_case(
            ctx.guild, action_type="warning", user=member, moderator=ctx.author, reason=reason
        )

        embed = _action_embed(
            f"⚠️ Member Warned — Warning #{count}",
            colour=_C_WARN,
            target=member,
            moderator=ctx.author,
            reason=reason,
            extra_fields=[("📊 Total Warnings", str(count), True)],
        )
        await ctx.send(embed=embed)

        notif_embed = _action_embed(
            f"⚠️ Member Warned — {ctx.guild.name}",
            colour=_C_WARN,
            target=member,
            moderator=ctx.author,
            reason=reason,
            extra_fields=[("📊 Total Warnings", str(count), True)],
        )
        await self.notify("warn", notif_embed)

    @commands.command(aliases=["warnlist", "infractions"])
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def warnings(
        self, ctx: commands.Context, member: discord.Member | None = None
    ) -> None:
        """Show all warnings for a member.

        **Example:**
        - `[p]warnings @User`
        """
        member = member or ctx.author
        warns = await self.get_warnings(member)

        embed = discord.Embed(
            title=f"⚠️ Warnings — {member.display_name}",
            colour=_C_WARN,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="👤 Member", value=member.mention, inline=True)
        embed.add_field(name="📊 Total", value=str(len(warns)), inline=True)
        embed.timestamp = datetime.now(tz=timezone.utc)

        if not warns:
            embed.description = _("✅ This member has no recorded warnings.")
        else:
            for i, warn in enumerate(warns[-10:], start=max(1, len(warns) - 9)):
                ts = warn.get("timestamp", "")
                ts_display = ""
                with suppress(Exception):
                    dt = datetime.fromisoformat(ts)
                    ts_display = f" — <t:{int(dt.timestamp())}:D>"
                mod_id = warn.get("moderator_id")
                mod_display = f"<@{mod_id}>" if mod_id else _("Unknown")
                embed.add_field(
                    name=f"#{i}{ts_display}",
                    value=f"**Reason:** {warn.get('reason', 'No reason')}\n**By:** {mod_display}",
                    inline=False,
                )
            if len(warns) > 10:
                embed.set_footer(text=_("Showing last 10 of {total} warnings.").format(total=len(warns)))

        await ctx.send(embed=embed)

    @commands.command(aliases=["clearwarnings"])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    @commands.bot_has_permissions(embed_links=True)
    async def clearwarns(
        self, ctx: commands.Context, member: discord.Member
    ) -> None:
        """Clear all warnings for a member.

        **Example:**
        - `[p]clearwarns @User`
        """
        count = await self.clear_warnings(member)

        embed = _base_embed("🧹 Warnings Cleared", colour=_C_UNMUTE)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="👤 Member", value=member.mention, inline=True)
        embed.add_field(name="🗑️ Removed", value=str(count), inline=True)
        embed.set_footer(text=_("Cleared by {mod}").format(mod=ctx.author))
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------ #
    # Purge / Clean messages                                               #
    # ------------------------------------------------------------------ #

    @commands.command(aliases=["purge", "prune"])
    @commands.guild_only()
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True, embed_links=True)
    async def clean(
        self,
        ctx: commands.Context,
        amount: int,
        member: discord.Member | None = None,
    ) -> None:
        """Bulk-delete messages from the current channel.

        Optionally filter by a specific member.
        Maximum 100 messages per use.

        **Examples:**
        - `[p]clean 25` — delete the last 25 messages.
        - `[p]clean 50 @User` — delete the last 50 messages from @User.
        """
        if not await self.action_check(ctx, "deletemessages"):
            return
        if not 1 <= amount <= 100:
            await ctx.send(_("Amount must be between 1 and 100."))
            return

        def check(msg: discord.Message) -> bool:
            if member is None:
                return True
            return msg.author == member

        with suppress(discord.HTTPException):
            await ctx.message.delete()

        try:
            deleted = await ctx.channel.purge(limit=amount, check=check)
        except discord.Forbidden:
            await ctx.send(_("I do not have permission to delete messages here."))
            return
        except discord.HTTPException:
            await ctx.send(_("An error occurred while deleting messages."))
            return

        embed = _base_embed("🗑️ Messages Purged", colour=_C_CHANNEL)
        embed.add_field(name="📌 Channel", value=ctx.channel.mention, inline=True)
        embed.add_field(name="🗑️ Deleted", value=str(len(deleted)), inline=True)
        if member:
            embed.add_field(name="👤 Filter", value=member.mention, inline=True)
        embed.set_footer(text=_("Purged by {mod}").format(mod=ctx.author))

        confirm = await ctx.send(embed=embed)
        await self.send_modlog_note(
            ctx.guild,
            title=_("Messages purged"),
            description=_(
                "{mod} purged **{count}** message(s) in {channel}{user_filter}."
            ).format(
                mod=ctx.author.mention,
                count=len(deleted),
                channel=ctx.channel.mention,
                user_filter=f" from {member.mention}" if member else "",
            ),
        )

        notif_embed = _base_embed(
            f"🗑️ Messages Purged — {ctx.guild.name}", colour=_C_CHANNEL
        )
        notif_embed.add_field(name="📌 Channel", value=ctx.channel.mention, inline=True)
        notif_embed.add_field(name="🗑️ Deleted", value=str(len(deleted)), inline=True)
        notif_embed.add_field(name="🛡️ Moderator", value=ctx.author.mention, inline=True)
        await self.notify("deletemessages", notif_embed)

        # Auto-delete the confirmation after 5 s
        await asyncio.sleep(5)
        with suppress(discord.HTTPException):
            await confirm.delete()

    # ------------------------------------------------------------------ #
    # Pin / Unpin                                                          #
    # ------------------------------------------------------------------ #

    @commands.command()
    @commands.guild_only()
    @commands.bot_has_permissions(manage_messages=True, embed_links=True)
    async def pin(
        self,
        ctx: commands.Context,
        message: discord.Message | None = None,
    ) -> None:
        """Pin a message in the current channel.

        Reply to a message or provide its ID/link.
        """
        if not await self.action_check(ctx, "deletemessages"):
            return

        target = message
        if target is None and ctx.message.reference:
            ref = ctx.message.reference.resolved
            if isinstance(ref, discord.Message):
                target = ref

        if target is None:
            await ctx.send(_("Reply to a message or provide a message ID/link to pin."))
            return

        try:
            await target.pin(reason=get_audit_reason(ctx.author, None))
        except discord.Forbidden:
            await ctx.send(_("I do not have permission to pin messages here."))
            return
        except discord.HTTPException:
            await ctx.send(_("Could not pin that message (max 50 pins reached?)."))
            return

        embed = _base_embed("📌 Message Pinned", colour=_C_INFO)
        embed.add_field(name="📌 Channel", value=ctx.channel.mention, inline=True)
        embed.add_field(
            name="🔗 Jump", value=f"[Click to view]({target.jump_url})", inline=True
        )
        embed.set_footer(text=_("Pinned by {mod}").format(mod=ctx.author))
        await ctx.send(embed=embed)
