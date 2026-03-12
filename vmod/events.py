"""Listeners for bot-managed automations, name tracking, and staff notes."""

from __future__ import annotations

from collections import defaultdict, deque
from contextlib import suppress
from datetime import timezone

import discord
from redbot.core import commands, i18n
from redbot.core.utils.mod import is_mod_or_superior

from .base import VModBase
from .constants import _


class VModEvents(VModBase):
    """Listeners for moderation automations, name tracking, and informational notes."""

    async def check_duplicates(self, message: discord.Message) -> bool:
        """Delete repeated messages when the per-guild threshold is enabled."""
        if not message.content:
            return False

        repeats = await self.config.guild(message.guild).delete_repeats()
        if repeats == -1:
            return False

        guild_cache = self.repeat_cache.get(message.guild.id)
        if guild_cache is None or any(cache.maxlen != repeats for cache in guild_cache.values()):
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

    async def check_mention_spam(self, message: discord.Message) -> bool:
        """Apply warn, kick, or ban behavior for mention spam using bot-side logic."""
        mention_spam = await self.config.guild(message.guild).mention_spam.all()
        mentions = message.raw_mentions if mention_spam["strict"] else {m.id for m in message.mentions}
        mention_count = len(mentions)
        guild = message.guild
        author = message.author

        if mention_spam["ban"] and mention_count >= mention_spam["ban"]:
            await self.maybe_dm_before_action(
                author,
                action=_("banned"),
                guild=guild,
                reason=_("Mention spam (Autoban)"),
            )
            with suppress(discord.HTTPException, discord.Forbidden):
                await guild.ban(author, reason=_("Mention spam (Autoban)"), delete_message_seconds=0)
                await self.create_modlog_case(
                    guild,
                    action_type="ban",
                    user=author,
                    moderator=guild.me or self.bot.user,
                    reason=_("Mention spam (Autoban)"),
                    created_at=message.created_at.replace(tzinfo=timezone.utc),
                )
                return True

        if mention_spam["kick"] and mention_count >= mention_spam["kick"]:
            await self.maybe_dm_before_action(
                author,
                action=_("kicked"),
                guild=guild,
                reason=_("Mention spam (Autokick)"),
            )
            with suppress(discord.HTTPException, discord.Forbidden):
                await guild.kick(author, reason=_("Mention spam (Autokick)"))
                await self.create_modlog_case(
                    guild,
                    action_type="kick",
                    user=author,
                    moderator=guild.me or self.bot.user,
                    reason=_("Mention spam (Autokick)"),
                    created_at=message.created_at.replace(tzinfo=timezone.utc),
                )
                return True

        if mention_spam["warn"] and mention_count >= mention_spam["warn"]:
            warned = False
            with suppress(discord.HTTPException, discord.Forbidden):
                await author.send(_("Please do not mass mention people."))
                warned = True
            if not warned:
                with suppress(discord.HTTPException, discord.Forbidden):
                    await message.channel.send(
                        _("{member}, please do not mass mention people.").format(member=author.mention)
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
                return True

        return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Run lightweight bot-managed automod checks for supported guild messages."""
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
        """Track username changes when enabled globally."""
        if before.name == after.name:
            return
        if not await self.config.track_all_names():
            return
        await self.append_name_history(before, before.name)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Track nickname changes and note when administrator roles are added."""
        if before.nick != after.nick and after.nick is not None:
            if not await self.bot.cog_disabled_in_guild(self, after.guild):
                if await self.config.track_all_names() and await self.config.guild(after.guild).track_nicknames():
                    if before.nick is not None:
                        await self.append_nick_history(before, before.nick)

        gained_roles = [role for role in after.roles if role not in before.roles]
        for role in gained_roles:
            if role.permissions.administrator:
                await self.send_modlog_note(
                    after.guild,
                    title=_("Administrator role granted"),
                    description=_("{member} gained administrator via role {role}.").format(
                        member=after.mention,
                        role=role.mention,
                    ),
                )
                break

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        """Note when a role gains administrator permissions."""
        if after.permissions.administrator and not before.permissions.administrator:
            await self.send_modlog_note(
                after.guild,
                title=_("Role permissions escalated"),
                description=_("Role {role} gained administrator permissions.").format(
                    role=after.mention,
                ),
            )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Note when a bot account joins the server."""
        if member.bot:
            await self.send_modlog_note(
                member.guild,
                title=_("Bot joined"),
                description=_("Bot {member} joined the server.").format(member=member.mention),
            )
