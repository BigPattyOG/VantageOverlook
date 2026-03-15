"""Custom help command for Vantage.

Features
--------
* Home page with bot stats and a category select-menu for navigation.
* Per-category command listings with paginated embeds (prev / next buttons).
* Detailed per-command view showing usage, aliases, and requirements.
* Live search via a Discord modal — searches command names, aliases, and help
  text for precise per-command results.
* Respects hidden commands and owner-only checks.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional

import discord
from discord.ext import commands

EMBED_COLOUR = discord.Color.from_str("#2DC5C5")  # Vantage teal
COMMANDS_PER_PAGE = 6


# ── Helpers ───────────────────────────────────────────────────────────────────

def _footer(ctx: commands.Context, extra: str = "") -> str:
    base = f"{ctx.clean_prefix}help <command> for details  •  Search button to find commands"
    return f"{base}  •  {extra}" if extra else base


def _base_embed(
    title: str,
    description: str = "",
    *,
    colour: discord.Color = EMBED_COLOUR,
) -> discord.Embed:
    return discord.Embed(title=title, description=description, colour=colour)


# ── Search modal ──────────────────────────────────────────────────────────────

class _SearchModal(discord.ui.Modal, title="Search Commands"):
    query: discord.ui.TextInput = discord.ui.TextInput(
        label="Keyword",
        placeholder="Command name, alias, or description keyword…",
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

        accessible: list[commands.Command] = []
        for cmd in matches:
            try:
                if await cmd.can_run(ctx):
                    accessible.append(cmd)
            except commands.CommandError:
                pass

        escaped = discord.utils.escape_markdown(self.query.value)

        if not accessible:
            embed = discord.Embed(
                title="No Results",
                description=(
                    f"No commands matched **{escaped}**.\n\n"
                    f"Try `{prefix}help` to browse all categories, "
                    "or use a different search term."
                ),
                colour=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        shown = accessible[:20]
        embed = discord.Embed(
            title=f'Search results for "{escaped}"',
            colour=EMBED_COLOUR,
        )
        for cmd in shown:
            sig = f"{prefix}{cmd.qualified_name}"
            if cmd.signature:
                sig += f" {cmd.signature}"
            cog_label = cmd.cog.qualified_name if cmd.cog else "Uncategorised"
            embed.add_field(
                name=f"`{prefix}{cmd.qualified_name}`",
                value=f"{cmd.short_doc or 'No description.'}\n> `{sig}`  ·  *{cog_label}*",
                inline=False,
            )
        if len(accessible) > 20:
            embed.set_footer(
                text=f"Showing 20 of {len(accessible)} matches — use a more specific term to narrow results."
            )
        else:
            embed.set_footer(text=f"{len(shown)} result(s) found")
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Category select menu ──────────────────────────────────────────────────────

class _CategorySelect(discord.ui.Select):
    """Drop-down to jump directly to a category's command list."""

    def __init__(
        self,
        cog_pages: Dict[str, List[discord.Embed]],
        home_embed: discord.Embed,
        help_command: "VantageHelp",
    ) -> None:
        self._cog_pages = cog_pages
        self._home_embed = home_embed
        self._help = help_command

        options = [
            discord.SelectOption(
                label="Overview",
                value="__home__",
                description="Back to the help overview",
            ),
        ]
        for name in cog_pages:
            cog = help_command.context.bot.cogs.get(name)
            desc = (cog.description[:100] if cog and cog.description else None)
            options.append(discord.SelectOption(label=name, value=name, description=desc))

        super().__init__(
            placeholder="Browse a category…",
            options=options[:25],  # Discord hard limit
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        chosen = self.values[0]
        view: HelpView = self.view  # type: ignore[assignment]
        if chosen == "__home__":
            view.pages = [self._home_embed]
            view.page = 0
            view._sync()
            await interaction.response.edit_message(embed=self._home_embed, view=view)
            return
        pages = self._cog_pages.get(chosen, [self._home_embed])
        view.pages = pages
        view.page = 0
        view._sync()
        await interaction.response.edit_message(embed=pages[0], view=view)


# ── Pagination view ───────────────────────────────────────────────────────────

class HelpView(discord.ui.View):
    """Navigation view attached to help embeds."""

    def __init__(
        self,
        pages: List[discord.Embed],
        help_command: "VantageHelp",
        *,
        cog_pages: Optional[Dict[str, List[discord.Embed]]] = None,
        home_embed: Optional[discord.Embed] = None,
        timeout: float = 180.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.pages = pages
        self._help = help_command
        self.page = 0
        self.message: Optional[discord.Message] = None

        if cog_pages and home_embed:
            self.add_item(_CategorySelect(cog_pages, home_embed, help_command))

        self._sync()

    def _sync(self) -> None:
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= len(self.pages) - 1
        self.counter_btn.label = f"{self.page + 1} / {len(self.pages)}"

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=1)
    async def prev_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page -= 1
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.secondary, disabled=True, row=1)
    async def counter_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page += 1
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    @discord.ui.button(label="Search", style=discord.ButtonStyle.primary, row=1)
    async def search_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_SearchModal(self._help))

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, row=1)
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


# ── Help command ──────────────────────────────────────────────────────────────

class VantageHelp(commands.HelpCommand):
    """Help command with category navigation, pagination, and live search."""

    # ── internal helpers ──────────────────────────────────────────────────────

    def _make_cog_pages(
        self,
        cog: Optional[commands.Cog],
        filtered: List[commands.Command],
        cog_name: str,
    ) -> List[discord.Embed]:
        """Build paginated embeds for a single cog/category."""
        prefix = self.context.clean_prefix
        cog_desc = getattr(cog, "description", "") or ""
        chunks = [
            filtered[i : i + COMMANDS_PER_PAGE]
            for i in range(0, len(filtered), COMMANDS_PER_PAGE)
        ]
        pages: List[discord.Embed] = []
        total = len(chunks)
        for idx, chunk in enumerate(chunks, 1):
            embed = _base_embed(
                cog_name,
                cog_desc if idx == 1 else "",
            )
            for cmd in chunk:
                sig = f"{prefix}{cmd.qualified_name}"
                if cmd.signature:
                    sig += f" {cmd.signature}"
                aliases_str = (
                    "  ·  also: " + "  ".join(f"`{a}`" for a in cmd.aliases)
                    if cmd.aliases
                    else ""
                )
                embed.add_field(
                    name=f"`{prefix}{cmd.qualified_name}`",
                    value=f"{cmd.short_doc or 'No description.'}\n> `{sig}`{aliases_str}",
                    inline=False,
                )
            footer_extra = f"Page {idx} of {total}" if total > 1 else ""
            embed.set_footer(text=_footer(self.context, footer_extra))
            pages.append(embed)
        return pages

    # ── HelpCommand overrides ─────────────────────────────────────────────────

    async def send_bot_help(
        self, mapping: Mapping[Optional[commands.Cog], List[commands.Command]]
    ) -> None:
        """Home page: bot overview, stats, and category select menu."""
        ctx = self.context
        prefix = ctx.clean_prefix
        bot = ctx.bot

        cog_pages: Dict[str, List[discord.Embed]] = {}
        category_lines: List[str] = []
        total_cmds = 0

        for cog, cmds in mapping.items():
            filtered = await self.filter_commands(cmds, sort=True)
            if not filtered:
                continue
            cog_name = getattr(cog, "qualified_name", "Uncategorised")
            pages = self._make_cog_pages(cog, filtered, cog_name)
            cog_pages[cog_name] = pages
            total_cmds += len(filtered)

            cmd_names = ", ".join(f"`{c.name}`" for c in filtered[:5])
            if len(filtered) > 5:
                cmd_names += f", *(+{len(filtered) - 5} more)*"
            cog_desc = getattr(cog, "description", "") or ""
            label = f"**{cog_name}**" + (f" — {cog_desc}" if cog_desc else "")
            category_lines.append(f"{label}\n{cmd_names}")

        guild_count = len(bot.guilds)
        user_count = sum(g.member_count or 0 for g in bot.guilds)
        latency_ms = round(bot.latency * 1000)

        bot_name = bot.user.display_name if bot.user else "Vantage"
        home_desc = (
            f"Use the **category menu** below to browse commands by group.\n"
            f"Click **Search** to find any command by name or keyword.\n"
            f"Run `{prefix}help <command>` for full details on any command."
        )
        home = _base_embed(f"{bot_name} — Help", home_desc)
        if bot.user:
            home.set_thumbnail(url=bot.user.display_avatar.url)

        home.add_field(
            name="Stats",
            value=(
                f"**Commands:** {total_cmds}\n"
                f"**Categories:** {len(cog_pages)}\n"
                f"**Prefix:** `{prefix}`"
            ),
            inline=True,
        )
        home.add_field(
            name="Status",
            value=(
                f"**Guilds:** {guild_count:,}\n"
                f"**Users:** {user_count:,}\n"
                f"**Latency:** {latency_ms} ms"
            ),
            inline=True,
        )
        home.add_field(name="\u200b", value="\u200b", inline=True)  # layout spacer

        if category_lines:
            home.add_field(
                name="Categories",
                value="\n\n".join(category_lines),
                inline=False,
            )

        home.set_footer(text=_footer(ctx))

        dest = self.get_destination()
        view = HelpView([home], self, cog_pages=cog_pages, home_embed=home)
        view.message = await dest.send(embed=home, view=view)

    async def send_cog_help(self, cog: commands.Cog) -> None:
        """Show all commands in a specific category with pagination."""
        filtered = await self.filter_commands(cog.get_commands(), sort=True)
        if not filtered:
            await self.send_error_message(
                f"No accessible commands in **{cog.qualified_name}**.\n"
                f"Some commands in this category may be restricted to bot owners."
            )
            return

        pages = self._make_cog_pages(cog, filtered, cog.qualified_name)
        dest = self.get_destination()
        view = HelpView(pages, self)
        view.message = await dest.send(embed=pages[0], view=view)

    async def send_group_help(self, group: commands.Group) -> None:
        """Detailed view for a command group and its sub-commands."""
        prefix = self.context.clean_prefix
        filtered = await self.filter_commands(group.commands, sort=True)

        embed = _base_embed(
            f"{prefix}{group.qualified_name}",
            group.help or group.short_doc or "No description available.",
        )

        sig = f"{prefix}{group.qualified_name}"
        if group.signature:
            sig += f" {group.signature}"
        embed.add_field(name="Usage", value=f"`{sig}`", inline=False)

        if group.aliases:
            embed.add_field(
                name="Aliases",
                value="  ".join(f"`{a}`" for a in group.aliases),
                inline=True,
            )
        if group.cog:
            embed.add_field(name="Category", value=group.cog.qualified_name, inline=True)

        if filtered:
            sub_lines = []
            for cmd in filtered:
                sub_sig = f"{prefix}{cmd.qualified_name}"
                if cmd.signature:
                    sub_sig += f" {cmd.signature}"
                sub_lines.append(
                    f"`{prefix}{cmd.name}` — {cmd.short_doc or 'No description.'}\n"
                    f"> `{sub_sig}`"
                )
            embed.add_field(
                name=f"Sub-commands ({len(filtered)})",
                value="\n".join(sub_lines),
                inline=False,
            )

        checks = [c.__doc__ for c in group.checks if c.__doc__]
        if checks:
            embed.add_field(name="Requirements", value="\n".join(checks), inline=False)

        embed.set_footer(text=_footer(self.context))
        await self.get_destination().send(embed=embed)

    async def send_command_help(self, command: commands.Command) -> None:
        """Detailed view for a single command."""
        prefix = self.context.clean_prefix
        embed = _base_embed(
            f"{prefix}{command.qualified_name}",
            command.help or command.short_doc or "No description available.",
        )

        sig = f"{prefix}{command.qualified_name}"
        if command.signature:
            sig += f" {command.signature}"
        embed.add_field(name="Usage", value=f"`{sig}`", inline=False)

        if command.aliases:
            embed.add_field(
                name="Aliases",
                value="  ".join(f"`{a}`" for a in command.aliases),
                inline=True,
            )
        if command.cog:
            embed.add_field(name="Category", value=command.cog.qualified_name, inline=True)

        checks = [c.__doc__ for c in command.checks if c.__doc__]
        if checks:
            embed.add_field(name="Requirements", value="\n".join(checks), inline=False)

        embed.set_footer(text=_footer(self.context))
        await self.get_destination().send(embed=embed)

    async def send_error_message(self, error: str) -> None:
        embed = discord.Embed(
            title="Help — Not Found",
            description=error,
            colour=discord.Color.red(),
        )
        embed.set_footer(text=_footer(self.context))
        await self.get_destination().send(embed=embed)

    def command_not_found(self, string: str) -> str:
        return (
            f"No command called `{string}` was found.\n"
            f"Run `{self.context.clean_prefix}help` to see all available commands, "
            f"or use the Search button to look by keyword."
        )

    def subcommand_not_found(self, command: commands.Command, string: str) -> str:
        if isinstance(command, commands.Group) and command.commands:
            subs = ", ".join(f"`{c.name}`" for c in command.commands)
            return (
                f"`{command.qualified_name}` has no sub-command called `{string}`.\n"
                f"Available sub-commands: {subs}"
            )
        return f"`{command.qualified_name}` has no sub-commands."
