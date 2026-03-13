"""Discord UI helpers for VMod.

Provides:
  - VModDashboardView  — interactive settings panel (`[p]vmodset panel`)
  - VModSetupWizard    — guided first-time setup wizard (`[p]vmodset wizard`)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from redbot.core.utils.chat_formatting import humanize_list, humanize_timedelta

from .constants import ACTION_KEYS, NOTIF_KEYS, _

if TYPE_CHECKING:
    from .base import VModBase


# ---------------------------------------------------------------------------
# Action-key metadata for wizard labels
# ---------------------------------------------------------------------------

_ACTION_META: dict[str, dict] = {
    "kick":           {"emoji": "👢", "label": "Kick",           "desc": "Can kick members"},
    "ban":            {"emoji": "🔨", "label": "Ban",            "desc": "Can ban / tempban / unban"},
    "mute":           {"emoji": "🔇", "label": "Mute",           "desc": "Can timeout / mute members"},
    "warn":           {"emoji": "⚠️",  "label": "Warn",           "desc": "Can warn members"},
    "channelperms":   {"emoji": "📌", "label": "Channel Perms",  "desc": "Can modify channel permissions"},
    "editchannel":    {"emoji": "✏️",  "label": "Edit Channel",   "desc": "Can create / rename / slowmode channels"},
    "deletemessages": {"emoji": "🗑️", "label": "Delete Messages","desc": "Can purge and pin messages"},
}

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _progress_bar(step: int, total: int) -> str:
    """Return a simple Unicode progress bar string."""
    filled = "█" * step
    empty  = "░" * (total - step)
    return f"`{filled}{empty}` {step}/{total}"


# ===========================================================================
# Dashboard panel (existing, extended with role/channel selects on sub-pages)
# ===========================================================================

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

    warn_value = discord.ui.TextInput(label="Warn threshold (0 = disabled)", placeholder="e.g. 5",  required=True, max_length=5)
    kick_value = discord.ui.TextInput(label="Kick threshold (0 = disabled)", placeholder="e.g. 8",  required=True, max_length=5)
    ban_value  = discord.ui.TextInput(label="Ban threshold (0 = disabled)",  placeholder="e.g. 12", required=True, max_length=5)
    strict_value = discord.ui.TextInput(label="Strict counting? (yes / no)", placeholder="yes",     required=True, max_length=5)

    def __init__(self, view: "VModDashboardView", current: dict):
        super().__init__()
        self.dashboard = view
        self.warn_value.default  = str(current.get("warn") or 0)
        self.kick_value.default  = str(current.get("kick") or 0)
        self.ban_value.default   = str(current.get("ban")  or 0)
        self.strict_value.default = "yes" if current.get("strict") else "no"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        def parse(value: str) -> int | None:
            n = int(value)
            if n < 0:
                raise ValueError
            return None if n == 0 else n

        try:
            warn  = parse(str(self.warn_value).strip())
            kick  = parse(str(self.kick_value).strip())
            ban   = parse(str(self.ban_value).strip())
            strict_raw = str(self.strict_value).strip().lower()
            if strict_raw not in {"yes", "no", "true", "false", "on", "off"}:
                raise ValueError
            strict = strict_raw in {"yes", "true", "on"}
        except ValueError:
            await interaction.response.send_message(
                "❌ Use whole numbers for thresholds and yes/no for strict mode.", ephemeral=True
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

    repeats_value = discord.ui.TextInput(label="Delete repeats (-1 = disabled, min 2)", placeholder="-1", required=True, max_length=5)
    default_days  = discord.ui.TextInput(label="Default ban delete days (0–7)",          placeholder="0",  required=True, max_length=2)
    tempban_hours = discord.ui.TextInput(label="Default tempban duration (hours)",        placeholder="24", required=True, max_length=6)

    def __init__(self, view: "VModDashboardView", snapshot: dict):
        super().__init__()
        self.dashboard = view
        self.repeats_value.default = str(snapshot["delete_repeats"])
        self.default_days.default  = str(snapshot["default_days"])
        self.tempban_hours.default = str(int(snapshot["default_tempban_duration"] / 3600))

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

    def __init__(self, cog: "VModBase", author: discord.abc.User, guild: discord.Guild):
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
            embed.add_field(name="🔁 Delete Repeats",      value=repeat_text,                                                     inline=False)
            embed.add_field(name="🛡️ Hierarchy Checks",   value="✅ Enabled" if snapshot["respect_hierarchy"] else "❌ Disabled", inline=True)
            embed.add_field(name="�� DM Before Action",    value="✅ Enabled" if snapshot["dm_on_kickban"]     else "❌ Disabled", inline=True)
            embed.add_field(name="🔗 Reinvite on Unban",   value="✅ Enabled" if snapshot["reinvite_on_unban"] else "❌ Disabled", inline=True)
            embed.add_field(name="🏷️ Track Nicknames",    value="✅ Enabled" if snapshot["track_nicknames"]   else "❌ Disabled", inline=True)
            embed.add_field(name="🗑️ Default Delete Days", value=str(snapshot["default_days"]),                                   inline=True)
            embed.add_field(name="⏳ Default Tempban",     value=humanize_timedelta(seconds=snapshot["default_tempban_duration"]), inline=True)

        elif section == "mention_spam":
            embed.description = "⚠️ **Mention Spam** — Auto-moderation thresholds."
            embed.add_field(name="⚠️ Warn", value=f"{ms['warn']} mention(s)" if ms["warn"] else "❌ Disabled", inline=True)
            embed.add_field(name="👢 Kick", value=f"{ms['kick']} mention(s)" if ms["kick"] else "❌ Disabled", inline=True)
            embed.add_field(name="🔨 Ban",  value=f"{ms['ban']}  mention(s)" if ms["ban"]  else "❌ Disabled", inline=True)
            embed.add_field(
                name="📐 Strict Mode",
                value="✅ On — duplicates count" if ms["strict"] else "❌ Off — unique mentions only",
                inline=False,
            )

        elif section == "permissions":
            embed.description = (
                "🔑 **Permissions** — Roles that may use each VMod action.\n"
                "Use the **Edit Permissions** button below to assign roles interactively."
            )
            action_roles = snapshot["action_roles"]
            for ak in ACTION_KEYS:
                meta  = _ACTION_META.get(ak, {})
                emoji = meta.get("emoji", "•")
                roles = [
                    self.guild.get_role(rid).mention
                    for rid in action_roles.get(ak, [])
                    if self.guild.get_role(rid)
                ]
                embed.add_field(
                    name=f"{emoji} {meta.get('label', ak)}",
                    value=humanize_list(roles) if roles else "*(none)*",
                    inline=True,
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
            embed.description = (
                "🏅 **Warning Roles** — Roles applied at warning milestones.\n"
                "Use the **Edit Roles** button below to set these interactively."
            )
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

        elif section == "notifications":
            embed.description = (
                "🔔 **Notifications** — Subscribe users or channels to moderation events.\n\n"
                "**To subscribe yourself:**\n"
                "`[p]vmodnotifs add <key>` — DM notifications\n\n"
                "**To subscribe a channel:**\n"
                "`[p]vmodnotifs channel add <key> #channel`\n\n"
                "**Available keys:** " + ", ".join(f"`{k}`" for k in NOTIF_KEYS)
            )

        return embed

    async def refresh_message(self) -> None:
        if self.message is None:
            return
        try:
            await self.message.edit(embed=await self.build_embed(), view=self)
        except Exception:
            pass

    async def refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    # ---- Buttons row 1 ----

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, row=1)
    async def btn_refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.refresh(interaction)

    @discord.ui.button(label="⚔️ Toggle Hierarchy", style=discord.ButtonStyle.primary, row=1)
    async def btn_hierarchy(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        current = await self.cog.config.guild(self.guild).respect_hierarchy()
        await self.cog.config.guild(self.guild).respect_hierarchy.set(not current)
        await interaction.response.send_message(
            f"{'✅ Hierarchy checks enabled.' if not current else '❌ Hierarchy checks disabled.'}", ephemeral=True
        )
        await self.refresh_message()

    @discord.ui.button(label="📨 Toggle DM", style=discord.ButtonStyle.primary, row=1)
    async def btn_dm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        current = await self.cog.config.guild(self.guild).dm_on_kickban()
        await self.cog.config.guild(self.guild).dm_on_kickban.set(not current)
        await interaction.response.send_message(
            f"{'✅ DM before action enabled.' if not current else '❌ DM before action disabled.'}", ephemeral=True
        )
        await self.refresh_message()

    # ---- Buttons row 2 ----

    @discord.ui.button(label="🔗 Toggle Reinvite", style=discord.ButtonStyle.primary, row=2)
    async def btn_reinvite(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        current = await self.cog.config.guild(self.guild).reinvite_on_unban()
        await self.cog.config.guild(self.guild).reinvite_on_unban.set(not current)
        await interaction.response.send_message(
            f"{'✅ Reinvite on unban enabled.' if not current else '❌ Reinvite on unban disabled.'}", ephemeral=True
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

    # ---- Buttons row 3 ----

    @discord.ui.button(label="🔑 Edit Permissions", style=discord.ButtonStyle.success, row=3)
    async def btn_edit_perms(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        """Open a role-selector wizard page for action permissions."""
        await interaction.response.send_message(
            embed=_perm_wizard_embed(0),
            view=PermWizardView(self.cog, self.guild, interaction.user),
            ephemeral=True,
        )

    @discord.ui.button(label="🏅 Edit Roles", style=discord.ButtonStyle.success, row=3)
    async def btn_edit_roles(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        """Open a role-selector panel for warning milestone and muted roles."""
        snapshot = await self.cog.build_settings_snapshot(self.guild)
        await interaction.response.send_message(
            embed=_warning_roles_embed(self.guild, snapshot),
            view=WarningRolesView(self.cog, self.guild, interaction.user),
            ephemeral=True,
        )


# ===========================================================================
# Permission Wizard — ephemeral RoleSelect pages for each action key
# ===========================================================================

def _perm_wizard_embed(step: int) -> discord.Embed:
    """Build the embed for step *step* of the permission wizard."""
    ak   = ACTION_KEYS[step]
    meta = _ACTION_META.get(ak, {"emoji": "•", "label": ak, "desc": ""})
    embed = discord.Embed(
        title=f"{meta['emoji']} Set roles for `{ak}`",
        description=(
            f"**{meta['label']}** — {meta['desc']}\n\n"
            "Select one or more roles that should have this permission.\n"
            "Leave blank and press **Next** to keep the current roles unchanged.\n\n"
            f"{_progress_bar(step + 1, len(ACTION_KEYS))}"
        ),
        colour=discord.Colour.blurple(),
    )
    embed.set_footer(text=f"Step {step + 1} of {len(ACTION_KEYS)}")
    return embed


class PermActionRoleSelect(discord.ui.RoleSelect):
    """RoleSelect for a single action key in the permission wizard."""

    def __init__(self, key: str, row: int = 0):
        self.key = key
        super().__init__(
            placeholder=f"Select roles for '{key}'…",
            min_values=0,
            max_values=25,
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        # Defer without responding — the view's buttons do the saving
        await interaction.response.defer()
        self.view.selected_roles = [r.id for r in self.values]


class PermWizardView(discord.ui.View):
    """Multi-step ephemeral wizard for assigning roles to action permission keys."""

    def __init__(self, cog: "VModBase", guild: discord.Guild, author: discord.abc.User):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild
        self.author_id = author.id
        self.step = 0
        self.selected_roles: list[int] = []
        self._rebuild_selector()

    def _rebuild_selector(self) -> None:
        """Remove old selectors and add one for the current step."""
        for item in list(self.children):
            if isinstance(item, discord.ui.RoleSelect):
                self.remove_item(item)
        self.add_item(PermActionRoleSelect(ACTION_KEYS[self.step], row=0))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    async def _save_current(self) -> None:
        """Persist whatever roles were selected for the current step."""
        if not self.selected_roles:
            return
        ak = ACTION_KEYS[self.step]
        async with self.cog.config.guild(self.guild).action_roles() as ar:
            ar[ak] = self.selected_roles
        self.selected_roles = []

    async def _advance(self, interaction: discord.Interaction, direction: int) -> None:
        await self._save_current()
        self.step += direction
        self.step = max(0, min(self.step, len(ACTION_KEYS) - 1))
        self._rebuild_selector()
        self._update_buttons()
        await interaction.response.edit_message(embed=_perm_wizard_embed(self.step), view=self)

    def _update_buttons(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "perm_prev":
                    item.disabled = self.step == 0
                elif item.custom_id == "perm_next":
                    item.label = "✅ Done" if self.step == len(ACTION_KEYS) - 1 else "Next ➡️"

    @discord.ui.button(label="⬅️ Back",   custom_id="perm_prev", style=discord.ButtonStyle.secondary, row=1, disabled=True)
    async def btn_prev(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._advance(interaction, -1)

    @discord.ui.button(label="Next ➡️", custom_id="perm_next", style=discord.ButtonStyle.primary, row=1)
    async def btn_next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.step == len(ACTION_KEYS) - 1:
            await self._save_current()
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="✅ Permissions saved!",
                    description="All role permissions have been updated.\nClose this panel — changes are live.",
                    colour=discord.Colour.green(),
                ),
                view=None,
            )
        else:
            await self._advance(interaction, 1)

    @discord.ui.button(label="⏭️ Skip",  custom_id="perm_skip", style=discord.ButtonStyle.secondary, row=1)
    async def btn_skip(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.selected_roles = []  # don't save
        await self._advance(interaction, 1)


# ===========================================================================
# Warning Roles panel — ephemeral RoleSelect for milestone + muted roles
# ===========================================================================

def _warning_roles_embed(guild: discord.Guild, snapshot: dict) -> discord.Embed:
    wr = snapshot["warning_roles"]
    embed = discord.Embed(
        title="🏅 Warning Milestone & Muted Roles",
        description=(
            "Use the dropdowns below to assign roles to each warning milestone.\n"
            "Members receive the matching role when they reach that warning count."
        ),
        colour=discord.Colour.blurple(),
    )
    for key in ("warning1", "warning2", "warning3+"):
        role = guild.get_role(wr.get(key)) if wr.get(key) else None
        embed.add_field(name=f"⚠️ {key.capitalize()}", value=role.mention if role else "*(not set)*", inline=True)
    muted = guild.get_role(snapshot["muted_role"]) if snapshot["muted_role"] else None
    embed.add_field(name="🔇 Muted Role", value=muted.mention if muted else "*(not set)*", inline=True)
    return embed


class _SingleRoleSelect(discord.ui.RoleSelect):
    """RoleSelect for a single config key."""

    def __init__(self, *, config_key: str, placeholder: str, row: int):
        super().__init__(placeholder=placeholder, min_values=0, max_values=1, row=row)
        self.config_key = config_key

    async def callback(self, interaction: discord.Interaction) -> None:
        role_id = self.values[0].id if self.values else None
        if self.config_key == "muted_role":
            await self.view.cog.config.guild(self.view.guild).muted_role.set(role_id)
        else:
            await self.view.cog.config.guild(self.view.guild).warning_roles.set_raw(
                self.config_key, value=role_id
            )
        label = "Muted role" if self.config_key == "muted_role" else self.config_key.capitalize()
        role_mention = self.values[0].mention if self.values else "*(cleared)*"
        await interaction.response.send_message(
            f"✅ **{label}** set to {role_mention}.", ephemeral=True
        )


class WarningRolesView(discord.ui.View):
    """Ephemeral view with four RoleSelects for warning milestone and muted roles."""

    def __init__(self, cog: "VModBase", guild: discord.Guild, author: discord.abc.User):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild = guild
        self.author_id = author.id
        self.add_item(_SingleRoleSelect(config_key="warning1",  placeholder="⚠️ Warning 1 role…", row=0))
        self.add_item(_SingleRoleSelect(config_key="warning2",  placeholder="⚠️ Warning 2 role…", row=1))
        self.add_item(_SingleRoleSelect(config_key="warning3+", placeholder="⚠️ Warning 3+ role…", row=2))
        self.add_item(_SingleRoleSelect(config_key="muted_role", placeholder="🔇 Muted role…",     row=3))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id


# ===========================================================================
# Setup Wizard — guided first-time setup flow
# ===========================================================================

_WIZARD_STEPS = [
    "welcome",
    "basic_settings",
    "permissions",
    "warning_roles",
    "notif_channel",
    "done",
]
_WIZARD_TOTAL = len(_WIZARD_STEPS) - 1   # 'done' doesn't count toward progress


def _wizard_embed_for(step_name: str, cog_or_none=None, guild=None, snapshot=None) -> discord.Embed:
    """Return the appropriate embed for the named wizard step."""

    if step_name == "welcome":
        embed = discord.Embed(
            title="🎉 Welcome to VMod Setup!",
            description=(
                "This wizard will guide you through the most important settings in a few easy steps.\n\n"
                "**What we'll configure:**\n"
                "1. 🛡️ Basic moderation settings\n"
                "2. 🔑 Role permissions (who can kick, ban, mute, etc.)\n"
                "3. 🏅 Warning milestone roles\n"
                "4. 🔔 Notification channel\n\n"
                "Use the **Next** button to get started, or **Skip** any step you want to set up later."
            ),
            colour=discord.Colour.blurple(),
        )
        embed.set_footer(text="Tip: You can run [p]vmodset panel at any time to adjust settings.")
        return embed

    if step_name == "basic_settings":
        embed = discord.Embed(
            title="🛡️ Basic Settings",
            description=(
                "Toggle the core moderation behaviours using the buttons below.\n\n"
                "**Hierarchy Checks** — Prevent moderators from actioning users above them in the role hierarchy.\n"
                "**DM Before Action** — DM members before they are kicked, banned, or muted.\n"
                "**Reinvite on Unban** — Send a fresh invite link when unbanning a user.\n\n"
                + (
                    f"Current values:"
                    f"\n🛡️ Hierarchy: **{'✅ On' if snapshot['respect_hierarchy'] else '❌ Off'}**"
                    f"\n📨 DM on action: **{'✅ On' if snapshot['dm_on_kickban'] else '❌ Off'}**"
                    f"\n🔗 Reinvite: **{'✅ On' if snapshot['reinvite_on_unban'] else '❌ Off'}**"
                    if snapshot
                    else ""
                )
            ),
            colour=discord.Colour.blurple(),
        )
        embed.set_footer(text=f"Step 1 of {_WIZARD_TOTAL}  •  {_progress_bar(1, _WIZARD_TOTAL)}")
        return embed

    if step_name == "permissions":
        embed = discord.Embed(
            title="🔑 Role Permissions",
            description=(
                "Assign roles that should have each moderation permission.\n\n"
                "Press **Open Permission Editor** to use the interactive role selectors.\n"
                "You can always use `[p]vmodperms add @Role <key>` as a text command.\n\n"
                "**Keys:** " + ", ".join(f"`{k}`" for k in ACTION_KEYS)
            ),
            colour=discord.Colour.blurple(),
        )
        embed.set_footer(text=f"Step 2 of {_WIZARD_TOTAL}  •  {_progress_bar(2, _WIZARD_TOTAL)}")
        return embed

    if step_name == "warning_roles":
        embed = discord.Embed(
            title="🏅 Warning Milestone Roles",
            description=(
                "Set which roles are automatically assigned when members receive their 1st, 2nd, or 3rd+ warning.\n\n"
                "Press **Open Role Editor** to use the interactive selectors.\n"
                "You can also use `[p]vmodroles warning1/2/3 @Role` as text commands."
            ),
            colour=discord.Colour.blurple(),
        )
        embed.set_footer(text=f"Step 3 of {_WIZARD_TOTAL}  •  {_progress_bar(3, _WIZARD_TOTAL)}")
        return embed

    if step_name == "notif_channel":
        embed = discord.Embed(
            title="🔔 Notification Channel",
            description=(
                "Choose a channel to receive moderation event notifications.\n"
                "Select a channel below and choose which events to send there.\n\n"
                "You can also set this up later with:\n"
                "`[p]vmodnotifs channel add <key> #channel`\n\n"
                "**Common notification keys:** `kick`, `ban`, `warn`, `ratelimit`, `adminrole`, `bot`"
            ),
            colour=discord.Colour.blurple(),
        )
        embed.set_footer(text=f"Step 4 of {_WIZARD_TOTAL}  •  {_progress_bar(4, _WIZARD_TOTAL)}")
        return embed

    # done
    embed = discord.Embed(
        title="✅ VMod is Ready!",
        description=(
            "Setup complete. Here's a quick recap of what you can do next:\n\n"
            "📋 **Review all settings** — `[p]vmodset show`\n"
            "⚙️ **Open the panel** — `[p]vmodset panel`\n"
            "📊 **Check what's configured** — `[p]vmodset checklist`\n"
            "❓ **Get help** — `[p]help vmod`\n\n"
            "VMod is now protecting your server. Happy moderating! 🛡️"
        ),
        colour=discord.Colour.green(),
    )
    embed.set_footer(text="Run [p]vmodset wizard at any time to re-run this wizard.")
    return embed


class _NotifChannelSelect(discord.ui.ChannelSelect):
    """Channel selector used on the notification channel wizard step."""

    def __init__(self):
        super().__init__(
            placeholder="📢 Pick a notification channel…",
            min_values=0,
            max_values=1,
            channel_types=[discord.ChannelType.text],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not self.values:
            await interaction.response.defer()
            return
        channel = self.values[0]
        # Subscribe all standard notif keys to this channel
        standard_keys = ("kick", "ban", "mute", "warn", "ratelimit", "adminrole", "bot")
        entry = [channel.guild.id, channel.id]
        async with self.view.cog.config.notif_channels() as nc:
            for key in standard_keys:
                if entry not in nc.get(key, []):
                    nc.setdefault(key, []).append(entry)
        await interaction.response.send_message(
            f"✅ Standard notifications will now be sent to {channel.mention}.",
            ephemeral=True,
        )


class VModSetupWizard(discord.ui.View):
    """Guided first-time setup wizard for VMod."""

    def __init__(self, cog: "VModBase", author: discord.abc.User, guild: discord.Guild):
        super().__init__(timeout=600)
        self.cog = cog
        self.author_id = author.id
        self.guild = guild
        self.step_name = "welcome"
        self.message: discord.Message | None = None
        self._rebuild_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ This wizard belongs to someone else.", ephemeral=True
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

    def _rebuild_items(self) -> None:
        """Clear all items and add the appropriate set for the current step."""
        self.clear_items()

        # Action buttons (always present)
        idx = _WIZARD_STEPS.index(self.step_name)
        is_first = idx == 0
        is_last  = self.step_name == "done"
        is_before_last = idx == len(_WIZARD_STEPS) - 2

        if not is_first and not is_last:
            btn_back = discord.ui.Button(
                label="⬅️ Back",
                style=discord.ButtonStyle.secondary,
                custom_id="wiz_back",
                row=4,
            )
            btn_back.callback = self._btn_back
            self.add_item(btn_back)

        if not is_last:
            next_label = "✅ Finish" if is_before_last else "Next ➡️"
            btn_next = discord.ui.Button(
                label=next_label,
                style=discord.ButtonStyle.primary,
                custom_id="wiz_next",
                row=4,
            )
            btn_next.callback = self._btn_next
            self.add_item(btn_next)

            if not is_first:
                btn_skip = discord.ui.Button(
                    label="⏭️ Skip",
                    style=discord.ButtonStyle.secondary,
                    custom_id="wiz_skip",
                    row=4,
                )
                btn_skip.callback = self._btn_next  # same as next but without saving
                self.add_item(btn_skip)

        # Step-specific items
        if self.step_name == "basic_settings":
            btn_h = discord.ui.Button(label="⚔️ Toggle Hierarchy", style=discord.ButtonStyle.primary, custom_id="wiz_h", row=1)
            btn_h.callback = self._toggle_hierarchy
            self.add_item(btn_h)

            btn_d = discord.ui.Button(label="📨 Toggle DM", style=discord.ButtonStyle.primary, custom_id="wiz_d", row=1)
            btn_d.callback = self._toggle_dm
            self.add_item(btn_d)

            btn_r = discord.ui.Button(label="🔗 Toggle Reinvite", style=discord.ButtonStyle.primary, custom_id="wiz_r", row=1)
            btn_r.callback = self._toggle_reinvite
            self.add_item(btn_r)

        elif self.step_name == "permissions":
            btn_ep = discord.ui.Button(
                label="🔑 Open Permission Editor",
                style=discord.ButtonStyle.success,
                custom_id="wiz_ep",
                row=1,
            )
            btn_ep.callback = self._open_perm_editor
            self.add_item(btn_ep)

        elif self.step_name == "warning_roles":
            btn_wr = discord.ui.Button(
                label="🏅 Open Role Editor",
                style=discord.ButtonStyle.success,
                custom_id="wiz_wr",
                row=1,
            )
            btn_wr.callback = self._open_role_editor
            self.add_item(btn_wr)

        elif self.step_name == "notif_channel":
            self.add_item(_NotifChannelSelect())

    async def _get_snapshot(self) -> dict:
        return await self.cog.build_settings_snapshot(self.guild)

    async def _build_embed(self) -> discord.Embed:
        snapshot = await self._get_snapshot() if self.step_name == "basic_settings" else None
        return _wizard_embed_for(self.step_name, self.cog, self.guild, snapshot)

    async def _go_to_step(self, interaction: discord.Interaction, step_name: str) -> None:
        self.step_name = step_name
        self._rebuild_items()
        await interaction.response.edit_message(embed=await self._build_embed(), view=self)

    # ---- Navigation callbacks ----

    async def _btn_next(self, interaction: discord.Interaction) -> None:
        idx = _WIZARD_STEPS.index(self.step_name)
        next_step = _WIZARD_STEPS[min(idx + 1, len(_WIZARD_STEPS) - 1)]
        await self._go_to_step(interaction, next_step)

    async def _btn_back(self, interaction: discord.Interaction) -> None:
        idx = _WIZARD_STEPS.index(self.step_name)
        prev_step = _WIZARD_STEPS[max(idx - 1, 0)]
        await self._go_to_step(interaction, prev_step)

    # ---- Step-specific callbacks ----

    async def _toggle_hierarchy(self, interaction: discord.Interaction) -> None:
        current = await self.cog.config.guild(self.guild).respect_hierarchy()
        await self.cog.config.guild(self.guild).respect_hierarchy.set(not current)
        await interaction.response.send_message(
            f"{'✅ Hierarchy checks enabled.' if not current else '❌ Hierarchy checks disabled.'}", ephemeral=True
        )
        await self.message.edit(embed=await self._build_embed(), view=self)

    async def _toggle_dm(self, interaction: discord.Interaction) -> None:
        current = await self.cog.config.guild(self.guild).dm_on_kickban()
        await self.cog.config.guild(self.guild).dm_on_kickban.set(not current)
        await interaction.response.send_message(
            f"{'✅ DM on action enabled.' if not current else '❌ DM on action disabled.'}", ephemeral=True
        )
        await self.message.edit(embed=await self._build_embed(), view=self)

    async def _toggle_reinvite(self, interaction: discord.Interaction) -> None:
        current = await self.cog.config.guild(self.guild).reinvite_on_unban()
        await self.cog.config.guild(self.guild).reinvite_on_unban.set(not current)
        await interaction.response.send_message(
            f"{'✅ Reinvite on unban enabled.' if not current else '❌ Reinvite on unban disabled.'}", ephemeral=True
        )
        await self.message.edit(embed=await self._build_embed(), view=self)

    async def _open_perm_editor(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=_perm_wizard_embed(0),
            view=PermWizardView(self.cog, self.guild, interaction.user),
            ephemeral=True,
        )

    async def _open_role_editor(self, interaction: discord.Interaction) -> None:
        snapshot = await self.cog.build_settings_snapshot(self.guild)
        await interaction.response.send_message(
            embed=_warning_roles_embed(self.guild, snapshot),
            view=WarningRolesView(self.cog, self.guild, interaction.user),
            ephemeral=True,
        )
