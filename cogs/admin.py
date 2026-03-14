"""Built-in Admin cog — owner-only bot management commands.

Commands
--------
``[p]ping``         — Latency check.
``[p]load``         — Load an extension.
``[p]unload``       — Unload an extension.
``[p]reload``       — Reload an extension.
``[p]cogs``         — List loaded extensions.
``[p]prefix``       — Get or change the command prefix.
``[p]shutdown``     — Gracefully shut down the bot.
"""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord.ext import commands

log = logging.getLogger("vantage.admin")

EMBED_COLOUR = discord.Color.from_str("#5865F2")


class Admin(commands.Cog, name="Admin"):
    """Owner-only bot management commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── helpers ───────────────────────────────────────────────────────────────

    def _ok(self, description: str) -> discord.Embed:
        return discord.Embed(description=f"✅ {description}", color=discord.Color.green())

    def _err(self, description: str) -> discord.Embed:
        return discord.Embed(description=f"❌ {description}", color=discord.Color.red())

    def _info(self, title: str, description: str = "") -> discord.Embed:
        return discord.Embed(title=title, description=description, color=EMBED_COLOUR)

    # ── commands ──────────────────────────────────────────────────────────────

    @commands.command()
    async def ping(self, ctx: commands.Context) -> None:
        """Check the bot's response time."""
        latency_ms = round(self.bot.latency * 1000)
        await ctx.send(embed=self._info("🏓 Pong!", f"API latency: **{latency_ms} ms**"))

    @commands.command()
    @commands.is_owner()
    async def load(self, ctx: commands.Context, extension: str) -> None:
        """Load an extension (cog).

        **Owner only.** The extension must be installed and importable.
        Example: ``{prefix}load my_repo.my_cog``
        """
        try:
            await self.bot.load_extension(extension)
            log.info("Loaded extension: %s (by %s)", extension, ctx.author)
            await ctx.send(embed=self._ok(f"Loaded `{extension}`."))
        except commands.ExtensionAlreadyLoaded:
            await ctx.send(embed=self._err(f"`{extension}` is already loaded."))
        except commands.ExtensionNotFound:
            await ctx.send(embed=self._err(f"Extension `{extension}` not found."))
        except Exception as exc:
            log.exception("Failed to load extension: %s", extension)
            await ctx.send(embed=self._err(f"Failed to load `{extension}`:\n```\n{exc}\n```"))

    @commands.command()
    @commands.is_owner()
    async def unload(self, ctx: commands.Context, extension: str) -> None:
        """Unload a running extension (cog).

        **Owner only.**
        """
        if extension in ("cogs.admin",):
            await ctx.send(embed=self._err("You cannot unload the built-in admin cog."))
            return
        try:
            await self.bot.unload_extension(extension)
            log.info("Unloaded extension: %s (by %s)", extension, ctx.author)
            await ctx.send(embed=self._ok(f"Unloaded `{extension}`."))
        except commands.ExtensionNotLoaded:
            await ctx.send(embed=self._err(f"`{extension}` is not currently loaded."))
        except Exception as exc:
            log.exception("Failed to unload extension: %s", extension)
            await ctx.send(embed=self._err(f"Failed to unload `{extension}`:\n```\n{exc}\n```"))

    @commands.command()
    @commands.is_owner()
    async def reload(self, ctx: commands.Context, extension: str) -> None:
        """Reload an extension (cog) — picks up code changes.

        **Owner only.**
        """
        try:
            await self.bot.reload_extension(extension)
            log.info("Reloaded extension: %s (by %s)", extension, ctx.author)
            await ctx.send(embed=self._ok(f"Reloaded `{extension}`."))
        except commands.ExtensionNotLoaded:
            await ctx.send(embed=self._err(f"`{extension}` is not loaded. Use `load` first."))
        except Exception as exc:
            log.exception("Failed to reload extension: %s", extension)
            await ctx.send(embed=self._err(f"Failed to reload `{extension}`:\n```\n{exc}\n```"))

    @commands.command(name="cogs")
    @commands.is_owner()
    async def list_cogs(self, ctx: commands.Context) -> None:
        """List all currently loaded extensions.

        **Owner only.**
        """
        loaded = sorted(self.bot.extensions.keys())
        embed = self._info(
            f"🧩 Loaded Extensions ({len(loaded)})",
            "\n".join(f"`{e}`" for e in loaded) if loaded else "None",
        )
        await ctx.send(embed=embed)

    @commands.command()
    @commands.is_owner()
    async def prefix(self, ctx: commands.Context, new_prefix: Optional[str] = None) -> None:
        """Get or change the command prefix.

        **Owner only** for changes.  Anyone can query the current prefix.
        """
        if new_prefix is None:
            current = ctx.clean_prefix
            await ctx.send(embed=self._info("⚙️ Prefix", f"Current prefix: `{current}`"))
            return

        if not ctx.author == await self.bot.fetch_user(list(self.bot.owner_ids)[0]):
            await ctx.send(embed=self._err("Only the bot owner can change the prefix."))
            return

        self.bot.config["prefix"] = new_prefix
        self.bot.command_prefix = commands.when_mentioned_or(new_prefix)

        from core.config import save_config
        save_config(self.bot.config)

        log.info("Prefix changed to '%s' by %s", new_prefix, ctx.author)
        await ctx.send(embed=self._ok(f"Prefix changed to `{new_prefix}`."))

    @commands.command()
    @commands.is_owner()
    async def shutdown(self, ctx: commands.Context) -> None:
        """Gracefully shut down the bot.

        **Owner only.**
        """
        await ctx.send(embed=self._ok("Shutting down… 👋"))
        log.info("Shutdown requested by %s", ctx.author)
        await self.bot.close()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
