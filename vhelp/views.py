"""Interactive views for VHelp."""

from __future__ import annotations

from typing import Any

import discord

from redbot.core import commands


class HelpCategorySelect(discord.ui.Select):
    """Dropdown for switching between visible categories."""

    def __init__(self, parent: "HelpNavigator"):
        self.parent_view = parent
        options: list[discord.SelectOption] = [
            discord.SelectOption(
                label="Home",
                value="__home__",
                description="Return to the main help page",
                emoji="🏠",
            )
        ]

        for index, entry in enumerate(parent.categories[:25]):
            label = entry["name"] or "No Category"
            command_count = len(entry["commands"])
            description = (entry["description"] or f"{command_count} commands")[:100]
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(index),
                    description=description,
                    emoji="📚",
                )
            )

        super().__init__(
            placeholder="Jump to a category…",
            min_values=1,
            max_values=1,
            options=options,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> Any:
        if self.values[0] == "__home__":
            await self.parent_view.show_home(interaction)
            return
        await self.parent_view.show_category(interaction, int(self.values[0]))


class HelpNavigator(discord.ui.View):
    """Navigation view for home, category, and group pages."""

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
    ):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.ctx = ctx
        self.categories = categories
        self.mode = mode
        self.page = 0
        self.category_index = category_index
        self.group_command = group_command
        self.group_subcommands = group_subcommands or []
        self.group_info_mode = False
        self.message: discord.Message | None = None

        self.select = HelpCategorySelect(self)
        self.add_item(self.select)
        self._sync_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.ctx.author.id:
            return True
        await interaction.response.send_message(
            "This help menu belongs to someone else.",
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    def _page_count(self) -> int:
        if self.mode == "home":
            return max(1, (len(self.categories) + self.cog.home_page_size - 1) // self.cog.home_page_size)
        if self.mode == "category" and self.category_index is not None:
            commands_list = self.categories[self.category_index]["commands"]
            return max(1, (len(commands_list) + self.cog.cog_page_size - 1) // self.cog.cog_page_size)
        if self.mode == "group":
            return max(1, (len(self.group_subcommands) + self.cog.group_page_size - 1) // self.cog.group_page_size)
        return 1

    def _sync_buttons(self) -> None:
        total_pages = self._page_count()
        is_static_group_info = self.mode == "group" and self.group_info_mode

        self.first_page.disabled = self.page <= 0 or is_static_group_info
        self.previous_page.disabled = self.page <= 0 or is_static_group_info
        self.next_page.disabled = self.page >= total_pages - 1 or is_static_group_info
        self.last_page.disabled = self.page >= total_pages - 1 or is_static_group_info
        self.home_button.disabled = self.mode == "home"

        self.page_indicator.label = f"Page {self.page + 1}/{total_pages}"
        self.page_indicator.disabled = True

        group_mode = self.mode == "group"
        self.group_info.disabled = not group_mode or self.group_info_mode
        self.group_subs.disabled = not group_mode or not self.group_info_mode

        # Make the active group tab stand out a little more.
        if group_mode:
            self.group_info.style = (
                discord.ButtonStyle.primary if self.group_info_mode else discord.ButtonStyle.secondary
            )
            self.group_subs.style = (
                discord.ButtonStyle.primary if not self.group_info_mode else discord.ButtonStyle.secondary
            )
        else:
            self.group_info.style = discord.ButtonStyle.secondary
            self.group_subs.style = discord.ButtonStyle.secondary

    async def render(self) -> discord.Embed:
        renderer = self.cog.renderer
        if self.mode == "home":
            return await renderer.home_embed(
                self.ctx,
                categories=self.categories,
                page=self.page,
                page_size=self.cog.home_page_size,
            )
        if self.mode == "category" and self.category_index is not None:
            entry = self.categories[self.category_index]
            return await renderer.cog_embed(
                self.ctx,
                cog_name=entry["name"] or "No Category",
                description=entry["description"],
                commands_list=entry["commands"],
                page=self.page,
                page_size=self.cog.cog_page_size,
            )
        if self.mode == "group" and self.group_command is not None:
            return await renderer.group_overview_embed(
                self.ctx,
                command=self.group_command,
                subcommands=self.group_subcommands,
                page=self.page,
                page_size=self.cog.group_page_size,
                show_parent_info=self.group_info_mode,
            )
        raise RuntimeError("Unsupported help menu state.")

    async def show_home(self, interaction: discord.Interaction) -> None:
        self.mode = "home"
        self.page = 0
        self.category_index = None
        self.group_command = None
        self.group_subcommands = []
        self.group_info_mode = False
        self._sync_buttons()
        await interaction.response.edit_message(embed=await self.render(), view=self)

    async def show_category(self, interaction: discord.Interaction, index: int) -> None:
        self.mode = "category"
        self.page = 0
        self.category_index = index
        self.group_command = None
        self.group_subcommands = []
        self.group_info_mode = False
        self._sync_buttons()
        await interaction.response.edit_message(embed=await self.render(), view=self)

    @discord.ui.button(label="Home", emoji="🏠", style=discord.ButtonStyle.secondary, row=0)
    async def home_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.show_home(interaction)

    @discord.ui.button(label="First", emoji="⏮️", style=discord.ButtonStyle.primary, row=0)
    async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = 0
        self._sync_buttons()
        await interaction.response.edit_message(embed=await self.render(), view=self)

    @discord.ui.button(label="Prev", emoji="◀️", style=discord.ButtonStyle.primary, row=0)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = max(0, self.page - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=await self.render(), view=self)

    @discord.ui.button(label="Page 1/1", style=discord.ButtonStyle.secondary, disabled=True, row=0)
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        return

    @discord.ui.button(label="Next", emoji="▶️", style=discord.ButtonStyle.primary, row=0)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = min(self._page_count() - 1, self.page + 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=await self.render(), view=self)

    @discord.ui.button(label="Last", emoji="⏭️", style=discord.ButtonStyle.primary, row=0)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = self._page_count() - 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=await self.render(), view=self)

    @discord.ui.button(label="Info", emoji="ℹ️", style=discord.ButtonStyle.secondary, row=1)
    async def group_info(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.group_info_mode = True
        self.page = 0
        self._sync_buttons()
        await interaction.response.edit_message(embed=await self.render(), view=self)

    @discord.ui.button(label="Subcommands", emoji="📖", style=discord.ButtonStyle.secondary, row=1)
    async def group_subs(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.group_info_mode = False
        self.page = 0
        self._sync_buttons()
        await interaction.response.edit_message(embed=await self.render(), view=self)

    @discord.ui.button(label="Close", emoji="✖️", style=discord.ButtonStyle.danger, row=1)
    async def close_menu(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()
