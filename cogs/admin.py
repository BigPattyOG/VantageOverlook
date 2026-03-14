"""Built-in Admin cog — owner-only bot management commands.

Commands
--------
``[p]ping``           — Latency check.
``[p]load``           — Load an extension.
``[p]unload``         — Unload an extension.
``[p]reload``         — Reload an extension.
``[p]cogs``           — List loaded extensions.
``[p]prefix``         — Get or change the command prefix.
``[p]shutdown``       — Gracefully shut down the bot.
``[p]vmanage``        — Interactive bot management panel (with buttons).
``[p]servers``        — List all guilds the bot is in.
``[p]stats``          — Detailed bot statistics.
``[p]announce``       — Broadcast a message to all guild system channels.
``[p]setactivity``    — Change the bot's activity/presence.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import subprocess
import sys
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands

log = logging.getLogger("vantage.admin")

EMBED_COLOUR = discord.Color.from_str("#5865F2")
GREEN = discord.Color.green()
RED = discord.Color.red()
GOLD = discord.Color.gold()
BLURPLE = discord.Color.blurple()


# ── Management panel view ─────────────────────────────────────────────────────

class VManageView(discord.ui.View):
    """Interactive buttons for the vmanage management panel."""

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(timeout=300)
        self.bot = bot

    # ── helpers ───────────────────────────────────────────────────────────────

    def _service_name(self) -> str:
        import re
        svc = self.bot.config.get("service_name", "vantage")
        # Validate: only lowercase alphanumeric and hyphens.  Prevents command
        # injection if an attacker somehow modifies config.json.
        if not re.match(r'^[a-z][a-z0-9-]*$', svc):
            raise ValueError(f"Invalid service_name in config: {svc!r}")
        return svc

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        owner_ids = self.bot.owner_ids or set()
        if interaction.user.id not in owner_ids:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="❌ Only bot owners can use these controls.",
                    color=RED,
                ),
                ephemeral=True,
            )
            return False
        return True

    def _run_service_cmd(self, action: str) -> tuple[int, str]:
        """Run ``sudo systemctl <action> <service>`` and return (returncode, stderr)."""
        svc = self._service_name()
        result = subprocess.run(
            ["sudo", "systemctl", action, svc],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode, result.stderr.strip()

    # ── buttons ───────────────────────────────────────────────────────────────

    @discord.ui.button(label="Restart", style=discord.ButtonStyle.primary, emoji="🔄", row=0)
    async def restart_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._check_owner(interaction):
            return
        try:
            svc = self._service_name()
        except ValueError as exc:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ {exc}", color=RED), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=discord.Embed(description="🔄 Restarting bot service…", color=BLURPLE),
            ephemeral=True,
        )
        subprocess.Popen(  # noqa: S603
            ["sudo", "systemctl", "restart", svc],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⛔", row=0)
    async def stop_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._check_owner(interaction):
            return
        try:
            svc = self._service_name()
        except ValueError as exc:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ {exc}", color=RED), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=discord.Embed(description="⛔ Stopping bot service…", color=RED),
            ephemeral=True,
        )
        subprocess.Popen(  # noqa: S603
            ["sudo", "systemctl", "stop", svc],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @discord.ui.button(label="Update", style=discord.ButtonStyle.secondary, emoji="⬆️", row=0)
    async def update_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._check_owner(interaction):
            return
        try:
            svc = self._service_name()
        except ValueError as exc:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ {exc}", color=RED), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=discord.Embed(
                description="⬆️ Pulling latest code and upgrading dependencies…\nThe bot will restart automatically.",
                color=GOLD,
            ),
            ephemeral=True,
        )

        def _do_update() -> str:
            import os
            from pathlib import Path
            install_dir = Path(__file__).resolve().parents[1]
            venv_pip = install_dir / "venv" / "bin" / "pip"
            lines = []
            try:
                r = subprocess.run(
                    ["git", "-C", str(install_dir), "pull", "--ff-only"],
                    capture_output=True, text=True, timeout=60,
                )
                lines.append(r.stdout.strip() or r.stderr.strip())
            except Exception as exc:
                lines.append(f"git pull failed: {exc}")
                return "\n".join(lines)
            if venv_pip.exists():
                try:
                    r2 = subprocess.run(
                        [str(venv_pip), "install", "-q", "--upgrade",
                         "-r", str(install_dir / "requirements.txt")],
                        capture_output=True, text=True, timeout=120,
                    )
                    lines.append("pip upgrade: " + (r2.stderr.strip() or "ok"))
                except Exception as exc:
                    lines.append(f"pip upgrade failed: {exc}")
            return "\n".join(lines)

        await asyncio.to_thread(_do_update)
        subprocess.Popen(  # noqa: S603
            ["sudo", "systemctl", "restart", svc],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @discord.ui.button(label="Logs", style=discord.ButtonStyle.secondary, emoji="📋", row=1)
    async def logs_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._check_owner(interaction):
            return
        try:
            svc = self._service_name()
        except ValueError as exc:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ {exc}", color=RED), ephemeral=True
            )
            return
        result = subprocess.run(
            ["journalctl", "-u", svc, "-n", "25", "--no-pager", "--output=short"],
            capture_output=True, text=True, timeout=10,
        )
        log_text = result.stdout.strip() or result.stderr.strip() or "(no log output)"
        if len(log_text) > 3900:
            log_text = "…" + log_text[-3900:]
        embed = discord.Embed(
            title=f"📋 Last 25 log lines — {svc}",
            description=f"```\n{log_text}\n```",
            color=BLURPLE,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Refresh Panel", style=discord.ButtonStyle.secondary, emoji="🔁", row=1)
    async def refresh_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._check_owner(interaction):
            return
        embed = await _build_vmanage_embed(self.bot)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]


# ── Helper: build the vmanage embed ──────────────────────────────────────────

async def _build_vmanage_embed(bot: commands.Bot) -> discord.Embed:
    """Construct the vmanage status embed."""
    import re
    cfg = bot.config
    bot_name = cfg.get("name", "Vantage")
    service_name = cfg.get("service_name", "vantage")
    # Validate service name before passing to subprocess; log a warning if invalid.
    if not re.match(r'^[a-z][a-z0-9-]*$', service_name):
        log.warning(
            "service_name '%s' in config is invalid — falling back to 'vantage'", service_name
        )
        service_name = "vantage"
    prefix = cfg.get("prefix", "!")

    # Service status via systemctl
    svc_result = subprocess.run(
        ["systemctl", "is-active", service_name],
        capture_output=True, text=True, timeout=5,
    )
    svc_active = svc_result.returncode == 0
    svc_status = (
        "🟢 **running**" if svc_active else "🔴 **stopped**"
    )

    # Uptime
    uptime_str = "N/A"
    if bot.start_time:
        delta = datetime.now(timezone.utc) - bot.start_time
        h, rem = divmod(int(delta.total_seconds()), 3600)
        m, s = divmod(rem, 60)
        uptime_str = f"{h}h {m}m {s}s"

    # Guild / user counts
    guild_count = len(bot.guilds)
    user_count = sum(g.member_count or 0 for g in bot.guilds)

    # Latency
    latency_ms = round(bot.latency * 1000)

    # discord.py version
    dpy_ver = discord.__version__
    py_ver = platform.python_version()

    embed = discord.Embed(
        title=f"⚙️  {bot_name} — Management Panel",
        color=EMBED_COLOUR,
    )
    if bot.user:
        embed.set_thumbnail(url=bot.user.display_avatar.url)

    embed.add_field(
        name="🤖  Bot",
        value=(
            f"**Name:** {bot.user} \n"
            f"**ID:** `{bot.user.id}`\n"
            f"**Prefix:** `{prefix}`"
        ) if bot.user else "N/A",
        inline=True,
    )
    embed.add_field(
        name="📊  Stats",
        value=(
            f"**Guilds:** {guild_count}\n"
            f"**Users:** {user_count:,}\n"
            f"**Latency:** {latency_ms} ms"
        ),
        inline=True,
    )
    embed.add_field(
        name="⏱️  Uptime",
        value=uptime_str,
        inline=True,
    )
    embed.add_field(
        name="🔧  Service",
        value=(
            f"**Status:** {svc_status}\n"
            f"**Unit:** `{service_name}.service`"
        ),
        inline=True,
    )
    embed.add_field(
        name="🐍  Runtime",
        value=(
            f"**Python:** {py_ver}\n"
            f"**discord.py:** {dpy_ver}"
        ),
        inline=True,
    )
    embed.add_field(
        name="🧩  Cogs",
        value=f"{len(bot.extensions)} loaded",
        inline=True,
    )
    embed.set_footer(text="Use the buttons below to control the bot  •  Panel expires after 5 min")
    embed.timestamp = datetime.now(timezone.utc)
    return embed


# ── Admin cog ─────────────────────────────────────────────────────────────────

class Admin(commands.Cog, name="Admin"):
    """Owner-only bot management commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── helpers ───────────────────────────────────────────────────────────────

    def _ok(self, description: str) -> discord.Embed:
        return discord.Embed(description=f"✅ {description}", color=GREEN)

    def _err(self, description: str) -> discord.Embed:
        return discord.Embed(description=f"❌ {description}", color=RED)

    def _info(self, title: str, description: str = "") -> discord.Embed:
        return discord.Embed(title=title, description=description, color=EMBED_COLOUR)

    # ── basic commands ────────────────────────────────────────────────────────

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

        self.bot.config["prefix"] = new_prefix
        self.bot.command_prefix = commands.when_mentioned_or(new_prefix)

        from core.config import save_config
        save_config(self.bot.config)

        log.info("Prefix changed to '%s' by %s", new_prefix, ctx.author)
        await ctx.send(embed=self._ok(f"Prefix changed to `{new_prefix}`."))

    @commands.command()
    @commands.is_owner()
    async def shutdown(self, ctx: commands.Context) -> None:
        """Gracefully shut down the bot (will not restart).

        **Owner only.**
        """
        await ctx.send(embed=self._ok("Shutting down… 👋"))
        log.info("Shutdown requested by %s", ctx.author)
        await self.bot.close()

    # ── vmanage ───────────────────────────────────────────────────────────────

    @commands.command()
    @commands.is_owner()
    async def vmanage(self, ctx: commands.Context, botname: Optional[str] = None) -> None:
        """Interactive bot management panel.

        **Owner only.**

        If *botname* is given the panel only appears when the bot's configured
        name matches — useful when multiple Vantage instances share a server.

        Examples::

            {prefix}vmanage
            {prefix}vmanage MyBot
        """
        cfg_name = self.bot.config.get("name", "Vantage")
        if botname and botname.lower() != cfg_name.lower():
            return  # Not this bot instance

        embed = await _build_vmanage_embed(self.bot)
        view = VManageView(self.bot)
        await ctx.send(embed=embed, view=view)

    # ── servers ───────────────────────────────────────────────────────────────

    @commands.command()
    @commands.is_owner()
    async def servers(self, ctx: commands.Context) -> None:
        """List all guilds the bot is currently in.

        **Owner only.**
        """
        guilds = sorted(self.bot.guilds, key=lambda g: g.name.lower())
        lines = [
            f"`{g.id}` **{discord.utils.escape_markdown(g.name)}** — {(g.member_count or 0):,} members"
            for g in guilds
        ]

        # Paginate at ~1800 chars per embed description
        pages: list[str] = []
        page: list[str] = []
        length = 0
        for line in lines:
            if length + len(line) + 1 > 1800:
                pages.append("\n".join(page))
                page = [line]
                length = len(line)
            else:
                page.append(line)
                length += len(line) + 1
        if page:
            pages.append("\n".join(page))

        total = len(guilds)
        for i, content in enumerate(pages, 1):
            embed = discord.Embed(
                title=f"🌐 Guilds ({total}) — page {i}/{len(pages)}",
                description=content or "None",
                color=EMBED_COLOUR,
            )
            await ctx.send(embed=embed)

    # ── stats ─────────────────────────────────────────────────────────────────

    @commands.command()
    @commands.is_owner()
    async def stats(self, ctx: commands.Context) -> None:
        """Display detailed bot statistics.

        **Owner only.**
        """
        bot_name = self.bot.config.get("name", "Vantage")
        guild_count = len(self.bot.guilds)
        user_count = sum(g.member_count or 0 for g in self.bot.guilds)
        text_channels = sum(len(g.text_channels) for g in self.bot.guilds)
        voice_channels = sum(len(g.voice_channels) for g in self.bot.guilds)
        latency_ms = round(self.bot.latency * 1000)
        cog_count = len(self.bot.extensions)
        cmd_count = len(self.bot.commands)

        uptime_str = "N/A"
        if self.bot.start_time:
            delta = datetime.now(timezone.utc) - self.bot.start_time
            h, rem = divmod(int(delta.total_seconds()), 3600)
            m, s = divmod(rem, 60)
            uptime_str = f"{h}h {m}m {s}s"

        embed = discord.Embed(
            title=f"📊 {bot_name} Statistics",
            color=EMBED_COLOUR,
            timestamp=datetime.now(timezone.utc),
        )
        if self.bot.user:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        embed.add_field(
            name="🌐 Reach",
            value=(
                f"**Guilds:** {guild_count:,}\n"
                f"**Users:** {user_count:,}\n"
                f"**Text channels:** {text_channels:,}\n"
                f"**Voice channels:** {voice_channels:,}"
            ),
            inline=True,
        )
        embed.add_field(
            name="🤖 Bot",
            value=(
                f"**Latency:** {latency_ms} ms\n"
                f"**Uptime:** {uptime_str}\n"
                f"**Cogs loaded:** {cog_count}\n"
                f"**Commands:** {cmd_count}"
            ),
            inline=True,
        )
        embed.add_field(
            name="🐍 Runtime",
            value=(
                f"**Python:** {platform.python_version()}\n"
                f"**discord.py:** {discord.__version__}\n"
                f"**OS:** {platform.system()} {platform.release()}"
            ),
            inline=True,
        )
        await ctx.send(embed=embed)

    # ── announce ──────────────────────────────────────────────────────────────

    @commands.command()
    @commands.is_owner()
    async def announce(self, ctx: commands.Context, *, message: str) -> None:
        """Broadcast a message to every guild's system channel.

        **Owner only.**  Guilds without a system channel are skipped.

        Example::

            {prefix}announce Bot maintenance in 10 minutes!
        """
        sent = 0
        failed = 0
        skipped = 0

        embed = discord.Embed(
            title="📢 Announcement",
            description=message,
            color=GOLD,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Sent by {ctx.author}")

        for guild in self.bot.guilds:
            channel = guild.system_channel
            if channel is None:
                skipped += 1
                continue
            try:
                await channel.send(embed=embed)
                sent += 1
            except discord.Forbidden:
                failed += 1
            except discord.HTTPException:
                failed += 1

        summary = self._ok(
            f"Announcement sent to **{sent}** guild(s).\n"
            f"Skipped (no system channel): **{skipped}**\n"
            f"Failed (no permission): **{failed}**"
        )
        await ctx.send(embed=summary)

    # ── setactivity ───────────────────────────────────────────────────────────

    @commands.command()
    @commands.is_owner()
    async def setactivity(
        self,
        ctx: commands.Context,
        activity_type: str,
        *,
        text: str,
    ) -> None:
        """Change the bot's activity/presence.

        **Owner only.**

        ``activity_type`` must be one of: ``playing``, ``watching``, ``listening``, ``competing``.

        Available template tokens in *text*: ``{guild_count}``, ``{prefix}``.

        Examples::

            {prefix}setactivity playing Minecraft
            {prefix}setactivity listening lo-fi beats
            {prefix}setactivity watching over {guild_count} servers
        """
        type_map = {
            "playing": discord.ActivityType.playing,
            "watching": discord.ActivityType.watching,
            "listening": discord.ActivityType.listening,
            "competing": discord.ActivityType.competing,
        }
        act_type = type_map.get(activity_type.lower())
        if act_type is None:
            await ctx.send(
                embed=self._err(
                    f"Unknown activity type `{activity_type}`.\n"
                    "Choose: `playing`, `watching`, `listening`, `competing`."
                )
            )
            return

        # Replace simple template tokens
        text = text.replace("{guild_count}", str(len(self.bot.guilds)))
        text = text.replace("{prefix}", self.bot.config.get("prefix", "!"))

        await self.bot.change_presence(
            activity=discord.Activity(type=act_type, name=text)
        )

        # Persist to config so it survives restarts
        self.bot.config["activity"] = text
        from core.config import save_config
        save_config(self.bot.config)

        log.info("Activity changed to %s '%s' by %s", activity_type, text, ctx.author)
        await ctx.send(embed=self._ok(f"Activity set to **{activity_type}** `{text}`."))

    # ── botinfo ───────────────────────────────────────────────────────────────

    @commands.command()
    async def botinfo(self, ctx: commands.Context) -> None:
        """Show basic information about this bot."""
        cfg = self.bot.config
        bot_name = cfg.get("name", "Vantage")
        prefix = cfg.get("prefix", "!")
        description = cfg.get("description", "")

        embed = discord.Embed(
            title=f"ℹ️ About {bot_name}",
            description=description,
            color=EMBED_COLOUR,
        )
        if self.bot.user:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.add_field(name="Prefix", value=f"`{prefix}`", inline=True)
        embed.add_field(name="Guilds", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="discord.py", value=discord.__version__, inline=True)
        embed.set_footer(text=f"Powered by Vantage • Python {platform.python_version()}")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
