from __future__ import annotations

import logging

import discord

log = logging.getLogger("red.vantage.errors")


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
        if self.verrors_cog is not None and hasattr(self.verrors_cog, "report_interaction_error"):
            await self.verrors_cog.report_interaction_error(
                interaction=interaction,
                error=error,
                system=self.system,
                command_name=self.command_name or getattr(item, "custom_id", None) or "view",
                location=f"view:{self.__class__.__name__}",
            )
        else:
            log.exception(
                "Unhandled view error in %s (item=%s) — VErrors cog unavailable.",
                self.__class__.__name__,
                getattr(item, "custom_id", repr(item)),
                exc_info=error,
            )
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("Something went wrong. Please try again later.", ephemeral=True)
                else:
                    await interaction.response.send_message("Something went wrong. Please try again later.", ephemeral=True)
            except discord.HTTPException:
                pass
