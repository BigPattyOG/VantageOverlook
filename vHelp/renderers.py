"""Embed rendering helpers for VHelp."""

from __future__ import annotations

from typing import Iterable

import discord

from redbot.core import commands
from redbot.core.utils.chat_formatting import box, humanize_number

from .utils import chunk_count, chunk_slice, command_aliases, command_scope, command_signature, short_doc

# ── Palette ───────────────────────────────────────────────────────────────────
_COLOR_DEFAULT = discord.Color.from_rgb(88, 101, 242)   # Blurple-ish
_COLOR_CATEGORY = discord.Color.from_rgb(57, 197, 187)  # Teal
_COLOR_COMMAND = discord.Color.from_rgb(87, 242, 135)   # Green
_COLOR_SEARCH = discord.Color.from_rgb(254, 231, 92)    # Yellow
_COLOR_ADMIN = discord.Color.from_rgb(240, 71, 71)      # Red
_COLOR_OWNER = discord.Color.from_rgb(155, 89, 182)     # Purple
_COLOR_NOT_FOUND = discord.Color.from_rgb(237, 66, 69)  # Error red

# ── Formatting constants ───────────────────────────────────────────────────────
_DIVIDER = "─" * 30
_BULLET = "›"
_TICK = "✔"


class HelpRenderer:
    accent_color = _COLOR_DEFAULT
    divider = _DIVIDER

    def __init__(self, cog: commands.Cog):
        self.cog = cog

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _base_embed(
        self,
        ctx: commands.Context,
        *,
        title: str,
        description: str,
        color: discord.Color | None = None,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=title,
            description=description,
            color=color or self.accent_color,
        )
        if ctx.me:
            embed.set_author(
                name=f"{ctx.me.display_name} — Help",
                icon_url=ctx.me.display_avatar.url,
            )
        return embed

    def default_footer(self, ctx: commands.Context, *, extra: str = "") -> str:
        base = f"Tip: {ctx.clean_prefix}help <command> for details  •  Use the 🔍 Search button to find anything"
        return f"{base}  •  {extra}" if extra else base

    def category_label(self, name: str | None) -> str:
        return name or "No Category"

    def _category_summary(self, entry: dict) -> str:
        count = len(entry["commands"])
        desc = (entry.get("description") or "No description provided.").strip().splitlines()[0][:70]
        return f"`{count}` cmd{'s' if count != 1 else ''}  —  {desc}"

    def _relevance_bar(self, score: float, *, max_length: int = 10) -> str:
        """Return a simple block-character bar representing a relevance score."""
        filled = min(max_length, max(1, int(score / 15)))
        return "█" * filled + "░" * (max_length - filled)

    def _bot_stats(self, ctx: commands.Context, categories: list[dict]) -> str:
        guilds = len(getattr(ctx.bot, "guilds", []))
        unique_users = len(getattr(ctx.bot, "users", []))
        public_commands = sum(len(entry["commands"]) for entry in categories)
        latency_ms = round(getattr(ctx.bot, "latency", 0.0) * 1000)
        return (
            f"🏢 **Servers:** {humanize_number(guilds)}\n"
            f"👥 **Users:** {humanize_number(unique_users)}\n"
            f"⌨️ **Commands:** {humanize_number(public_commands)}\n"
            f"📶 **Ping:** {latency_ms} ms"
        )

    def _server_stats(self, ctx: commands.Context) -> str:
        if not ctx.guild:
            return "📨 **DMs** — running in direct messages.\n💡 Invite me to a server for full access."
        text_channels = len(getattr(ctx.guild, "text_channels", []))
        voice_channels = len(getattr(ctx.guild, "voice_channels", []))
        forum_channels = len(getattr(ctx.guild, "forums", [])) if hasattr(ctx.guild, "forums") else 0
        return (
            f"👤 **Members:** {humanize_number(ctx.guild.member_count or 0)}\n"
            f"🎭 **Roles:** {humanize_number(len(ctx.guild.roles))}\n"
            f"💬 **Text:** {humanize_number(text_channels)}\n"
            f"🔊 **Voice/Forums:** {humanize_number(voice_channels + forum_channels)}"
        )

    # ── Public embed builders ──────────────────────────────────────────────────

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

        prefix = ctx.clean_prefix

        embed = await self._base_embed(
            ctx,
            title="📖  Help — Overview",
            description=(
                f"Hey **{ctx.author.display_name}**, welcome to the interactive help menu!\n"
                f"`{prefix}help <command>` · `{prefix}help <category>` · **🔍 Search** button\n"
                f"{_DIVIDER}\n"
                f"Use **⏮️ ⏭️** to flip pages, the **📂 dropdown** to jump to a category,\n"
                f"or the **🔍 Search** button to find anything by keyword."
            ),
            color=_COLOR_DEFAULT,
        )

        if ctx.me:
            embed.set_thumbnail(url=ctx.me.display_avatar.url)

        embed.add_field(name="📊 Bot Stats", value=self._bot_stats(ctx, categories), inline=True)
        embed.add_field(name="🏠 Server Stats", value=self._server_stats(ctx), inline=True)

        if categories:
            lines: list[str] = []
            for entry in categories:
                label = self.category_label(entry["name"])
                cmd_count = len(entry["commands"])
                desc_first = (entry.get("description") or "").strip().splitlines()[0][:60]
                lines.append(f"**{label}** `{cmd_count} cmd{'s' if cmd_count != 1 else ''}`\n{_BULLET} {desc_first or 'No description.'}")
            embed.add_field(
                name=f"{_DIVIDER}\n📂  Categories  ({len(categories)} total)",
                value="\n\n".join(lines) or "No categories available.",
                inline=False,
            )
        else:
            embed.add_field(name="📂 Categories", value="No visible categories were found.", inline=False)

        quick_paths: list[str] = [
            f"`{prefix}help <command>` — detailed command page",
            f"`{prefix}help <category>` — browse a category",
        ]
        if is_admin or is_owner:
            quick_paths.append(f"`{prefix}help admin` — admin/elevated commands")
        if is_owner:
            quick_paths.append(f"`{prefix}help owner` — bot-owner commands")

        embed.add_field(name="🔍 Quick Access", value="\n".join(quick_paths), inline=False)
        embed.set_footer(text=f"Page 1/{total_pages}  •  Use the dropdown or search to navigate quickly.")
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
            title=f"📂  {cog_name}",
            description=(
                (description or "No description provided.").strip().splitlines()[0]
                + f"\n{_DIVIDER}"
            ),
            color=_COLOR_CATEGORY,
        )

        if current:
            lines = [
                f"**`{cmd.qualified_name}`**\n{_BULLET} {short_doc(cmd)}"
                for cmd in current
            ]
            embed.add_field(
                name=f"⌨️  Commands  (page {page + 1}/{total_pages})",
                value="\n\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(name="⌨️ Commands", value="No visible commands on this page.", inline=False)

        embed.add_field(
            name="💡 Tip",
            value=f"`{ctx.clean_prefix}help <command>` — shows full usage, aliases and details.",
            inline=False,
        )

        footer_page = (browser_page + 1) if browser_page is not None else (page + 1)
        footer_total = browser_total or total_pages
        embed.set_footer(text=f"Page {footer_page}/{footer_total}  •  {len(commands_list)} command(s) in {cog_name}")
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
            title = "🛡️  Admin Commands"
            description = "Commands that require elevated server permissions."
            color = _COLOR_ADMIN
        else:
            title = "👑  Owner Commands"
            description = "Commands reserved exclusively for the bot owner."
            color = _COLOR_OWNER

        embed = await self._base_embed(
            ctx,
            title=title,
            description=description + f"\n{_DIVIDER}",
            color=color,
        )

        if current:
            lines = [
                f"**`{cmd.qualified_name}`**\n{_BULLET} {short_doc(cmd)}"
                for cmd in current
            ]
            embed.add_field(
                name=f"⌨️  Commands  (page {page + 1}/{total_pages})",
                value="\n\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(name="⌨️ Commands", value="No visible commands on this page.", inline=False)

        hint = f"{ctx.clean_prefix}help {scope} <command>"
        embed.add_field(name="💡 Tip", value=f"`{hint}` — full detail for any command listed above.", inline=False)
        embed.set_footer(text=f"Page {page + 1}/{total_pages}  •  {len(commands_list)} command(s) in this scope")
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
        scope = command_scope(command)
        if scope == "owner":
            color = _COLOR_OWNER
        elif scope == "admin" or admin_context:
            color = _COLOR_ADMIN
        else:
            color = _COLOR_COMMAND

        full_description = (command.help or short_doc(command)).strip()

        embed = await self._base_embed(
            ctx,
            title=f"⌨️  {command.qualified_name}",
            description=full_description,
            color=color,
        )

        embed.add_field(
            name="📋 Usage",
            value=box(command_signature(ctx.clean_prefix, command), lang=""),
            inline=False,
        )

        details: list[str] = []
        aliases = command_aliases(command)
        if aliases != "No aliases.":
            details.append(f"**Aliases:** {aliases}")
        if command.cog_name:
            details.append(f"**Category:** `{command.cog_name}`")
        if command.parent is not None:
            details.append(f"**Parent:** `{command.parent.qualified_name}`")
        if scope == "admin" or admin_context:
            details.append("**Access:** 🛡️ Requires elevated permissions")
        elif scope == "owner":
            details.append("**Access:** 👑 Bot owner only")
        else:
            details.append("**Access:** 🌐 Public")

        if details:
            embed.add_field(name="ℹ️ Details", value="\n".join(details), inline=False)

        if redirect_from and redirect_from.casefold() != command.qualified_name.casefold():
            embed.add_field(
                name="🔀 Redirected",
                value=f"No exact match for `{redirect_from}` — showing closest: `{command.qualified_name}`",
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
            title=f"⌨️  {command.qualified_name}",
            description=(command.help or short_doc(command)).strip(),
            color=_COLOR_COMMAND,
        )

        embed.add_field(
            name="📋 Usage",
            value=box(command_signature(ctx.clean_prefix, command), lang=""),
            inline=False,
        )

        aliases = command_aliases(command)
        if aliases != "No aliases.":
            embed.add_field(name="ℹ️ Aliases", value=aliases, inline=False)

        if command.cog_name:
            embed.add_field(name="📂 Category", value=f"`{command.cog_name}`", inline=False)

        if redirect_from and redirect_from.casefold() != command.qualified_name.casefold():
            embed.add_field(
                name="🔀 Redirected",
                value=f"No exact match for `{redirect_from}` — showing: `{command.qualified_name}`",
                inline=False,
            )

        if current:
            lines = [
                f"**`{sub.qualified_name}`**\n{_BULLET} {short_doc(sub)}"
                for sub in current
            ]
            embed.add_field(
                name=f"📂  Subcommands  (page {page + 1}/{total_pages})",
                value="\n\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(name="📂 Subcommands", value="No visible subcommands.", inline=False)

        embed.set_footer(text=f"Page {page + 1}/{total_pages}  •  {len(subcommands)} subcommand(s)")
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
            title=f"🔎  Search — {query!r}",
            description=(
                f"Found **{len(results)}** result{'s' if len(results) != 1 else ''}.\n"
                f"Use **⭐ Best Match** below to jump straight to the top result.\n"
                f"{_DIVIDER}"
            ),
            color=_COLOR_SEARCH,
        )

        if best:
            kind_label = "📂 Category" if best.kind == "cog" else "⌨️ Command"
            score_bar = self._relevance_bar(best.score)
            embed.add_field(
                name="⭐ Top Result",
                value=(
                    f"{kind_label} — **`{best.name}`**\n"
                    f"{_BULLET} {best.summary}\n"
                    f"Relevance: `{score_bar}`"
                ),
                inline=False,
            )

        if current:
            lines: list[str] = []
            for i, result in enumerate(current, start=page * page_size + 1):
                kind_emoji = "📂" if result.kind == "cog" else "⌨️"
                lines.append(f"**{i}.** {kind_emoji} `{result.name}` — {result.summary}")
            embed.add_field(
                name=f"📋  All Results  (page {page + 1}/{total_pages})",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(name="📋 Results", value="Nothing matched that search.", inline=False)

        embed.add_field(
            name="💡 Tip",
            value=(
                f"`{ctx.clean_prefix}help search <query>` — search from the command line\n"
                f"Use the **🔍 Search** button to run another search."
            ),
            inline=False,
        )
        embed.set_footer(text=f"Page {page + 1}/{total_pages}  •  Results for: {query}")
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
            title="❓  Nothing Found",
            description=(
                f"No command, category, or alias matched **`{query}`**.\n"
                f"Check your spelling or try a shorter search term."
            ),
            color=_COLOR_NOT_FOUND,
        )
        if ctx.me:
            embed.set_author(
                name=f"{ctx.me.display_name} — Help",
                icon_url=ctx.me.display_avatar.url,
            )

        if note:
            embed.add_field(name="ℹ️ Note", value=note, inline=False)

        if suggestions:
            suggestion_list = list(suggestions)
            if suggestion_list:
                embed.add_field(
                    name="💡 Did you mean…",
                    value="\n".join(f"{_BULLET} `{entry}`" for entry in suggestion_list),
                    inline=False,
                )

        embed.add_field(
            name="🔎 Try a Search",
            value=(
                f"`{ctx.clean_prefix}help search {query}` — fuzzy search across all commands and categories\n"
                f"Or use the **🔍 Search** button in the interactive help menu (`{ctx.clean_prefix}help`)."
            ),
            inline=False,
        )
        embed.set_footer(text=self.default_footer(ctx))
        return embed
