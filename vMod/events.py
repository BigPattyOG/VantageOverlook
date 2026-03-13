"""Listeners for bot-managed automations, name tracking, and notification dispatch."""

from __future__ import annotations

from collections import defaultdict, deque
from contextlib import suppress
from datetime import datetime, timezone

import discord
from redbot.core import commands, i18n
from redbot.core.utils.mod import is_mod_or_superior

from .base import VModBase
from .constants import _

# Colour constants reused from moderation.py logic (avoid import cycle — define inline)
_C_BAN   = discord.Color.from_rgb(194, 33,  33)
_C_KICK  = discord.Color.from_rgb(237, 66,  69)
_C_WARN  = discord.Color.from_rgb(240, 173, 22)
_C_NOTIF = discord.Color.from_rgb(255, 165,  0)   # orange for system notifications


def _ts_embed(title: str, description: str, *, colour: discord.Color) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, colour=colour)
    embed.timestamp = datetime.now(tz=timezone.utc)
    return embed


class VModEvents(VModBase):
    """Event listeners for automod, name tracking, and notification dispatch."""

    # ------------------------------------------------------------------ #
    # Duplicate-message automod                                            #
    # ------------------------------------------------------------------ #

    async def check_duplicates(self, message: discord.Message) -> bool:
        """Delete repeated messages when the per-guild threshold is enabled."""
        if not message.content:
            return False

        repeats = await self.config.guild(message.guild).delete_repeats()
        if repeats == -1:
            return False

        guild_cache = self.repeat_cache.get(message.guild.id)
        if guild_cache is None or any(c.maxlen != repeats for c in guild_cache.values()):
            guild_cache = defaultdict(lambda: deque(maxlen=repeats))
            self.repeat_cache[message.guild.id] = guild_cache

        author_cache = guild_cache[message.author.id]
        author_cache.append(message.content)
        if len(author_cache) == author_cache.maxlen and len(set(author_cache)) == 1:
            with suppress(discord.HTTPException, discord.Forbidden):
                await message.delete()
                await self.send_modlog_note(
                    message.guild,
                    title=_("Repeated messages removed"),
                    description=_("Deleted repeated messages from {member} in {channel}.").format(
                        member=message.author.mention,
                        channel=message.channel.mention,
                    ),
                )
            return True
        return False

    # ------------------------------------------------------------------ #
    # Mention-spam automod                                                 #
    # ------------------------------------------------------------------ #

    async def check_mention_spam(self, message: discord.Message) -> bool:
        """Apply warn/kick/ban behaviour for mention spam, and notify subscribers."""
        ms = await self.config.guild(message.guild).mention_spam.all()
        mentions = message.raw_mentions if ms["strict"] else {m.id for m in message.mentions}
        count = len(mentions)
        guild = message.guild
        author = message.author

        if ms["ban"] and count >= ms["ban"]:
            await self.maybe_dm_before_action(
                author, action=_("banned"), guild=guild, reason=_("Mention spam — autoban")
            )
            banned = False
            with suppress(discord.HTTPException, discord.Forbidden):
                await guild.ban(author, reason=_("Mention spam (Autoban)"), delete_message_seconds=0)
                banned = True
            if banned:
                await self.create_modlog_case(
                    guild,
                    action_type="ban",
                    user=author,
                    moderator=guild.me or self.bot.user,
                    reason=_("Mention spam (Autoban)"),
                    created_at=message.created_at.replace(tzinfo=timezone.utc),
                )
                notif = _ts_embed(
                    title=f"🔨 Autoban — Mention Spam ({guild.name})",
                    description=(
                        f"**Member:** {author.mention} (`{author.id}`)\n"
                        f"**Mentions:** {count}\n"
                        f"**Channel:** {message.channel.mention}"
                    ),
                    colour=_C_BAN,
                )
                await self.notify("ban", notif)
                return True

        if ms["kick"] and count >= ms["kick"]:
            await self.maybe_dm_before_action(
                author, action=_("kicked"), guild=guild, reason=_("Mention spam — autokick")
            )
            kicked = False
            with suppress(discord.HTTPException, discord.Forbidden):
                await guild.kick(author, reason=_("Mention spam (Autokick)"))
                kicked = True
            if kicked:
                await self.create_modlog_case(
                    guild,
                    action_type="kick",
                    user=author,
                    moderator=guild.me or self.bot.user,
                    reason=_("Mention spam (Autokick)"),
                    created_at=message.created_at.replace(tzinfo=timezone.utc),
                )
                notif = _ts_embed(
                    title=f"👢 Autokick — Mention Spam ({guild.name})",
                    description=(
                        f"**Member:** {author.mention} (`{author.id}`)\n"
                        f"**Mentions:** {count}\n"
                        f"**Channel:** {message.channel.mention}"
                    ),
                    colour=_C_KICK,
                )
                await self.notify("kick", notif)
                return True

        if ms["warn"] and count >= ms["warn"]:
            warned = False
            warn_embed = discord.Embed(
                title=_("⚠️ Mention spam warning"),
                description=_("Please do not mass-mention people in **{guild}**.").format(guild=guild.name),
                colour=_C_WARN,
            )
            with suppress(discord.HTTPException, discord.Forbidden):
                await author.send(embed=warn_embed)
                warned = True
            if not warned:
                with suppress(discord.HTTPException, discord.Forbidden):
                    await message.channel.send(
                        _("{member}, please do not mass-mention people.").format(member=author.mention)
                    )
                    warned = True
            if warned:
                await self.create_modlog_case(
                    guild,
                    action_type="warning",
                    user=author,
                    moderator=guild.me or self.bot.user,
                    reason=_("Mention spam (Autowarn)"),
                    created_at=message.created_at.replace(tzinfo=timezone.utc),
                )
                notif = _ts_embed(
                    title=f"⚠️ Autowarn — Mention Spam ({guild.name})",
                    description=(
                        f"**Member:** {author.mention} (`{author.id}`)\n"
                        f"**Mentions:** {count}\n"
                        f"**Channel:** {message.channel.mention}"
                    ),
                    colour=_C_WARN,
                )
                await self.notify("warn", notif)
                return True

        return False

    # ------------------------------------------------------------------ #
    # Event listeners                                                      #
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Run automod checks for incoming guild messages."""
        if message.guild is None or message.author.bot:
            return
        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        if not isinstance(message.author, discord.Member):
            return
        if await is_mod_or_superior(self.bot, obj=message.author):
            return
        if await self.bot.is_automod_immune(message):
            return

        await i18n.set_contextual_locales_from_guild(self.bot, message.guild)

        deleted = await self.check_duplicates(message)
        if not deleted:
            await self.check_mention_spam(message)

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User) -> None:
        """Track username changes globally."""
        if before.name == after.name:
            return
        if not await self.config.track_all_names():
            return
        await self.append_name_history(before, before.name)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Track nickname changes and alert on administrator role grants."""
        if before.nick != after.nick and after.nick is not None:
            if not await self.bot.cog_disabled_in_guild(self, after.guild):
                if await self.config.track_all_names() and await self.config.guild(after.guild).track_nicknames():
                    if before.nick is not None:
                        await self.append_nick_history(before, before.nick)

        gained_roles = [r for r in after.roles if r not in before.roles]
        for role in gained_roles:
            if role.permissions.administrator:
                await self.send_modlog_note(
                    after.guild,
                    title=_("Administrator role granted"),
                    description=_("{member} gained administrator via role {role}.").format(
                        member=after.mention, role=role.mention
                    ),
                )
                notif = _ts_embed(
                    title=f"🚨 Admin Role Granted — {after.guild.name}",
                    description=(
                        f"**Member:** {after.mention} (`{after.id}`)\n"
                        f"**Role:** {role.mention} (`{role.id}`)"
                    ),
                    colour=discord.Color.from_rgb(255, 80, 80),
                )
                await self.notify("adminrole", notif)
                break

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        """Alert when a role gains administrator permissions."""
        if after.permissions.administrator and not before.permissions.administrator:
            await self.send_modlog_note(
                after.guild,
                title=_("Role permissions escalated"),
                description=_("Role {role} gained administrator permissions.").format(role=after.mention),
            )
            notif = _ts_embed(
                title=f"🚨 Role Gained Admin — {after.guild.name}",
                description=(
                    f"**Role:** {after.mention} (`{after.id}`)\n"
                    f"**Server:** {after.guild.name} (`{after.guild.id}`)"
                ),
                colour=discord.Color.from_rgb(255, 80, 80),
            )
            await self.notify("adminrole", notif)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Alert when a bot joins the server."""
        if not member.bot:
            return
        await self.send_modlog_note(
            member.guild,
            title=_("Bot joined"),
            description=_("Bot {member} joined the server.").format(member=member.mention),
        )
        notif = _ts_embed(
            title=f"🤖 Bot Joined — {member.guild.name}",
            description=(
                f"**Bot:** {member.mention} (`{member.id}`)\n"
                f"**Name:** {member}\n"
                f"**Server:** {member.guild.name} (`{member.guild.id}`)"
            ),
            colour=_C_NOTIF,
        )
        await self.notify("bot", notif)
