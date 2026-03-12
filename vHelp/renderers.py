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
        return f"Use {ctx.clean_prefix}help <command> for a detailed command page."

    def category_label(self, name: str | None) -> str:
        return name or "No Category"

    def _category_summary(self, entry: dict) -> str:
        desc = (entry.get("description") or "No description provided.").strip().splitlines()[0]
        return f"`{len(entry['commands'])}` command{'s' if len(entry['commands']) != 1 else ''} • {desc[:80]}"

    def _bot_stats(self, ctx: commands.Context, categories: list[dict]) -> str:
        guilds = len(getattr(ctx.bot, "guilds", []))
        unique_users = len(getattr(ctx.bot, "users", []))
        public_commands = sum(len(entry["commands"]) for entry in categories)
        latency_ms = round(getattr(ctx.bot, "latency", 0.0) * 1000)
        return (
            f"🏢 **Servers:** {humanize_number(guilds)}\n"
            f"👥 **Users:** {humanize_number(unique_users)}\n"
            f"⌨️ **Commands:** {humanize_number(public_commands)}\n"
            f"📶 **Latency:** {latency_ms} ms"
        )

    def _server_stats(self, ctx: commands.Context) -> str:
        if not ctx.guild:
            return "📨 **Context:** Direct messages\n💡 Run inside a server to see local stats."
        text_channels = len(getattr(ctx.guild, "text_channels", []))
        voice_channels = len(getattr(ctx.guild, "voice_channels", []))
        forum_channels = len(getattr(ctx.guild, "forums", [])) if hasattr(ctx.guild, "forums") else 0
        return (
            f"👤 **Members:** {humanize_number(ctx.guild.member_count or 0)}\n"
            f"🎭 **Roles:** {humanize_number(len(ctx.guild.roles))}\n"
            f"💬 **Text:** {humanize_number(text_channels)}\n"
            f"🔊 **Voice/Forums:** {humanize_number(voice_channels + forum_channels)}"
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

        is_owner = await ctx.bot.is_owner(ctx.author)
        is_admin = bool(ctx.guild and ctx.author.guild_permissions.administrator) or is_owner

        embed = await self._base_embed(
            ctx,
            title="📖 Vantage Help",
            description=(
                f"Welcome, **{ctx.author.display_name}**! Use the buttons below to browse commands.\n"
                f"{self.divider}\n"
                f"📄 Page **1** is your overview — use **<** and **>** to browse categories.\n"
                f"🔎 Search with `{ctx.clean_prefix}help search <query>`."
            ),
        )
        embed.add_field(name="📊 Bot Overview", value=self._bot_stats(ctx, categories), inline=True)
        embed.add_field(name="🏠 This Server", value=self._server_stats(ctx), inline=True)
        embed.add_field(name=self.divider, value="**📂 Public Categories**", inline=False)
        if categories:
            lines = []
            for offset, entry in enumerate(categories, start=2):
                label = self.category_label(entry["name"])
                lines.append(f"**{offset}. {label}**\n{self._category_summary(entry)}")
            embed.add_field(name="Browse using the navigation buttons", value="\n\n".join(lines), inline=False)
        else:
            embed.add_field(name="📂 Categories", value="No visible categories were found.", inline=False)

        quick_paths = [
            f"`{ctx.clean_prefix}help <command>` — open a specific command",
            f"`{ctx.clean_prefix}help <category>` — browse a category directly",
        ]
        if is_admin or is_owner:
            quick_paths.append(f"`{ctx.clean_prefix}help admin` — elevated/admin commands")
        if is_owner:
            quick_paths.append(f"`{ctx.clean_prefix}help owner` — bot owner commands")

        embed.add_field(name="🔍 Quick Paths", value="\n".join(quick_paths), inline=False)
        embed.set_footer(text=f"Page 1/{total_pages} • {self.default_footer(ctx)}")
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
            title=f"📂 {cog_name}",
            description=(description or "No description provided.").strip().splitlines()[0] + f"\n{self.divider}",
        )
        if current:
            lines = []
            for command in current:
                lines.append(f"• `{command.qualified_name}` — {short_doc(command)}")
            embed.add_field(
                name=f"⌨️ Commands — Page {page + 1}/{total_pages}",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(name="⌨️ Commands", value="No visible commands were found.", inline=False)
        embed.add_field(
            name="💡 How to open a command",
            value=f"`{ctx.clean_prefix}help <command>` — shows usage, aliases, and details.",
            inline=False,
        )
        footer_page = browser_page + 1 if browser_page is not None else page + 1
        footer_total = browser_total or total_pages
        embed.set_footer(text=f"Page {footer_page}/{footer_total} • {self.default_footer(ctx)}")
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
        if scope == "admin":
            title = "🛡️ Admin Commands"
            description = "These commands require elevated server permissions to use."
        else:
            title = "👑 Owner Commands"
            description = "These commands are reserved for the bot owner only."
        embed = await self._base_embed(ctx, title=title, description=description + f"\n{self.divider}")
        if current:
            lines = []
            for command in current:
                lines.append(f"• `{command.qualified_name}` — {short_doc(command)}")
            embed.add_field(
                name=f"⌨️ Commands — Page {page + 1}/{total_pages}",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(name="⌨️ Commands", value="No visible commands were found.", inline=False)
        target_hint = f"{ctx.clean_prefix}help {scope} <command>"
        embed.add_field(name="💡 Open a Command", value=f"`{target_hint}` — shows full details for a specific command.", inline=False)
        embed.set_footer(text=f"Page {page + 1}/{total_pages} • {self.default_footer(ctx)}")
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
        embed = await self._base_embed(ctx, title=f"⌨️ {command.qualified_name}", description=description)
        embed.add_field(
            name="📋 Usage",
            value=box(command_signature(ctx.clean_prefix, command), lang=""),
            inline=False,
        )
        details = []
        aliases = command_aliases(command)
        if aliases != "No aliases.":
            details.append(f"**Aliases:** {aliases}")
        if command.cog_name:
            details.append(f"**Category:** {command.cog_name}")
        if command.parent is not None:
            details.append(f"**Parent command:** `{command.parent.qualified_name}`")
        scope = command_scope(command)
        if scope == "admin" or admin_context:
            details.append("**Access:** 🛡️ Requires elevated/admin permissions")
        elif scope == "owner":
            details.append("**Access:** 👑 Bot owner only")
        if details:
            embed.add_field(name="ℹ️ Details", value="\n".join(details), inline=False)
        if redirect_from and redirect_from.casefold() != command.qualified_name.casefold():
            embed.add_field(
                name="🔀 Closest Match",
                value=f"No exact match for `{redirect_from}` — showing `{command.qualified_name}` instead.",
                inline=False,
            )
        if note:
            embed.add_field(name="⚠️ Usage Issue", value=note, inline=False)
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
        embed = await self._base_embed(
            ctx,
            title=f"⌨️ {command.qualified_name}",
            description=(command.help or short_doc(command)).strip(),
        )
        embed.add_field(
            name="📋 Usage",
            value=box(command_signature(ctx.clean_prefix, command), lang=""),
            inline=False,
        )
        aliases = command_aliases(command)
        if aliases != "No aliases.":
            embed.add_field(name="ℹ️ Aliases", value=aliases, inline=False)
        if redirect_from and redirect_from.casefold() != command.qualified_name.casefold():
            embed.add_field(
                name="🔀 Closest Match",
                value=f"No exact match for `{redirect_from}` — showing `{command.qualified_name}` instead.",
                inline=False,
            )
        if current:
            lines = []
            for subcommand in current:
                lines.append(f"• `{subcommand.qualified_name}` — {short_doc(subcommand)}")
            embed.add_field(
                name=f"📂 Subcommands — Page {page + 1}/{total_pages}",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(name="📂 Subcommands", value="No visible subcommands were found.", inline=False)
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
        best = results[0] if results else None
        embed = await self._base_embed(
            ctx,
            title=f"🔎 Search Results — {query}",
            description=(
                f"Found **{len(results)}** result{'s' if len(results) != 1 else ''} matching `{query}`.\n"
                f"{self.divider}"
            ),
        )
        if best:
            kind_label = "📂 Category" if best.kind == "cog" else "⌨️ Command"
            embed.add_field(
                name="⭐ Best Match",
                value=f"{kind_label} — `{best.name}`\n{best.summary}",
                inline=False,
            )
        if current:
            lines = []
            for result in current:
                kind_label = "📂" if result.kind == "cog" else "⌨️"
                lines.append(f"{kind_label} `{result.name}` — {result.summary}")
            embed.add_field(
                name=f"📋 Results — Page {page + 1}/{total_pages}",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(name="📋 Results", value="No matching topics were found.", inline=False)
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
        embed = discord.Embed(
            title="❓ Help Topic Not Found",
            description=(
                f"No command, category, or alias matched `{query}`.\n"
                f"Try a shorter search term or check your spelling."
            ),
            color=discord.Color.orange(),
        )
        if ctx.me:
            embed.set_author(name=f"{ctx.me.display_name} Help", icon_url=ctx.me.display_avatar.url)
        if note:
            embed.add_field(name="ℹ️ Details", value=note, inline=False)
        if suggestions:
            suggestion_list = list(suggestions)
            if suggestion_list:
                embed.add_field(
                    name="💡 Did you mean…",
                    value="\n".join(f"• `{entry}`" for entry in suggestion_list),
                    inline=False,
                )
        embed.add_field(
            name="🔎 Search Instead",
            value=f"`{ctx.clean_prefix}help search {query}` — try a fuzzy search.",
            inline=False,
        )
        embed.set_footer(text=self.default_footer(ctx))
        return embed
