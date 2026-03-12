"""Embed rendering helpers for VHelp."""

from __future__ import annotations

from contextlib import suppress
from typing import Iterable

import discord

from redbot.core import commands
from redbot.core.utils.chat_formatting import box, humanize_list

from .utils import chunk_count, chunk_slice, command_aliases, command_signature, short_doc


class HelpRenderer:
    """Central place for building help embeds.

    Keeping all embed rendering in one module makes it easier to keep a
    consistent look across home, category, command, group, search, and error
    pages.
    """

    accent_color = discord.Color.from_rgb(88, 101, 242)

    def __init__(self, cog: commands.Cog):
        self.cog = cog

    async def _base_embed(
        self,
        ctx: commands.Context,
        *,
        title: str,
        description: str,
    ) -> discord.Embed:
        color = self.accent_color
        if ctx.guild and ctx.me:
            with suppress(Exception):
                color = ctx.me.color if ctx.me.color.value else color

        embed = discord.Embed(title=title, description=description, color=color)
        if ctx.me:
            embed.set_author(name=f"{ctx.me.display_name} Help Menu", icon_url=ctx.me.display_avatar.url)
        return embed

    def default_footer(self, ctx: commands.Context) -> str:
        return f"Type {ctx.clean_prefix}help <command> for more info. You can also type {ctx.clean_prefix}help <category> for category help."

    def category_label(self, name: str | None) -> str:
        return name or "No Category"

    async def home_embed(
        self,
        ctx: commands.Context,
        *,
        categories: list[dict],
        page: int = 0,
        page_size: int = 8,
    ) -> discord.Embed:
        total_pages = chunk_count(len(categories), page_size)
        page = max(0, min(page, total_pages - 1))
        current = chunk_slice(categories, page, page_size)

        embed = await self._base_embed(
            ctx,
            title="Help",
            description="Browse available categories with the dropdown or the navigation buttons below.",
        )

        if current:
            lines = []
            for entry in current:
                label = self.category_label(entry["name"])
                lines.append(f"**{label}** — {len(entry['commands'])} commands")
            embed.add_field(name="Categories", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Categories", value="No visible categories were found.", inline=False)

        embed.set_footer(text=f"Page {page + 1}/{total_pages} • {self.default_footer(ctx)}")
        return embed

    async def cog_embed(
        self,
        ctx: commands.Context,
        *,
        cog_name: str,
        description: str,
        commands_list: list[commands.Command],
        page: int = 0,
        page_size: int = 10,
    ) -> discord.Embed:
        total_pages = chunk_count(len(commands_list), page_size)
        page = max(0, min(page, total_pages - 1))
        current = chunk_slice(commands_list, page, page_size)

        embed = await self._base_embed(
            ctx,
            title=f"Help • {cog_name}",
            description=description or "No description provided.",
        )

        if current:
            chunks = []
            for command in current:
                chunks.append(f"**{command.qualified_name}**\n`{command_signature(ctx.clean_prefix, command)}`\n{short_doc(command)}")
            embed.add_field(name="Commands", value="\n\n".join(chunks), inline=False)
        else:
            embed.add_field(name="Commands", value="No visible commands were found.", inline=False)

        embed.set_footer(text=f"Page {page + 1}/{total_pages} • {self.default_footer(ctx)}")
        return embed

    async def command_embed(
        self,
        ctx: commands.Context,
        *,
        command: commands.Command,
        note: str | None = None,
        redirect_from: str | None = None,
    ) -> discord.Embed:
        embed = await self._base_embed(
            ctx,
            title=f"Help • {command.qualified_name}",
            description=(command.help or short_doc(command)),
        )
        embed.add_field(name="Syntax", value=box(command_signature(ctx.clean_prefix, command), lang=""), inline=False)
        embed.add_field(name="Aliases", value=command_aliases(command), inline=False)

        if command.cog_name:
            embed.add_field(name="Category", value=command.cog_name, inline=True)

        if command.parent is not None:
            embed.add_field(name="Parent", value=command.parent.qualified_name, inline=True)

        if redirect_from and redirect_from.casefold() != command.qualified_name.casefold():
            embed.add_field(
                name="Matched help topic",
                value=f"I couldn't find `{redirect_from}`, so I opened `{command.qualified_name}` instead.",
                inline=False,
            )

        if note:
            embed.add_field(name="Note", value=note, inline=False)

        embed.set_footer(text=self.default_footer(ctx))
        return embed

    async def group_overview_embed(
        self,
        ctx: commands.Context,
        *,
        command: commands.Group,
        subcommands: list[commands.Command],
        page: int = 0,
        page_size: int = 6,
        show_parent_info: bool = True,
    ) -> discord.Embed:
        total_pages = chunk_count(len(subcommands), page_size)
        page = max(0, min(page, total_pages - 1))
        current = chunk_slice(subcommands, page, page_size)

        description = command.help or short_doc(command)
        embed = await self._base_embed(ctx, title=f"Help • {command.qualified_name}", description=description)
        embed.add_field(name="Syntax", value=box(command_signature(ctx.clean_prefix, command), lang=""), inline=False)

        if show_parent_info:
            aliases = command_aliases(command)
            extra = [f"**Aliases:** {aliases}"]
            if command.cog_name:
                extra.append(f"**Category:** {command.cog_name}")
            embed.add_field(name="Command info", value="\n".join(extra), inline=False)

        if current:
            blocks = []
            for subcommand in current:
                blocks.append(f"**{subcommand.qualified_name}**\n`{command_signature(ctx.clean_prefix, subcommand)}`\n{short_doc(subcommand)}")
            embed.add_field(name="Subcommands", value="\n\n".join(blocks), inline=False)
        else:
            embed.add_field(name="Subcommands", value="No visible subcommands were found.", inline=False)

        embed.set_footer(text=f"Page {page + 1}/{total_pages} • {self.default_footer(ctx)}")
        return embed

    async def search_results_embed(
        self,
        ctx: commands.Context,
        *,
        query: str,
        results: list,
        page: int = 0,
        page_size: int = 6,
    ) -> discord.Embed:
        total_pages = chunk_count(len(results), page_size)
        page = max(0, min(page, total_pages - 1))
        current = chunk_slice(results, page, page_size)

        embed = await self._base_embed(
            ctx,
            title=f"Help Search • {query}",
            description="Search results are ranked by exact name, aliases, partial matches, and fuzzy similarity.",
        )

        if current:
            lines = []
            for result in current:
                kind = "Category" if result.kind == "cog" else "Command"
                lines.append(f"**{result.name}** — {kind}\n{result.summary}")
            embed.add_field(name="Results", value="\n\n".join(lines), inline=False)
        else:
            embed.add_field(name="Results", value="No matching help topics were found.", inline=False)

        embed.set_footer(text=f"Page {page + 1}/{total_pages} • {self.default_footer(ctx)}")
        return embed

    async def not_found_embed(
        self,
        ctx: commands.Context,
        *,
        query: str,
        suggestions: Iterable[str] | None = None,
        note: str | None = None,
    ) -> discord.Embed:
        embed = await self._base_embed(
            ctx,
            title="Help • Not Found",
            description=f"I couldn't find a help topic for `{query}`.",
        )

        if note:
            embed.add_field(name="Details", value=note, inline=False)

        if suggestions:
            embed.add_field(name="Maybe you meant", value="\n".join(f"• `{entry}`" for entry in suggestions), inline=False)

        embed.set_footer(text=self.default_footer(ctx))
        return embed
