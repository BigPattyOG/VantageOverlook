"""Converters used by VMod commands."""

from __future__ import annotations

import re

from redbot.core import commands
from redbot.core.commands import BadArgument, Converter

from .constants import _

_ID_REGEX = re.compile(r"([0-9]{15,21})$")
_MENTION_REGEX = re.compile(r"<@!?([0-9]{15,21})>$")


class RawUserIds(Converter):
    """Accept a raw Discord user ID or a user mention and return the ID as ``int``."""

    async def convert(self, ctx: commands.Context, argument: str) -> int:
        match = _ID_REGEX.match(argument) or _MENTION_REGEX.match(argument)
        if match:
            return int(match.group(1))
        raise BadArgument(_("{arg} doesn't look like a valid user ID.").format(arg=argument))
