"""Custom Red help formatter implementation."""

from __future__ import annotations

from typing import Any

from redbot.core import commands
from redbot.core.commands.help import HelpFormatterABC

from .utils import normalize
from .views import HelpNavigator


class VHelpFormatter(HelpFormatterABC):
    def __init__(self, cog: commands.Cog):
        self.cog = cog

    async def send_help(self, ctx: commands.Context, help_for: Any = None, *, from_help_command: bool = False) -> None:
        try:
            if help_for is None or getattr(help_for, "__class__", None).__name__ == "Red":
                await self._send_home(ctx)
                return
            if isinstance(help_for, str):
                normalized = normalize(help_for)
                if normalized == "search":
                    embed = await self.cog.renderer.not_found_embed(
                        ctx,
                        query="search",
                        suggestions=[],
                        note=f"Use `{ctx.clean_prefix}help search <query>` to search commands, aliases, and categories.",
                    )
                    await ctx.send(embed=embed)
                    return
                if normalized.startswith("search "):
                    query = help_for.split(maxsplit=1)[1].strip()
                    if not query:
                        embed = await self.cog.renderer.not_found_embed(
                            ctx,
                            query="search",
                            suggestions=[],
                            note=f"Use `{ctx.clean_prefix}help search <query>` to search commands, aliases, and categories.",
                        )
                        await ctx.send(embed=embed)
                        return
                    await self.cog.show_search(ctx, query)
                    return
                scope = self.cog.extract_scope(help_for)
                if scope is not None:
                    scope_name, scoped_query = scope
                    if not scoped_query:
                        await self._send_scope(ctx, scope_name)
                        return
                    result = await self.cog.resolve_scoped_help_target(ctx, scope_name, scoped_query)
                    if result is None:
                        await self._send_not_found(ctx, f"{scope_name} {scoped_query}")
                        return
                    redirect_from = None
                    if isinstance(result, tuple) and len(result) == 2 and result[0] == "redirect":
                        redirect_from = f"{scope_name} {scoped_query}"
                        result = result[1]
                    await self._dispatch_object(ctx, result, redirect_from=redirect_from)
                    return
                category = await self.cog.find_category(ctx, help_for)
                if category is not None:
                    await self._send_category(ctx, category[0], category[1])
                    return
                result = await self.cog.resolve_help_target(ctx, help_for)
                if result is None:
                    await self._send_not_found(ctx, help_for)
                    return
                redirect_from = None
                if isinstance(result, tuple) and len(result) == 2 and result[0] == "redirect":
                    redirect_from = help_for
                    result = result[1]
                await self._dispatch_object(ctx, result, redirect_from=redirect_from)
                return
            await self._dispatch_object(ctx, help_for)
        except Exception as exc:
            await self.cog.send_internal_error_for_context(ctx, exc, source="help-formatter")

    async def _dispatch_object(self, ctx: commands.Context, target: Any, *, redirect_from: str | None = None) -> None:
        if isinstance(target, commands.Cog):
            category = await self.cog.find_category(ctx, target.qualified_name)
            if category is not None:
                await self._send_category(ctx, category[0], category[1])
                return
        if isinstance(target, commands.Group):
            await self._send_group(ctx, target, redirect_from=redirect_from)
            return
        await self._send_command(ctx, target, redirect_from=redirect_from)

    async def _send_home(self, ctx: commands.Context) -> None:
        categories = await self.cog.collect_categories(ctx)
        view = HelpNavigator(self.cog, ctx, categories, timeout=self.cog.menu_timeout)
        embed = await view.render()
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    async def _send_category(self, ctx: commands.Context, categories: list[dict], index: int) -> None:
        view = HelpNavigator(self.cog, ctx, categories, timeout=self.cog.menu_timeout, mode="category", category_index=index)
        embed = await view.render()
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    async def _send_scope(self, ctx: commands.Context, scope_name: str) -> None:
        categories = await self.cog.collect_categories(ctx)
        scope_commands = await self.cog.collect_scope_commands(ctx, scope_name)
        view = HelpNavigator(
            self.cog,
            ctx,
            categories,
            timeout=self.cog.menu_timeout,
            mode="scope",
            scope_name=scope_name,
            scope_commands=scope_commands,
        )
        embed = await view.render()
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    async def _send_command(self, ctx: commands.Context, command: commands.Command, *, redirect_from: str | None = None) -> None:
        embed = await self.cog.renderer.command_embed(ctx, command=command, redirect_from=redirect_from, admin_context=self.cog.command_is_admin(command))
        await ctx.send(embed=embed)

    async def _send_group(self, ctx: commands.Context, command: commands.Group, *, redirect_from: str | None = None) -> None:
        subcommands = await self.cog.filter_visible_commands(ctx, command.commands)
        if not subcommands:
            embed = await self.cog.renderer.command_embed(ctx, command=command, redirect_from=redirect_from, admin_context=self.cog.command_is_admin(command))
            await ctx.send(embed=embed)
            return
        categories = await self.cog.collect_categories(ctx)
        view = HelpNavigator(self.cog, ctx, categories, timeout=self.cog.menu_timeout, mode="group", group_command=command, group_subcommands=subcommands)
        embed = await self.cog.renderer.group_embed(ctx, command=command, subcommands=subcommands, page=0, page_size=self.cog.group_page_size, redirect_from=redirect_from)
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    async def _send_not_found(self, ctx: commands.Context, query: str) -> None:
        bundle = await self.cog.build_suggestions(ctx, query)
        note = None
        normalized = normalize(query)
        if normalized.startswith("admin "):
            note = f"Use `{ctx.clean_prefix}help admin` to browse elevated commands."
        elif normalized.startswith("owner "):
            note = f"Use `{ctx.clean_prefix}help owner` to browse bot-owner commands."
        embed = await self.cog.renderer.not_found_embed(ctx, query=query, suggestions=bundle.suggestions, note=note)
        await ctx.send(embed=embed)
