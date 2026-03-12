from __future__ import annotations

import logging
import time
import traceback
from dataclasses import asdict
from typing import Optional

import discord
from redbot.core import Config, commands

from .codes import next_internal_error_code
from .models import ErrorKind, InternalErrorRecord
from .utils import command_display, internal_error_embed

log = logging.getLogger("red.vantage.errors")


class ErrorReporter:
    """Shared internal-error reporter used by commands, views, and tasks."""

    def __init__(self, bot, config: Config):
        self.bot = bot
        self.config = config

    async def record_internal_error(
        self,
        *,
        system: str,
        kind: ErrorKind,
        summary: str,
        traceback_text: str,
        command_name: Optional[str] = None,
        location: Optional[str] = None,
        guild_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> str:
        async with self.config.internal_errors() as entries:
            existing_codes = [entry.get("code") for entry in entries if isinstance(entry, dict)]
            code = next_internal_error_code(existing_codes)
            record = InternalErrorRecord(
                code=code,
                system=system,
                kind=kind.value,
                command_name=command_name,
                location=location,
                summary=summary,
                guild_id=guild_id,
                channel_id=channel_id,
                user_id=user_id,
                created_at=time.time(),
                traceback_text=traceback_text,
            )
            entries.insert(0, asdict(record))
            max_entries = await self.config.max_internal_errors()
            del entries[max_entries:]
        return code

    async def notify_owners(self, record: dict) -> None:
        owner_ids = getattr(self.bot, "owner_ids", set()) or set()
        if not owner_ids:
            return

        summary_lines = [
            f"**Error code:** `{record['code']}`",
            f"**System:** `{record['system']}`",
            f"**Kind:** `{record['kind']}`",
            f"**Command:** `{record.get('command_name') or 'Unknown'}`",
            f"**Location:** `{record.get('location') or 'Unknown'}`",
            f"**Summary:** `{record.get('summary') or 'Unknown'}`",
        ]
        tb = record.get("traceback_text", "")[:1400]
        content = "\n".join(summary_lines)
        if tb:
            content += f"\n\n```py\n{tb}\n```"

        for owner_id in owner_ids:
            user = self.bot.get_user(owner_id)
            if user is None:
                try:
                    user = await self.bot.fetch_user(owner_id)
                except discord.HTTPException:
                    continue
            try:
                await user.send(content)
            except discord.HTTPException:
                continue

    async def report_command_exception(self, ctx: commands.Context, error: Exception, system: str) -> str:
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        summary = f"{type(error).__name__}: {error}"
        code = await self.record_internal_error(
            system=system,
            kind=ErrorKind.INTERNAL,
            summary=summary,
            traceback_text=tb,
            command_name=ctx.command.qualified_name if ctx.command else None,
            location="command",
            guild_id=ctx.guild.id if ctx.guild else None,
            channel_id=ctx.channel.id if ctx.channel else None,
            user_id=ctx.author.id if ctx.author else None,
        )
        log.exception("Internal command error %s", code, exc_info=error)
        try:
            await ctx.send(embed=internal_error_embed(command_display(ctx), code))
        except discord.HTTPException:
            pass
        latest = (await self.config.internal_errors())[0]
        await self.notify_owners(latest)
        return code

    async def report_generic_exception(
        self,
        *,
        system: str,
        kind: ErrorKind,
        summary: str,
        error: Exception,
        interaction: Optional[discord.Interaction] = None,
        location: Optional[str] = None,
        command_name: Optional[str] = None,
        guild_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> str:
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        code = await self.record_internal_error(
            system=system,
            kind=kind,
            summary=summary,
            traceback_text=tb,
            command_name=command_name,
            location=location,
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
        )
        log.exception("Internal %s error %s", kind.value, code, exc_info=error)
        latest = (await self.config.internal_errors())[0]
        await self.notify_owners(latest)

        if interaction is not None:
            embed = internal_error_embed(command_name or "that interaction", code)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.response.send_message(embed=embed, ephemeral=True)
            except discord.HTTPException:
                pass

        return code
