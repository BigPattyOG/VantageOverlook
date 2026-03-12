from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ErrorKind(str, Enum):
    """High-level error families used by the public/private error system."""

    ARGUMENT = "ARG"
    CHECK = "CHK"
    CONTEXT = "CTX"
    COOLDOWN = "CD"
    API = "API"
    INTERNAL = "INT"
    UI = "UI"
    TASK = "TSK"


@dataclass(slots=True)
class InternalErrorRecord:
    """Stored metadata for unexpected internal failures."""

    code: str
    system: str
    kind: str
    command_name: Optional[str]
    location: Optional[str]
    summary: str
    guild_id: Optional[int]
    channel_id: Optional[int]
    user_id: Optional[int]
    created_at: float
    traceback_text: str
