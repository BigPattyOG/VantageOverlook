from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class PublicErrorInfo:
    """Information shown to end-users when they run ?error <code>."""

    code: str
    title: str
    summary: str
    fix: str
    example: Optional[str] = None
    group: str = "General"
    family: str = "GN"
    slot: str = "00"
    issue_family: str = "A"
    issue_variant: str = "1"
    issue_key: str = "missing_argument"
    command_name: Optional[str] = None
    syntax: Optional[str] = None
    details: Optional[str] = None


ISSUE_DEFINITIONS: dict[tuple[str, str], dict[str, str]] = {
    ("A", "1"): {
        "key": "missing_argument",
        "title": "Missing Something Error",
        "summary": "This command is missing something it needs before it can run.",
        "fix": "Run the command again and include every required part of the syntax.",
    },
    ("A", "2"): {
        "key": "invalid_argument",
        "title": "Invalid Value Error",
        "summary": "One of the values you entered could not be understood.",
        "fix": "Double-check the value you entered and make sure it matches the command's expected format.",
    },
    ("B", "1"): {
        "key": "no_permission",
        "title": "No Permissions Error",
        "summary": "You do not have permission to run that command.",
        "fix": "Ask a server admin or bot owner to grant the right role or permission, or use a command you already have access to.",
    },
    ("B", "2"): {
        "key": "bot_missing_permissions",
        "title": "Bot Permissions Error",
        "summary": "The bot does not have the permissions it needs to finish that command.",
        "fix": "Ask a server admin to update the bot's role permissions and channel overrides.",
    },
    ("C", "1"): {
        "key": "server_only",
        "title": "Server Only Error",
        "summary": "That command can only be used in a server.",
        "fix": "Run the command in a server channel instead of DMs.",
    },
    ("C", "2"): {
        "key": "dm_only",
        "title": "DM Only Error",
        "summary": "That command can only be used in DMs with the bot.",
        "fix": "Open a direct message with the bot and run the command there.",
    },
    ("C", "3"): {
        "key": "command_disabled",
        "title": "Command Disabled Error",
        "summary": "That command is currently disabled.",
        "fix": "Try again later or contact the bot owners if you believe this command should be available.",
    },
    ("D", "1"): {
        "key": "cooldown",
        "title": "Cooldown Error",
        "summary": "That command is on cooldown right now.",
        "fix": "Wait for the cooldown to end, then try the command again.",
    },
}

DEFAULT_FAMILIES: dict[str, str] = {
    "GN": "General",
    "HP": "Help",
    "MD": "Moderation",
    "ST": "Settings",
    "ER": "Errors",
    "OW": "Owner",
    "AD": "Admin",
}


def make_public_code(family: str, slot: str, issue_family: str, issue_variant: str) -> str:
    return f"VTG{family}{slot}{issue_family}{issue_variant}"



def grouped_public_errors(registry: dict[str, PublicErrorInfo]) -> dict[str, list[PublicErrorInfo]]:
    grouped: defaultdict[str, list[PublicErrorInfo]] = defaultdict(list)
    for info in registry.values():
        grouped[info.group].append(info)

    ordered: dict[str, list[PublicErrorInfo]] = {}
    for family in sorted(grouped.keys()):
        ordered[family] = sorted(grouped[family], key=lambda item: (item.command_name or "", item.code))
    return ordered
