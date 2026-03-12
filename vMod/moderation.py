"""User-facing moderation and information commands for VMod."""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import cast

import discord
from redbot.core import checks, commands
from redbot.core.commands import Greedy
from redbot.core.utils.chat_formatting import humanize_timedelta
from redbot.core.utils.common_filters import escape_spoilers_and_mass_mentions, filter_invites
from redbot.core.utils.mod import get_audit_reason

from .base import VModBase
from .converters import RawUserIds
from .constants import _


class VModModeration(VModBase):
    """Moderation commands and informational member utilities."""

    @commands.command()
    @commands.guild_only()
    async def slowmode(
        self,
        ctx: commands.Context,
        *,
        interval: commands.TimedeltaConverter(
            minimum=timedelta(seconds=0), maximum=timedelta(hours=6), default_unit="seconds"
        ) = timedelta(seconds=0),
    ) -> None:
        """Set the current channel's slowmode interval."""
        if not await self.action_check(ctx, "editchannel"):
            return
        with suppress(discord.HTTPException, discord.Forbidden):
            await ctx.channel.edit(slowmode_delay=int(interval.total_seconds()))
            if interval.total_seconds() > 0:
                await ctx.send(
                    _("Slowmode set to **{interval}**.").format(
                        interval=humanize_timedelta(timedelta=interval)
                    )
                )
            else:
                await ctx.send(_("Slowmode disabled."))
            await self.send_modlog_note(
                ctx.guild,
                title=_("Slowmode changed"),
                description=_("{moderator} changed slowmode in {channel} to {interval}.").format(
                    moderator=ctx.author.mention,
                    channel=ctx.channel.mention,
                    interval=(humanize_timedelta(timedelta=interval) if interval.total_seconds() > 0 else _("off")),
                ),
            )
            return
        await ctx.send(_("I could not change slowmode in this channel."))

    @commands.command()
    @commands.guild_only()
    @commands.bot_has_permissions(manage_nicknames=True)
    @checks.admin_or_permissions(manage_nicknames=True)
    async def rename(
        self, ctx: commands.Context, user: discord.Member, *, nickname: str = ""
    ) -> None:
        """Change a user's nickname. Leave the nickname blank to clear it."""
        nickname = nickname.strip() or None
        me = cast(discord.Member, ctx.me)
        if nickname is not None and not 2 <= len(nickname) <= 32:
            await ctx.send(_("Nicknames must be between 2 and 32 characters long."))
            return
        if not (
            (me.guild_permissions.manage_nicknames or me.guild_permissions.administrator)
            and me.top_role > user.top_role
            and user != ctx.guild.owner
        ):
            await ctx.send(_("I do not have permission to rename that member."))
            return
        try:
            await user.edit(nick=nickname, reason=get_audit_reason(ctx.author, None))
        except discord.Forbidden:
            await ctx.send(_("I do not have permission to rename that member."))
        except discord.HTTPException:
            await ctx.send(_("That nickname is invalid or Discord rejected the request."))
        else:
            await ctx.send(_("Done."))
            await self.send_modlog_note(
                ctx.guild,
                title=_("Nickname changed"),
                description=_("{moderator} renamed {member}.").format(
                    moderator=ctx.author.mention,
                    member=user.mention,
                ),
            )

    @commands.command()
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def userinfo(self, ctx: commands.Context, *, user: discord.Member | None = None) -> None:
        """Show information about a member, including stored names and nicknames."""
        user = user or ctx.author
        names, nicks = await self.get_names_and_nicks(user)
        roles = user.roles[-1:0:-1]
        joined_at = user.joined_at or ctx.message.created_at

        embed = discord.Embed(
            colour=user.colour,
            description=(user.activity.name if user.activity and getattr(user.activity, "name", None) else None),
            timestamp=ctx.message.created_at,
        )
        embed.set_author(name=str(user), icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name=_("Joined Discord"), value=user.created_at.strftime("%d %b %Y %H:%M"))
        embed.add_field(name=_("Joined Server"), value=joined_at.strftime("%d %b %Y %H:%M"))
        if roles:
            role_text = ", ".join(role.mention for role in roles)
            if len(role_text) > 1024:
                role_text = role_text[:1000] + "..."
            embed.add_field(name=_("Roles"), value=role_text, inline=False)
        if names:
            safe_names = [escape_spoilers_and_mass_mentions(name) for name in names]
            embed.add_field(name=_("Past names"), value=", ".join(safe_names), inline=False)
        if nicks:
            safe_nicks = [escape_spoilers_and_mass_mentions(name) for name in nicks]
            embed.add_field(name=_("Past nicknames"), value=", ".join(safe_nicks), inline=False)
        if not names and not nicks:
            embed.set_footer(text=_("No recorded name history for this user."))
        await ctx.send(embed=embed)


    @commands.command()
    @commands.guild_only()
    async def kick(
        self, ctx: commands.Context, member: discord.Member, *, reason: str | None = None
    ) -> None:
        """Kick a member from the server."""
        if not await self.action_check(ctx, "kick"):
            return
        if not await self.is_allowed_by_hierarchy(ctx.guild, ctx.author, member):
            await ctx.send(_("You cannot kick that user because of role hierarchy."))
            return
        await self.maybe_dm_before_action(member, action=_("kicked"), guild=ctx.guild, reason=reason)
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
        await ctx.send(_("Kicked {member}.").format(member=member.mention))

    @commands.command()
    @commands.guild_only()
    async def ban(
        self,
        ctx: commands.Context,
        member: discord.Member | discord.User,
        days: int | None = None,
        *,
        reason: str | None = None,
    ) -> None:
        """Ban a user from the server.

        ``days`` controls message history deletion from 0 to 7 days.
        """
        if not await self.action_check(ctx, "ban"):
            return
        if isinstance(member, discord.Member):
            if not await self.is_allowed_by_hierarchy(ctx.guild, ctx.author, member):
                await ctx.send(_("You cannot ban that user because of role hierarchy."))
                return
        if days is None:
            days = await self.config.guild(ctx.guild).default_days()
        if not 0 <= days <= 7:
            await ctx.send(_("Discord only allows between 0 and 7 days of deleted history."))
            return
        await self.maybe_dm_before_action(member, action=_("banned"), guild=ctx.guild, reason=reason)
        try:
            await ctx.guild.ban(
                member,
                delete_message_days=days,
                reason=get_audit_reason(ctx.author, reason),
            )
        except TypeError:
            await ctx.guild.ban(
                member,
                delete_message_seconds=days * 86400,
                reason=get_audit_reason(ctx.author, reason),
            )
        except discord.HTTPException:
            await ctx.send(_("Discord rejected the ban request."))
            return
        await self.create_modlog_case(
            ctx.guild,
            action_type="ban",
            user=member,
            moderator=ctx.author,
            reason=reason,
        )
        await ctx.send(_("Banned {member}.").format(member=getattr(member, "mention", str(member))))

    @commands.command()
    @commands.guild_only()
    async def softban(
        self, ctx: commands.Context, member: discord.Member, *, reason: str | None = None
    ) -> None:
        """Softban a member by banning and immediately unbanning them."""
        if not await self.action_check(ctx, "ban"):
            return
        if not await self.is_allowed_by_hierarchy(ctx.guild, ctx.author, member):
            await ctx.send(_("You cannot softban that user because of role hierarchy."))
            return
        await self.maybe_dm_before_action(member, action=_("softbanned"), guild=ctx.guild, reason=reason)
        try:
            try:
                await ctx.guild.ban(member, delete_message_days=1, reason=get_audit_reason(ctx.author, reason))
            except TypeError:
                await ctx.guild.ban(member, delete_message_seconds=86400, reason=get_audit_reason(ctx.author, reason))
            await ctx.guild.unban(member, reason=_("Softban follow-up unban."))
        except discord.HTTPException:
            await ctx.send(_("Discord rejected the softban request."))
            return
        await self.create_modlog_case(
            ctx.guild,
            action_type="softban",
            user=member,
            moderator=ctx.author,
            reason=reason,
        )
        await ctx.send(_("Softbanned {member}.").format(member=member.mention))

    @commands.command()
    @commands.guild_only()
    async def tempban(
        self,
        ctx: commands.Context,
        member: discord.Member | discord.User,
        duration: commands.TimedeltaConverter(
            minimum=timedelta(minutes=1), maximum=timedelta(days=365), default_unit="hours"
        ) = None,
        *,
        reason: str | None = None,
    ) -> None:
        """Temporarily ban a user until the configured expiry task removes the ban."""
        if not await self.action_check(ctx, "ban"):
            return
        if isinstance(member, discord.Member):
            if not await self.is_allowed_by_hierarchy(ctx.guild, ctx.author, member):
                await ctx.send(_("You cannot tempban that user because of role hierarchy."))
                return

        if duration is None:
            default_seconds = await self.config.guild(ctx.guild).default_tempban_duration()
            duration = timedelta(seconds=default_seconds)

        expiry = datetime.now(tz=timezone.utc) + duration
        await self.maybe_dm_before_action(member, action=_("tempbanned"), guild=ctx.guild, reason=reason)
        try:
            await ctx.guild.ban(member, reason=get_audit_reason(ctx.author, reason), delete_message_seconds=0)
        except TypeError:
            try:
                await ctx.guild.ban(member, reason=get_audit_reason(ctx.author, reason), delete_message_days=0)
            except discord.HTTPException:
                await ctx.send(_("Discord rejected the tempban request."))
                return
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
        await ctx.send(
            _("Tempbanned {member} for {duration}.").format(
                member=getattr(member, "mention", str(member)),
                duration=humanize_timedelta(timedelta=duration),
            )
        )

    @commands.command()
    @commands.guild_only()
    async def unban(
        self, ctx: commands.Context, user_id: RawUserIds, *, reason: str | None = None
    ) -> None:
        """Unban a user by ID and optionally send a fresh invite if enabled."""
        if not await self.action_check(ctx, "ban"):
            return

        user = discord.Object(id=user_id)
        try:
            await ctx.guild.unban(user, reason=get_audit_reason(ctx.author, reason))
        except discord.HTTPException:
            await ctx.send(_("I could not unban that user. Make sure they are banned."))
            return

        async with self.config.guild(ctx.guild).current_tempbans() as tempbans:
            with suppress(ValueError):
                tempbans.remove(user_id)
        await self.config.member_from_ids(ctx.guild.id, user_id).banned_until.clear()
        await self.create_modlog_case(
            ctx.guild,
            action_type="unban",
            user=user,
            moderator=ctx.author,
            reason=reason,
        )

        msg = _("Unbanned `{user_id}`.").format(user_id=user_id)
        if await self.config.guild(ctx.guild).reinvite_on_unban():
            invite = await self.get_invite_for_reinvite(ctx)
            if invite is not None:
                try:
                    fetched_user = await self.bot.fetch_user(user_id)
                except discord.HTTPException:
                    fetched_user = None
                if fetched_user is not None:
                    with suppress(discord.HTTPException, discord.Forbidden):
                        await fetched_user.send(
                            _("You were unbanned from **{guild}**. Here is a new invite: {invite}").format(
                                guild=ctx.guild.name,
                                invite=invite.url,
                            )
                        )
                msg += _(" I also created a reinvite.")

        await ctx.send(msg)

    @commands.command()
    @commands.guild_only()
    async def massban(
        self, ctx: commands.Context, user_ids: Greedy[RawUserIds], *, reason: str | None = None
    ) -> None:
        """Ban multiple users by ID in one command."""
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
                await ctx.guild.ban(target, reason=get_audit_reason(ctx.author, reason), delete_message_seconds=0)
            except TypeError:
                try:
                    await ctx.guild.ban(target, reason=get_audit_reason(ctx.author, reason), delete_message_days=0)
                except discord.HTTPException:
                    failed.append(str(user_id))
                    continue
            except discord.HTTPException:
                failed.append(str(user_id))
                continue
            banned.append(str(user_id))
            await self.create_modlog_case(
                ctx.guild,
                action_type="ban",
                user=target,
                moderator=ctx.author,
                reason=reason or _("Massban"),
            )

        parts = []
        if banned:
            parts.append(_("Banned: {ids}").format(ids=", ".join(banned)))
        if failed:
            parts.append(_("Failed: {ids}").format(ids=", ".join(failed)))
        await ctx.send("\n".join(parts))