"""Custom paginated help command for Vantage.

Features
--------
* Embeds with pagination (◀ / ▶ buttons).
* Live search via a Discord modal — searches actual command names, aliases,
  and help text rather than scanning rendered embed fields.
* Per-cog and per-command detail views.
* Respects hidden commands and owner-only checks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Mapping, Optional

import discord
from discord.ext import commands

if TYPE_CHECKING:
    pass

EMBED_COLOUR = discord.Color.from_str("#2DC5C5")  # Vantage teal
COMMANDS_PER_PAGE = 8


# ── Pagination view ───────────────────────────────────────────────────────────


class HelpView(discord.ui.View):
    """Navigation view attached to help embeds."""

    def __init__(
        self,
        pages: List[discord.Embed],
        help_command: "VantageHelp",
        *,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.pages = pages
        self._help = help_command
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

    @discord.ui.button(label="🔍 Search", style=discord.ButtonStyle.primary)
    async def search_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_SearchModal(self._help))

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
        placeholder="Command name, alias, or keyword…",
        min_length=1,
        max_length=60,
    )

    def __init__(self, help_command: "VantageHelp") -> None:
        super().__init__()
        self._help = help_command

    async def on_submit(self, interaction: discord.Interaction) -> None:
        q = self.query.value.strip().lower()
        ctx = self._help.context
        prefix = ctx.clean_prefix

        # Search through actual command data (name, qualified name, aliases,
        # short description, full help text) for precise, per-command results.
        seen: set[str] = set()
        matches: list[commands.Command] = []
        for cmd in ctx.bot.walk_commands():
            qname = cmd.qualified_name
            if qname in seen:
                continue
            if (
                q in cmd.name.lower()
                or q in qname.lower()
                or any(q in alias.lower() for alias in cmd.aliases)
                or q in (cmd.short_doc or "").lower()
                or q in (cmd.help or "").lower()
            ):
                seen.add(qname)
                matches.append(cmd)

        # Keep only commands the invoking user can actually run.
        accessible: list[commands.Command] = []
        for cmd in matches:
            try:
                if await cmd.can_run(ctx):
                    accessible.append(cmd)
            except commands.CommandError:
                pass

        escaped_query = discord.utils.escape_markdown(self.query.value)

        if not accessible:
            embed = discord.Embed(
                title="🔍  No Results",
                description=(
                    f"No commands matched **{escaped_query}**.\n"
                    f"Try `{prefix}help` to browse all commands."
                ),
                color=discord.Color.red(),
            )
        else:
            shown = accessible[:15]
            embed = discord.Embed(
                title=f"🔍  Results for \"{escaped_query}\"",
                color=EMBED_COLOUR,
            )
            for cmd in shown:
                usage = f"`{prefix}{cmd.qualified_name} {cmd.signature}`".strip()
                cog_label = cmd.cog.qualified_name if cmd.cog else "No Category"
                embed.add_field(
                    name=f"`{prefix}{cmd.qualified_name}`  ·  {cog_label}",
                    value=f"{cmd.short_doc or 'No description.'}\n{usage}",
                    inline=False,
                )
            if len(accessible) > 15:
                embed.set_footer(text=f"Showing 15 of {len(accessible)} matches")

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Help command ──────────────────────────────────────────────────────────────


class VantageHelp(commands.HelpCommand):
    """Custom paginated help command."""

    # ── internal helpers ──────────────────────────────────────────────────────

    def _base_embed(self, title: str, description: str = "") -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=EMBED_COLOUR)
        embed.set_footer(
            text=f"Use {self.context.clean_prefix}help <command> for details  •  "
                 "🔍 Search button to find commands"
        )
        return embed

    def _paginate(self, embeds: List[discord.Embed]) -> List[discord.Embed]:
        """Stamp page numbers onto a list of embeds."""
        total = len(embeds)
        for i, embed in enumerate(embeds, 1):
            embed.set_footer(
                text=(
                    f"Page {i}/{total}  •  "
                    f"{self.context.clean_prefix}help <command> for details  •  "
                    "🔍 Search button to find commands"
                )
            )
        return embeds

    async def _send_pages(self, pages: List[discord.Embed]) -> None:
        dest = self.get_destination()
        view = HelpView(pages, self)
        view.message = await dest.send(embed=pages[0], view=view)

    # ── HelpCommand overrides ─────────────────────────────────────────────────

    async def send_bot_help(
        self, mapping: Mapping[Optional[commands.Cog], List[commands.Command]]
    ) -> None:
        """Show all cogs and their top-level commands."""
        prefix = self.context.clean_prefix
        pages: List[discord.Embed] = []
        current_embed = self._base_embed(
            "📖  Vantage Help",
            f"**Prefix:** `{prefix}`\n\n"
            f"Use `{prefix}help <command>` for full details on any command,\n"
            "or hit **🔍 Search** to find commands by keyword.",
        )
        count = 0

        for cog, cmds in mapping.items():
            filtered = await self.filter_commands(cmds, sort=True)
            if not filtered:
                continue

            cog_name = getattr(cog, "qualified_name", "No Category")
            cog_desc = getattr(cog, "description", "") or ""

            # Each command on its own bulleted line — bold name stands out clearly.
            lines = [
                f"▸ **{c.name}** — {c.short_doc or 'No description.'}"
                for c in filtered
            ]
            value = "\n".join(lines)

            # Start a new page when the current one is full.
            if count + len(filtered) > COMMANDS_PER_PAGE:
                pages.append(current_embed)
                current_embed = self._base_embed("📖  Vantage Help (continued)")
                count = 0

            header = f"⚙️  {cog_name}" + (f"  —  {cog_desc}" if cog_desc else "")
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

        prefix = self.context.clean_prefix
        pages: List[discord.Embed] = []
        chunks = [filtered[i:i + COMMANDS_PER_PAGE] for i in range(0, len(filtered), COMMANDS_PER_PAGE)]

        for chunk in chunks:
            embed = self._base_embed(
                f"⚙️  {cog.qualified_name}",
                cog.description or "",
            )
            for cmd in chunk:
                usage = f"`{prefix}{cmd.qualified_name} {cmd.signature}`".strip()
                aliases = (
                    "  ·  aliases: " + ", ".join(f"`{a}`" for a in cmd.aliases)
                    if cmd.aliases
                    else ""
                )
                embed.add_field(
                    name=f"`{prefix}{cmd.name}`{aliases}",
                    value=f"{cmd.help or cmd.short_doc or 'No description.'}\n**Usage:** {usage}",
                    inline=False,
                )
            pages.append(embed)

        await self._send_pages(self._paginate(pages))

    async def send_group_help(self, group: commands.Group) -> None:
        """Show a command group and its sub-commands."""
        prefix = self.context.clean_prefix
        filtered = await self.filter_commands(group.commands, sort=True)

        embed = self._base_embed(
            f"`{prefix}{group.qualified_name}`",
            group.help or group.short_doc or "No description.",
        )
        embed.add_field(
            name="Usage",
            value=f"`{prefix}{group.qualified_name} {group.signature}`".strip(),
            inline=False,
        )

        if filtered:
            sub_lines = [
                f"▸ **{cmd.name}** — {cmd.short_doc or 'No description.'}"
                for cmd in filtered
            ]
            embed.add_field(name="Sub-commands", value="\n".join(sub_lines), inline=False)

        if group.aliases:
            embed.add_field(
                name="Aliases",
                value=", ".join(f"`{a}`" for a in group.aliases),
                inline=True,
            )
        if group.cog:
            embed.add_field(name="Category", value=group.cog.qualified_name, inline=True)

        await self.get_destination().send(embed=embed)

    async def send_command_help(self, command: commands.Command) -> None:
        """Show detailed help for a single command."""
        prefix = self.context.clean_prefix
        embed = self._base_embed(
            f"`{prefix}{command.qualified_name}`",
            command.help or command.short_doc or "No description.",
        )
        embed.add_field(
            name="Usage",
            value=f"`{prefix}{command.qualified_name} {command.signature}`".strip(),
            inline=False,
        )

        if command.aliases:
            embed.add_field(
                name="Aliases",
                value=", ".join(f"`{a}`" for a in command.aliases),
                inline=True,
            )

        if command.cog:
            embed.add_field(name="Category", value=command.cog.qualified_name, inline=True)

        checks = [c.__doc__ for c in command.checks if c.__doc__]
        if checks:
            embed.add_field(name="Requirements", value="\n".join(checks), inline=False)

        await self.get_destination().send(embed=embed)

    async def send_error_message(self, error: str) -> None:
        embed = discord.Embed(
            title="❌  Help Error",
            description=error,
            color=discord.Color.red(),
        )
        await self.get_destination().send(embed=embed)

    def command_not_found(self, string: str) -> str:
        return (
            f"No command called `{string}` found.\n"
            f"Use `{self.context.clean_prefix}help` to browse all commands."
        )

    def subcommand_not_found(self, command: commands.Command, string: str) -> str:
        return f"`{command.qualified_name}` has no sub-command called `{string}`."
