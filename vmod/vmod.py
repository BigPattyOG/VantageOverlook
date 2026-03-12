"""Concrete cog class assembled from the VMod mixins."""

from __future__ import annotations

from .base import VModBase
from .events import VModEvents
from .moderation import VModModeration
from .settings import VModSettings


class VMod(VModModeration, VModSettings, VModEvents, VModBase):
    """Combined moderation cog for VMod."""

    pass
