"""Custom paginated help command for Vantage.

Features
--------
* Embeds with pagination (◀ / ▶ buttons).
* Live search via a Discord modal.
* Per-cog and per-command detail views.
* Respects hidden commands and owner-only checks.
"""

from __future__ import annotations

import math
from typing import List, Mapping, Optional

import discord
from discord.ext import commands

EMBED_COLOUR = discord.Color.from_str("#2DC5C5")  # Vantage teal
COMMANDS_PER_PAGE = 8


# ── Pagination view ───────────────────────────────────────────────────────────


class HelpView(discord.ui.View):
    """Navigation view attached to help embeds."""

    def __init__(self, pages: List[discord.Embed], *, timeout: float = 120.0) -> None:
        super().__init__(timeout=timeout)
        self.pages = pages
        self.page = 0
        self.message: Optional[discord.Message] = None
        self._sync()

    def _sync(self) -> None:
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= len(self.pages) - 1
        self.counter_btn.label = f"{self.page + 1}/{len(self.pages)}"

    @discord.ui.button(emoji="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page -= 1
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.secondary, disabled=True)
    async def counter_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()

    @discord.ui.button(emoji="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page += 1
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    @discord.ui.button(label="Search", style=discord.ButtonStyle.primary)
    async def search_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_SearchModal(self.pages))

    @discord.ui.button(label="✖", style=discord.ButtonStyle.danger)
    async def close_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.message.delete()
        self.stop()

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class _SearchModal(discord.ui.Modal, title="Search Commands"):
    query: discord.ui.TextInput = discord.ui.TextInput(
        label="Search",
        placeholder="Command name or keyword…",
        min_length=1,
        max_length=60,
    )

    def __init__(self, pages: List[discord.Embed]) -> None:
        super().__init__()
        self._pages = pages

    async def on_submit(self, interaction: discord.Interaction) -> None:
        q = self.query.value.strip().lower()
        matches: List[discord.EmbedField] = []

        for page in self._pages:
            for field in page.fields:
                if q in (field.name or "").lower() or q in (field.value or "").lower():
                    matches.append(field)

        if not matches:
            embed = discord.Embed(
                title="No results",
                description=f"No commands matched **{discord.utils.escape_markdown(self.query.value)}**.",
                color=discord.Color.red(),
            )
        else:
            embed = discord.Embed(
                title=f"Results for '{discord.utils.escape_markdown(self.query.value)}'",
                color=EMBED_COLOUR,
            )
            for field in matches[:15]:
                embed.add_field(name=field.name, value=field.value, inline=False)
            if len(matches) > 15:
                embed.set_footer(text=f"Showing 15 of {len(matches)} matches")

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Help command ──────────────────────────────────────────────────────────────


class VantageHelp(commands.HelpCommand):
    """Custom paginated help command."""

    # ── internal helpers ──────────────────────────────────────────────────────

    def _base_embed(self, title: str, description: str = "") -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=EMBED_COLOUR)
        embed.set_footer(
            text=f"Use {self.context.clean_prefix}help <command> for details • "
                 "Search button to find commands"
        )
        return embed

    def _paginate(self, embeds: List[discord.Embed]) -> List[discord.Embed]:
        """Stamp page numbers onto a list of embeds."""
        total = len(embeds)
        for i, embed in enumerate(embeds, 1):
            embed.set_footer(
                text=f"Page {i}/{total} • {self.context.clean_prefix}help <command> for details"
            )
        return embeds

    async def _send_pages(self, pages: List[discord.Embed]) -> None:
        dest = self.get_destination()
        view = HelpView(pages)
        view.message = await dest.send(embed=pages[0], view=view)

    # ── HelpCommand overrides ─────────────────────────────────────────────────

    async def send_bot_help(
        self, mapping: Mapping[Optional[commands.Cog], List[commands.Command]]
    ) -> None:
        """Show all cogs and their top-level commands."""
        pages: List[discord.Embed] = []
        current_embed = self._base_embed(
            "Vantage Help",
            f"**Prefix:** `{self.context.clean_prefix}`\n\n"
            "Use the buttons below to navigate, or search for a specific command.",
        )
        count = 0

        for cog, cmds in mapping.items():
            filtered = await self.filter_commands(cmds, sort=True)
            if not filtered:
                continue

            cog_name = getattr(cog, "qualified_name", "No Category")
            cog_desc = getattr(cog, "description", "") or ""
            lines = [f"`{self.context.clean_prefix}{c.name}` — {c.short_doc or 'No description'}" for c in filtered]
            value = "\n".join(lines)

            # Split large cogs across pages
            if count + len(filtered) > COMMANDS_PER_PAGE:
                pages.append(current_embed)
                current_embed = self._base_embed("Vantage Help (continued)")
                count = 0

            header = f"**{cog_name}**" + (f" — {cog_desc}" if cog_desc else "")
            current_embed.add_field(name=header, value=value, inline=False)
            count += len(filtered)

        pages.append(current_embed)
        await self._send_pages(self._paginate(pages))

    async def send_cog_help(self, cog: commands.Cog) -> None:
        """Show all commands in a specific cog."""
        filtered = await self.filter_commands(cog.get_commands(), sort=True)
        if not filtered:
            await self.send_error_message(f"No accessible commands in **{cog.qualified_name}**.")
            return

        pages: List[discord.Embed] = []
        chunks = [filtered[i:i + COMMANDS_PER_PAGE] for i in range(0, len(filtered), COMMANDS_PER_PAGE)]

        for chunk in chunks:
            embed = self._base_embed(
                f"{cog.qualified_name}",
                cog.description or "",
            )
            for cmd in chunk:
                embed.add_field(
                    name=f"`{self.context.clean_prefix}{cmd.name}` {cmd.signature}",
                    value=cmd.help or cmd.short_doc or "No description.",
                    inline=False,
                )
            pages.append(embed)

        await self._send_pages(self._paginate(pages))

    async def send_group_help(self, group: commands.Group) -> None:
        """Show a command group and its sub-commands."""
        filtered = await self.filter_commands(group.commands, sort=True)

        embed = self._base_embed(
            f"{self.context.clean_prefix}{group.qualified_name}",
            group.help or group.short_doc or "No description.",
        )
        embed.add_field(name="Usage", value=f"`{self.context.clean_prefix}{group.qualified_name} {group.signature}`", inline=False)

        if filtered:
            sub_lines = [
                f"`{self.context.clean_prefix}{cmd.qualified_name}` — {cmd.short_doc or 'No description'}"
                for cmd in filtered
            ]
            embed.add_field(name="Sub-commands", value="\n".join(sub_lines), inline=False)

        if group.aliases:
            embed.add_field(name="Aliases", value=", ".join(f"`{a}`" for a in group.aliases), inline=True)

        await self.get_destination().send(embed=embed)

    async def send_command_help(self, command: commands.Command) -> None:
        """Show detailed help for a single command."""
        embed = self._base_embed(
            f"{self.context.clean_prefix}{command.qualified_name}",
            command.help or command.short_doc or "No description.",
        )
        embed.add_field(
            name="Usage",
            value=f"`{self.context.clean_prefix}{command.qualified_name} {command.signature}`",
            inline=False,
        )

        if command.aliases:
            embed.add_field(name="Aliases", value=", ".join(f"`{a}`" for a in command.aliases), inline=True)

        cog = command.cog
        if cog:
            embed.add_field(name="Category", value=cog.qualified_name, inline=True)

        checks = [c.__doc__ for c in command.checks if c.__doc__]
        if checks:
            embed.add_field(name="Requirements", value="\n".join(checks), inline=False)

        await self.get_destination().send(embed=embed)

    async def send_error_message(self, error: str) -> None:
        embed = discord.Embed(
            title="Help Error",
            description=error,
            color=discord.Color.red(),
        )
        await self.get_destination().send(embed=embed)

    def command_not_found(self, string: str) -> str:
        return f"No command called `{string}` found. Use `{self.context.clean_prefix}help` to see all commands."

    def subcommand_not_found(self, command: commands.Command, string: str) -> str:
        return f"`{command.qualified_name}` has no sub-command called `{string}`."
