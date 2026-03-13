"""Discord UI helpers for VMod.

Provides an interactive settings dashboard accessible via `[p]vmodset panel`.
All moderation actions still have prefix commands; this panel gives server admins
a friendlier way to review and tweak the most common settings.
"""

from __future__ import annotations

from datetime import timedelta

import discord
from redbot.core.utils.chat_formatting import humanize_list, humanize_timedelta

from .constants import ACTION_KEYS, NOTIF_KEYS, _


class VModSectionSelect(discord.ui.Select):
    """Dropdown to switch between settings sections in the dashboard."""

    def __init__(self, view: "VModDashboardView"):
        self.dashboard = view
        options = [
            discord.SelectOption(label="Overview",       value="overview",       emoji="⚙️",  description="Main moderation settings"),
            discord.SelectOption(label="Mention Spam",   value="mention_spam",   emoji="⚠️",  description="Auto-mod warn/kick/ban thresholds"),
            discord.SelectOption(label="Permissions",    value="permissions",    emoji="🔑",  description="Role-action permission map"),
            discord.SelectOption(label="Rate Limits",    value="rate_limits",    emoji="⏱️",  description="Moderator action rate caps"),
            discord.SelectOption(label="Warning Roles",  value="warning_roles",  emoji="🏅",  description="Milestone warning roles"),
            discord.SelectOption(label="Notifications",  value="notifications",  emoji="🔔",  description="Notification key overview"),
        ]
        super().__init__(
            placeholder="📋 Choose a settings section…",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.dashboard.section = self.values[0]
        await self.dashboard.refresh(interaction)


class MentionSpamModal(discord.ui.Modal, title="Edit mention spam thresholds"):
    """Modal for updating mention-spam automod thresholds."""

    warn_value = discord.ui.TextInput(
        label="Warn threshold (0 = disabled)",
        placeholder="e.g. 5",
        required=True,
        max_length=5,
    )
    kick_value = discord.ui.TextInput(
        label="Kick threshold (0 = disabled)",
        placeholder="e.g. 8",
        required=True,
        max_length=5,
    )
    ban_value = discord.ui.TextInput(
        label="Ban threshold (0 = disabled)",
        placeholder="e.g. 12",
        required=True,
        max_length=5,
    )
    strict_value = discord.ui.TextInput(
        label="Strict counting? (yes / no)",
        placeholder="yes",
        required=True,
        max_length=5,
    )

    def __init__(self, view: "VModDashboardView", current: dict):
        super().__init__()
        self.dashboard = view
        self.warn_value.default = str(current.get("warn") or 0)
        self.kick_value.default = str(current.get("kick") or 0)
        self.ban_value.default  = str(current.get("ban")  or 0)
        self.strict_value.default = "yes" if current.get("strict") else "no"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        def parse(value: str) -> int | None:
            n = int(value)
            if n < 0:
                raise ValueError
            return None if n == 0 else n

        try:
            warn   = parse(str(self.warn_value).strip())
            kick   = parse(str(self.kick_value).strip())
            ban    = parse(str(self.ban_value).strip())
            strict_raw = str(self.strict_value).strip().lower()
            if strict_raw not in {"yes", "no", "true", "false", "on", "off"}:
                raise ValueError
            strict = strict_raw in {"yes", "true", "on"}
        except ValueError:
            await interaction.response.send_message(
                "❌ Use whole numbers for thresholds and yes/no for strict mode.",
                ephemeral=True,
            )
            return

        await self.dashboard.cog.config.guild(self.dashboard.guild).mention_spam.set(
            {"warn": warn, "kick": kick, "ban": ban, "strict": strict}
        )
        self.dashboard.section = "mention_spam"
        await interaction.response.send_message("✅ Mention spam settings updated.", ephemeral=True)
        await self.dashboard.refresh_message()


class DefaultsModal(discord.ui.Modal, title="Edit VMod defaults"):
    """Modal for frequently changed general moderation defaults."""

    repeats_value = discord.ui.TextInput(
        label="Delete repeats (-1 = disabled, min 2)",
        placeholder="-1",
        required=True,
        max_length=5,
    )
    default_days = discord.ui.TextInput(
        label="Default ban delete days (0–7)",
        placeholder="0",
        required=True,
        max_length=2,
    )
    tempban_hours = discord.ui.TextInput(
        label="Default tempban duration (hours)",
        placeholder="24",
        required=True,
        max_length=6,
    )

    def __init__(self, view: "VModDashboardView", snapshot: dict):
        super().__init__()
        self.dashboard = view
        self.repeats_value.default  = str(snapshot["delete_repeats"])
        self.default_days.default   = str(snapshot["default_days"])
        self.tempban_hours.default  = str(int(snapshot["default_tempban_duration"] / 3600))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            repeats       = int(str(self.repeats_value).strip())
            default_days  = int(str(self.default_days).strip())
            tempban_hours = int(str(self.tempban_hours).strip())
            if repeats != -1 and repeats < 2:
                raise ValueError
            if not 0 <= default_days <= 7:
                raise ValueError
            if tempban_hours < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Use `-1` or ≥ `2` for repeats, `0–7` for delete days, and ≥ `1` hour for tempbans.",
                ephemeral=True,
            )
            return

        gc = self.dashboard.cog.config.guild(self.dashboard.guild)
        await gc.delete_repeats.set(repeats)
        await gc.default_days.set(default_days)
        await gc.default_tempban_duration.set(tempban_hours * 3600)
        self.dashboard.cog.repeat_cache.pop(self.dashboard.guild.id, None)
        self.dashboard.section = "overview"
        await interaction.response.send_message("✅ Defaults updated.", ephemeral=True)
        await self.dashboard.refresh_message()


class VModDashboardView(discord.ui.View):
    """Interactive settings dashboard for VMod."""

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
            await interaction.response.send_message(
                "❌ This control panel belongs to someone else.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Embed builder                                                        #
    # ------------------------------------------------------------------ #

    async def build_embed(self) -> discord.Embed:
        snapshot = await self.cog.build_settings_snapshot(self.guild)
        ms = snapshot["mention_spam"]

        embed = discord.Embed(
            title=f"⚙️ VMod Control Panel — {self.guild.name}",
            colour=discord.Colour.blurple(),
        )
        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)
        embed.set_footer(text="Use the dropdown to switch sections • Buttons apply quick edits")

        section = self.section

        if section == "overview":
            repeat_text = (
                f"After **{snapshot['delete_repeats']}** identical messages"
                if snapshot["delete_repeats"] != -1
                else "❌ Disabled"
            )
            embed.description = "📋 **Overview** — Core moderation defaults for this server."
            embed.add_field(name="🔁 Delete Repeats",     value=repeat_text,                                                     inline=False)
            embed.add_field(name="🛡️ Hierarchy Checks",  value="✅ Enabled" if snapshot["respect_hierarchy"] else "❌ Disabled", inline=True)
            embed.add_field(name="📨 DM Before Action",   value="✅ Enabled" if snapshot["dm_on_kickban"]       else "❌ Disabled", inline=True)
            embed.add_field(name="🔗 Reinvite on Unban",  value="✅ Enabled" if snapshot["reinvite_on_unban"]   else "❌ Disabled", inline=True)
            embed.add_field(name="🏷️ Track Nicknames",   value="✅ Enabled" if snapshot["track_nicknames"]     else "❌ Disabled", inline=True)
            embed.add_field(name="🗑️ Default Delete Days", value=str(snapshot["default_days"]),                                   inline=True)
            embed.add_field(name="⏳ Default Tempban",    value=humanize_timedelta(seconds=snapshot["default_tempban_duration"]), inline=True)

        elif section == "mention_spam":
            embed.description = "⚠️ **Mention Spam** — Auto-moderation thresholds."
            embed.add_field(name="⚠️ Warn",   value=f"{ms['warn']} mention(s)" if ms["warn"] else "❌ Disabled", inline=True)
            embed.add_field(name="👢 Kick",   value=f"{ms['kick']} mention(s)" if ms["kick"] else "❌ Disabled", inline=True)
            embed.add_field(name="🔨 Ban",    value=f"{ms['ban']}  mention(s)"  if ms["ban"]  else "❌ Disabled", inline=True)
            embed.add_field(
                name="📐 Strict Mode",
                value="✅ On — duplicates count" if ms["strict"] else "❌ Off — unique mentions only",
                inline=False,
            )

        elif section == "permissions":
            embed.description = "🔑 **Permissions** — Roles with access to each VMod action."
            action_roles = snapshot["action_roles"]
            for ak in ACTION_KEYS:
                roles = [
                    self.guild.get_role(rid).mention
                    for rid in action_roles.get(ak, [])
                    if self.guild.get_role(rid)
                ]
                embed.add_field(
                    name=f"`{ak}`",
                    value=humanize_list(roles) if roles else "*(none)*",
                    inline=False,
                )

        elif section == "rate_limits":
            embed.description = "⏱️ **Rate Limits** — Action caps applied to moderator roles."
            for ak, data in snapshot["action_rate_limits"].items():
                count = data["limit"]
                embed.add_field(
                    name=f"`{ak}`",
                    value=f"**{count}** action{'s' if count != 1 else ''} / {humanize_timedelta(seconds=data['window'])}",
                    inline=True,
                )

        elif section == "warning_roles":
            embed.description = "🏅 **Warning Roles** — Roles applied at warning milestones."
            wr = snapshot["warning_roles"]
            for key in ("warning1", "warning2", "warning3+"):
                role = self.guild.get_role(wr.get(key)) if wr.get(key) else None
                embed.add_field(
                    name=f"⚠️ {key.capitalize()}",
                    value=role.mention if role else "*(not set)*",
                    inline=True,
                )
            muted_role = self.guild.get_role(snapshot["muted_role"]) if snapshot["muted_role"] else None
            embed.add_field(name="🔇 Muted Role", value=muted_role.mention if muted_role else "*(not set)*", inline=True)
            embed.add_field(
                name="ℹ️ How to configure",
                value=(
                    "Use `[p]vmodroles warning1 @Role`, `[p]vmodroles warning2 @Role`, "
                    "`[p]vmodroles warning3 @Role`, and `[p]vmodroles muted @Role`."
                ),
                inline=False,
            )

        elif section == "notifications":
            embed.description = (
                "🔔 **Notifications** — Subscribe users or channels to moderation events.\n\n"
                "Use `[p]vmodnotifs add <key>` to subscribe yourself to a key,\n"
                "or `[p]vmodnotifs channel add <key> #channel` for a channel.\n\n"
                "**Available keys:** " + ", ".join(f"`{k}`" for k in NOTIF_KEYS)
            )

        return embed

    # ------------------------------------------------------------------ #
    # Refresh helpers                                                      #
    # ------------------------------------------------------------------ #

    async def refresh_message(self) -> None:
        if self.message is None:
            return
        try:
            await self.message.edit(embed=await self.build_embed(), view=self)
        except Exception:
            pass

    async def refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    # ------------------------------------------------------------------ #
    # Buttons                                                              #
    # ------------------------------------------------------------------ #

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, row=1)
    async def btn_refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.refresh(interaction)

    @discord.ui.button(label="⚔️ Toggle Hierarchy", style=discord.ButtonStyle.primary, row=1)
    async def btn_hierarchy(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        current = await self.cog.config.guild(self.guild).respect_hierarchy()
        await self.cog.config.guild(self.guild).respect_hierarchy.set(not current)
        await interaction.response.send_message(
            f"{'✅ Hierarchy checks enabled.' if not current else '❌ Hierarchy checks disabled.'}",
            ephemeral=True,
        )
        await self.refresh_message()

    @discord.ui.button(label="📨 Toggle DM", style=discord.ButtonStyle.primary, row=1)
    async def btn_dm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        current = await self.cog.config.guild(self.guild).dm_on_kickban()
        await self.cog.config.guild(self.guild).dm_on_kickban.set(not current)
        await interaction.response.send_message(
            f"{'✅ DM before action enabled.' if not current else '❌ DM before action disabled.'}",
            ephemeral=True,
        )
        await self.refresh_message()

    @discord.ui.button(label="🔗 Toggle Reinvite", style=discord.ButtonStyle.primary, row=2)
    async def btn_reinvite(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        current = await self.cog.config.guild(self.guild).reinvite_on_unban()
        await self.cog.config.guild(self.guild).reinvite_on_unban.set(not current)
        await interaction.response.send_message(
            f"{'✅ Reinvite on unban enabled.' if not current else '❌ Reinvite on unban disabled.'}",
            ephemeral=True,
        )
        await self.refresh_message()

    @discord.ui.button(label="⚠️ Edit Mention Spam", style=discord.ButtonStyle.success, row=2)
    async def btn_mention_spam(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        current = await self.cog.config.guild(self.guild).mention_spam.all()
        await interaction.response.send_modal(MentionSpamModal(self, current))

    @discord.ui.button(label="📝 Edit Defaults", style=discord.ButtonStyle.success, row=2)
    async def btn_defaults(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        snapshot = await self.cog.build_settings_snapshot(self.guild)
        await interaction.response.send_modal(DefaultsModal(self, snapshot))

from __future__ import annotations

from datetime import timedelta
