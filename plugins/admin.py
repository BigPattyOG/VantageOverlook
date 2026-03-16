"""Built-in Admin plugin — owner-only bot management commands.

Commands
--------
``[p]ping``           — Latency check.
``[p]load``           — Load an extension.
``[p]unload``         — Unload an extension.
``[p]reload``         — Reload an extension.
``[p]plugins``        — List loaded extensions.
``[p]prefix``         — Get or change the command prefix.
``[p]maintenance``    — Toggle maintenance mode on/off.
``[p]invite``         — Show the bot's invite URL (Administrator permission).
``[p]version``        — Show the current bot version and git info.
``[p]shutdown``       — Gracefully shut down the bot.
``[p]vmanage``        — Interactive bot management panel (with buttons).
``[p]servers``        — List all guilds the bot is in.
``[p]stats``          — Detailed bot statistics.
``[p]announce``       — Broadcast a message to all guild system channels.
``[p]setactivity``    — Change the bot's activity/presence.
``[p]botinfo``        — Show basic bot information.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands

from framework.embeds import VantageEmbed, TEAL, GREEN, RED, GOLD, BLURPLE

log = logging.getLogger("vprod.admin")


# ── Management panel view ─────────────────────────────────────────────────────

class VManageView(discord.ui.View):
    """Interactive buttons for the vmanage management panel."""

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.message: Optional[discord.Message] = None

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
                    description="Only bot owners can use these controls.",
                    color=RED,
                ),
                ephemeral=True,
            )
            return False
        return True

    def _probe_service_access(self, svc: str) -> tuple[bool, str]:
        """Non-destructively test whether sudo systemctl is available.

        Uses ``sudo -n`` (non-interactive) so it never blocks on a password
        prompt.  Returns ``(True, "")`` when access is confirmed, or
        ``(False, error_message)`` when it is not.

        The probe runs ``sudo -n systemctl start --dry-run <svc>`` so that the
        test command is covered by the same sudoers rule recommended to users
        (restart/stop/start).  ``--dry-run`` makes start a no-op.
        """
        if not shutil.which("systemctl"):
            return False, "systemctl is not installed on this system."
        if not shutil.which("sudo"):
            return False, (
                "sudo is not installed. "
                "Use `vmanage --restart` from the server terminal instead."
            )
        try:
            r = subprocess.run(
                ["sudo", "-n", "systemctl", "start", "--dry-run", svc],
                capture_output=True, text=True, timeout=5,
            )
        except subprocess.TimeoutExpired:
            return False, (
                "Timed out waiting for `sudo systemctl` to respond. "
                "The system may be overloaded or sudo is hung."
            )
        except OSError as exc:
            return False, f"Failed to launch `sudo systemctl`: {exc}"
        stderr_lower = r.stderr.lower()
        # sudo prefixes its own error messages with "sudo:" at the start of a line.
        # A service name will never match this pattern.
        if r.stderr.lstrip().startswith("sudo:") and any(
            kw in stderr_lower
            for kw in ("password", "not allowed", "not permitted", "no tty", "sorry")
        ):
            # Resolve the real systemctl path so the printed sudoers rule
            # matches the actual binary (commonly /usr/bin/systemctl on Ubuntu).
            systemctl_path = shutil.which("systemctl") or "/usr/bin/systemctl"
            return False, (
                f"The bot process does not have permission to run `sudo systemctl` "
                f"commands for `{svc}.service`.\n\n"
                "To fix this, add a passwordless sudo rule for the bot user. "
                "Run the following **on the server as root**, replacing `botuser` "
                "with the user the bot runs as (e.g. `vprodbot`):\n"
                f"```\necho 'botuser ALL=(ALL) NOPASSWD: "
                f"{systemctl_path} restart {svc}, "
                f"{systemctl_path} stop {svc}, "
                f"{systemctl_path} start {svc}, "
                f"{systemctl_path} start --dry-run {svc}'"
                f" | tee /etc/sudoers.d/{svc}-control\nchmod 440 /etc/sudoers.d/{svc}-control\n```\n"
                "Alternatively, use `vmanage --restart` / `vmanage --stop` "
                "from the server terminal."
            )
        # sudo passed; check whether systemctl itself ran successfully.
        # For `start --dry-run`: exit 0 = ok, exit 5 = unit not found.
        # Both confirm that sudo accepted the command.  Anything else (e.g.
        # exit 1 with "Failed to connect to bus") indicates a host-level error.
        if r.returncode not in (0, 5):
            detail = (r.stderr.strip() or r.stdout.strip() or f"exit code {r.returncode}")
            return False, (
                f"systemctl returned an unexpected error for `{svc}.service` "
                f"(exit {r.returncode}):\n```\n{detail}\n```\n"
                "This may indicate that systemd is not running on this host, "
                "or that the service name is incorrect."
            )
        return True, ""

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

    @discord.ui.button(label="Restart", style=discord.ButtonStyle.primary, row=0)
    async def restart_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._check_owner(interaction):
            return
        try:
            svc = self._service_name()
        except ValueError as exc:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"{exc}", color=RED), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        can_control, err_msg = await asyncio.to_thread(self._probe_service_access, svc)
        if not can_control:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Service Control Unavailable",
                    description=err_msg,
                    color=RED,
                ),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            embed=discord.Embed(description="Restarting bot service...", color=BLURPLE),
            ephemeral=True,
        )
        subprocess.Popen(  # noqa: S603
            ["sudo", "systemctl", "restart", svc],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, row=0)
    async def stop_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._check_owner(interaction):
            return
        try:
            svc = self._service_name()
        except ValueError as exc:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"{exc}", color=RED), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        can_control, err_msg = await asyncio.to_thread(self._probe_service_access, svc)
        if not can_control:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Service Control Unavailable",
                    description=err_msg,
                    color=RED,
                ),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            embed=discord.Embed(description="Stopping bot service...", color=RED),
            ephemeral=True,
        )
        subprocess.Popen(  # noqa: S603
            ["sudo", "systemctl", "stop", svc],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @discord.ui.button(label="Update", style=discord.ButtonStyle.secondary, row=0)
    async def update_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._check_owner(interaction):
            return
        try:
            svc = self._service_name()
        except ValueError as exc:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"{exc}", color=RED), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        can_control, err_msg = await asyncio.to_thread(self._probe_service_access, svc)
        if not can_control:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Service Control Unavailable",
                    description=err_msg,
                    color=RED,
                ),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            embed=discord.Embed(
                description="Pulling latest code and upgrading dependencies...\nThe bot will restart automatically.",
                color=GOLD,
            ),
            ephemeral=True,
        )

        def _do_update() -> str:
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

    @discord.ui.button(label="Logs", style=discord.ButtonStyle.secondary, row=1)
    async def logs_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._check_owner(interaction):
            return
        try:
            svc = self._service_name()
        except ValueError as exc:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"{exc}", color=RED), ephemeral=True
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
            title=f"Last 25 log lines — {svc}",
            description=f"```\n{log_text}\n```",
            color=TEAL,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Refresh Panel", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._check_owner(interaction):
            return
        embed = await _build_vmanage_embed(self.bot)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException as exc:
                log.debug(
                    "Could not disable vmanage panel buttons (message deleted or no permission): %s",
                    exc,
                )


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
            "service_name '%s' in config is invalid — falling back to 'vprod'", service_name
        )
        service_name = "vprod"
    prefix = cfg.get("prefix", "!")

    # Service status via systemctl
    try:
        svc_result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True, text=True, timeout=5,
        )
        svc_active = svc_result.returncode == 0
    except FileNotFoundError:
        svc_active = False
    svc_status = "🟢 **running**" if svc_active else "🔴 **stopped**"

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

    # discord.py / python versions
    dpy_ver = discord.__version__
    py_ver = platform.python_version()

    embed = discord.Embed(
        title=f"⚙️  {bot_name} — Management Panel",
        color=TEAL,
        timestamp=datetime.now(timezone.utc),
    )
    if bot.user:
        embed.set_thumbnail(url=bot.user.display_avatar.url)

    embed.add_field(
        name="🤖  Bot",
        value=(
            f"**Name:** {bot.user}\n"
            f"**ID:** `{bot.user.id}`\n"
            f"**Prefix:** `{prefix}`"
        ) if bot.user else "N/A",
        inline=True,
    )
    embed.add_field(
        name="📊  Stats",
        value=(
            f"**Guilds:** {guild_count:,}\n"
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
        name="🧩  Extensions",
        value=f"{len(bot.extensions)} loaded",
        inline=True,
    )
    embed.set_footer(text="Use the buttons below to control the bot  •  Expires in 5 min")
    return embed


# ── Admin plugin ─────────────────────────────────────────────────────────────

class Admin(commands.Cog, name="Owner"):
    """Owner-only bot management commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── embed helpers ─────────────────────────────────────────────────────────

    def _ok(self, description: str) -> discord.Embed:
        return VantageEmbed.ok(description)

    def _err(self, description: str) -> discord.Embed:
        return VantageEmbed.error("Error", description)

    def _info(self, title: str, description: str = "") -> discord.Embed:
        return VantageEmbed.info(title, description)

    # ── basic commands ────────────────────────────────────────────────────────

    @commands.command()
    async def ping(self, ctx: commands.Context) -> None:
        """Check the bot's latency and response time."""
        api_ms = round(self.bot.latency * 1000)
        start = time.perf_counter()
        msg = await ctx.send(
            embed=discord.Embed(description="Measuring...", color=TEAL)
        )
        rtt_ms = round((time.perf_counter() - start) * 1000)
        embed = discord.Embed(title="🏓  Pong!", color=TEAL)
        embed.add_field(name="API Latency", value=f"`{api_ms} ms`", inline=True)
        embed.add_field(name="Round-trip", value=f"`{rtt_ms} ms`", inline=True)
        await msg.edit(embed=embed)

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
            await ctx.send(embed=self._ok(f"Loaded **{extension}**."))
        except commands.ExtensionAlreadyLoaded:
            await ctx.send(embed=self._err(f"**{extension}** is already loaded."))
        except commands.ExtensionNotFound:
            await ctx.send(embed=self._err(f"Extension **{extension}** was not found."))
        except Exception as exc:
            log.exception("Failed to load extension: %s", extension)
            await ctx.send(embed=self._err(f"Failed to load **{extension}**:\n```\n{exc}\n```"))

    @commands.command()
    @commands.is_owner()
    async def unload(self, ctx: commands.Context, extension: str) -> None:
        """Unload a running extension (cog).

        **Owner only.**
        """
        if extension in ("plugins.admin",):
            await ctx.send(embed=self._err("You cannot unload the built-in admin plugin."))
            return
        try:
            await self.bot.unload_extension(extension)
            log.info("Unloaded extension: %s (by %s)", extension, ctx.author)
            await ctx.send(embed=self._ok(f"Unloaded **{extension}**."))
        except commands.ExtensionNotLoaded:
            await ctx.send(embed=self._err(f"**{extension}** is not currently loaded."))
        except Exception as exc:
            log.exception("Failed to unload extension: %s", extension)
            await ctx.send(embed=self._err(f"Failed to unload **{extension}**:\n```\n{exc}\n```"))

    @commands.command()
    @commands.is_owner()
    async def reload(self, ctx: commands.Context, extension: str) -> None:
        """Reload an extension (cog) — picks up code changes.

        **Owner only.**
        """
        try:
            await self.bot.reload_extension(extension)
            log.info("Reloaded extension: %s (by %s)", extension, ctx.author)
            await ctx.send(embed=self._ok(f"Reloaded **{extension}**."))
        except commands.ExtensionNotLoaded:
            await ctx.send(embed=self._err(f"**{extension}** is not loaded — use `load` first."))
        except Exception as exc:
            log.exception("Failed to reload extension: %s", extension)
            await ctx.send(embed=self._err(f"Failed to reload **{extension}**:\n```\n{exc}\n```"))

    @commands.command(name="plugins")
    @commands.is_owner()
    async def list_plugins(self, ctx: commands.Context) -> None:
        """List all currently loaded extensions and their display names.

        **Owner only.**
        """
        if not self.bot.extensions:
            embed = self._info("Loaded Extensions — 0", "None")
            await ctx.send(embed=embed)
            return

        # Build a reverse map: module path → plugin display name.
        module_to_name: dict[str, str] = {
            getattr(type(cog), "__module__", ""): cog.qualified_name
            for cog in self.bot.cogs.values()
            if getattr(type(cog), "__module__", "")
        }

        lines = []
        for ext_key in sorted(self.bot.extensions.keys()):
            friendly = module_to_name.get(ext_key)
            if friendly:
                lines.append(f"**{friendly}** — `{ext_key}`")
            else:
                lines.append(f"`{ext_key}`")

        embed = self._info(
            f"Loaded Extensions — {len(lines)}",
            "\n".join(lines),
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
            await ctx.send(embed=self._info("Prefix", f"Current prefix: `{current}`"))
            return

        self.bot.config["prefix"] = new_prefix
        self.bot.command_prefix = commands.when_mentioned_or(new_prefix)

        from framework.config import save_config
        save_config(self.bot.config)

        log.info("Prefix changed to '%s' by %s", new_prefix, ctx.author)
        await ctx.send(embed=self._ok(f"Prefix changed to `{new_prefix}`."))

    @commands.command()
    @commands.is_owner()
    async def shutdown(self, ctx: commands.Context) -> None:
        """Gracefully shut down the bot (will not restart).

        **Owner only.**
        """
        await ctx.send(embed=self._ok("Shutting down..."))
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
        view.message = await ctx.send(embed=embed, view=view)

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
                title=f"🏠  Guilds ({total}) — page {i}/{len(pages)}",
                description=content or "None",
                color=TEAL,
                timestamp=datetime.now(timezone.utc),
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
            title=f"📊  {bot_name} — Statistics",
            color=TEAL,
            timestamp=datetime.now(timezone.utc),
        )
        if self.bot.user:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        embed.add_field(
            name="🌐  Reach",
            value=(
                f"**Guilds:** {guild_count:,}\n"
                f"**Users:** {user_count:,}\n"
                f"**Text channels:** {text_channels:,}\n"
                f"**Voice channels:** {voice_channels:,}"
            ),
            inline=True,
        )
        embed.add_field(
            name="🤖  Bot",
            value=(
                f"**Latency:** {latency_ms} ms\n"
                f"**Uptime:** {uptime_str}\n"
                f"**Extensions:** {cog_count}\n"
                f"**Commands:** {cmd_count}"
            ),
            inline=True,
        )
        embed.add_field(
            name="🐍  Runtime",
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
            title="📢  Announcement",
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
            f"Skipped — no system channel: **{skipped}**\n"
            f"Failed — no permission: **{failed}**"
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
            "playing":    discord.ActivityType.playing,
            "watching":   discord.ActivityType.watching,
            "listening":  discord.ActivityType.listening,
            "competing":  discord.ActivityType.competing,
        }
        act_type = type_map.get(activity_type.lower())
        if act_type is None:
            valid = ", ".join(f"`{k}`" for k in type_map)
            await ctx.send(
                embed=self._err(
                    f"Unknown activity type **{activity_type}**.\n"
                    f"Valid types: {valid}."
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
        from framework.config import save_config
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

        embed = VantageEmbed.info(
            f"ℹ️  About {bot_name}",
            description,
            bot=self.bot,
            thumbnail=True,
        )
        embed.add_field(name="Prefix", value=f"`{prefix}`", inline=True)
        embed.add_field(name="Guilds", value=f"{len(self.bot.guilds):,}", inline=True)
        embed.add_field(name="discord.py", value=discord.__version__, inline=True)
        await ctx.send(embed=embed)

    # ── maintenance ───────────────────────────────────────────────────────────

    @commands.command()
    @commands.is_owner()
    async def maintenance(self, ctx: commands.Context, state: str = "") -> None:
        """Toggle maintenance mode on or off.

        **Owner only.**  While maintenance is active, all non-owner commands
        receive a maintenance notice instead of running normally.  Owners are
        unaffected and can still use every command.

        Examples::

            {prefix}maintenance on
            {prefix}maintenance off
            {prefix}maintenance          (shows current state)
        """
        current: bool = self.bot.config.get("maintenance", False)

        if state.lower() in ("on", "enable", "true", "1", "yes"):
            new_state = True
        elif state.lower() in ("off", "disable", "false", "0", "no"):
            new_state = False
        elif state == "":
            label = "**ON** 🔧" if current else "**OFF** ✅"
            await ctx.send(embed=self._info("Maintenance Mode", f"Currently: {label}"))
            return
        else:
            await ctx.send(embed=self._err("Use `on` or `off`."))
            return

        self.bot.config["maintenance"] = new_state
        from framework.config import save_config
        save_config(self.bot.config)
        log.info("Maintenance mode set to %s by %s", new_state, ctx.author)

        if new_state:
            await ctx.send(embed=VantageEmbed.warn(
                "🔧  Maintenance Mode Enabled",
                "The bot is now in maintenance mode.\n"
                "Non-owner commands will return a maintenance notice.\n"
                "Run `maintenance off` when done.",
            ))
        else:
            await ctx.send(embed=self._ok("Maintenance mode **disabled**. The bot is back online."))

    # ── invite ────────────────────────────────────────────────────────────────

    @commands.command()
    @commands.is_owner()
    async def invite(self, ctx: commands.Context) -> None:
        """Generate an invite URL for this bot with Administrator permission.

        **Owner only.**  Use this to add the bot to a new server or to
        re-invite it with full permissions if it is missing access.
        """
        if self.bot.application_id is None:
            await ctx.send(embed=self._err(
                "Application ID not available yet — try again in a moment."
            ))
            return

        perms = discord.Permissions(administrator=True)
        url = discord.utils.oauth_url(
            self.bot.application_id,
            permissions=perms,
            scopes=("bot", "applications.commands"),
        )
        embed = VantageEmbed.info(
            "🔗  Bot Invite Link",
            f"Click the link below to add the bot to a server with **Administrator** permission.\n\n"
            f"[Invite {self.bot.user.display_name if self.bot.user else 'Bot'}]({url})",
            bot=self.bot,
        )
        embed.set_footer(text="Only share this link with people you trust.")
        await ctx.send(embed=embed, ephemeral=False)

    # ── version ───────────────────────────────────────────────────────────────

    @commands.command()
    async def version(self, ctx: commands.Context) -> None:
        """Show the current bot version and git commit info."""
        from framework.embeds import get_version
        from pathlib import Path
        import subprocess as _sp

        ver = get_version()
        install_dir = Path(__file__).resolve().parents[1]

        git_hash = "unknown"
        git_branch = "unknown"
        git_date = "unknown"
        try:
            git_hash = _sp.run(
                ["git", "-C", str(install_dir), "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip() or "unknown"
            git_branch = _sp.run(
                ["git", "-C", str(install_dir), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip() or "unknown"
            git_date = _sp.run(
                ["git", "-C", str(install_dir), "log", "-1", "--format=%ci"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip() or "unknown"
        except Exception:
            pass

        embed = VantageEmbed.info(
            f"📦  {self.bot.config.get('name', 'Vantage')} v{ver}",
            bot=self.bot,
            thumbnail=True,
        )
        embed.add_field(name="Version", value=f"`{ver}`", inline=True)
        embed.add_field(name="Branch", value=f"`{git_branch}`", inline=True)
        embed.add_field(name="Commit", value=f"`{git_hash}`", inline=True)
        embed.add_field(name="Commit Date", value=git_date or "—", inline=True)
        embed.add_field(name="discord.py", value=discord.__version__, inline=True)
        embed.add_field(name="Python", value=platform.python_version(), inline=True)
        await ctx.send(embed=embed)


    # ── plugin management ─────────────────────────────────────────────────────

    @commands.group(name="plugin", invoke_without_command=True)
    @commands.is_owner()
    async def plugin_group(self, ctx: commands.Context) -> None:
        """Manage external (local/private) plugins.

        **Owner only.**  Run ``!plugin`` on its own to see the sub-commands.

        Sub-commands::

            {prefix}plugin list             — Show all registered external plugins
            {prefix}plugin install <path>   — Register a local plugin
            {prefix}plugin remove  <name>   — Remove from registry (keeps files)
            {prefix}plugin enable  <name>   — Enable a disabled plugin
            {prefix}plugin disable <name>   — Disable without removing
            {prefix}plugin reload  <name>   — Hot-reload a running plugin
            {prefix}plugin verify           — Check all plugin integrity hashes
        """
        embed = self._info(
            "📦  Plugin Management",
            (
                f"`{ctx.clean_prefix}plugin list` — list registered external plugins\n"
                f"`{ctx.clean_prefix}plugin install <path>` — register a local plugin\n"
                f"`{ctx.clean_prefix}plugin remove <name>` — unregister\n"
                f"`{ctx.clean_prefix}plugin enable <name>` — enable\n"
                f"`{ctx.clean_prefix}plugin disable <name>` — disable\n"
                f"`{ctx.clean_prefix}plugin reload <name>` — hot-reload\n"
                f"`{ctx.clean_prefix}plugin verify` — verify integrity hashes"
            ),
        )
        await ctx.send(embed=embed)

    @plugin_group.command(name="list")
    @commands.is_owner()
    async def plugin_list(self, ctx: commands.Context) -> None:
        """List all registered external plugins and their status."""
        from framework.plugin_manager import PluginManager
        mgr = PluginManager()
        reg = mgr.get_ext_plugins()

        if not reg:
            await ctx.send(embed=self._info(
                "📦  External Plugins",
                "No external plugins registered.\n"
                f"Add one with `{ctx.clean_prefix}plugin install <path>`.",
            ))
            return

        lines = []
        for name, info in reg.items():
            enabled = info.get("enabled", True)
            loaded = f"_vp_ext.{name}" in self.bot.extensions
            manifest = info.get("manifest", {})
            ver = manifest.get("version", "?")
            status = "🟢 loaded" if loaded else ("🟡 enabled" if enabled else "🔴 disabled")
            lines.append(f"**{name}** `v{ver}` — {status}")
            if info.get("path"):
                lines.append(f"  └ `{info['path']}`")

        embed = self._info(f"📦  External Plugins — {len(reg)}", "\n".join(lines))
        await ctx.send(embed=embed)

    @plugin_group.command(name="install")
    @commands.is_owner()
    async def plugin_install(self, ctx: commands.Context, path: str) -> None:
        """Register a local plugin directory or file.

        **Owner only.**

        *path* must be an absolute path to a plugin directory (containing
        ``__init__.py``) or a single ``.py`` file.  The plugin is validated
        (path containment check + hash computed) and added to the registry.
        After registering, load it with ``!load _vp_ext.<name>``.

        Example::

            {prefix}plugin install /var/lib/vprod/ext_plugins/welcome
        """
        from pathlib import Path
        from framework.config import resolve_ext_plugins_dir
        from framework.plugin_loader import PluginLoader, compute_plugin_hash, _read_manifest
        from framework.plugin_manager import PluginManager

        raw = Path(path).expanduser()
        ext_dir = resolve_ext_plugins_dir(self.bot.config)
        loader = PluginLoader(ext_dir)

        resolved = loader._safe_resolve(raw)
        if resolved is None:
            await ctx.send(embed=self._err(
                f"Path `{path}` is outside the allowed plugins directory "
                f"(`{ext_dir}`).\n"
                "Move the plugin there first, then run this command again."
            ))
            return

        if not resolved.exists():
            await ctx.send(embed=self._err(f"Path does not exist: `{resolved}`"))
            return

        name = resolved.stem if resolved.is_file() else resolved.name
        if not name.isidentifier():
            await ctx.send(embed=self._err(
                f"`{name}` is not a valid Python identifier. "
                "Rename the plugin directory/file and try again."
            ))
            return

        manifest_root = resolved if resolved.is_dir() else resolved.parent
        manifest = _read_manifest(manifest_root)
        plugin_hash = compute_plugin_hash(resolved)

        mgr = PluginManager()
        mgr.register_ext_plugin(
            name=name,
            path=str(resolved),
            plugin_hash=plugin_hash,
            manifest=manifest,
            enabled=True,
        )

        display = manifest.get("name", name)
        ver = manifest.get("version", "?")
        embed = self._ok(
            f"Registered external plugin **{display}** `v{ver}`.\n"
            f"Load it now with: `{ctx.clean_prefix}load _vp_ext.{name}`"
        )
        log.info("Registered external plugin '%s' from %s by %s", name, resolved, ctx.author)
        await ctx.send(embed=embed)

    @plugin_group.command(name="remove")
    @commands.is_owner()
    async def plugin_remove(self, ctx: commands.Context, name: str) -> None:
        """Remove an external plugin from the registry (does not delete files).

        **Owner only.**  Unload it from Discord first with
        ``!unload _vp_ext.<name>``.
        """
        from framework.plugin_manager import PluginManager
        mgr = PluginManager()
        try:
            mgr.remove_ext_plugin(name)
            await ctx.send(embed=self._ok(
                f"External plugin **{name}** removed from registry.\n"
                "Files on disk are unchanged."
            ))
            log.info("Removed external plugin '%s' from registry by %s", name, ctx.author)
        except ValueError as exc:
            await ctx.send(embed=self._err(str(exc)))

    @plugin_group.command(name="enable")
    @commands.is_owner()
    async def plugin_enable(self, ctx: commands.Context, name: str) -> None:
        """Enable a disabled external plugin."""
        from framework.plugin_manager import PluginManager
        mgr = PluginManager()
        try:
            mgr.enable_ext_plugin(name, enabled=True)
            await ctx.send(embed=self._ok(
                f"External plugin **{name}** enabled.\n"
                f"Load it with: `{ctx.clean_prefix}load _vp_ext.{name}`"
            ))
        except ValueError as exc:
            await ctx.send(embed=self._err(str(exc)))

    @plugin_group.command(name="disable")
    @commands.is_owner()
    async def plugin_disable(self, ctx: commands.Context, name: str) -> None:
        """Disable an external plugin (unload and mark as disabled)."""
        from framework.plugin_manager import PluginManager
        mgr = PluginManager()
        try:
            ext_path = f"_vp_ext.{name}"
            if ext_path in self.bot.extensions:
                await self.bot.unload_extension(ext_path)
            mgr.enable_ext_plugin(name, enabled=False)
            await ctx.send(embed=self._ok(
                f"External plugin **{name}** disabled and unloaded."
            ))
        except ValueError as exc:
            await ctx.send(embed=self._err(str(exc)))
        except Exception as exc:
            await ctx.send(embed=self._err(f"Failed to unload: `{exc}`"))

    @plugin_group.command(name="reload")
    @commands.is_owner()
    async def plugin_reload(self, ctx: commands.Context, name: str) -> None:
        """Hot-reload an external plugin (picks up file changes).

        **Owner only.**  The bot does not need to restart.
        """
        from framework.config import resolve_ext_plugins_dir
        from framework.plugin_loader import PluginLoader
        from framework.plugin_manager import PluginManager

        mgr = PluginManager()
        reg = mgr.get_ext_plugins()
        if name not in reg:
            await ctx.send(embed=self._err(
                f"External plugin **{name}** is not registered.\n"
                f"Register it first with `{ctx.clean_prefix}plugin install <path>`."
            ))
            return

        ext_dir = resolve_ext_plugins_dir(self.bot.config)
        loader = PluginLoader(ext_dir)
        async with ctx.typing():
            try:
                ep = await loader.reload_one(self.bot, name, reg)
                # Update stored hash after successful reload
                mgr.update_ext_plugin_hash(name, ep.current_hash)
                await ctx.send(embed=self._ok(
                    f"External plugin **{ep.display_name}** `v{ep.version}` reloaded."
                ))
                log.info("Reloaded external plugin '%s' by %s", name, ctx.author)
            except Exception as exc:
                await ctx.send(embed=self._err(
                    f"Failed to reload **{name}**:\n```\n{exc}\n```"
                ))

    @plugin_group.command(name="verify")
    @commands.is_owner()
    async def plugin_verify(self, ctx: commands.Context) -> None:
        """Verify SHA-256 integrity hashes for all external plugins.

        **Owner only.**  Compares the hash stored at install time with the
        current hash of the plugin files.  A mismatch means files changed
        since the plugin was registered (e.g. a ``git pull`` update).

        Run ``!plugin reload <name>`` after updating to refresh the stored hash.
        """
        from framework.config import resolve_ext_plugins_dir
        from framework.plugin_loader import compute_plugin_hash, _read_manifest
        from framework.plugin_manager import PluginManager
        from pathlib import Path

        mgr = PluginManager()
        reg = mgr.get_ext_plugins()

        if not reg:
            await ctx.send(embed=self._info("🔐  Plugin Verify", "No external plugins registered."))
            return

        lines: list[str] = []
        for name, info in reg.items():
            path = Path(info.get("path", ""))
            if not path.exists():
                lines.append(f"❓ **{name}** — path not found: `{path}`")
                continue
            current = compute_plugin_hash(path)
            stored = info.get("hash", "")
            if not stored:
                lines.append(f"⬜ **{name}** — no stored hash (run `!plugin install` to register properly)")
            elif current == stored:
                lines.append(f"✅ **{name}** — hash OK")
            else:
                lines.append(
                    f"⚠️ **{name}** — hash mismatch (files changed since install)\n"
                    f"  Run `{ctx.clean_prefix}plugin reload {name}` to update hash"
                )

        embed = self._info("🔐  Plugin Integrity", "\n".join(lines))
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
