"""Utility helpers for the VHelp package."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

from redbot.core import commands
from redbot.core.commands.requires import PrivilegeLevel


@dataclass(slots=True)
class SearchResult:
    kind: str
    name: str
    score: float
    object_ref: object
    summary: str


@dataclass(slots=True)
class SuggestionBundle:
    suggestions: list[str]
    best_match: object | None
    best_score: float = 0.0


BAD_USAGE_ERRORS = (
    commands.MissingRequiredArgument,
    commands.BadArgument,
    commands.BadBoolArgument,
    commands.BadLiteralArgument,
    commands.BadUnionArgument,
    commands.ArgumentParsingError,
    commands.TooManyArguments,
    commands.UserInputError,
)


OWNER_PRIV_NAMES = {"BOT_OWNER", "OWNER"}
ADMIN_PRIV_NAMES = {"MOD", "ADMIN", "GUILD_OWNER"}


def normalize(text: str) -> str:
    return " ".join((text or "").strip().casefold().split())


def short_doc(command: commands.Command) -> str:
    return (command.short_doc or command.help or "No description provided.").strip().splitlines()[0][:160]


def command_signature(prefix: str, command: commands.Command) -> str:
    signature = (command.signature or "").strip()
    return f"{prefix}{command.qualified_name}{(' ' + signature) if signature else ''}"


def command_aliases(command: commands.Command) -> str:
    if not command.aliases:
        return "No aliases."
    return ", ".join(f"`{alias}`" for alias in command.aliases)


def chunk_count(total_items: int, page_size: int) -> int:
    page_size = max(1, page_size)
    return max(1, (total_items + page_size - 1) // page_size)


def chunk_slice(items: list, page: int, page_size: int) -> list:
    page_size = max(1, page_size)
    total_pages = chunk_count(len(items), page_size)
    page = max(0, min(page, total_pages - 1))
    start = page * page_size
    end = start + page_size
    return items[start:end]


def best_similarity(query: str, pool: Iterable[str]) -> float:
    q = normalize(query)
    best = 0.0
    for entry in pool:
        candidate = normalize(entry)
        if not candidate:
            continue
        best = max(best, SequenceMatcher(None, q, candidate).ratio())
    return best


def command_search_score(query: str, command: commands.Command, *, fuzzy: bool = True) -> float:
    q = normalize(query)
    qualified = normalize(command.qualified_name)
    simple = normalize(command.name)
    aliases = [normalize(alias) for alias in command.aliases]
    doc = normalize(short_doc(command))
    help_text = normalize(command.help or "")
    cog_name = normalize(command.cog_name or "")
    score = 0.0
    if q == qualified:
        score += 150
    if q == simple:
        score += 145
    if q in aliases:
        score += 140
    if qualified.startswith(q):
        score += 60
    if simple.startswith(q):
        score += 55
    if any(alias.startswith(q) for alias in aliases):
        score += 50
    if q in {qualified, simple, cog_name}:
        score += 20
    haystacks = [qualified, simple, *aliases, doc, help_text, cog_name]
    if any(q in hay for hay in haystacks if hay):
        score += 35
    if fuzzy:
        score += best_similarity(q, [qualified, simple, *aliases]) * 40
        score += best_similarity(q, [doc, help_text, cog_name]) * 15
    return score


def cog_search_score(query: str, cog_name: str, description: str = "", *, fuzzy: bool = True) -> float:
    q = normalize(query)
    name = normalize(cog_name)
    desc = normalize(description)
    score = 0.0
    if q == name:
        score += 130
    if name.startswith(q):
        score += 60
    if q in name:
        score += 35
    if q in desc:
        score += 20
    if fuzzy:
        score += best_similarity(q, [name]) * 35
        score += best_similarity(q, [desc]) * 10
    return score


def _truthy_permission_mapping(mapping) -> bool:
    if mapping is None:
        return False
    try:
        return any(bool(value) for value in dict(mapping).values())
    except Exception:
        return False


def _check_name_tokens(command: commands.Command) -> set[str]:
    tokens: set[str] = set()
    for check in getattr(command, "checks", []):
        name = getattr(check, "__qualname__", "") or getattr(check, "__name__", "")
        lowered = name.casefold()
        if lowered:
            tokens.add(lowered)
    return tokens


def is_owner_command(command: commands.Command) -> bool:
    callback = getattr(command, "callback", None)
    if getattr(callback, "__vhelp_force_owner__", False):
        return True
    requires = getattr(command, "requires", None)
    if requires is not None:
        privilege = getattr(requires, "privilege_level", None)
        priv_name = getattr(privilege, "name", "")
        if priv_name in OWNER_PRIV_NAMES:
            return True
    tokens = _check_name_tokens(command)
    if any("owner" in token for token in tokens):
        return True
    qualified = command.qualified_name.casefold()
    if qualified.startswith("vhelpset") or qualified.startswith("errors"):
        return True
    return False


def is_admin_command(command: commands.Command) -> bool:
    if is_owner_command(command):
        return False
    callback = getattr(command, "callback", None)
    if getattr(callback, "__vhelp_force_admin__", False):
        return True
    requires = getattr(command, "requires", None)
    if requires is not None:
        privilege = getattr(requires, "privilege_level", None)
        priv_name = getattr(privilege, "name", "")
        if priv_name in ADMIN_PRIV_NAMES:
            return True
        if _truthy_permission_mapping(getattr(requires, "user_perms", None)):
            return True
        if _truthy_permission_mapping(getattr(requires, "bot_perms", None)):
            return True
    for token in _check_name_tokens(command):
        if any(word in token for word in ("admin", "guildowner", "mod", "permissions")):
            return True
    return False


def command_scope(command: commands.Command) -> str:
    if is_owner_command(command):
        return "owner"
    if is_admin_command(command):
        return "admin"
    return "public"
