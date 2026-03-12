"""Interactive views for VHelp."""

from __future__ import annotations

import contextlib
from typing import Any

import discord

from redbot.core import commands


class VHelpBaseView(discord.ui.View):
    def __init__(self, cog: commands.Cog, ctx: commands.Context, *, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.ctx = ctx
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.ctx.author.id:
            return True
        await interaction.response.send_message("This help menu belongs to someone else.", ephemeral=True)
        return False

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[Any]) -> None:
        handler = getattr(self.cog, "send_internal_error_for_interaction", None)
        if handler is not None:
            await handler(interaction, error, item=item)
            return
        await super().on_error(interaction, error, item)


class HelpNavigator(VHelpBaseView):
    def __init__(
        self,
        cog: commands.Cog,
        ctx: commands.Context,
        categories: list[dict],
        *,
        timeout: float = 180,
        mode: str = "home",
        category_index: int | None = None,
        group_command: commands.Group | None = None,
        group_subcommands: list[commands.Command] | None = None,
        search_query: str | None = None,
        search_results: list | None = None,
        scope_name: str | None = None,
        scope_commands: list[commands.Command] | None = None,
    ):
        super().__init__(cog, ctx, timeout=timeout)
        self.categories = categories
        self.mode = mode
        self.page = 0
        self.category_index = category_index
        self.group_command = group_command
        self.group_subcommands = group_subcommands or []
        self.search_query = search_query
        self.search_results = search_results or []
        self.scope_name = scope_name
        self.scope_commands = scope_commands or []
        if self.mode != "search":
            self.remove_item(self.closest_match_button)
        self._sync_buttons()
        self._sync_visibility()

    def _home_pages(self) -> list[tuple[str, int | None, int]]:
        pages: list[tuple[str, int | None, int]] = [("home", None, 0)]
        for index, entry in enumerate(self.categories):
            command_count = len(entry["commands"])
            subpages = max(1, (command_count + self.cog.cog_page_size - 1) // self.cog.cog_page_size)
            for subpage in range(subpages):
                pages.append(("category", index, subpage))
        return pages

    def _page_count(self) -> int:
        if self.mode == "home":
            return max(1, len(self._home_pages()))
        if self.mode == "category" and self.category_index is not None:
            return max(1, (len(self.categories[self.category_index]["commands"]) + self.cog.cog_page_size - 1) // self.cog.cog_page_size)
        if self.mode == "group":
            return max(1, (len(self.group_subcommands) + self.cog.group_page_size - 1) // self.cog.group_page_size)
        if self.mode == "search":
            return max(1, (len(self.search_results) + self.cog.cog_page_size - 1) // self.cog.cog_page_size)
        if self.mode == "scope":
            return max(1, (len(self.scope_commands) + self.cog.cog_page_size - 1) // self.cog.cog_page_size)
        return 1

    def _sync_buttons(self) -> None:
        total_pages = self._page_count()
        self.previous_page.disabled = self.page <= 0
        self.next_page.disabled = self.page >= total_pages - 1
        self.page_indicator.label = f"{self.page + 1}/{total_pages}"
        self.home_button.disabled = (self.mode == "home" and self.page == 0)

    def _sync_visibility(self) -> None:
        if self.mode != "search":
            return
        active = bool(self.search_results)
        self.closest_match_button.disabled = not active
        self.closest_match_button.style = discord.ButtonStyle.success if active else discord.ButtonStyle.secondary

    async def render(self) -> discord.Embed:
        renderer = self.cog.renderer
        if self.mode == "home":
            page_map = self._home_pages()
            state, index, subpage = page_map[max(0, min(self.page, len(page_map) - 1))]
            if state == "home":
                return await renderer.home_embed(
                    self.ctx,
                    categories=self.categories,
                    page=self.page,
                    page_size=self.cog.home_page_size,
                    total_pages=len(page_map),
                )
            entry = self.categories[index]
            return await renderer.cog_embed(
                self.ctx,
                cog_name=entry["name"] or "No Category",
                description=entry.get("description") or "",
                commands_list=entry["commands"],
                page=subpage,
                page_size=self.cog.cog_page_size,
                browser_page=self.page,
                browser_total=len(page_map),
            )
        if self.mode == "category" and self.category_index is not None:
            entry = self.categories[self.category_index]
            return await renderer.cog_embed(
                self.ctx,
                cog_name=entry["name"] or "No Category",
                description=entry.get("description") or "",
                commands_list=entry["commands"],
                page=self.page,
                page_size=self.cog.cog_page_size,
            )
        if self.mode == "group":
            return await renderer.group_embed(
                self.ctx,
                command=self.group_command,
                subcommands=self.group_subcommands,
                page=self.page,
                page_size=self.cog.group_page_size,
            )
        if self.mode == "search":
            return await renderer.search_results_embed(
                self.ctx,
                query=self.search_query or "search",
                results=self.search_results,
                page=self.page,
                page_size=self.cog.cog_page_size,
            )
        if self.mode == "scope":
            return await renderer.scoped_embed(
                self.ctx,
                scope=self.scope_name or "admin",
                commands_list=self.scope_commands,
                page=self.page,
                page_size=self.cog.cog_page_size,
            )
        raise RuntimeError("Unsupported help menu state.")

    @discord.ui.button(label="Closest Match", style=discord.ButtonStyle.success, row=0)
    async def closest_match_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.mode != "search" or not self.search_results:
            await interaction.response.defer()
            return
        best = self.search_results[0].object_ref
        if isinstance(best, commands.Group):
            await self.cog.formatter._send_group(self.ctx, best, redirect_from=self.search_query)
        elif isinstance(best, commands.Command):
            await self.cog.formatter._send_command(self.ctx, best, redirect_from=self.search_query)
        elif isinstance(best, commands.Cog):
            category = await self.cog.find_category(self.ctx, best.qualified_name)
            if category is not None:
                await self.cog.formatter._send_category(self.ctx, category[0], category[1])
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.delete()
        self.stop()
        if not interaction.response.is_done():
            await interaction.response.defer()

    @discord.ui.button(label="🏠 Home", style=discord.ButtonStyle.secondary, row=1)
    async def home_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Return to the main help overview page."""
        self.mode = "home"
        self.page = 0
        self.category_index = None
        self._sync_buttons()
        self._sync_visibility()
        await interaction.response.edit_message(embed=await self.render(), view=self)

    @discord.ui.button(label="<", style=discord.ButtonStyle.secondary, row=0)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = max(0, self.page - 1)
        self._sync_buttons()
        self._sync_visibility()
        await interaction.response.edit_message(embed=await self.render(), view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.secondary, disabled=True, row=0)
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()

    @discord.ui.button(label=">", style=discord.ButtonStyle.secondary, row=0)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = min(self._page_count() - 1, self.page + 1)
        self._sync_buttons()
        self._sync_visibility()
        await interaction.response.edit_message(embed=await self.render(), view=self)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, row=0)
    async def close_menu(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        deleted = False
        if self.message is not None:
            try:
                await self.message.delete()
                deleted = True
            except discord.HTTPException:
                pass
        if not interaction.response.is_done():
            if deleted:
                await interaction.response.defer()
            else:
                await interaction.response.edit_message(view=None)
