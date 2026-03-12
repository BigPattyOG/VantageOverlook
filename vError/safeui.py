from __future__ import annotations

import discord

from .models import ErrorKind


class VErrorSafeView(discord.ui.View):
    """Base view that reports unexpected UI callback failures through VErrors.

    Pass the loaded VErrors cog when constructing the view.
    """

    def __init__(self, verrors_cog, *, system: str = "SYS", command_name: str | None = None, timeout: float | None = 180):
        super().__init__(timeout=timeout)
        self.verrors_cog = verrors_cog
        self.system = system
        self.command_name = command_name

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        await self.verrors_cog.report_interaction_error(
            interaction=interaction,
            error=error,
            system=self.system,
            command_name=self.command_name or getattr(item, "custom_id", None) or "view",
            location=f"view:{self.__class__.__name__}",
        )
