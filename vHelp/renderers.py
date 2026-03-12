"""Embed rendering helpers for VHelp."""

from __future__ import annotations

from contextlib import suppress
from typing import Iterable

import discord

from redbot.core import commands
from redbot.core.utils.chat_formatting import box, humanize_number

from .utils import chunk_count, chunk_slice, command_aliases, command_scope, command_signature, short_doc


class HelpRenderer:
    accent_color = discord.Color.from_rgb(46, 160, 67)
    divider = "─" * 28

    def __init__(self, cog: commands.Cog):
        self.cog = cog

    async def _base_embed(self, ctx: commands.Context, *, title: str, description: str) -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=self.accent_color)
        if ctx.me:
            embed.set_author(name=f"{ctx.me.display_name} Help", icon_url=ctx.me.display_avatar.url)
            embed.set_thumbnail(url=ctx.me.display_avatar.url)
        return embed

    def default_footer(self, ctx: commands.Context) -> str:
        return (
            f"Use {ctx.clean_prefix}help <command>, {ctx.clean_prefix}help admin <command>, "
            f"or {ctx.clean_prefix}help owner <command>."
        )

    def category_label(self, name: str | None) -> str:
        return name or "No Category"

    def _category_summary(self, entry: dict) -> str:
        desc = (entry.get("description") or "No description provided.").strip().splitlines()[0]
        return f"`{len(entry['commands'])}` commands • {desc[:80]}"

    def _bot_stats(self, ctx: commands.Context, categories: list[dict]) -> str:
        guilds = len(getattr(ctx.bot, "guilds", []))
        unique_users = len(getattr(ctx.bot, "users", []))
        public_commands = sum(len(entry["commands"]) for entry in categories)
        latency_ms = round(getattr(ctx.bot, "latency", 0.0) * 1000)
        return (
            f"**Servers:** {humanize_number(guilds)}\n"
            f"**Users:** {humanize_number(unique_users)}\n"
            f"**Visible commands:** {humanize_number(public_commands)}\n"
            f"**Latency:** {latency_ms} ms"
        )

    def _server_stats(self, ctx: commands.Context) -> str:
        if not ctx.guild:
            return "**Context:** Direct messages\n**Tip:** Run this inside a server to see local stats."
        text_channels = len(getattr(ctx.guild, "text_channels", []))
        voice_channels = len(getattr(ctx.guild, "voice_channels", []))
        forum_channels = len(getattr(ctx.guild, "forums", [])) if hasattr(ctx.guild, "forums") else 0
        return (
            f"**Members:** {humanize_number(ctx.guild.member_count or 0)}\n"
            f"**Roles:** {humanize_number(len(ctx.guild.roles))}\n"
            f"**Text channels:** {humanize_number(text_channels)}\n"
            f"**Voice/forums:** {humanize_number(voice_channels + forum_channels)}"
        )

    async def home_embed(
        self,
        ctx: commands.Context,
        *,
        categories: list[dict],
        page: int = 0,
        page_size: int = 6,
        total_pages: int | None = None,
    ) -> discord.Embed:
        total_pages = total_pages or max(1, chunk_count(len(categories), page_size))
        embed = await self._base_embed(
            ctx,
            title="Vantage Help",
            description=(
                "Welcome to Vantage's help hub.\n"
                f"{self.divider}\n"
                "Page **1** is your dashboard. Use **<** and **>** to move through the public categories.\n"
                f"Search with `{ctx.clean_prefix}help search <query>`."
            ),
        )
        embed.add_field(name="Bot Overview", value=self._bot_stats(ctx, categories), inline=True)
        embed.add_field(name="This Server", value=self._server_stats(ctx), inline=True)
        embed.add_field(name=self.divider, value="**Public Categories**", inline=False)
        if categories:
            lines = []
            for offset, entry in enumerate(categories, start=2):
                label = self.category_label(entry["name"])
                lines.append(f"**{offset}. {label}**\n{self._category_summary(entry)}")
            embed.add_field(name="Browse with the buttons", value="\n\n".join(lines), inline=False)
        else:
            embed.add_field(name="Categories", value="No visible categories were found.", inline=False)
        embed.add_field(
            name="Quick Paths",
            value=(
                "Use the **<** and **>** buttons to browse public categories\n"
                f"`{ctx.clean_prefix}help <command>` • open a command directly\n"
                f"`{ctx.clean_prefix}help admin` • admin commands\n"
                f"`{ctx.clean_prefix}help owner` • bot owner commands"
            ),
            inline=False,
        )
        embed.set_footer(text=f"1/{total_pages} • {self.default_footer(ctx)}")
        return embed

    async def cog_embed(
        self,
        ctx: commands.Context,
        *,
        cog_name: str,
        description: str,
        commands_list: list[commands.Command],
        page: int = 0,
        page_size: int = 6,
        browser_page: int | None = None,
        browser_total: int | None = None,
    ) -> discord.Embed:
        total_pages = chunk_count(len(commands_list), page_size)
        page = max(0, min(page, total_pages - 1))
        current = chunk_slice(commands_list, page, page_size)
        embed = await self._base_embed(
            ctx,
            title=f"{cog_name}",
            description=(description or "No description provided.") + f"\n{self.divider}",
        )
        if current:
            lines = []
            for command in current:
                lines.append(
                    f"`{command.qualified_name}`\n{short_doc(command)}"
                )
            embed.add_field(name=f"Commands • Page {page + 1}/{total_pages}", value="\n\n".join(lines), inline=False)
        else:
            embed.add_field(name="Commands", value="No visible commands were found.", inline=False)
        embed.add_field(
            name="Open a Command",
            value=f"Use `{ctx.clean_prefix}help <command>` for the full command card.",
            inline=False,
        )
        footer_page = browser_page + 1 if browser_page is not None else page + 1
        footer_total = browser_total or total_pages
        embed.set_footer(text=f"{footer_page}/{footer_total} • {self.default_footer(ctx)}")
        return embed

    async def scoped_embed(
        self,
        ctx: commands.Context,
        *,
        scope: str,
        commands_list: list[commands.Command],
        page: int = 0,
        page_size: int = 6,
    ) -> discord.Embed:
        total_pages = chunk_count(len(commands_list), page_size)
        page = max(0, min(page, total_pages - 1))
        current = chunk_slice(commands_list, page, page_size)
        title = "Admin Commands" if scope == "admin" else "Owner Commands"
        description = (
            "Commands that need elevated server access."
            if scope == "admin"
            else "Commands reserved for bot owners."
        )
        embed = await self._base_embed(ctx, title=title, description=description + f"\n{self.divider}")
        if current:
            lines = []
            for command in current:
                lines.append(f"`{command.qualified_name}`\n{short_doc(command)}")
            embed.add_field(name=f"Commands • Page {page + 1}/{total_pages}", value="\n\n".join(lines), inline=False)
        else:
            embed.add_field(name="Commands", value="No visible commands were found.", inline=False)
        target_hint = f"{ctx.clean_prefix}help {scope} <command>"
        embed.add_field(name="Open a Command", value=f"Use `{target_hint}` for a detailed page.", inline=False)
        embed.set_footer(text=f"{page + 1}/{total_pages} • {self.default_footer(ctx)}")
        return embed

    async def command_embed(
        self,
        ctx: commands.Context,
        *,
        command: commands.Command,
        note: str | None = None,
        redirect_from: str | None = None,
        admin_context: bool = False,
    ) -> discord.Embed:
        description = (command.help or short_doc(command)).strip()
        embed = await self._base_embed(ctx, title=command.qualified_name, description=description)
        embed.add_field(name="How to Use It", value=box(command_signature(ctx.clean_prefix, command), lang=""), inline=False)
        details = [f"**Aliases:** {command_aliases(command)}"]
        if command.cog_name:
            details.append(f"**Category:** {command.cog_name}")
        if command.parent is not None:
            details.append(f"**Parent:** {command.parent.qualified_name}")
        scope = command_scope(command)
        if scope == "admin" or admin_context:
            details.append("**Access:** Admin-only / elevated command")
        elif scope == "owner":
            details.append("**Access:** Bot owner only")
        embed.add_field(name=self.divider, value="\n".join(details), inline=False)
        if redirect_from and redirect_from.casefold() != command.qualified_name.casefold():
            embed.add_field(
                name="Closest Match",
                value=f"I couldn't find `{redirect_from}`, so I opened `{command.qualified_name}` instead.",
                inline=False,
            )
        if note:
            embed.add_field(name="What Went Wrong?", value=note, inline=False)
        embed.set_footer(text=self.default_footer(ctx))
        return embed

    async def group_embed(
        self,
        ctx: commands.Context,
        *,
        command: commands.Group,
        subcommands: list[commands.Command],
        page: int = 0,
        page_size: int = 6,
        redirect_from: str | None = None,
    ) -> discord.Embed:
        total_pages = chunk_count(len(subcommands), page_size)
        page = max(0, min(page, total_pages - 1))
        current = chunk_slice(subcommands, page, page_size)
        embed = await self._base_embed(ctx, title=command.qualified_name, description=(command.help or short_doc(command)).strip())
        embed.add_field(name="How to Use It", value=box(command_signature(ctx.clean_prefix, command), lang=""), inline=False)
        embed.add_field(name=self.divider, value=f"**Aliases:** {command_aliases(command)}", inline=False)
        if redirect_from and redirect_from.casefold() != command.qualified_name.casefold():
            embed.add_field(name="Closest Match", value=f"I couldn't find `{redirect_from}`, so I opened `{command.qualified_name}` instead.", inline=False)
        if current:
            lines = []
            for subcommand in current:
                lines.append(f"`{subcommand.qualified_name}`\n{short_doc(subcommand)}")
            embed.add_field(name=f"Subcommands • Page {page + 1}/{total_pages}", value="\n\n".join(lines), inline=False)
        else:
            embed.add_field(name="Subcommands", value="No visible subcommands were found.", inline=False)
        embed.set_footer(text=f"{page + 1}/{total_pages} • {self.default_footer(ctx)}")
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
        best = results[0] if results else None
        embed = await self._base_embed(
            ctx,
            title=f"Help Search • {query}",
            description=(
                "Search across visible commands and categories.\n"
                f"{self.divider}"
            ),
        )
        if best:
            label = "Category" if best.kind == "cog" else "Command"
            embed.add_field(
                name="Closest Match",
                value=f"**{best.name}** • {label}\n{best.summary}",
                inline=False,
            )
        if current:
            lines = []
            for result in current:
                label = "Category" if result.kind == "cog" else "Command"
                lines.append(f"`{result.name}` • {label}\n{result.summary}")
            embed.add_field(name=f"Results • Page {page + 1}/{total_pages}", value="\n\n".join(lines), inline=False)
        else:
            embed.add_field(name="Results", value="No matching help topics were found.", inline=False)
        embed.set_footer(text=f"{page + 1}/{total_pages} • {self.default_footer(ctx)}")
        return embed

    async def not_found_embed(self, ctx: commands.Context, *, query: str, suggestions: Iterable[str] | None = None, note: str | None = None) -> discord.Embed:
        embed = await self._base_embed(ctx, title="Help Topic Not Found", description=f"I couldn't find a help topic for `{query}`.")
        if note:
            embed.add_field(name="Details", value=note, inline=False)
        if suggestions:
            embed.add_field(name="Closest Matches", value="\n".join(f"• `{entry}`" for entry in suggestions), inline=False)
        embed.set_footer(text=self.default_footer(ctx))
        return embed
