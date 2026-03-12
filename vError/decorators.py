from __future__ import annotations

from typing import Any, Callable


def error_family(code: str, *, name: str | None = None) -> Callable[[type], type]:
    """Attach a stable public error family code to a cog class."""

    def decorator(cls: type) -> type:
        setattr(cls, "__vantage_error_family__", str(code).upper()[:2])
        if name is not None:
            setattr(cls, "__vantage_error_family_name__", name)
        return cls

    return decorator



def error_slot(slot: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Attach a stable command slot code to a callback."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        value = str(slot).upper()
        if len(value) == 1:
            value = f"0{value}"
        setattr(func, "__vantage_error_slot__", value[:2])
        return func

    return decorator



def error_meta(**meta: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Attach human-friendly public error metadata to a command callback."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        current = dict(getattr(func, "__vantage_error_meta__", {}) or {})
        current.update(meta)
        setattr(func, "__vantage_error_meta__", current)
        return func

    return decorator
