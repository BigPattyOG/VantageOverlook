"""Main cog for the VHelp system."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Iterable

import discord

from redbot.core import Config, commands
from redbot.core.bot import Red

from .formatter import VHelpFormatter
from .renderers import HelpRenderer
from .utils import (
    BAD_USAGE_ERRORS,
    SearchResult,
    SuggestionBundle,
    cog_search_score,
    command_search_score,
    normalize,
    short_doc,
)

log = logging.getLogger("red.vhelp")


@dataclass(slots=True)
class _RedirectTarget:
    """Internal helper for redirecting ambiguous help lookups."""

    original: str
    target: object


class VHelp(commands.Cog):
    """Custom help formatter with button navigation, smart lookup, and search."""

    default_global_settings = {
        "menu_timeout": 180,
        "home_page_size": 8,
        "cog_page_size": 6,
        "group_page_size": 6,
        "search_limit": 8,
        "suggestion_count": 5,
        "fuzzy_enabled": True,
        "autocorrect_enabled": True,
    }

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=7801152201, force_registration=True)
        self.config.register_global(**self.default_global_settings)

        self.renderer = HelpRenderer(self)
        self.formatter = VHelpFormatter(self)

        self.menu_timeout = 180
        self.home_page_size = 8
        self.cog_page_size = 6
        self.group_page_size = 6
        self.search_limit = 8
        self.suggestion_count = 5
        self.fuzzy_enabled = True
        self.autocorrect_enabled = True
        self._formatter_active = False
        self.command_index: list[dict] = []
        self.cog_index: list[dict] = []

    async def cog_load(self) -> None:
        self.menu_timeout = await self.config.menu_timeout()
        self.home_page_size = await self.config.home_page_size()
        self.cog_page_size = await self.config.cog_page_size()
        self.group_page_size = await self.config.group_page_size()
        self.search_limit = await self.config.search_limit()
        self.suggestion_count = await self.config.suggestion_count()
        self.fuzzy_enabled = await self.config.fuzzy_enabled()
        self.autocorrect_enabled = await self.config.autocorrect_enabled()
        self.rebuild_index()

        try:
            self.bot.set_help_formatter(self.formatter)
        except RuntimeError:
            log.exception("A custom help formatter is already active; VHelp could not replace it.")
        else:
            self._formatter_active = True

    def cog_unload(self) -> None:
        if self._formatter_active:
            try:
                self.bot.reset_help_formatter()
            except Exception:
                log.exception("Failed to reset Red's help formatter during unload.")

    def rebuild_index(self) -> None:
        """Rebuild the cached help metadata.

        This is intentionally lightweight. Visibility still gets checked at
        request time so access changes are respected.
        """
        self.command_index = []
        self.cog_index = []

        for command in self.bot.walk_commands():
            self.command_index.append(
                {
                    "qualified_name": command.qualified_name,
                    "name": command.name,
                    "aliases": list(command.aliases),
                    "summary": short_doc(command),
                    "help": (command.help or "").strip(),
                    "cog_name": command.cog_name,
                    "object": command,
                }
            )

        for cog_name, cog in self.bot.cogs.items():
            description = ""
            if hasattr(cog, "format_help_for_context"):
                try:
                    description = (cog.format_help_for_context(SimpleNamespace(clean_prefix="")) or "").strip()
                except Exception:
                    description = ""
            self.cog_index.append(
                {
                    "name": cog_name,
                    "description": description,
                    "object": cog,
                }
            )

    async def filter_visible_commands(
        self,
        ctx: commands.Context,
        commands_iterable: Iterable[commands.Command],
    ) -> list[commands.Command]:
        visible: list[commands.Command] = []
        for command in commands_iterable:
            if command.hidden:
                continue
            if not getattr(command, "enabled", True):
                continue
            try:
                allowed = await command.can_see(ctx)
            except Exception:
                allowed = False
            if allowed:
                visible.append(command)
        return sorted(visible, key=lambda c: c.qualified_name.casefold())

    async def collect_categories(self, ctx: commands.Context) -> list[dict]:
        categories: list[dict] = []

        for cog_name, cog in sorted(ctx.bot.cogs.items(), key=lambda item: item[0].casefold()):
            root_commands = [cmd for cmd in ctx.bot.commands if cmd.cog is cog and cmd.parent is None]
            visible = await self.filter_visible_commands(ctx, root_commands)
            if not visible:
                continue

            description = ""
            if hasattr(cog, "format_help_for_context"):
                try:
                    description = (cog.format_help_for_context(ctx) or "").strip()
                except Exception:
                    description = ""
            categories.append(
                {
                    "name": cog_name,
                    "description": description or f"Commands in {cog_name}.",
                    "commands": visible,
                    "cog": cog,
                }
            )

        uncategorized = [cmd for cmd in ctx.bot.commands if cmd.cog is None and cmd.parent is None]
        uncategorized_visible = await self.filter_visible_commands(ctx, uncategorized)
        if uncategorized_visible:
            categories.append(
                {
                    "name": None,
                    "description": "Commands not attached to a cog.",
                    "commands": uncategorized_visible,
                    "cog": None,
                }
            )
        return categories

    async def visible_help_names(self, ctx: commands.Context) -> list[str]:
        names: set[str] = set()
        categories = await self.collect_categories(ctx)
        for category in categories:
            if category["name"]:
                names.add(category["name"])
            for command in category["commands"]:
                names.add(command.qualified_name)
                names.add(command.name)
                names.update(command.aliases)
        return sorted(names, key=str.casefold)

    async def build_suggestions(self, ctx: commands.Context, query: str) -> SuggestionBundle:
        results = await self.search_help(ctx, query, limit=self.suggestion_count)
        suggestions = [result.name for result in results[: self.suggestion_count]]
        best_match = results[0].object_ref if results else None
        best_score = results[0].score if results else 0.0
        return SuggestionBundle(suggestions=suggestions, best_match=best_match, best_score=best_score)

    async def resolve_help_target(self, ctx: commands.Context, query: str):
        query = query.strip()
        if not query:
            return None

        direct = ctx.bot.get_command(query)
        if direct is not None:
            try:
                if await direct.can_see(ctx):
                    return direct
            except Exception:
                pass

        lowered = normalize(query)

        # Exact name / alias lookup from the cached command index.
        for entry in self.command_index:
            names = [entry["qualified_name"], entry["name"], *entry["aliases"]]
            if lowered in {normalize(name) for name in names}:
                command = entry["object"]
                try:
                    if await command.can_see(ctx):
                        return command
                except Exception:
                    continue

        # Exact cog lookup.
        for entry in self.cog_index:
            if normalize(entry["name"]) == lowered:
                categories = await self.collect_categories(ctx)
                for category in categories:
                    if normalize(category["name"] or "") == lowered:
                        return entry["object"]

        # Fall back to search-based suggestions/autocorrect.
        results = await self.search_help(ctx, query, limit=max(self.search_limit, self.suggestion_count))
        if not results:
            return None

        best = results[0]
        if self.autocorrect_enabled and best.score >= 120:
            return _RedirectTarget(original=query, target=best.object_ref)
        return None

    async def search_help(self, ctx: commands.Context, query: str, *, limit: int | None = None) -> list[SearchResult]:
        limit = limit or self.search_limit
        results: list[SearchResult] = []
        normalized_query = normalize(query)
        if not normalized_query:
            return results

        for entry in self.command_index:
            command = entry["object"]
            try:
                visible = await command.can_see(ctx)
            except Exception:
                visible = False
            if not visible or command.hidden:
                continue

            score = command_search_score(normalized_query, command, fuzzy=self.fuzzy_enabled)
            if score <= 0:
                continue
            results.append(
                SearchResult(
                    kind="command",
                    name=command.qualified_name,
                    score=score,
                    object_ref=command,
                    summary=entry["summary"],
                )
            )

        categories = await self.collect_categories(ctx)
        for category in categories:
            name = category["name"] or "No Category"
            score = cog_search_score(normalized_query, name, category["description"], fuzzy=self.fuzzy_enabled)
            if score <= 0:
                continue
            results.append(
                SearchResult(
                    kind="cog",
                    name=name,
                    score=score,
                    object_ref=category["cog"],
                    summary=category["description"],
                )
            )

        # Deduplicate by name while keeping the best score.
        deduped: dict[str, SearchResult] = {}
        for result in results:
            current = deduped.get(result.name.casefold())
            if current is None or result.score > current.score:
                deduped[result.name.casefold()] = result

        ordered = sorted(deduped.values(), key=lambda item: (-item.score, item.name.casefold()))
        return ordered[:limit]

    def _has_custom_error_handler(self, ctx: commands.Context) -> bool:
        command = ctx.command
        if command is None:
            return False
        if getattr(command, "has_error_handler", lambda: False)():
            return True
        cog = ctx.cog
        if cog is not None and getattr(cog, "has_error_handler", lambda: False)():
            return True
        return False

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        if ctx.command is None:
            return
        if self._has_custom_error_handler(ctx):
            return
        if isinstance(error, commands.CommandNotFound):
            return

        original = getattr(error, "original", error)
        if not isinstance(original, BAD_USAGE_ERRORS):
            return

        try:
            if not await ctx.command.can_see(ctx):
                return
        except Exception:
            return

        note: str | None = None
        if isinstance(original, commands.MissingRequiredArgument):
            note = f"Missing required argument: `{original.param.name}`"
        elif isinstance(original, commands.TooManyArguments):
            note = "Too many arguments were given."
        else:
            note = str(original) or "That command usage was invalid."

        embed = await self.renderer.command_embed(ctx, command=ctx.command, note=note)
        await ctx.send(embed=embed)

    @commands.command(name="helpsearch", aliases=["hsearch", "searchhelp"])
    async def helpsearch(self, ctx: commands.Context, *, query: str) -> None:
        """Search commands, command groups, aliases, and categories."""
        results = await self.search_help(ctx, query, limit=self.search_limit)
        if not results:
            bundle = await self.build_suggestions(ctx, query)
            embed = await self.renderer.not_found_embed(
                ctx,
                query=query,
                suggestions=bundle.suggestions,
                note="No search results were found.",
            )
            await ctx.send(embed=embed)
            return

        if len(results) == 1 and results[0].score >= 120:
            target = results[0].object_ref
            if isinstance(target, commands.Cog):
                await self.formatter._send_cog(ctx, target)
                return
            if isinstance(target, commands.Group):
                await self.formatter._send_group(ctx, target, redirect_from=query)
                return
            await self.formatter._send_command(ctx, target, redirect_from=query)
            return

        embed = await self.renderer.search_results_embed(
            ctx,
            query=query,
            results=results,
            page=0,
            page_size=self.cog_page_size,
        )
        await ctx.send(embed=embed)

    @commands.group(name="vhelpset", invoke_without_command=True)
    @commands.is_owner()
    async def vhelpset(self, ctx: commands.Context) -> None:
        """Owner-only settings for VHelp."""
        await ctx.send_help()

    @vhelpset.command(name="status")
    @commands.is_owner()
    async def vhelpset_status(self, ctx: commands.Context) -> None:
        """Show current VHelp settings."""
        lines = [
            f"Formatter active: `{self._formatter_active}`",
            f"Menu timeout: `{self.menu_timeout}` seconds",
            f"Home page size: `{self.home_page_size}`",
            f"Cog page size: `{self.cog_page_size}`",
            f"Group page size: `{self.group_page_size}`",
            f"Search limit: `{self.search_limit}`",
            f"Suggestion count: `{self.suggestion_count}`",
            f"Fuzzy matching: `{self.fuzzy_enabled}`",
            f"Autocorrect: `{self.autocorrect_enabled}`",
            f"Indexed commands: `{len(self.command_index)}`",
            f"Indexed cogs: `{len(self.cog_index)}`",
        ]
        await ctx.send("\n".join(lines))

    @vhelpset.command(name="timeout")
    @commands.is_owner()
    async def vhelpset_timeout(self, ctx: commands.Context, seconds: commands.Range[int, 30, 600]) -> None:
        """Set how long help menus stay active."""
        await self.config.menu_timeout.set(seconds)
        self.menu_timeout = seconds
        await ctx.send(f"Help menu timeout set to `{seconds}` seconds.")

    @vhelpset.command(name="pagesize")
    @commands.is_owner()
    async def vhelpset_pagesize(self, ctx: commands.Context, number: commands.Range[int, 3, 20]) -> None:
        """Set command results per page for category and search pages."""
        await self.config.cog_page_size.set(number)
        await self.config.group_page_size.set(number)
        self.cog_page_size = number
        self.group_page_size = number
        await ctx.send(f"Category and group page size set to `{number}`.")

    @vhelpset.command(name="homepagesize")
    @commands.is_owner()
    async def vhelpset_homepagesize(self, ctx: commands.Context, number: commands.Range[int, 3, 15]) -> None:
        """Set how many categories appear on each help home page."""
        await self.config.home_page_size.set(number)
        self.home_page_size = number
        await ctx.send(f"Home page size set to `{number}`.")

    @vhelpset.command(name="searchlimit")
    @commands.is_owner()
    async def vhelpset_searchlimit(self, ctx: commands.Context, number: commands.Range[int, 3, 20]) -> None:
        """Set the maximum number of search results to show."""
        await self.config.search_limit.set(number)
        self.search_limit = number
        await ctx.send(f"Search result limit set to `{number}`.")

    @vhelpset.command(name="suggestions")
    @commands.is_owner()
    async def vhelpset_suggestions(self, ctx: commands.Context, number: commands.Range[int, 1, 10]) -> None:
        """Set how many suggestions are shown for unknown help topics."""
        await self.config.suggestion_count.set(number)
        self.suggestion_count = number
        await ctx.send(f"Suggestion count set to `{number}`.")

    @vhelpset.command(name="fuzzy")
    @commands.is_owner()
    async def vhelpset_fuzzy(self, ctx: commands.Context, enabled: bool) -> None:
        """Enable or disable fuzzy matching for help search."""
        await self.config.fuzzy_enabled.set(enabled)
        self.fuzzy_enabled = enabled
        await ctx.send(f"Fuzzy matching is now `{enabled}`.")

    @vhelpset.command(name="autocorrect")
    @commands.is_owner()
    async def vhelpset_autocorrect(self, ctx: commands.Context, enabled: bool) -> None:
        """Enable or disable automatic redirecting to strong help matches."""
        await self.config.autocorrect_enabled.set(enabled)
        self.autocorrect_enabled = enabled
        await ctx.send(f"Autocorrect is now `{enabled}`.")

    @vhelpset.command(name="rebuild")
    @commands.is_owner()
    async def vhelpset_rebuild(self, ctx: commands.Context) -> None:
        """Rebuild the cached help index."""
        self.rebuild_index()
        await ctx.send(
            f"Help index rebuilt. Cached `{len(self.command_index)}` commands across `{len(self.cog_index)}` cogs."
        )
