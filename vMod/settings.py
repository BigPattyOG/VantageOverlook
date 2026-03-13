"""Configuration commands for VMod.

Includes:
  - vmodset    — guild-level settings; shows help embed when invoked alone
  - vmodperms  — role-based action permission management
  - vmodroles  — warning and muted role configuration
  - vmodnotifs — notification subscription management (modulus-style)
"""

from __future__ import annotations

from datetime import timedelta

import discord
from redbot.core import checks, commands
from redbot.core.utils.chat_formatting import humanize_list, humanize_timedelta

from .base import VModBase
from .constants import ACTION_KEYS, NOTIF_KEYS, NOTIF_SYS_INFO, PERM_SYS_INFO, _
from .views import VModDashboardView, VModSetupWizard


# ---------------------------------------------------------------------------
# Helper: group-level help embeds
# ---------------------------------------------------------------------------

def _group_help_embed(
    title: str,
    description: str,
    commands_list: list[tuple[str, str]],
    *,
    colour: discord.Color = discord.Color.blurple(),
) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, colour=colour)
    for cmd, desc in commands_list:
        embed.add_field(name=f"`{cmd}`", value=desc, inline=False)
    return embed


class VModSettings(VModBase):
    """Commands used to configure moderation behaviour, permissions, and notifications."""

    # ==================================================================
    # vmodset — main settings group
    # ==================================================================

    @commands.group(name="vmodset", invoke_without_command=True)
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    @commands.bot_has_permissions(embed_links=True)
    async def vmodset(self, ctx: commands.Context) -> None:
        """Configure VMod settings — run without a subcommand to see all options."""
        embed = _group_help_embed(
            "⚙️ VMod Configuration",
            (
                "Run `[p]vmodset wizard` for a guided step-by-step setup, "
                "or `[p]vmodset panel` for the interactive control panel.\n\n"
                "**Available subcommands:**"
            ),
            [
                ("[p]vmodset wizard",       "🧙 Guided first-time setup wizard"),
                ("[p]vmodset panel",        "🖥️ Interactive control panel with buttons"),
                ("[p]vmodset checklist",    "📋 Show what's configured and what's missing"),
                ("[p]vmodset show",         "📊 Show all current settings"),
                ("[p]vmodset hierarchy",    "⚔️ Toggle role hierarchy checks"),
                ("[p]vmodset dmonaction",   "📨 Toggle DM-before-action"),
                ("[p]vmodset reinvite",     "🔗 Toggle reinvite on unban"),
                ("[p]vmodset repeats",      "🔁 Set repeat-message threshold"),
                ("[p]vmodset defaultdays",  "🗑️ Set default ban delete days"),
                ("[p]vmodset defaulttempban","⏳ Set default tempban duration"),
                ("[p]vmodset tracknicks",   "🏷️ Toggle nickname tracking"),
                ("[p]vmodset mentionspam",  "⚠️ Configure mention-spam thresholds"),
            ],
        )
        embed.set_author(name=ctx.me.display_name, icon_url=ctx.me.display_avatar.url)
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------ #
    # Wizard                                                               #
    # ------------------------------------------------------------------ #

    @vmodset.command(name="wizard", aliases=["setup"])
    @commands.bot_has_permissions(embed_links=True)
    async def vmodset_wizard(self, ctx: commands.Context) -> None:
        """Launch the guided VMod setup wizard.

        Walks through the most important settings step by step using interactive
        buttons, role selectors, and channel selectors — no commands to memorise.
        """
        wizard = VModSetupWizard(self, ctx.author, ctx.guild)
        message = await ctx.send(embed=await wizard._build_embed(), view=wizard)
        wizard.message = message

    # ------------------------------------------------------------------ #
    # Checklist                                                            #
    # ------------------------------------------------------------------ #

    @vmodset.command(name="checklist", aliases=["status"])
    @commands.bot_has_permissions(embed_links=True)
    async def vmodset_checklist(self, ctx: commands.Context) -> None:
        """Show a checklist of what's configured and what still needs attention."""
        snapshot = await self.build_settings_snapshot(ctx.guild)
        guild    = ctx.guild
        action_roles = snapshot["action_roles"]
        wr           = snapshot["warning_roles"]
        global_data  = await self.config.all()
        notif_chs    = global_data.get("notif_channels", {})

        def tick(cond: bool) -> str:
            return "✅" if cond else "⚠️"

        # Check: at least one role has kick permission
        has_kick = any(guild.get_role(rid) for rid in action_roles.get("kick", []))
        has_ban  = any(guild.get_role(rid) for rid in action_roles.get("ban",  []))
        has_mute = any(guild.get_role(rid) for rid in action_roles.get("mute", []))
        has_warn = any(guild.get_role(rid) for rid in action_roles.get("warn", []))

        # Check: at least one warning role set
        any_warn_role = any(wr.get(k) and guild.get_role(wr[k]) for k in ("warning1", "warning2", "warning3+"))

        # Check: at least one notification channel set for important events
        any_notif_ch = any(
            entry
            for key in ("kick", "ban", "ratelimit", "adminrole", "bot")
            for entry in notif_chs.get(key, [])
            if guild.get_channel(entry[1])
        )

        # Modlog channel (Red built-in)
        from redbot.core import modlog
        try:
            modlog_ch = await modlog.get_modlog_channel(guild)
        except RuntimeError:
            modlog_ch = None

        lines_perms = (
            f"{tick(has_kick)} Kick permission role\n"
            f"{tick(has_ban)}  Ban permission role\n"
            f"{tick(has_mute)} Mute permission role\n"
            f"{tick(has_warn)} Warn permission role"
        )
        lines_roles = (
            f"{tick(any_warn_role)} At least one warning milestone role\n"
            f"{tick(bool(snapshot['muted_role'] and guild.get_role(snapshot['muted_role'])))} Muted role configured"
        )
        lines_notifs = (
            f"{tick(any_notif_ch)}  Notification channel set\n"
            f"{tick(bool(modlog_ch))} Red modlog channel set"
        )
        lines_settings = (
            f"{'✅' if snapshot['respect_hierarchy'] else '💡'} Hierarchy checks: "
            f"**{'On' if snapshot['respect_hierarchy'] else 'Off'}**\n"
            f"{'✅' if snapshot['dm_on_kickban']     else '💡'} DM before action: "
            f"**{'On' if snapshot['dm_on_kickban'] else 'Off'}**\n"
            f"{'✅' if snapshot['reinvite_on_unban'] else '💡'} Reinvite on unban: "
            f"**{'On' if snapshot['reinvite_on_unban'] else 'Off'}**"
        )

        # Summary line
        issues = []
        if not has_kick:
            issues.append("no kick role")
        if not has_ban:
            issues.append("no ban role")
        if not any_notif_ch:
            issues.append("no notification channel")
        if not modlog_ch:
            issues.append("no modlog channel")

        if issues:
            summary = f"⚠️ **Needs attention:** {', '.join(issues)}."
            colour  = discord.Color.orange()
        else:
            summary = "✅ **Everything looks good!** VMod is fully configured."
            colour  = discord.Color.green()

        embed = discord.Embed(
            title=f"📋 VMod Setup Checklist — {guild.name}",
            description=summary,
            colour=colour,
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.set_author(name=ctx.me.display_name, icon_url=ctx.me.display_avatar.url)

        embed.add_field(name="🔑 Permissions",    value=lines_perms,    inline=True)
        embed.add_field(name="🏅 Roles",          value=lines_roles,    inline=True)
        embed.add_field(name="🔔 Notifications",  value=lines_notifs,   inline=False)
        embed.add_field(name="⚙️ Settings",       value=lines_settings, inline=False)

        if issues:
            embed.set_footer(text="Run [p]vmodset wizard to fix missing items interactively.")
        else:
            embed.set_footer(text="Run [p]vmodset panel to tweak any setting.")

        await ctx.send(embed=embed)

    # ------------------------------------------------------------------ #
    # Show                                                                 #
    # ------------------------------------------------------------------ #

    @vmodset.command(name="show", aliases=["config"])
    @commands.bot_has_permissions(embed_links=True)
    async def vmodset_show(self, ctx: commands.Context) -> None:
        """Show the full VMod configuration for this server."""
        snapshot = await self.build_settings_snapshot(ctx.guild)
        ms = snapshot["mention_spam"]

        on = "✅ Enabled"
        off = "❌ Disabled"
        repeat_text = (
            _("After **{n}** identical messages").format(n=snapshot["delete_repeats"])
            if snapshot["delete_repeats"] != -1
            else "❌ Disabled"
        )

        embed = discord.Embed(
            title=_("⚙️ VMod Configuration — {guild}").format(guild=ctx.guild.name),
            colour=discord.Color.blurple(),
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        embed.set_author(name=ctx.me.display_name, icon_url=ctx.me.display_avatar.url)

        embed.add_field(
            name="🛡️ Moderation",
            value=(
                f"Hierarchy checks: **{on if snapshot['respect_hierarchy'] else off}**\n"
                f"DM before action: **{on if snapshot['dm_on_kickban'] else off}**\n"
                f"Reinvite on unban: **{on if snapshot['reinvite_on_unban'] else off}**\n"
                f"Track nicknames: **{on if snapshot['track_nicknames'] else off}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="📋 Defaults",
            value=(
                f"Ban delete days: **{snapshot['default_days']}**\n"
                f"Tempban duration: **{humanize_timedelta(seconds=snapshot['default_tempban_duration'])}**\n"
                f"Delete repeats: **{repeat_text}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="⚠️ Mention Spam",
            value=(
                f"Warn at: **{ms['warn'] or 'Disabled'}** mention(s)\n"
                f"Kick at: **{ms['kick'] or 'Disabled'}** mention(s)\n"
                f"Ban at: **{ms['ban'] or 'Disabled'}** mention(s)\n"
                f"Strict mode: **{'✅ Yes' if ms['strict'] else '❌ No'}**"
            ),
            inline=False,
        )
        wr = snapshot["warning_roles"]
        guild = ctx.guild
        wr_lines = []
        for key in ("warning1", "warning2", "warning3+"):
            role = guild.get_role(wr.get(key)) if wr.get(key) else None
            wr_lines.append(f"**{key}:** {role.mention if role else 'Not set'}")
        embed.add_field(name="🏅 Warning Roles", value="\n".join(wr_lines), inline=True)
        muted_role = guild.get_role(snapshot["muted_role"]) if snapshot["muted_role"] else None
        embed.add_field(name="🔇 Muted Role", value=muted_role.mention if muted_role else "Not set", inline=True)

        await ctx.send(embed=embed)

    # ------------------------------------------------------------------ #
    # Panel                                                                #
    # ------------------------------------------------------------------ #

    @vmodset.command(name="panel", aliases=["dashboard", "ui"])
    @commands.bot_has_permissions(embed_links=True)
    async def vmodset_panel(self, ctx: commands.Context) -> None:
        """Open the interactive VMod control panel with section dropdowns and buttons."""
        view = VModDashboardView(self, ctx.author, ctx.guild)
        message = await ctx.send(embed=await view.build_embed(), view=view)
        view.message = message

    # ------------------------------------------------------------------ #
    # Individual settings                                                  #
    # ------------------------------------------------------------------ #

    @vmodset.command(name="hierarchy")
    async def vmodset_hierarchy(self, ctx: commands.Context, enabled: bool | None = None) -> None:
        """Toggle role hierarchy checks for moderation commands."""
        current = await self.config.guild(ctx.guild).respect_hierarchy()
        new = (not current) if enabled is None else enabled
        await self.config.guild(ctx.guild).respect_hierarchy.set(new)
        await ctx.send(
            _("✅ Role hierarchy checks are now **enabled**.")
            if new
            else _("❌ Role hierarchy checks are now **disabled**.")
        )

    @vmodset.command(name="dmonaction")
    async def vmodset_dmonaction(self, ctx: commands.Context, enabled: bool) -> None:
        """Enable or disable DM notifications to users before moderation actions."""
        await self.config.guild(ctx.guild).dm_on_kickban.set(enabled)
        await ctx.send(
            _("✅ Users will now receive a DM before kick/ban/mute actions.")
            if enabled
            else _("❌ Users will no longer receive a DM before actions.")
        )

    @vmodset.command(name="reinvite")
    async def vmodset_reinvite(self, ctx: commands.Context, enabled: bool) -> None:
        """Enable or disable sending a reinvite link when unbanning users."""
        await self.config.guild(ctx.guild).reinvite_on_unban.set(enabled)
        await ctx.send(
            _("✅ VMod will now send a reinvite when unbanning users.")
            if enabled
            else _("❌ VMod will no longer send reinvites on unban.")
        )

    @vmodset.command(name="repeats")
    async def vmodset_repeats(self, ctx: commands.Context, repeats: int) -> None:
        """Set the duplicate-message deletion threshold (`-1` to disable)."""
        if repeats != -1 and repeats < 2:
            await ctx.send(_("Use `-1` to disable, or a value of at least `2`."))
            return
        await self.config.guild(ctx.guild).delete_repeats.set(repeats)
        self.repeat_cache.pop(ctx.guild.id, None)
        if repeats == -1:
            await ctx.send(_("❌ Repeated-message deletion disabled."))
        else:
            await ctx.send(
                _("✅ Messages will be deleted after **{n}** identical consecutive messages.").format(n=repeats)
            )

    @vmodset.command(name="defaultdays")
    async def vmodset_defaultdays(self, ctx: commands.Context, days: int) -> None:
        """Set the default number of days of message history deleted on ban (0–7)."""
        if not 0 <= days <= 7:
            await ctx.send(_("Discord only allows 0–7 days."))
            return
        await self.config.guild(ctx.guild).default_days.set(days)
        await ctx.send(_("✅ Default ban delete days set to **{days}**.").format(days=days))

    @vmodset.command(name="defaulttempban")
    async def vmodset_defaulttempban(
        self,
        ctx: commands.Context,
        *,
        duration: commands.TimedeltaConverter(
            minimum=timedelta(minutes=1),
            maximum=timedelta(days=365),
            default_unit="hours",
        ),
    ) -> None:
        """Set the default tempban duration used when none is provided."""
        await self.config.guild(ctx.guild).default_tempban_duration.set(int(duration.total_seconds()))
        await ctx.send(
            _("✅ Default tempban duration set to **{dur}**.").format(
                dur=humanize_timedelta(timedelta=duration)
            )
        )

    @vmodset.command(name="tracknicks")
    async def vmodset_tracknicks(self, ctx: commands.Context, enabled: bool) -> None:
        """Enable or disable nickname history tracking for this server."""
        await self.config.guild(ctx.guild).track_nicknames.set(enabled)
        await ctx.send(
            _("✅ Nickname tracking enabled.") if enabled else _("❌ Nickname tracking disabled.")
        )

    # ==================================================================
    # vmodset mentionspam subgroup
    # ==================================================================

    @vmodset.group(name="mentionspam", invoke_without_command=True)
    @commands.bot_has_permissions(embed_links=True)
    async def mentionspam(self, ctx: commands.Context) -> None:
        """Configure auto-moderation thresholds for mention spam."""
        ms = await self.config.guild(ctx.guild).mention_spam.all()
        embed = discord.Embed(title="⚠️ Mention Spam Thresholds", colour=discord.Color.orange())
        embed.add_field(name="⚠️ Warn", value=str(ms["warn"] or "Disabled"), inline=True)
        embed.add_field(name="👢 Kick", value=str(ms["kick"] or "Disabled"), inline=True)
        embed.add_field(name="🔨 Ban",  value=str(ms["ban"]  or "Disabled"), inline=True)
        embed.add_field(
            name="📐 Strict mode",
            value="✅ On — duplicate mentions count" if ms["strict"] else "❌ Off — unique mentions only",
            inline=False,
        )
        embed.set_footer(text="Subcommands: warn, kick, ban, strict, show")
        await ctx.send(embed=embed)

    @mentionspam.command(name="show")
    @commands.bot_has_permissions(embed_links=True)
    async def mentionspam_show(self, ctx: commands.Context) -> None:
        """Show the current mention-spam thresholds."""
        ms = await self.config.guild(ctx.guild).mention_spam.all()
        embed = discord.Embed(title="⚠️ Mention Spam Thresholds", colour=discord.Color.orange())
        embed.add_field(name="⚠️ Warn", value=str(ms["warn"] or "Disabled"), inline=True)
        embed.add_field(name="👢 Kick", value=str(ms["kick"] or "Disabled"), inline=True)
        embed.add_field(name="🔨 Ban",  value=str(ms["ban"]  or "Disabled"), inline=True)
        embed.add_field(
            name="📐 Strict mode",
            value="✅ On — duplicate mentions count" if ms["strict"] else "❌ Off — unique mentions only",
            inline=False,
        )
        await ctx.send(embed=embed)

    @mentionspam.command(name="warn")
    async def mentionspam_warn(self, ctx: commands.Context, max_mentions: int) -> None:
        """Set the mention-spam warn threshold. Use `0` to disable."""
        await self._set_mentionspam_threshold(ctx, "warn", max_mentions, "warn")

    @mentionspam.command(name="kick")
    async def mentionspam_kick(self, ctx: commands.Context, max_mentions: int) -> None:
        """Set the mention-spam kick threshold. Use `0` to disable."""
        await self._set_mentionspam_threshold(ctx, "kick", max_mentions, "kick")

    @mentionspam.command(name="ban")
    async def mentionspam_ban(self, ctx: commands.Context, max_mentions: int) -> None:
        """Set the mention-spam ban threshold. Use `0` to disable."""
        await self._set_mentionspam_threshold(ctx, "ban", max_mentions, "ban")

    @mentionspam.command(name="strict")
    async def mentionspam_strict(self, ctx: commands.Context, enabled: bool | None = None) -> None:
        """Toggle whether duplicate mentions count toward the threshold."""
        if enabled is None:
            current = await self.config.guild(ctx.guild).mention_spam.strict()
            await ctx.send(
                _("Strict mode is **enabled** — duplicate mentions count.")
                if current
                else _("Strict mode is **disabled** — only unique mentions count.")
            )
            return
        await self.config.guild(ctx.guild).mention_spam.strict.set(enabled)
        await ctx.send(
            _("✅ Strict mode enabled — duplicate mentions now count.")
            if enabled
            else _("❌ Strict mode disabled — only unique mentions count.")
        )

    async def _set_mentionspam_threshold(
        self, ctx: commands.Context, key: str, max_mentions: int, verb: str
    ) -> None:
        ms = await self.config.guild(ctx.guild).mention_spam.all()
        if max_mentions == 0:
            await self.config.guild(ctx.guild).set_raw("mention_spam", key, value=None)
            await ctx.send(_("❌ Automatic **{verb}** for mention spam disabled.").format(verb=verb))
            return
        if max_mentions < 1:
            await ctx.send(_("`<max_mentions>` must be at least 1, or `0` to disable."))
            return
        ms[key] = max_mentions
        await self.config.guild(ctx.guild).mention_spam.set(ms)
        await ctx.send(
            _("✅ Automatic **{verb}** set to **{n}** mention(s).").format(verb=verb, n=max_mentions)
        )

    # ==================================================================
    # vmodperms — role-based action permissions
    # ==================================================================

    @commands.group(name="vmodperms", aliases=["vmodperm"], invoke_without_command=True)
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    @commands.bot_has_permissions(embed_links=True)
    async def vmodperms(self, ctx: commands.Context) -> None:
        """Manage role-based VMod action permissions — shows current state when invoked alone."""
        action_roles = await self.config.guild(ctx.guild).action_roles()
        embed = discord.Embed(
            title="🔑 VMod Action Permissions",
            description=(
                "These roles are allowed to use each VMod action.\n"
                "Use `[p]vmodperms add @Role <key>` to grant a permission, "
                "or `[p]vmodset wizard` to configure interactively.\n\n"
                "**Subcommands:** `add`, `remove`, `list`, `byrole`, `info`"
            ),
            colour=discord.Color.blurple(),
        )
        for ak in ACTION_KEYS:
            roles = [
                ctx.guild.get_role(rid).mention
                for rid in action_roles.get(ak, [])
                if ctx.guild.get_role(rid)
            ]
            embed.add_field(
                name=f"`{ak}`",
                value=humanize_list(roles) if roles else "*(none)*",
                inline=True,
            )
        await ctx.send(embed=embed)

    @vmodperms.command(name="info")
    async def perms_info(self, ctx: commands.Context) -> None:
        """Show information about the VMod permission system."""
        embed = discord.Embed(
            title="🔐 VMod Permission System",
            description=PERM_SYS_INFO,
            colour=discord.Color.blurple(),
        )
        await ctx.send(embed=embed)

    @vmodperms.command(name="add")
    async def perms_add(self, ctx: commands.Context, role: discord.Role, *, key: str) -> None:
        """Grant a permission key to a role.

        **Example:**
        - `[p]vmodperms add @Moderator kick`
        """
        key = key.lower().strip()
        if key not in ACTION_KEYS:
            await ctx.send(
                _("Unknown key. Valid keys: {keys}").format(keys=", ".join(f"`{k}`" for k in ACTION_KEYS))
            )
            return
        async with self.config.guild(ctx.guild).action_roles() as ar:
            if role.id in ar[key]:
                await ctx.send(_("{role} already has `{key}`.").format(role=role.mention, key=key))
                return
            ar[key].append(role.id)
        await ctx.send(_("✅ Granted `{key}` to {role}.").format(key=key, role=role.mention))

    @vmodperms.command(name="remove")
    async def perms_remove(self, ctx: commands.Context, role: discord.Role, *, key: str) -> None:
        """Revoke a permission key from a role.

        **Example:**
        - `[p]vmodperms remove @Moderator kick`
        """
        key = key.lower().strip()
        if key not in ACTION_KEYS:
            await ctx.send(
                _("Unknown key. Valid keys: {keys}").format(keys=", ".join(f"`{k}`" for k in ACTION_KEYS))
            )
            return
        async with self.config.guild(ctx.guild).action_roles() as ar:
            if role.id not in ar[key]:
                await ctx.send(_("{role} does not have `{key}`.").format(role=role.mention, key=key))
                return
            ar[key].remove(role.id)
        await ctx.send(_("✅ Revoked `{key}` from {role}.").format(key=key, role=role.mention))

    @vmodperms.command(name="list")
    @commands.bot_has_permissions(embed_links=True)
    async def perms_list(self, ctx: commands.Context, key: str | None = None) -> None:
        """List roles assigned to a permission key, or show all permissions."""
        action_roles = await self.config.guild(ctx.guild).action_roles()
        if key is not None:
            key = key.lower().strip()
            if key not in ACTION_KEYS:
                await ctx.send(
                    _("Unknown key. Valid keys: {keys}").format(keys=", ".join(f"`{k}`" for k in ACTION_KEYS))
                )
                return
            roles = [
                ctx.guild.get_role(rid).mention
                for rid in action_roles[key]
                if ctx.guild.get_role(rid)
            ]
            await ctx.send(
                _("Roles with `{key}`: {roles}").format(
                    key=key,
                    roles=humanize_list(roles) if roles else _("*(none)*"),
                )
            )
            return
        embed = discord.Embed(title="🔑 VMod Action Permissions", colour=discord.Color.blurple())
        for ak in ACTION_KEYS:
            roles = [
                ctx.guild.get_role(rid).mention
                for rid in action_roles[ak]
                if ctx.guild.get_role(rid)
            ]
            embed.add_field(name=f"`{ak}`", value=humanize_list(roles) if roles else "*(none)*", inline=True)
        await ctx.send(embed=embed)

    @vmodperms.command(name="byrole")
    async def perms_by_role(self, ctx: commands.Context, role: discord.Role) -> None:
        """Show all permission keys a role has."""
        action_roles = await self.config.guild(ctx.guild).action_roles()
        keys = [k for k in ACTION_KEYS if role.id in action_roles.get(k, [])]
        if keys:
            await ctx.send(
                _("{role} has: {keys}").format(
                    role=role.mention,
                    keys=", ".join(f"`{k}`" for k in keys),
                )
            )
        else:
            await ctx.send(_("{role} has no VMod permissions.").format(role=role.mention))

    # ==================================================================
    # vmodroles — warning and muted role config
    # ==================================================================

    @commands.group(name="vmodroles", invoke_without_command=True)
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    @commands.bot_has_permissions(embed_links=True)
    async def vmodroles(self, ctx: commands.Context) -> None:
        """Configure milestone warning roles and the muted role — shows current config when invoked alone."""
        snapshot = await self.build_settings_snapshot(ctx.guild)
        wr = snapshot["warning_roles"]
        guild = ctx.guild
        embed = discord.Embed(
            title="🏅 VMod Role Configuration",
            description=(
                "Set roles applied at warning milestones or for the muted state.\n"
                "Tip: Use `[p]vmodset wizard` to configure these interactively.\n\n"
                "**Subcommands:** `warning1`, `warning2`, `warning3`, `muted`, `show`"
            ),
            colour=discord.Color.blurple(),
        )
        for key in ("warning1", "warning2", "warning3+"):
            role = guild.get_role(wr.get(key)) if wr.get(key) else None
            embed.add_field(
                name=f"⚠️ {key.capitalize()}",
                value=role.mention if role else "*(not set)*",
                inline=True,
            )
        muted_role = guild.get_role(snapshot["muted_role"]) if snapshot["muted_role"] else None
        embed.add_field(name="🔇 Muted Role", value=muted_role.mention if muted_role else "*(not set)*", inline=True)
        await ctx.send(embed=embed)

    @vmodroles.command(name="warning1")
    async def roles_warning1(self, ctx: commands.Context, role: discord.Role | None = None) -> None:
        """Set (or clear) the role applied to members on their **first** warning."""
        await self.config.guild(ctx.guild).warning_roles.set_raw("warning1", value=role.id if role else None)
        if role:
            await ctx.send(_("✅ Warning 1 role set to {role}.").format(role=role.mention))
        else:
            await ctx.send(_("❌ Warning 1 role cleared."))

    @vmodroles.command(name="warning2")
    async def roles_warning2(self, ctx: commands.Context, role: discord.Role | None = None) -> None:
        """Set (or clear) the role applied to members on their **second** warning."""
        await self.config.guild(ctx.guild).warning_roles.set_raw("warning2", value=role.id if role else None)
        if role:
            await ctx.send(_("✅ Warning 2 role set to {role}.").format(role=role.mention))
        else:
            await ctx.send(_("❌ Warning 2 role cleared."))

    @vmodroles.command(name="warning3")
    async def roles_warning3(self, ctx: commands.Context, role: discord.Role | None = None) -> None:
        """Set (or clear) the role applied to members on their **third or later** warning."""
        await self.config.guild(ctx.guild).warning_roles.set_raw("warning3+", value=role.id if role else None)
        if role:
            await ctx.send(_("✅ Warning 3+ role set to {role}.").format(role=role.mention))
        else:
            await ctx.send(_("❌ Warning 3+ role cleared."))

    @vmodroles.command(name="muted")
    async def roles_muted(self, ctx: commands.Context, role: discord.Role | None = None) -> None:
        """Set (or clear) the fallback Muted role."""
        await self.config.guild(ctx.guild).muted_role.set(role.id if role else None)
        if role:
            await ctx.send(_("✅ Muted role set to {role}.").format(role=role.mention))
        else:
            await ctx.send(_("❌ Muted role cleared."))

    @vmodroles.command(name="show")
    @commands.bot_has_permissions(embed_links=True)
    async def roles_show(self, ctx: commands.Context) -> None:
        """Show the configured warning milestone and muted roles."""
        snapshot = await self.build_settings_snapshot(ctx.guild)
        wr = snapshot["warning_roles"]
        guild = ctx.guild
        embed = discord.Embed(title="🏅 VMod Role Configuration", colour=discord.Color.blurple())
        for key in ("warning1", "warning2", "warning3+"):
            role = guild.get_role(wr.get(key)) if wr.get(key) else None
            embed.add_field(name=f"⚠️ {key.capitalize()}", value=role.mention if role else "*(not set)*", inline=True)
        muted_role = guild.get_role(snapshot["muted_role"]) if snapshot["muted_role"] else None
        embed.add_field(name="�� Muted Role", value=muted_role.mention if muted_role else "*(not set)*", inline=True)
        await ctx.send(embed=embed)

    # ==================================================================
    # vmodratelimit — moderator rate limit config
    # ==================================================================

    @commands.group(name="vmodratelimit", aliases=["vmodrl"], invoke_without_command=True)
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    @commands.bot_has_permissions(embed_links=True)
    async def vmodratelimit(self, ctx: commands.Context) -> None:
        """Configure moderator action rate limits — shows current limits when invoked alone."""
        limits = await self.config.guild(ctx.guild).action_rate_limits()
        embed = discord.Embed(
            title="⏱️ VMod Rate Limits",
            description=(
                "How many times a moderator role may use each action per window.\n"
                "Exceeding the limit strips their mod roles and notifies subscribers.\n\n"
                "**Subcommands:** `show`, `set`"
            ),
            colour=discord.Color.blurple(),
        )
        for ak, data in limits.items():
            count = data["limit"]
            embed.add_field(
                name=f"`{ak}`",
                value=_(
                    "{count} action per {window}" if count == 1 else "{count} actions per {window}"
                ).format(count=count, window=humanize_timedelta(seconds=int(data["window"]))),
                inline=True,
            )
        await ctx.send(embed=embed)

    @vmodratelimit.command(name="show")
    @commands.bot_has_permissions(embed_links=True)
    async def ratelimit_show(self, ctx: commands.Context) -> None:
        """Show the configured rate limits for each action."""
        limits = await self.config.guild(ctx.guild).action_rate_limits()
        embed = discord.Embed(title="⏱️ VMod Rate Limits", colour=discord.Color.blurple())
        for ak, data in limits.items():
            count = data["limit"]
            embed.add_field(
                name=f"`{ak}`",
                value=_(
                    "{count} action per {window}" if count == 1 else "{count} actions per {window}"
                ).format(count=count, window=humanize_timedelta(seconds=int(data["window"]))),
                inline=True,
            )
        await ctx.send(embed=embed)

    @vmodratelimit.command(name="set")
    async def ratelimit_set(
        self, ctx: commands.Context, key: str, limit: int, window_seconds: int
    ) -> None:
        """Set a rate limit for a specific action key.

        **Example:**
        - `[p]vmodratelimit set kick 5 3600` — 5 kicks per hour.
        """
        key = key.lower().strip()
        if key not in ACTION_KEYS:
            await ctx.send(
                _("Unknown key. Valid keys: {keys}").format(keys=", ".join(f"`{k}`" for k in ACTION_KEYS))
            )
            return
        if limit < 1 or window_seconds < 1:
            await ctx.send(_("Both `limit` and `window_seconds` must be at least 1."))
            return
        async with self.config.guild(ctx.guild).action_rate_limits() as limits:
            limits[key] = {"limit": limit, "window": window_seconds}
        await ctx.send(
            _("✅ Rate limit for `{key}` set to **{limit}** action(s) per **{window}** seconds.").format(
                key=key, limit=limit, window=window_seconds
            )
        )

    # ==================================================================
    # vmodnotifs — modulus-style notification subscriptions
    # ==================================================================

    @commands.group(name="vmodnotifs", aliases=["vmodnotif", "vnotifs"], invoke_without_command=True)
    @checks.mod_or_permissions(manage_guild=True)
    @commands.bot_has_permissions(embed_links=True)
    async def vmodnotifs(self, ctx: commands.Context) -> None:
        """Manage VMod notification subscriptions — shows your subscriptions when invoked alone."""
        data = await self.config.notif_users()
        subscribed = [k for k in NOTIF_KEYS if ctx.author.id in data.get(k, [])]

        embed = discord.Embed(
            title="🔔 VMod Notifications",
            description=(
                "Subscribe to receive DMs or channel alerts when moderation events occur.\n\n"
                "**Subcommands:** `add`, `remove`, `list`, `info`, `channel`"
            ),
            colour=discord.Color.blurple(),
        )
        if subscribed:
            embed.add_field(
                name="Your active subscriptions",
                value=", ".join(f"`{k}`" for k in subscribed),
                inline=False,
            )
        else:
            embed.add_field(
                name="Your active subscriptions",
                value="*(none — use `[p]vmodnotifs add <key>` to subscribe)*",
                inline=False,
            )
        embed.add_field(
            name="Available keys",
            value=", ".join(f"`{k}`" for k in NOTIF_KEYS),
            inline=False,
        )
        await ctx.send(embed=embed)

    @vmodnotifs.command(name="info")
    async def notifs_info(self, ctx: commands.Context) -> None:
        """Show information about the notification system and available keys."""
        embed = discord.Embed(
            title="🔔 VMod Notification System",
            description=NOTIF_SYS_INFO,
            colour=discord.Color.blurple(),
        )
        await ctx.send(embed=embed)

    @vmodnotifs.command(name="add")
    async def notifs_add(
        self, ctx: commands.Context, key: str, user: discord.Member | None = None
    ) -> None:
        """Subscribe a user (default: yourself) to a notification key.

        **Example:**
        - `[p]vmodnotifs add kick` — subscribe yourself to kick notifications.
        - `[p]vmodnotifs add ban @Mod` — subscribe @Mod to ban notifications.
        """
        key = key.lower().strip()
        if key not in NOTIF_KEYS:
            await ctx.send(
                _("Unknown key. Valid keys: {keys}").format(keys=", ".join(f"`{k}`" for k in NOTIF_KEYS))
            )
            return
        target = user or ctx.author
        async with self.config.notif_users() as notif_users:
            if target.id in notif_users[key]:
                await ctx.send(
                    _("{user} is already subscribed to `{key}` notifications.").format(
                        user=target.display_name, key=key
                    )
                )
                return
            notif_users[key].append(target.id)
        await ctx.send(
            _("✅ {user} will now receive DM notifications for `{key}` events.").format(
                user=target.display_name, key=key
            )
        )

    @vmodnotifs.command(name="remove")
    async def notifs_remove(
        self, ctx: commands.Context, key: str, user: discord.Member | None = None
    ) -> None:
        """Unsubscribe a user (default: yourself) from a notification key."""
        key = key.lower().strip()
        if key not in NOTIF_KEYS:
            await ctx.send(
                _("Unknown key. Valid keys: {keys}").format(keys=", ".join(f"`{k}`" for k in NOTIF_KEYS))
            )
            return
        target = user or ctx.author
        async with self.config.notif_users() as notif_users:
            if target.id not in notif_users[key]:
                await ctx.send(
                    _("{user} is not subscribed to `{key}` notifications.").format(
                        user=target.display_name, key=key
                    )
                )
                return
            notif_users[key].remove(target.id)
        await ctx.send(
            _("✅ {user} will no longer receive notifications for `{key}` events.").format(
                user=target.display_name, key=key
            )
        )

    @vmodnotifs.command(name="list")
    async def notifs_list(
        self, ctx: commands.Context, user: discord.Member | None = None
    ) -> None:
        """Show which notification keys a user (default: yourself) is subscribed to."""
        target = user or ctx.author
        data = await self.config.notif_users()
        subscribed = [k for k in NOTIF_KEYS if target.id in data.get(k, [])]
        if subscribed:
            await ctx.send(
                _("🔔 {user} is subscribed to: {keys}").format(
                    user=target.display_name,
                    keys=", ".join(f"`{k}`" for k in subscribed),
                )
            )
        else:
            await ctx.send(
                _("🔕 {user} has no active notification subscriptions.").format(user=target.display_name)
            )

    @vmodnotifs.group(name="channel", invoke_without_command=True)
    async def notifs_channel(self, ctx: commands.Context) -> None:
        """Manage channel-based notification subscriptions."""
        embed = discord.Embed(
            title="📢 Channel Notifications",
            description=(
                "Subscribe a text channel to receive notification embeds for moderation events.\n\n"
                "**Subcommands:** `add`, `remove`, `list`\n\n"
                "**Example:** `[p]vmodnotifs channel add kick #mod-log`"
            ),
            colour=discord.Color.blurple(),
        )
        await ctx.send(embed=embed)

    @notifs_channel.command(name="add")
    async def notifs_channel_add(
        self, ctx: commands.Context, key: str, channel: discord.TextChannel
    ) -> None:
        """Subscribe a text channel to a notification key.

        **Example:**
        - `[p]vmodnotifs channel add kick #mod-log`
        """
        key = key.lower().strip()
        if key not in NOTIF_KEYS:
            await ctx.send(
                _("Unknown key. Valid keys: {keys}").format(keys=", ".join(f"`{k}`" for k in NOTIF_KEYS))
            )
            return
        entry = [channel.guild.id, channel.id]
        async with self.config.notif_channels() as notif_channels:
            if entry in notif_channels[key]:
                await ctx.send(
                    _("{channel} is already subscribed to `{key}` notifications.").format(
                        channel=channel.mention, key=key
                    )
                )
                return
            notif_channels[key].append(entry)
        await ctx.send(
            _("✅ {channel} will now receive notifications for `{key}` events.").format(
                channel=channel.mention, key=key
            )
        )

    @notifs_channel.command(name="remove")
    async def notifs_channel_remove(
        self, ctx: commands.Context, key: str, channel: discord.TextChannel
    ) -> None:
        """Unsubscribe a text channel from a notification key."""
        key = key.lower().strip()
        if key not in NOTIF_KEYS:
            await ctx.send(
                _("Unknown key. Valid keys: {keys}").format(keys=", ".join(f"`{k}`" for k in NOTIF_KEYS))
            )
            return
        entry = [channel.guild.id, channel.id]
        async with self.config.notif_channels() as notif_channels:
            if entry not in notif_channels[key]:
                await ctx.send(
                    _("{channel} is not subscribed to `{key}` notifications.").format(
                        channel=channel.mention, key=key
                    )
                )
                return
            notif_channels[key].remove(entry)
        await ctx.send(
            _("✅ {channel} will no longer receive notifications for `{key}` events.").format(
                channel=channel.mention, key=key
            )
        )

    @notifs_channel.command(name="list")
    async def notifs_channel_list(
        self, ctx: commands.Context, channel: discord.TextChannel
    ) -> None:
        """Show which notification keys a channel is subscribed to."""
        data = await self.config.notif_channels()
        entry = [channel.guild.id, channel.id]
        subscribed = [k for k in NOTIF_KEYS if entry in data.get(k, [])]
        if subscribed:
            await ctx.send(
                _("🔔 {channel} is subscribed to: {keys}").format(
                    channel=channel.mention,
                    keys=", ".join(f"`{k}`" for k in subscribed),
                )
            )
        else:
            await ctx.send(
                _("🔕 {channel} has no active notification subscriptions.").format(channel=channel.mention)
            )
