"""Utility helpers for the VHelp package."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

from redbot.core import commands


@dataclass(slots=True)
class SearchResult:
    """Container for a help search result."""

    kind: str
    name: str
    score: float
    object_ref: object
    summary: str


@dataclass(slots=True)
class SuggestionBundle:
    """Suggestions for failed help resolution."""

    suggestions: list[str]
    best_match: object | None
    best_score: float = 0.0


BAD_USAGE_ERRORS = (
    commands.MissingRequiredArgument,
    commands.BadArgument,
    commands.TooManyArguments,
    commands.UserInputError,
)


def normalize(text: str) -> str:
    """Normalize text for fuzzy matching."""
    return " ".join((text or "").strip().casefold().split())


def chunk_count(total_items: int, page_size: int) -> int:
    """Return the number of pages needed for a list."""
    if page_size <= 0:
        page_size = 1
    return max(1, (total_items + page_size - 1) // page_size)


def chunk_slice(items: list, page: int, page_size: int) -> list:
    """Return the slice for a given page."""
    total_pages = chunk_count(len(items), page_size)
    page = max(0, min(page, total_pages - 1))
    start = page * page_size
    end = start + page_size
    return items[start:end]


def command_signature(prefix: str, command: commands.Command) -> str:
    """Build a display signature for a command."""
    signature = (command.signature or "").strip()
    base = f"{prefix}{command.qualified_name}".strip()
    return f"{base} {signature}".strip()


def short_doc(command: commands.Command) -> str:
    """Return a usable short description for a command."""
    return (command.short_doc or command.help or "No description provided.").strip()


def command_aliases(command: commands.Command) -> str:
    """Return aliases as a readable string."""
    if not command.aliases:
        return "None"
    return ", ".join(sorted(set(command.aliases), key=str.casefold))


def best_similarity(query: str, candidates: Iterable[str]) -> float:
    """Return the best fuzzy similarity score for a set of candidates."""
    q = normalize(query)
    best = 0.0
    for candidate in candidates:
        c = normalize(candidate)
        if not c:
            continue
        best = max(best, SequenceMatcher(None, q, c).ratio())
    return best


def command_search_score(query: str, command: commands.Command, *, fuzzy: bool = True) -> float:
    """Score a command against a search query.

    The scale is arbitrary but intended to produce stable ordering.
    """
    q = normalize(query)
    if not q:
        return 0.0

    qualified = normalize(command.qualified_name)
    simple = normalize(command.name)
    aliases = [normalize(alias) for alias in command.aliases]
    doc = normalize(short_doc(command))
    help_text = normalize(command.help or "")
    parent = normalize(command.cog_name or "")

    score = 0.0

    if q == qualified:
        score += 150
    if q == simple:
        score += 140
    if q in aliases:
        score += 135
    if q == parent:
        score += 30

    if qualified.startswith(q):
        score += 60
    if simple.startswith(q):
        score += 55
    if any(alias.startswith(q) for alias in aliases):
        score += 50

    haystacks = [qualified, simple, *aliases, doc, help_text, parent]
    if any(q in hay for hay in haystacks if hay):
        score += 35

    if fuzzy:
        score += best_similarity(q, [qualified, simple, *aliases]) * 40
        score += best_similarity(q, [doc, help_text]) * 15
    return score


def cog_search_score(query: str, cog_name: str, description: str = "", *, fuzzy: bool = True) -> float:
    """Score a cog/category against a search query."""
    q = normalize(query)
    name = normalize(cog_name)
    desc = normalize(description)
    score = 0.0
    if q == name:
        score += 130
    if name.startswith(q):
        score += 50
    if q in name:
        score += 35
    if q in desc:
        score += 20
    if fuzzy:
        score += best_similarity(q, [name]) * 35
        score += best_similarity(q, [desc]) * 10
    return score
