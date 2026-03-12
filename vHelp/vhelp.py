"""Main cog for the VHelp system."""

from __future__ import annotations

import logging
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
    command_scope,
    command_search_score,
    is_admin_command,
    is_owner_command,
    normalize,
    short_doc,
)
from .views import HelpNavigator

try:
    from verrors.decorators import error_family, error_meta, error_slot
except Exception:
    def error_family(*args, **kwargs):
        def deco(cls):
            return cls
        return deco

    def error_meta(**kwargs):
        def deco(func):
            return func
        return deco

    def error_slot(slot: str):
        def deco(func):
            return func
        return deco

try:
    from verrors.utils import (
        fixable_error_reply as verrors_fixable_error_reply,
        internal_lookup_embed as verrors_internal_lookup_embed,
        public_code_for_error as verrors_public_code_for_error,
        resolve_system_prefix as verrors_resolve_system_prefix,
    )
except Exception:
    verrors_fixable_error_reply = None
    verrors_internal_lookup_embed = None
    verrors_public_code_for_error = None
    verrors_resolve_system_prefix = None


log = logging.getLogger("red.vhelp")


@error_family("HP", name="Help")
class VHelp(commands.Cog):
    """Custom help formatter with scoped admin/owner help and VErrors integration."""

    default_global_settings = {
        "menu_timeout": 180,
        "home_page_size": 6,
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
        self.home_page_size = 6
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
                    "scope": self.command_scope(command),
                    "is_admin": self.command_is_admin(command),
                    "is_owner": self.command_is_owner(command),
                }
            )
        for cog_name, cog in self.bot.cogs.items():
            description = ""
            if hasattr(cog, "format_help_for_context"):
                try:
                    description = (cog.format_help_for_context(SimpleNamespace(clean_prefix="")) or "").strip()
                except Exception:
                    description = ""
            self.cog_index.append({"name": cog_name, "description": description, "object": cog})

    def command_is_admin(self, command: commands.Command) -> bool:
        return is_admin_command(command)

    def command_is_owner(self, command: commands.Command) -> bool:
        return is_owner_command(command)

    def command_scope(self, command: commands.Command) -> str:
        return command_scope(command)

    def extract_scope(self, query: str) -> tuple[str, str] | None:
        normalized = normalize(query)
        for scope in ("admin", "owner"):
            if normalized == scope:
                return scope, ""
            if normalized.startswith(f"{scope} "):
                return scope, query.split(maxsplit=1)[1].strip()
        return None

    def _get_verrors(self):
        return self.bot.get_cog("VErrors")

    async def send_internal_error_for_context(self, ctx: commands.Context, error: Exception, *, source: str) -> None:
        verrors = self._get_verrors()
        if verrors is not None:
            system = verrors.get_system_prefix(ctx) if hasattr(verrors, "get_system_prefix") else (verrors_resolve_system_prefix(ctx) if verrors_resolve_system_prefix is not None else "VH")
            await verrors.reporter.report_command_exception(ctx, error, system)
            return
        log.exception("Internal VHelp error (%s)", source, exc_info=error)
        await ctx.send("Something went wrong while building that help page.")

    async def send_internal_error_for_interaction(self, interaction: discord.Interaction, error: Exception, *, item=None) -> None:
        verrors = self._get_verrors()
        if verrors is None:
            log.exception("Internal VHelp interaction error", exc_info=error)
            return
        code = await verrors.report_interaction_error(
            interaction=interaction,
            error=error,
            system="VH",
            command_name="help",
            location="vhelp-view",
        )
        embed = verrors.build_internal_lookup_embed(code) if hasattr(verrors, "build_internal_lookup_embed") else (verrors_internal_lookup_embed(code) if verrors_internal_lookup_embed is not None else discord.Embed(
            title="Internal Error",
            description=f"Error `{code}` occurred.",
            color=discord.Color.red(),
        ))
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException:
            pass

    async def filter_visible_commands(self, ctx: commands.Context, commands_iterable: Iterable[commands.Command]) -> list[commands.Command]:
        visible = []
        for command in commands_iterable:
            if command.hidden or not getattr(command, "enabled", True):
                continue
            try:
                allowed = await command.can_see(ctx)
            except Exception:
                allowed = False
            if allowed:
                visible.append(command)
        return sorted(visible, key=lambda c: c.qualified_name.casefold())

    async def collect_scope_commands(self, ctx: commands.Context, scope: str) -> list[commands.Command]:
        commands_for_scope: list[commands.Command] = []
        for command in ctx.bot.commands:
            if command.parent is not None:
                continue
            command_scope = self.command_scope(command)
            if command_scope != scope:
                continue
            visible = await self.filter_visible_commands(ctx, [command])
            if visible:
                commands_for_scope.extend(visible)
        deduped = {cmd.qualified_name: cmd for cmd in commands_for_scope}
        return sorted(deduped.values(), key=lambda c: c.qualified_name.casefold())

    async def collect_categories(self, ctx: commands.Context) -> list[dict]:
        categories = []
        for cog_name, cog in sorted(ctx.bot.cogs.items(), key=lambda item: item[0].casefold()):
            root_commands = [cmd for cmd in ctx.bot.commands if cmd.cog is cog and cmd.parent is None]
            visible = await self.filter_visible_commands(ctx, root_commands)
            public_visible = [command for command in visible if self.command_scope(command) == "public"]
            if not public_visible:
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
                    "commands": public_visible,
                    "cog": cog,
                    "aliases": [cog_name],
                }
            )
        uncategorized = [cmd for cmd in ctx.bot.commands if cmd.cog is None and cmd.parent is None]
        uncategorized_visible = await self.filter_visible_commands(ctx, uncategorized)
        public_uncategorized = [cmd for cmd in uncategorized_visible if self.command_scope(cmd) == "public"]
        if public_uncategorized:
            categories.append(
                {
                    "name": None,
                    "description": "Commands not attached to a cog.",
                    "commands": public_uncategorized,
                    "cog": None,
                    "aliases": ["no category", "uncategorized"],
                }
            )
        return categories

    async def find_category(self, ctx: commands.Context, query: str):
        categories = await self.collect_categories(ctx)
        lowered = normalize(query)
        for index, category in enumerate(categories):
            names = [category["name"] or "No Category", *category.get("aliases", [])]
            if lowered in {normalize(name) for name in names if name}:
                return categories, index
        return None

    async def build_suggestions(self, ctx: commands.Context, query: str) -> SuggestionBundle:
        results = await self.search_help(ctx, query, limit=self.suggestion_count)
        suggestions = [result.name for result in results[: self.suggestion_count]]
        best_match = results[0].object_ref if results else None
        best_score = results[0].score if results else 0.0
        return SuggestionBundle(suggestions=suggestions, best_match=best_match, best_score=best_score)

    async def resolve_scoped_help_target(self, ctx: commands.Context, scope: str, query: str):
        query = query.strip()
        if not query:
            return None
        direct = ctx.bot.get_command(query)
        if direct is not None:
            try:
                if await direct.can_see(ctx) and self.command_scope(direct) == scope:
                    return direct
            except Exception:
                pass
        lowered = normalize(query)
        for entry in self.command_index:
            names = [entry["qualified_name"], entry["name"], *entry["aliases"]]
            if lowered in {normalize(name) for name in names}:
                command = entry["object"]
                if entry["scope"] != scope:
                    continue
                try:
                    if await command.can_see(ctx):
                        return command
                except Exception:
                    continue
        results = await self.search_help(ctx, f"{scope} {query}", limit=max(self.search_limit, self.suggestion_count))
        if not results:
            return None
        best = results[0]
        if self.autocorrect_enabled and best.score >= 120:
            return ("redirect", best.object_ref)
        return None

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
        for entry in self.command_index:
            names = [entry["qualified_name"], entry["name"], *entry["aliases"]]
            if lowered in {normalize(name) for name in names}:
                command = entry["object"]
                try:
                    if await command.can_see(ctx):
                        return command
                except Exception:
                    continue
        results = await self.search_help(ctx, query, limit=max(self.search_limit, self.suggestion_count))
        if not results:
            return None
        best = results[0]
        if self.autocorrect_enabled and best.score >= 120:
            return ("redirect", best.object_ref)
        return None

    async def show_search(self, ctx: commands.Context, query: str) -> None:
        """Render the interactive help search flow."""
        results = await self.search_help(ctx, query, limit=self.search_limit)
        if not results:
            bundle = await self.build_suggestions(ctx, query)
            embed = await self.renderer.not_found_embed(ctx, query=query, suggestions=bundle.suggestions, note="No search results were found.")
            await ctx.send(embed=embed)
            return
        categories = await self.collect_categories(ctx)
        view = HelpNavigator(self, ctx, categories, timeout=self.menu_timeout, mode="search", search_query=query, search_results=results)
        embed = await view.render()
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    async def search_help(self, ctx: commands.Context, query: str, *, limit: int | None = None) -> list[SearchResult]:
        limit = limit or self.search_limit
        results = []
        normalized_query = normalize(query)
        if not normalized_query:
            return results
        scope = None
        extracted = self.extract_scope(query)
        if extracted is not None:
            scope, scoped_query = extracted
            normalized_query = normalize(scoped_query)
        for entry in self.command_index:
            command = entry["object"]
            try:
                visible = await command.can_see(ctx)
            except Exception:
                visible = False
            if not visible or command.hidden:
                continue
            if scope is not None and entry["scope"] != scope:
                continue
            if scope is None and entry["scope"] != "public":
                # keep elevated commands out of the default search results
                continue
            score = command_search_score(normalized_query, command, fuzzy=self.fuzzy_enabled)
            if scope == "admin" and entry["scope"] == "admin":
                score += 15
            if scope == "owner" and entry["scope"] == "owner":
                score += 15
            if score <= 0:
                continue
            results.append(SearchResult(kind="command", name=command.qualified_name, score=score, object_ref=command, summary=entry["summary"]))
        if scope is None:
            categories = await self.collect_categories(ctx)
            for category in categories:
                name = category["name"] or "No Category"
                score = cog_search_score(normalized_query, name, category["description"], fuzzy=self.fuzzy_enabled)
                if score <= 0:
                    continue
                results.append(SearchResult(kind="cog", name=name, score=score, object_ref=category["cog"], summary=category["description"]))
        deduped = {}
        for result in results:
            current = deduped.get(result.name.casefold())
            if current is None or result.score > current.score:
                deduped[result.name.casefold()] = result
        return sorted(deduped.values(), key=lambda item: (-item.score, item.name.casefold()))[:limit]

    async def cog_command_error(self, ctx: commands.Context, error: Exception) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, BAD_USAGE_ERRORS):
            try:
                if not await ctx.command.can_see(ctx):
                    return
            except Exception:
                return
            verrors = self._get_verrors()
            if verrors is not None:
                code = None
                if hasattr(verrors, "get_public_error_code"):
                    code = verrors.get_public_error_code(ctx, original)
                elif verrors_public_code_for_error is not None:
                    code = verrors_public_code_for_error(ctx, original)

                if code is not None:
                    embed = None
                    if hasattr(verrors, "build_fixable_error_embed"):
                        embed = verrors.build_fixable_error_embed(ctx, original, code)
                    elif verrors_fixable_error_reply is not None:
                        embed = verrors_fixable_error_reply(ctx, original, code)

                    if embed is not None:
                        await ctx.send(embed=embed)
                        return
            note = str(original) or "That command usage was invalid."
            if isinstance(original, commands.MissingRequiredArgument):
                note = f"Looks like you forgot **{original.param.name}** for this command."
            elif isinstance(original, commands.TooManyArguments):
                note = "Looks like that command has extra text or parameters at the end."
            embed = await self.renderer.command_embed(ctx, command=ctx.command, note=note, admin_context=self.command_is_admin(ctx.command))
            await ctx.send(embed=embed)
            return
        verrors = self._get_verrors()
        if verrors is not None:
            system = verrors.get_system_prefix(ctx) if hasattr(verrors, "get_system_prefix") else (verrors_resolve_system_prefix(ctx) if verrors_resolve_system_prefix is not None else "VH")
            await verrors.reporter.report_command_exception(ctx, original, system)
            return
        await self.send_internal_error_for_context(ctx, original, source="vhelp-command")

    @commands.command(name="helpsearch", aliases=["hsearch", "searchhelp"], hidden=True)
    @error_slot("0A")
    @error_meta(
        examples=["?help search ban", "?help search admin timeout"],
        missing_argument={
            "summary": "The help search command needs a search phrase before it can run.",
            "fix": "Add a word or phrase after `help search`, like a command name, alias, or category.",
        },
        invalid_argument={
            "summary": "Try a short word or phrase that matches a command, alias, or category.",
            "fix": "Use plain text like `ban`, `timeout`, or `owner`.",
        },
    )
    async def helpsearch(self, ctx: commands.Context, *, query: str) -> None:
        """Compatibility alias for the integrated `help search` flow."""
        await self.show_search(ctx, query)

    @commands.group(name="vhelpset", invoke_without_command=True)
    @commands.is_owner()
    @error_slot("0B")
    @error_meta(
        examples=["?vhelpset status", "?vhelpset pagesize 8"],
        missing_argument={
            "summary": "`vhelpset` needs a subcommand such as `status`, `timeout`, `pagesize`, or `rebuild`.",
            "fix": "Run `?help owner vhelpset` to browse the available owner settings commands, then run the subcommand you need.",
        },
        no_permission={
            "summary": "`vhelpset` is limited to bot owners.",
            "fix": "Ask a bot owner to run this settings command for you.",
        },
    )
    async def vhelpset(self, ctx: commands.Context) -> None:
        """Owner-only settings for VHelp."""
        await ctx.send_help()

    @vhelpset.command(name="status")
    @commands.is_owner()
    @error_slot("0C")
    @error_meta(
        examples=["?vhelpset status"],
        no_permission={
            "summary": "The VHelp status command is bot-owner only.",
            "fix": "Ask a bot owner to check the VHelp status for you.",
        },
    )
    async def vhelpset_status(self, ctx: commands.Context) -> None:
        formatter_status = "✅ Active" if self._formatter_active else "❌ Inactive"
        embed = discord.Embed(
            title="⚙️ VHelp Status",
            description=f"**Formatter:** {formatter_status}",
            color=discord.Color.green() if self._formatter_active else discord.Color.red(),
        )
        embed.add_field(
            name="⏱️ Menu Settings",
            value=(
                f"Timeout: `{self.menu_timeout}s`\n"
                f"Home page size: `{self.home_page_size}`\n"
                f"Category page size: `{self.cog_page_size}`\n"
                f"Group page size: `{self.group_page_size}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="🔎 Search Settings",
            value=(
                f"Search limit: `{self.search_limit}`\n"
                f"Suggestion count: `{self.suggestion_count}`\n"
                f"Fuzzy matching: `{self.fuzzy_enabled}`\n"
                f"Autocorrect: `{self.autocorrect_enabled}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="📇 Index",
            value=(
                f"Commands indexed: `{len(self.command_index)}`\n"
                f"Cogs indexed: `{len(self.cog_index)}`"
            ),
            inline=False,
        )
        if ctx.me:
            embed.set_author(name=ctx.me.display_name, icon_url=ctx.me.display_avatar.url)
        await ctx.send(embed=embed)

    @vhelpset.command(name="timeout")
    @commands.is_owner()
    @error_slot("0D")
    @error_meta(
        examples=["?vhelpset timeout 180"],
        param_labels={"seconds": "how long help buttons should stay active, in seconds"},
        missing_argument={
            "summary": "`vhelpset timeout` needs a number of seconds.",
            "fix": "Run the command again and include a whole number from 30 to 600.",
            "details": "For example, `180` keeps the help buttons active for three minutes.",
        },
        invalid_argument={
            "summary": "The timeout value must be a whole number from 30 to 600 seconds.",
            "fix": "Pick a value between `30` and `600`, then run the command again.",
            "details": "Examples: `?vhelpset timeout 60`, `?vhelpset timeout 180`, `?vhelpset timeout 300`.",
        },
        no_permission={
            "summary": "Only bot owners can change the VHelp menu timeout.",
            "fix": "Ask a bot owner to update the timeout value for you.",
        },
    )
    async def vhelpset_timeout(self, ctx: commands.Context, seconds: commands.Range[int, 30, 600]) -> None:
        await self.config.menu_timeout.set(seconds)
        self.menu_timeout = seconds
        await ctx.send(f"Help menu timeout set to `{seconds}` seconds.")

    @vhelpset.command(name="pagesize")
    @commands.is_owner()
    @error_slot("0E")
    @error_meta(
        examples=["?vhelpset pagesize 8"],
        param_labels={"number": "how many commands should appear on each help page"},
        missing_argument={
            "summary": "`vhelpset pagesize` needs a page size number.",
            "fix": "Run the command again and include a whole number from 3 to 20.",
        },
        invalid_argument={
            "summary": "The page size must be a whole number from 3 to 20.",
            "fix": "Choose a number between `3` and `20`, then run the command again.",
            "details": "A smaller page size makes menus shorter; a larger page size shows more commands at once.",
        },
        no_permission={
            "summary": "Only bot owners can change the VHelp page size.",
            "fix": "Ask a bot owner to update the page size for you.",
        },
    )
    async def vhelpset_pagesize(self, ctx: commands.Context, number: commands.Range[int, 3, 20]) -> None:
        await self.config.home_page_size.set(number)
        await self.config.cog_page_size.set(number)
        self.home_page_size = number
        self.cog_page_size = number
        await ctx.send(f"Home and category page size set to `{number}`.")

    @vhelpset.command(name="rebuild")
    @commands.is_owner()
    @error_slot("0F")
    @error_meta(
        examples=["?vhelpset rebuild"],
        no_permission={
            "summary": "Only bot owners can rebuild the VHelp indexes.",
            "fix": "Ask a bot owner to run the rebuild command for you.",
        },
    )
    async def vhelpset_rebuild(self, ctx: commands.Context) -> None:
        self.rebuild_index()
        verrors = self._get_verrors()
        if verrors is not None:
            verrors.rebuild_registry()
        await ctx.send("Rebuilt VHelp indexes.")
