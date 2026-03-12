from __future__ import annotations


def next_internal_error_code(existing_codes: list[str]) -> str:
    """Return the next sequential internal error incident code."""

    highest = 0
    for code in existing_codes:
        if isinstance(code, str) and code.startswith("VTGINT"):
            suffix = code[6:]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
    return f"VTGINT{highest + 1:04d}"
