from __future__ import annotations

from collections import Counter
from typing import Optional

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify

from .models import ErrorKind
from .registry import grouped_public_errors
from .reporter import ErrorReporter
from .utils import (
    fixable_error_reply,
    internal_lookup_embed,
    not_found_embed,
    public_code_for_error,
    public_error_embed,
    public_registry_for_bot,
    resolve_system_prefix,
)


class PublicErrorsPager(discord.ui.View):
    def __init__(self, ctx: commands.Context, pages: list[discord.Embed], *, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.pages = pages
        self.index = 0
        self.message: Optional[discord.Message] = None
        self._sync()

    def _sync(self) -> None:
        total = max(len(self.pages), 1)
        self.prev_button.disabled = self.index <= 0
        self.next_button.disabled = self.index >= total - 1
        self.page_button.label = f"{self.index + 1}/{total}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user.id == self.ctx.author.id:
            return True
        await interaction.response.send_message("Only the command invoker can use these buttons.", ephemeral=True)
        return False

    async def update(self, interaction: discord.Interaction) -> None:
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="<", style=discord.ButtonStyle.secondary, row=0)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.index > 0:
            self.index -= 1
        await self.update(interaction)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.secondary, disabled=True, row=0)
    async def page_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()

    @discord.ui.button(label=">", style=discord.ButtonStyle.secondary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.index < len(self.pages) - 1:
            self.index += 1
        await self.update(interaction)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, row=0)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            await interaction.message.delete()
        except discord.HTTPException:
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(view=self)
        self.stop()


class VErrors(commands.Cog):
    __author__ = "OpenAI"
    __version__ = "2.1.0"

    default_global_settings = {
        "internal_errors": [],
        "max_internal_errors": 250,
    }

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=7028459110, force_registration=True)
        self.config.register_global(**self.default_global_settings)
        self.reporter = ErrorReporter(bot, self.config)
        self._public_registry_cache: Optional[dict] = None

    def format_help_for_context(self, ctx: commands.Context) -> str:
        pre = super().format_help_for_context(ctx)
        return f"{pre}\n\nVersion: {self.__version__}"

    def rebuild_registry(self) -> None:
        self._public_registry_cache = public_registry_for_bot(self.bot)

    def get_public_error_code(self, ctx: commands.Context, error: Exception) -> Optional[str]:
        return public_code_for_error(ctx, error)

    def build_fixable_error_embed(self, ctx: commands.Context, error: Exception, code: Optional[str] = None) -> Optional[discord.Embed]:
        code = code or public_code_for_error(ctx, error)
        if code is None:
            return None
        return fixable_error_reply(ctx, error, code)

    def build_internal_lookup_embed(self, code: str) -> discord.Embed:
        return internal_lookup_embed(code)

    def get_system_prefix(self, ctx: commands.Context) -> str:
        return resolve_system_prefix(ctx)

    def get_public_registry(self) -> dict:
        if self._public_registry_cache is None:
            self.rebuild_registry()
        return dict(self._public_registry_cache or {})

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if ctx.command and ctx.command.has_error_handler():
            return
        if ctx.cog and getattr(ctx.cog, "has_error_handler", lambda: False)():
            return
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.UserFeedbackCheckFailure):
            return

        public_code = public_code_for_error(ctx, error)
        if public_code is not None:
            try:
                await ctx.send(embed=fixable_error_reply(ctx, error, public_code))
            except discord.HTTPException:
                pass
            return

        system = resolve_system_prefix(ctx)
        await self.reporter.report_command_exception(ctx, error, system)

    async def report_interaction_error(self, *, interaction: discord.Interaction, error: Exception, system: str = "SYS", command_name: Optional[str] = None, location: Optional[str] = None) -> str:
        return await self.reporter.report_generic_exception(
            system=system,
            kind=ErrorKind.UI,
            summary=f"{type(error).__name__}: {error}",
            error=error,
            interaction=interaction,
            location=location,
            command_name=command_name,
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            user_id=interaction.user.id if interaction.user else None,
        )

    async def report_task_error(self, *, error: Exception, system: str = "SYS", command_name: Optional[str] = None, location: Optional[str] = None, guild_id: Optional[int] = None, channel_id: Optional[int] = None, user_id: Optional[int] = None) -> str:
        return await self.reporter.report_generic_exception(
            system=system,
            kind=ErrorKind.TASK,
            summary=f"{type(error).__name__}: {error}",
            error=error,
            interaction=None,
            location=location,
            command_name=command_name,
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
        )

    @commands.command(name="error")
    async def error_lookup(self, ctx: commands.Context, code: str) -> None:
        code = code.upper().strip()
        registry = self.get_public_registry()
        info = registry.get(code)
        if info is not None:
            await ctx.send(embed=public_error_embed(info))
            return

        entries = await self.config.internal_errors()
        if any(entry["code"] == code for entry in entries):
            await ctx.send(embed=internal_lookup_embed(code))
            return

        await ctx.send(embed=not_found_embed(code))

    @commands.group(name="errors", invoke_without_command=True)
    @commands.is_owner()
    async def errors_group(self, ctx: commands.Context) -> None:
        await ctx.send_help()

    @errors_group.command(name="public")
    async def errors_public(self, ctx: commands.Context, family: Optional[str] = None) -> None:
        registry = self.get_public_registry()
        grouped = grouped_public_errors(registry)
        if family is not None:
            wanted = family.strip().lower()
            grouped = {name: entries for name, entries in grouped.items() if name.lower() == wanted}

        if not grouped:
            await ctx.send("I couldn't find any public error codes for that group.")
            return

        pages: list[discord.Embed] = []
        family_names = list(grouped.keys())
        total_codes = sum(len(entries) for entries in grouped.values())
        for family_name, entries in grouped.items():
            current: list[str] = []
            for info in entries:
                label = f"`{info.code}` — **{info.command_name or info.title}**\n{info.summary}"
                test = "\n\n".join(current + [label])
                if len(test) > 3500 and current:
                    embed = discord.Embed(
                        title="Public Error Codes",
                        description=(
                            "Use `?error <code>` to open the full explanation and fix steps.\n\n"
                            f"**Group:** {family_name}"
                        ),
                        color=discord.Color.green(),
                    )
                    embed.add_field(name="Codes", value="\n\n".join(current), inline=False)
                    embed.set_footer(text=f"Groups: {len(family_names)} • Public codes: {total_codes}")
                    pages.append(embed)
                    current = [label]
                else:
                    current.append(label)
            if current:
                embed = discord.Embed(
                    title="Public Error Codes",
                    description=(
                        "Use `?error <code>` to open the full explanation and fix steps.\n\n"
                        f"**Group:** {family_name}"
                    ),
                    color=discord.Color.green(),
                )
                embed.add_field(name="Codes", value="\n\n".join(current), inline=False)
                embed.set_footer(text=f"Groups: {len(family_names)} • Public codes: {total_codes}")
                pages.append(embed)

        view = PublicErrorsPager(ctx, pages)
        message = await ctx.send(embed=pages[0], view=view)
        view.message = message

    @errors_group.command(name="latest")
    async def errors_latest(self, ctx: commands.Context, limit: int = 10) -> None:
        limit = max(1, min(limit, 15))
        entries = (await self.config.internal_errors())[:limit]
        if not entries:
            await ctx.send("No internal errors are currently stored.")
            return
        lines = [f"`{entry['code']}` • {entry.get('system', 'SYS')} • {entry.get('command_name') or 'Unknown command'} • {entry.get('summary', 'Unknown error')[:60]}" for entry in entries]
        await ctx.send(embed=discord.Embed(title="Recent Internal Errors", description="\n".join(lines), color=discord.Color.red()))

    @errors_group.command(name="show")
    async def errors_show(self, ctx: commands.Context, code: str) -> None:
        code = code.upper().strip()
        entries = await self.config.internal_errors()
        match = next((entry for entry in entries if entry["code"] == code), None)
        if match is None:
            await ctx.send(f"I couldn't find an internal error with code `{code}`.")
            return
        embed = discord.Embed(title=f"Internal Error {code}", color=discord.Color.red())
        embed.add_field(name="System", value=match.get("system") or "Unknown")
        embed.add_field(name="Kind", value=match.get("kind") or "Unknown")
        embed.add_field(name="Command", value=match.get("command_name") or "Unknown", inline=False)
        embed.add_field(name="Location", value=match.get("location") or "Unknown", inline=False)
        embed.add_field(name="Summary", value=match.get("summary") or "Unknown", inline=False)
        meta = f"Guild: `{match.get('guild_id')}`\nChannel: `{match.get('channel_id')}`\nUser: `{match.get('user_id')}`"
        embed.add_field(name="Context", value=meta, inline=False)
        await ctx.send(embed=embed)

    @errors_group.command(name="traceback")
    async def errors_traceback(self, ctx: commands.Context, code: Optional[str] = None) -> None:
        entries = await self.config.internal_errors()
        if not entries:
            await ctx.send("No internal errors are currently stored.")
            return
        target = entries[0] if code is None else next((entry for entry in entries if entry["code"] == code.upper().strip()), None)
        if target is None:
            await ctx.send(f"I couldn't find an internal error with code `{code}`.")
            return
        header = f"Traceback for `{target['code']}`\n"
        pages = list(pagify(target.get("traceback_text", "No traceback stored."), page_length=1800)) or ["No traceback stored."]
        for index, page in enumerate(pages, start=1):
            prefix = header if index == 1 else f"Traceback for `{target['code']}` (cont.)\n"
            await ctx.send(f"{prefix}{box(page, lang='py')}")

    @errors_group.command(name="search")
    async def errors_search(self, ctx: commands.Context, *, query: str) -> None:
        lowered = query.lower()
        matches = []
        for entry in await self.config.internal_errors():
            haystack = " ".join(str(entry.get(key, "")) for key in ("code", "system", "kind", "command_name", "location", "summary")).lower()
            if lowered in haystack:
                matches.append(entry)
            if len(matches) >= 10:
                break
        if not matches:
            await ctx.send(f"No internal errors matched `{query}`.")
            return
        lines = [f"`{entry['code']}` • {entry.get('command_name') or 'Unknown'} • {entry.get('summary', 'Unknown')[:70]}" for entry in matches]
        await ctx.send(embed=discord.Embed(title=f"Search results for {query}", description="\n".join(lines), color=discord.Color.red()))

    @errors_group.command(name="stats")
    async def errors_stats(self, ctx: commands.Context) -> None:
        entries = await self.config.internal_errors()
        if not entries:
            await ctx.send("No internal errors are currently stored.")
            return
        by_kind = Counter(entry.get("kind", "UNK") for entry in entries)
        by_system = Counter(entry.get("system", "SYS") for entry in entries)
        embed = discord.Embed(title="Internal Error Stats", color=discord.Color.red())
        embed.add_field(name="By Kind", value="\n".join(f"`{kind}`: {count}" for kind, count in by_kind.most_common()) or "None")
        embed.add_field(name="By System", value="\n".join(f"`{system}`: {count}" for system, count in by_system.most_common()) or "None")
        embed.set_footer(text=f"Stored reports: {len(entries)}")
        await ctx.send(embed=embed)

    @errors_group.command(name="clear")
    async def errors_clear(self, ctx: commands.Context) -> None:
        await self.config.internal_errors.set([])
        await ctx.send("Cleared stored internal error reports.")

    @errors_group.command(name="maxstored")
    async def errors_maxstored(self, ctx: commands.Context, amount: int) -> None:
        amount = max(25, min(amount, 1000))
        await self.config.max_internal_errors.set(amount)
        await ctx.send(f"Now storing up to `{amount}` internal error reports.")
