"""Configuration commands for VMod."""

from __future__ import annotations

from datetime import timedelta

import discord
from redbot.core import checks, commands
from redbot.core.utils.chat_formatting import humanize_list, humanize_timedelta

from .base import VModBase
from .constants import ACTION_KEYS, PERM_SYS_INFO, _
from .views import VModDashboardView


class VModSettings(VModBase):
    """Commands used to configure moderation behavior and permissions."""

    @commands.group(name="vmodset")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def vmodset(self, ctx: commands.Context) -> None:
        """Configure VMod."""

    @vmodset.command(name="show", aliases=["status"])
    @commands.bot_has_permissions(embed_links=True)
    async def vmodset_show(self, ctx: commands.Context) -> None:
        """Show the most important VMod settings for the current server."""
        snapshot = await self.build_settings_snapshot(ctx.guild)
        mention_spam = snapshot["mention_spam"]

        repeat_text = (
            _("After {num} identical messages").format(num=snapshot["delete_repeats"])
            if snapshot["delete_repeats"] != -1
            else _("Disabled")
        )
        on = _("✅ On")
        off = _("❌ Off")
        yes = _("✅ Yes")
        no = _("❌ No")

        embed = discord.Embed(
            title=_("⚙️ VMod Settings — {guild}").format(guild=ctx.guild.name),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name=_("🛡️ Moderation"),
            value=(
                f"{_('Hierarchy checks')}: **{on if snapshot['respect_hierarchy'] else off}**\n"
                f"{_('DM before kick/ban')}: **{on if snapshot['dm_on_kickban'] else off}**\n"
                f"{_('Reinvite on unban')}: **{on if snapshot['reinvite_on_unban'] else off}**\n"
                f"{_('Track nicknames')}: **{on if snapshot['track_nicknames'] else off}**"
            ),
            inline=True,
        )
        embed.add_field(
            name=_("📋 Defaults"),
            value=(
                f"{_('Ban delete days')}: **{snapshot['default_days']}**\n"
                f"{_('Tempban duration')}: **{humanize_timedelta(seconds=snapshot['default_tempban_duration'])}**\n"
                f"{_('Delete repeats')}: **{repeat_text}**"
            ),
            inline=True,
        )
        embed.add_field(
            name=_("⚠️ Mention Spam"),
            value=(
                f"{_('Warn')}: **{mention_spam['warn'] or _('Disabled')}**\n"
                f"{_('Kick')}: **{mention_spam['kick'] or _('Disabled')}**\n"
                f"{_('Ban')}: **{mention_spam['ban'] or _('Disabled')}**\n"
                f"{_('Strict')}: **{yes if mention_spam['strict'] else no}**"
            ),
            inline=False,
        )
        embed.set_author(name=ctx.me.display_name, icon_url=ctx.me.display_avatar.url)
        await ctx.send(embed=embed)

    @vmodset.command(name="panel", aliases=["dashboard", "ui"])
    @commands.bot_has_permissions(embed_links=True)
    async def vmodset_panel(self, ctx: commands.Context) -> None:
        """Open an interactive setup panel with buttons, a dropdown, and forms."""
        view = VModDashboardView(self, ctx.author, ctx.guild)
        message = await ctx.send(embed=await view.build_embed(), view=view)
        view.message = message

    @vmodset.command(name="hierarchy")
    async def vmodset_hierarchy(self, ctx: commands.Context, enabled: bool | None = None) -> None:
        """Toggle role hierarchy checks for moderation commands."""
        current = await self.config.guild(ctx.guild).respect_hierarchy()
        new_value = (not current) if enabled is None else enabled
        await self.config.guild(ctx.guild).respect_hierarchy.set(new_value)
        await ctx.send(
            _("Role hierarchy checks are now **enabled**.")
            if new_value
            else _("Role hierarchy checks are now **disabled**.")
        )

    @vmodset.command(name="repeats")
    async def vmodset_repeats(self, ctx: commands.Context, repeats: int) -> None:
        """Set repeated-message deletion threshold. Use -1 to disable."""
        if repeats != -1 and repeats < 2:
            await ctx.send(_("Use `-1` to disable or a value of at least `2` to enable."))
            return
        await self.config.guild(ctx.guild).delete_repeats.set(repeats)
        self.repeat_cache.pop(ctx.guild.id, None)
        if repeats == -1:
            await ctx.send(_("Repeated-message deletion disabled."))
        else:
            await ctx.send(
                _("Repeated-message deletion enabled after **{num}** identical messages.").format(
                    num=repeats
                )
            )

    @vmodset.command(name="dmonaction")
    async def vmodset_dmonaction(self, ctx: commands.Context, enabled: bool) -> None:
        """Enable or disable DMing users before kick/ban style actions."""
        await self.config.guild(ctx.guild).dm_on_kickban.set(enabled)
        await ctx.send(
            _("Users will now be DM'd before kick/ban actions when possible.")
            if enabled
            else _("Users will no longer be DM'd before kick/ban actions.")
        )

    @vmodset.command(name="reinvite")
    async def vmodset_reinvite(self, ctx: commands.Context, enabled: bool) -> None:
        """Enable or disable reinvite attempts when unbanning through VMod."""
        await self.config.guild(ctx.guild).reinvite_on_unban.set(enabled)
        await ctx.send(
            _("VMod will now try to create a reinvite when a user is unbanned.")
            if enabled
            else _("VMod will no longer create reinvite links on unban.")
        )

    @vmodset.command(name="defaultdays")
    async def vmodset_defaultdays(self, ctx: commands.Context, days: int) -> None:
        """Set default days of message history to delete on ban."""
        if not 0 <= days <= 7:
            await ctx.send(_("Discord only allows between 0 and 7 days."))
            return
        await self.config.guild(ctx.guild).default_days.set(days)
        await ctx.send(_("Default ban delete days set to **{days}**.").format(days=days))

    @vmodset.command(name="defaulttempban")
    async def vmodset_defaulttempban(
        self,
        ctx: commands.Context,
        *,
        duration: commands.TimedeltaConverter(
            minimum=timedelta(minutes=1), maximum=timedelta(days=365), default_unit="hours"
        ),
    ) -> None:
        """Set the default tempban duration used when none is provided."""
        await self.config.guild(ctx.guild).default_tempban_duration.set(int(duration.total_seconds()))
        await ctx.send(
            _("Default tempban duration set to **{duration}**.").format(
                duration=humanize_timedelta(timedelta=duration)
            )
        )

    @vmodset.command(name="tracknicks")
    async def vmodset_tracknicks(self, ctx: commands.Context, enabled: bool) -> None:
        """Enable or disable nickname history tracking for this server."""
        await self.config.guild(ctx.guild).track_nicknames.set(enabled)
        await ctx.send(
            _("Nickname tracking is now enabled.") if enabled else _("Nickname tracking is now disabled.")
        )

    @vmodset.group(name="mentionspam")
    async def mentionspam(self, ctx: commands.Context) -> None:
        """Configure mention-spam moderation thresholds."""

    @mentionspam.command(name="show")
    @commands.bot_has_permissions(embed_links=True)
    async def mentionspam_show(self, ctx: commands.Context) -> None:
        """Show the current mention-spam thresholds."""
        mention_spam = await self.config.guild(ctx.guild).mention_spam.all()
        warn_value = str(mention_spam["warn"] or _("Disabled"))
        kick_value = str(mention_spam["kick"] or _("Disabled"))
        ban_value = str(mention_spam["ban"] or _("Disabled"))
        strict_text = (
            _("✅ Yes — duplicate mentions count")
            if mention_spam["strict"]
            else _("❌ No — only unique mentions count")
        )
        embed = discord.Embed(
            title=_("⚠️ Mention Spam Thresholds"),
            color=discord.Color.orange(),
        )
        embed.add_field(name=_("Warn"), value=warn_value, inline=True)
        embed.add_field(name=_("Kick"), value=kick_value, inline=True)
        embed.add_field(name=_("Ban"), value=ban_value, inline=True)
        embed.add_field(name=_("Strict counting"), value=strict_text, inline=False)
        await ctx.send(embed=embed)

    @mentionspam.command(name="strict")
    async def mentionspam_strict(self, ctx: commands.Context, enabled: bool | None = None) -> None:
        """Toggle whether duplicate mentions count toward the threshold."""
        if enabled is None:
            current = await self.config.guild(ctx.guild).mention_spam.strict()
            await ctx.send(
                _("Mention spam currently counts duplicate mentions.")
                if current
                else _("Mention spam currently only counts unique mentions.")
            )
            return
        await self.config.guild(ctx.guild).mention_spam.strict.set(enabled)
        await ctx.send(
            _("Mention spam will now count duplicate mentions.")
            if enabled
            else _("Mention spam will now only count unique mentions.")
        )

    async def _set_mentionspam_threshold(
        self, ctx: commands.Context, key: str, max_mentions: int, verb: str
    ) -> None:
        mention_spam = await self.config.guild(ctx.guild).mention_spam.all()
        if max_mentions == 0:
            await self.config.guild(ctx.guild).set_raw("mention_spam", key, value=None)
            await ctx.send(_("Automatic {verb} for mention spam disabled.").format(verb=verb))
            return
        if max_mentions < 1:
            await ctx.send(_("`<max_mentions>` must be at least 1, or `0` to disable."))
            return
        mention_spam[key] = max_mentions
        await self.config.guild(ctx.guild).mention_spam.set(mention_spam)
        await ctx.send(
            _("Automatic {verb} for mention spam set to **{count}** mentions.").format(
                verb=verb,
                count=max_mentions,
            )
        )

    @mentionspam.command(name="warn")
    async def mentionspam_warn(self, ctx: commands.Context, max_mentions: int) -> None:
        """Set or disable the mention-spam autowarn threshold."""
        await self._set_mentionspam_threshold(ctx, "warn", max_mentions, "warn")

    @mentionspam.command(name="kick")
    async def mentionspam_kick(self, ctx: commands.Context, max_mentions: int) -> None:
        """Set or disable the mention-spam autokick threshold."""
        await self._set_mentionspam_threshold(ctx, "kick", max_mentions, "kick")

    @mentionspam.command(name="ban")
    async def mentionspam_ban(self, ctx: commands.Context, max_mentions: int) -> None:
        """Set or disable the mention-spam autoban threshold."""
        await self._set_mentionspam_threshold(ctx, "ban", max_mentions, "ban")

    @vmodset.group(name="perms", aliases=["permissions", "perm"])
    async def permissions(self, ctx: commands.Context) -> None:
        """Configure role-based permission access for VMod actions."""

    @permissions.command(name="info")
    async def perms_info(self, ctx: commands.Context) -> None:
        """Explain the built-in VMod action keys."""
        await ctx.send(PERM_SYS_INFO)

    @permissions.command(name="add")
    async def perms_add(self, ctx: commands.Context, role: discord.Role, *, key: str) -> None:
        """Grant a VMod action key to a role."""
        key = key.lower().strip()
        if key not in ACTION_KEYS:
            await ctx.send(_("Unknown action key. Valid keys: {keys}").format(keys=", ".join(ACTION_KEYS)))
            return
        async with self.config.guild(ctx.guild).action_roles() as action_roles:
            if role.id in action_roles[key]:
                await ctx.send(_("{role} already has `{key}`.").format(role=role.mention, key=key))
                return
            action_roles[key].append(role.id)
        await ctx.send(_("Granted `{key}` to {role}.").format(key=key, role=role.mention))

    @permissions.command(name="remove")
    async def perms_remove(self, ctx: commands.Context, role: discord.Role, *, key: str) -> None:
        """Revoke a VMod action key from a role."""
        key = key.lower().strip()
        if key not in ACTION_KEYS:
            await ctx.send(_("Unknown action key. Valid keys: {keys}").format(keys=", ".join(ACTION_KEYS)))
            return
        async with self.config.guild(ctx.guild).action_roles() as action_roles:
            if role.id not in action_roles[key]:
                await ctx.send(_("{role} does not have `{key}`.").format(role=role.mention, key=key))
                return
            action_roles[key].remove(role.id)
        await ctx.send(_("Revoked `{key}` from {role}.").format(key=key, role=role.mention))

    @permissions.command(name="list")
    async def perms_list(self, ctx: commands.Context, key: str | None = None) -> None:
        """List action permissions by key or show all configured action roles."""
        action_roles = await self.config.guild(ctx.guild).action_roles()
        if key is not None:
            key = key.lower().strip()
            if key not in ACTION_KEYS:
                await ctx.send(_("Unknown action key. Valid keys: {keys}").format(keys=", ".join(ACTION_KEYS)))
                return
            roles = [
                ctx.guild.get_role(role_id).mention
                for role_id in action_roles[key]
                if ctx.guild.get_role(role_id)
            ]
            await ctx.send(
                _("Roles with `{key}`: {roles}").format(
                    key=key,
                    roles=humanize_list(roles) if roles else _("none"),
                )
            )
            return

        if ctx.channel.permissions_for(ctx.me).embed_links:
            embed = discord.Embed(title=_("🔑 VMod Action Permissions"), color=discord.Color.blurple())
            for action_key in ACTION_KEYS:
                roles = [
                    ctx.guild.get_role(role_id).mention
                    for role_id in action_roles[action_key]
                    if ctx.guild.get_role(role_id)
                ]
                embed.add_field(
                    name=f"`{action_key}`",
                    value=humanize_list(roles) if roles else _("*(none)*"),
                    inline=True,
                )
            await ctx.send(embed=embed)
        else:
            lines = []
            for action_key in ACTION_KEYS:
                roles = [
                    ctx.guild.get_role(role_id).mention
                    for role_id in action_roles[action_key]
                    if ctx.guild.get_role(role_id)
                ]
                lines.append(f"`{action_key}`: {humanize_list(roles) if roles else _('none')}")
            await ctx.send("\n".join(lines))

    @vmodset.group(name="ratelimit", aliases=["ratelimits"])
    async def ratelimit(self, ctx: commands.Context) -> None:
        """Configure moderator action rate limits."""

    @ratelimit.command(name="show")
    @commands.bot_has_permissions(embed_links=True)
    async def ratelimit_show(self, ctx: commands.Context) -> None:
        """Show configured action rate limits."""
        limits = await self.config.guild(ctx.guild).action_rate_limits()
        embed = discord.Embed(title=_("⏱️ VMod Rate Limits"), color=discord.Color.blurple())
        for action_key, data in limits.items():
            count = data['limit']
            embed.add_field(
                name=f"`{action_key}`",
                value=_("{count} action per {window}" if count == 1 else "{count} actions per {window}").format(
                    count=count,
                    window=humanize_timedelta(seconds=int(data["window"])),
                ),
                inline=True,
            )
        await ctx.send(embed=embed)

    @ratelimit.command(name="set")
    async def ratelimit_set(self, ctx: commands.Context, key: str, limit: int, window_seconds: int) -> None:
        """Set a rate limit for an action key."""
        key = key.lower().strip()
        if key not in ACTION_KEYS:
            await ctx.send(_("Unknown action key. Valid keys: {keys}").format(keys=", ".join(ACTION_KEYS)))
            return
        if limit < 1 or window_seconds < 1:
            await ctx.send(_("`limit` and `window_seconds` must both be at least 1."))
            return
        async with self.config.guild(ctx.guild).action_rate_limits() as limits:
            limits[key] = {"limit": limit, "window": window_seconds}
        await ctx.send(
            _("Rate limit for `{key}` set to {limit} per {window} seconds.").format(
                key=key,
                limit=limit,
                window=window_seconds,
            )
        )
