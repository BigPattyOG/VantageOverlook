from __future__ import annotations

from typing import Optional

import discord

from .codes import ISSUE_LABELS, ISSUE_VARIANT_HELP, parse_public_error_code
from .models import ISSUE_TITLES, InternalErrorRecord, IssueType, PublicErrorExplanation, RegistryEntry
from .utils import command_display, help_hint, missing_param_label


ERROR_COLOR = 0xC0392B
INFO_COLOR = 0x2ECC71


class ExplanationBuilder:
    def __init__(self, prefix: str):
        self.prefix = prefix

    def build_public_explanation(
        self,
        code: str,
        entry: RegistryEntry,
        issue: IssueType,
        variant: str,
    ) -> PublicErrorExplanation:
        title = ISSUE_TITLES[issue]
        command_syntax = command_display(self.prefix, entry)
        base_note = entry.issue_notes.get(issue.value) or entry.issue_notes.get(issue.name.lower())
        base_fix = entry.fix_text.get(issue.value) or entry.fix_text.get(issue.name.lower())
        related = help_hint(self.prefix, entry)
        examples = [ex if ex.startswith(self.prefix) else ex.replace("{prefix}", self.prefix) for ex in entry.examples]

        if issue == IssueType.MISSING_ARGUMENT:
            missing = missing_param_label(entry, variant) or "a required value"
            description = (
                f"Looks like you forgot to provide **{missing}** for `{entry.qualified_name}`.\n"
                f"Try:\n`{command_syntax}`"
            )
            fix = base_fix or f"Run `{related}` to see the full syntax and include the missing value."
            note = base_note or "This usually happens when a required part of the command is missing."
        elif issue == IssueType.INVALID_ARGUMENT:
            bad = missing_param_label(entry, variant) or "one of the values"
            description = (
                f"Looks like the value you gave for **{bad}** was not valid for `{entry.qualified_name}`.\n"
                f"Try:\n`{command_syntax}`"
            )
            fix = base_fix or f"Double-check the value format, then run `{related}` for detailed usage."
            note = base_note or "This usually happens when the command gets a value in the wrong format."
        elif issue == IssueType.NO_PERMISSIONS:
            description = "Looks like you can't run this command."
            fix = base_fix or "Ask a server admin or bot owner if you should have access to this command."
            note = base_note or "Your account does not currently meet the checks for this command."
        elif issue == IssueType.BOT_MISSING_PERMISSIONS:
            description = "Looks like the bot cannot complete this command right now."
            fix = base_fix or "Ask a server admin to check the bot's permissions and role position."
            note = base_note or "The bot is missing one or more required Discord permissions."
        elif issue == IssueType.SERVER_ONLY:
            description = "This command can only be used inside a server."
            fix = base_fix or "Run the command in a server channel instead of DMs."
            note = base_note
        elif issue == IssueType.DM_ONLY:
            description = "This command can only be used in direct messages."
            fix = base_fix or "Run the command in DMs with the bot instead of a server channel."
            note = base_note
        elif issue == IssueType.COOLDOWN:
            description = "This command is on cooldown right now."
            fix = base_fix or "Wait a moment, then try again."
            note = base_note
        elif issue == IssueType.DISABLED:
            description = "This command is currently disabled."
            fix = base_fix or "Ask a server admin or bot owner whether this command should be enabled."
            note = base_note
        elif issue == IssueType.TOPIC_NOT_FOUND:
            description = "Looks like I couldn't find the thing you asked for."
            fix = base_fix or f"Try `{self.prefix}helpsearch <query>` or check the spelling and try again."
            note = base_note
        elif issue == IssueType.SUBCOMMAND_REQUIRED:
            description = "This command group needs a subcommand before it can do anything."
            fix = base_fix or f"Run `{related}` to see the available subcommands."
            note = base_note
        elif issue == IssueType.TARGET_NOT_FOUND:
            description = "Looks like I couldn't find the target you gave me."
            fix = base_fix or "Check the user, member, channel, role, or message you provided and try again."
            note = base_note
        elif issue == IssueType.INVALID_CHOICE:
            description = "One of the options you gave isn't valid here."
            fix = base_fix or f"Run `{related}` to see the accepted values for this command."
            note = base_note
        else:
            description = f"This error belongs to `{entry.qualified_name}`."
            fix = base_fix or f"Run `{related}` for the full command help."
            note = base_note or ISSUE_VARIANT_HELP.get(issue)

        return PublicErrorExplanation(
            code=code,
            title=title,
            description=description,
            fix=fix,
            examples=examples,
            command_name=entry.qualified_name,
            related_help=related,
            note=note,
        )


def public_error_embed(explanation: PublicErrorExplanation) -> discord.Embed:
    embed = discord.Embed(title=explanation.title, color=ERROR_COLOR)
    embed.description = (
        f"**Error {explanation.code}**\n\n"
        f"{explanation.description}\n\n"
        f"**How to fix it**\n{explanation.fix}"
    )
    if explanation.examples:
        sample = "\n".join(f"`{item}`" for item in explanation.examples[:3])
        embed.add_field(name="Examples", value=sample, inline=False)
    if explanation.related_help:
        embed.add_field(name="Need more help?", value=f"Run `{explanation.related_help}`", inline=False)
    if explanation.note:
        embed.set_footer(text=explanation.note)
    return embed



def internal_public_embed(code: str) -> discord.Embed:
    embed = discord.Embed(title="Internal Error", color=ERROR_COLOR)
    embed.description = (
        f"**Error {code}**\n\n"
        "If you got this error, it means that an internal error with Vantage has occurred.\n"
        "Our developers should have been notified of this error and will fix it as soon as possible.\n\n"
        "We apologise for the inconvenience this may cause."
    )
    return embed



def incident_owner_embed(record: InternalErrorRecord) -> discord.Embed:
    embed = discord.Embed(title=f"Internal Error {record.code}", color=ERROR_COLOR)
    embed.description = record.summary[:4000]
    embed.add_field(name="Source", value=record.source, inline=True)
    embed.add_field(name="Command", value=record.command_name or "Unknown", inline=True)
    embed.add_field(name="Cog", value=record.cog_name or "Unknown", inline=True)
    location = f"Guild: {record.guild_id or 'N/A'}\nChannel: {record.channel_id or 'N/A'}\nUser: {record.user_id or 'N/A'}"
    embed.add_field(name="Location", value=location, inline=False)
    if record.message_content:
        embed.add_field(name="Message", value=record.message_content[:1000], inline=False)
    embed.set_footer(text="Use ?errors traceback <code> to view the stored traceback.")
    return embed



def public_code_overview_embed(rows: list[tuple[str, RegistryEntry]], *, family: str | None = None) -> discord.Embed:
    title = "Public Error Codes"
    if family:
        title = f"Public Error Codes • {family}"
    embed = discord.Embed(title=title, color=INFO_COLOR)
    chunks: list[str] = []
    for code, entry in rows[:40]:
        chunks.append(f"`{code}` • `{entry.qualified_name}`")
    embed.description = "\n".join(chunks) or "No public error codes were found."
    if len(rows) > 40:
        embed.set_footer(text=f"Showing 40 of {len(rows)} codes.")
    return embed
