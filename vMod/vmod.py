"""Concrete cog class assembled from the VMod mixins."""

from __future__ import annotations

from .base import VModBase
from .events import VModEvents
from .moderation import VModModeration
from .settings import VModSettings

try:
    from verrors.decorators import error_family
except ImportError:
    def error_family(*args, **kwargs):
        def deco(cls):
            return cls
        return deco


@error_family("MD", name="Moderation")
class VMod(VModModeration, VModSettings, VModEvents, VModBase):
    """Combined moderation cog for VMod."""

    pass
