"""Discord UI helpers for VMod.

These views are intentionally small and focused on setup UX, not moderation.
Prefix commands still exist for everything, but the panel gives server admins a
friendlier way to review and tweak the common settings.
"""

from __future__ import annotations

from datetime import timedelta

import discord
from redbot.core.utils.chat_formatting import humanize_list, humanize_timedelta

from .constants import ACTION_KEYS, _


class VModSectionSelect(discord.ui.Select):
    """Dropdown used to switch between overview sections in the dashboard."""

    def __init__(self, view: "VModDashboardView"):
        self.dashboard = view
        options = [
            discord.SelectOption(label="Overview", value="overview", description="Main moderation settings"),
            discord.SelectOption(label="Mention Spam", value="mention_spam", description="Warn / kick / ban thresholds"),
            discord.SelectOption(label="Permissions", value="permissions", description="Action-role access map"),
            discord.SelectOption(label="Rate Limits", value="rate_limits", description="Moderator action caps"),
        ]
        super().__init__(placeholder="Choose a settings section…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.dashboard.section = self.values[0]
        await self.dashboard.refresh(interaction)


class MentionSpamModal(discord.ui.Modal, title="Edit mention spam thresholds"):
    """Modal form for the most common automod threshold settings."""

    warn_value = discord.ui.TextInput(
        label="Warn threshold (0 disables)",
        placeholder="Example: 5",
        required=True,
        max_length=5,
    )
    kick_value = discord.ui.TextInput(
        label="Kick threshold (0 disables)",
        placeholder="Example: 8",
        required=True,
        max_length=5,
    )
    ban_value = discord.ui.TextInput(
        label="Ban threshold (0 disables)",
        placeholder="Example: 12",
        required=True,
        max_length=5,
    )
    strict_value = discord.ui.TextInput(
        label="Strict counting? yes/no",
        placeholder="yes",
        required=True,
        max_length=5,
    )

    def __init__(self, view: "VModDashboardView", current: dict[str, int | bool | None]):
        super().__init__()
        self.dashboard = view
        self.warn_value.default = str(current.get("warn") or 0)
        self.kick_value.default = str(current.get("kick") or 0)
        self.ban_value.default = str(current.get("ban") or 0)
        self.strict_value.default = "yes" if current.get("strict") else "no"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        def parse_threshold(value: str) -> int | None:
            number = int(value)
            if number < 0:
                raise ValueError
            return None if number == 0 else number

        try:
            warn = parse_threshold(str(self.warn_value).strip())
            kick = parse_threshold(str(self.kick_value).strip())
            ban = parse_threshold(str(self.ban_value).strip())
            strict_text = str(self.strict_value).strip().lower()
            if strict_text not in {"yes", "no", "true", "false", "on", "off"}:
                raise ValueError
            strict = strict_text in {"yes", "true", "on"}
        except ValueError:
            await interaction.response.send_message(
                "Use whole numbers for thresholds and yes/no for strict mode.", ephemeral=True
            )
            return

        await self.dashboard.cog.config.guild(self.dashboard.guild).mention_spam.set(
            {"warn": warn, "kick": kick, "ban": ban, "strict": strict}
        )
        self.dashboard.section = "mention_spam"
        await interaction.response.send_message("Mention spam settings updated.", ephemeral=True)
        await self.dashboard.refresh_message()


class DefaultsModal(discord.ui.Modal, title="Edit VMod defaults"):
    """Modal for the frequently changed general moderation defaults."""

    repeats_value = discord.ui.TextInput(
        label="Delete repeats (-1 disables)",
        placeholder="Example: 3",
        required=True,
        max_length=5,
    )
    default_days = discord.ui.TextInput(
        label="Default ban delete days (0-7)",
        placeholder="0",
        required=True,
        max_length=2,
    )
    tempban_hours = discord.ui.TextInput(
        label="Default tempban duration in hours",
        placeholder="24",
        required=True,
        max_length=6,
    )

    def __init__(self, view: "VModDashboardView", snapshot: dict):
        super().__init__()
        self.dashboard = view
        self.repeats_value.default = str(snapshot["delete_repeats"])
        self.default_days.default = str(snapshot["default_days"])
        self.tempban_hours.default = str(int(snapshot["default_tempban_duration"]/3600))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            repeats = int(str(self.repeats_value).strip())
            default_days = int(str(self.default_days).strip())
            tempban_hours = int(str(self.tempban_hours).strip())
            if repeats != -1 and repeats < 2:
                raise ValueError
            if not 0 <= default_days <= 7:
                raise ValueError
            if tempban_hours < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "Use `-1` or at least `2` for repeats, `0-7` for delete days, and `1+` hours for tempbans.",
                ephemeral=True,
            )
            return

        guild_conf = self.dashboard.cog.config.guild(self.dashboard.guild)
        await guild_conf.delete_repeats.set(repeats)
        await guild_conf.default_days.set(default_days)
        await guild_conf.default_tempban_duration.set(tempban_hours * 3600)
        self.dashboard.cog.repeat_cache.pop(self.dashboard.guild.id, None)
        self.dashboard.section = "overview"
        await interaction.response.send_message("Defaults updated.", ephemeral=True)
        await self.dashboard.refresh_message()


class VModDashboardView(discord.ui.View):
    """Small interactive dashboard for common VMod setup tasks."""

    def __init__(self, cog, author: discord.abc.User, guild: discord.Guild):
        super().__init__(timeout=300)
        self.cog = cog
        self.author_id = author.id
        self.guild = guild
        self.section = "overview"
        self.message: discord.Message | None = None
        self.add_item(VModSectionSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This control panel belongs to someone else.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            await self.message.edit(view=self)

    async def build_embed(self) -> discord.Embed:
        snapshot = await self.cog.build_settings_snapshot(self.guild)
        mention_spam = snapshot["mention_spam"]
        embed = discord.Embed(
            title=f"⚙️ VMod Control Panel — {self.guild.name}",
            colour=discord.Colour.blurple(),
        )
        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)
        embed.set_footer(text="Use the dropdown to switch sections • Buttons apply quick edits")

        if self.section == "overview":
            repeat_text = (
                f"After {snapshot['delete_repeats']} identical messages"
                if snapshot["delete_repeats"] != -1
                else "Disabled"
            )
            embed.description = "📋 **Overview** — Main moderation defaults for this server."
            embed.add_field(name="🔁 Delete repeats", value=repeat_text, inline=False)
            embed.add_field(
                name="🛡️ Hierarchy checks",
                value="✅ Enabled" if snapshot["respect_hierarchy"] else "❌ Disabled",
                inline=True,
            )
            embed.add_field(
                name="📨 DM before kick/ban",
                value="✅ Enabled" if snapshot["dm_on_kickban"] else "❌ Disabled",
                inline=True,
            )
            embed.add_field(
                name="🔗 Reinvite on unban",
                value="✅ Enabled" if snapshot["reinvite_on_unban"] else "❌ Disabled",
                inline=True,
            )
            embed.add_field(
                name="🏷️ Track nicknames",
                value="✅ Enabled" if snapshot["track_nicknames"] else "❌ Disabled",
                inline=True,
            )
            embed.add_field(name="🗑️ Default ban delete days", value=str(snapshot["default_days"]), inline=True)
            embed.add_field(
                name="⏳ Default tempban duration",
                value=humanize_timedelta(seconds=snapshot["default_tempban_duration"]),
                inline=True,
            )
        elif self.section == "mention_spam":
            embed.description = "⚠️ **Mention Spam** — Auto-moderation thresholds for mass mentions."
            embed.add_field(
                name="⚠️ Warn",
                value=f"{mention_spam['warn']} mentions" if mention_spam["warn"] else "disabled",
                inline=True,
            )
            embed.add_field(
                name="👢 Kick",
                value=f"{mention_spam['kick']} mentions" if mention_spam["kick"] else "disabled",
                inline=True,
            )
            embed.add_field(
                name="🔨 Ban",
                value=f"{mention_spam['ban']} mentions" if mention_spam["ban"] else "disabled",
                inline=True,
            )
            embed.add_field(
                name="📐 Strict mode",
                value="✅ On — duplicate mentions count" if mention_spam["strict"] else "❌ Off — unique mentions only",
                inline=False,
            )
        elif self.section == "permissions":
            embed.description = "🔑 **Permissions** — Role-based access to moderation actions."
            action_roles = snapshot["action_roles"]
            for action_key in ACTION_KEYS:
                roles = [
                    self.guild.get_role(role_id).mention
                    for role_id in action_roles[action_key]
                    if self.guild.get_role(role_id) is not None
                ]
                embed.add_field(
                    name=f"`{action_key}`",
                    value=humanize_list(roles) if roles else "*(none)*",
                    inline=False,
                )
        elif self.section == "rate_limits":
            embed.description = "⏱️ **Rate Limits** — In-memory caps applied to moderator roles."
            for action_key, settings in snapshot["action_rate_limits"].items():
                embed.add_field(
                    name=f"`{action_key}`",
                    value=f"{settings['limit']} action{'s' if settings['limit'] != 1 else ''} per {humanize_timedelta(seconds=settings['window'])}",
                    inline=True,
                )

        return embed

    async def refresh_message(self) -> None:
        if self.message is None:
            return
        await self.message.edit(embed=await self.build_embed(), view=self)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.refresh(interaction)

    @discord.ui.button(label="Toggle hierarchy", style=discord.ButtonStyle.primary, row=1)
    async def toggle_hierarchy(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        current = await self.cog.config.guild(self.guild).respect_hierarchy()
        await self.cog.config.guild(self.guild).respect_hierarchy.set(not current)
        await interaction.response.send_message(
            f"Hierarchy checks {'enabled' if not current else 'disabled'}.", ephemeral=True
        )
        await self.refresh_message()

    @discord.ui.button(label="Toggle DM on action", style=discord.ButtonStyle.primary, row=1)
    async def toggle_dm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        current = await self.cog.config.guild(self.guild).dm_on_kickban()
        await self.cog.config.guild(self.guild).dm_on_kickban.set(not current)
        await interaction.response.send_message(
            f"DM before action {'enabled' if not current else 'disabled'}.", ephemeral=True
        )
        await self.refresh_message()

    @discord.ui.button(label="Toggle reinvite", style=discord.ButtonStyle.primary, row=2)
    async def toggle_reinvite(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        current = await self.cog.config.guild(self.guild).reinvite_on_unban()
        await self.cog.config.guild(self.guild).reinvite_on_unban.set(not current)
        await interaction.response.send_message(
            f"Reinvite on unban {'enabled' if not current else 'disabled'}.", ephemeral=True
        )
        await self.refresh_message()

    @discord.ui.button(label="Edit mention spam", style=discord.ButtonStyle.success, row=2)
    async def edit_mention_spam(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        current = await self.cog.config.guild(self.guild).mention_spam.all()
        await interaction.response.send_modal(MentionSpamModal(self, current))

    @discord.ui.button(label="Edit defaults", style=discord.ButtonStyle.success, row=2)
    async def edit_defaults(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        snapshot = await self.cog.build_settings_snapshot(self.guild)
        await interaction.response.send_modal(DefaultsModal(self, snapshot))
