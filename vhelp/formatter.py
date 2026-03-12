"""Custom Red help formatter implementation."""

from __future__ import annotations

from typing import Any

from redbot.core import commands
from redbot.core.commands.help import HelpFormatterABC

from .views import HelpNavigator


class VHelpFormatter(HelpFormatterABC):
    """A button-driven custom help formatter."""

    def __init__(self, cog: commands.Cog):
        self.cog = cog

    async def send_help(
        self,
        ctx: commands.Context,
        help_for: Any = None,
        *,
        from_help_command: bool = False,
    ) -> None:
        try:
            if help_for is None or getattr(help_for, "__class__", None).__name__ == "Red":
                await self._send_home(ctx)
                return

            if isinstance(help_for, str):
                result = await self.cog.resolve_help_target(ctx, help_for)
                if result is None:
                    await self._send_not_found(ctx, help_for)
                    return
                if getattr(result, "__class__", None).__name__ == "_RedirectTarget":
                    await self._dispatch_object(ctx, result.target, redirect_from=result.original)
                    return
                await self._dispatch_object(ctx, result)
                return

            await self._dispatch_object(ctx, help_for)
        except Exception as exc:
            await ctx.send(f"Something went wrong while building help: `{exc}`")

    async def _dispatch_object(self, ctx: commands.Context, target: Any, *, redirect_from: str | None = None) -> None:
        if isinstance(target, commands.Cog):
            await self._send_cog(ctx, target)
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

    async def _send_cog(self, ctx: commands.Context, cog: commands.Cog) -> None:
        categories = await self.cog.collect_categories(ctx)
        index = 0
        for idx, entry in enumerate(categories):
            if entry["name"] == cog.qualified_name:
                index = idx
                break

        view = HelpNavigator(
            self.cog,
            ctx,
            categories,
            timeout=self.cog.menu_timeout,
            mode="category",
            category_index=index,
        )
        embed = await view.render()
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    async def _send_group(self, ctx: commands.Context, command: commands.Group, *, redirect_from: str | None = None) -> None:
        categories = await self.cog.collect_categories(ctx)
        subcommands = await self.cog.filter_visible_commands(ctx, command.commands)
        view = HelpNavigator(
            self.cog,
            ctx,
            categories,
            timeout=self.cog.menu_timeout,
            mode="group",
            group_command=command,
            group_subcommands=subcommands,
        )
        embed = await self.cog.renderer.group_overview_embed(
            ctx,
            command=command,
            subcommands=subcommands,
            page=0,
            page_size=self.cog.group_page_size,
            show_parent_info=True,
        )
        if redirect_from and redirect_from.casefold() != command.qualified_name.casefold():
            embed.add_field(
                name="Matched help topic",
                value=f"I couldn't find `{redirect_from}`, so I opened `{command.qualified_name}` instead.",
                inline=False,
            )
        view.group_info_mode = True
        view._sync_buttons()
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    async def _send_command(self, ctx: commands.Context, command: commands.Command, *, redirect_from: str | None = None) -> None:
        embed = await self.cog.renderer.command_embed(ctx, command=command, redirect_from=redirect_from)
        await ctx.send(embed=embed)

    async def _send_not_found(self, ctx: commands.Context, query: str) -> None:
        bundle = await self.cog.build_suggestions(ctx, query)
        embed = await self.cog.renderer.not_found_embed(
            ctx,
            query=query,
            suggestions=bundle.suggestions,
            note="Try a shorter query or use the search command for broader matches.",
        )
        await ctx.send(embed=embed)
