from __future__ import annotations

import re
from typing import Optional

import discord
from redbot.core import commands

from .registry import DEFAULT_FAMILIES, ISSUE_DEFINITIONS, PublicErrorInfo, grouped_public_errors, make_public_code

SEPARATOR = "─" * 16


def resolve_system_prefix(ctx: commands.Context) -> str:
    cog_name = (ctx.cog.qualified_name if ctx.cog else "").lower()
    if cog_name.startswith("vhelp"):
        return "VH"
    if cog_name.startswith("vmod") or cog_name.startswith("vantage"):
        return "VM"
    return "SYS"



def _command_from_ctx(ctx: commands.Context):
    return getattr(ctx, "command", None)



def command_meta(command: Optional[commands.Command]) -> dict:
    if command is None:
        return {}
    callback = getattr(command, "callback", None)
    return dict(getattr(callback, "__vantage_error_meta__", {}) or {}) if callback else {}



def resolve_family_for_command(command: Optional[commands.Command]) -> tuple[str, str]:
    cog = getattr(command, "cog", None)
    if cog is None:
        return "GN", DEFAULT_FAMILIES["GN"]

    explicit = getattr(cog, "__vantage_error_family__", None)
    explicit_name = getattr(cog, "__vantage_error_family_name__", None)
    if explicit:
        return str(explicit).upper()[:2], str(explicit_name or explicit_name or cog.qualified_name)

    cog_name = cog.qualified_name.lower()
    if cog_name.startswith("vhelp"):
        return "HP", DEFAULT_FAMILIES["HP"]
    if cog_name.startswith("vmod") or cog_name.startswith("vantage"):
        return "MD", DEFAULT_FAMILIES["MD"]
    if cog_name.startswith("verrors"):
        return "ER", DEFAULT_FAMILIES["ER"]
    return "GN", cog.qualified_name



def resolve_family_code(ctx: commands.Context) -> tuple[str, str]:
    return resolve_family_for_command(_command_from_ctx(ctx))



def resolve_slot_code(ctx: commands.Context) -> str:
    return slot_for_command(_command_from_ctx(ctx))



def slot_for_command(command: Optional[commands.Command]) -> str:
    if command is None:
        return "00"
    callback = getattr(command, "callback", None)
    explicit = getattr(callback, "__vantage_error_slot__", None) if callback else None
    if explicit is not None:
        value = str(explicit).upper()
        if len(value) == 1:
            return f"0{value}"
        return value[:2]
    return "00"



def issue_descriptor_for_error(error: Exception) -> Optional[tuple[str, str, str]]:
    issue_family: Optional[str] = None
    issue_variant: Optional[str] = None

    if isinstance(error, commands.MissingRequiredArgument):
        issue_family, issue_variant = "A", "1"
    elif isinstance(error, commands.BadUnionArgument):
        issue_family, issue_variant = "A", "2"
    elif isinstance(error, (commands.BadArgument, commands.UserInputError)):
        issue_family, issue_variant = "A", "2"
    elif isinstance(error, commands.BotMissingPermissions):
        issue_family, issue_variant = "B", "2"
    elif isinstance(error, commands.CheckFailure):
        issue_family, issue_variant = "B", "1"
    elif isinstance(error, commands.NoPrivateMessage):
        issue_family, issue_variant = "C", "1"
    elif isinstance(error, commands.PrivateMessageOnly):
        issue_family, issue_variant = "C", "2"
    elif isinstance(error, commands.DisabledCommand):
        issue_family, issue_variant = "C", "3"
    elif isinstance(error, commands.CommandOnCooldown):
        issue_family, issue_variant = "D", "1"

    if issue_family is None or issue_variant is None:
        return None
    definition = ISSUE_DEFINITIONS[(issue_family, issue_variant)]
    return issue_family, issue_variant, definition["key"]



def public_code_for_error(ctx: commands.Context, error: Exception) -> Optional[str]:
    descriptor = issue_descriptor_for_error(error)
    if descriptor is None:
        return None
    issue_family, issue_variant, _ = descriptor
    family, _group = resolve_family_code(ctx)
    slot = resolve_slot_code(ctx)
    return make_public_code(family, slot, issue_family, issue_variant)



def syntax_for_command(command: Optional[commands.Command], prefix: str = "?") -> str:
    if command is None:
        return f"{prefix}help"
    signature = command.signature or ""
    base = f"{prefix}{command.qualified_name}"
    return f"{base} {signature}".strip()



def localize_example(example: str | None, prefix: str) -> Optional[str]:
    if not example:
        return None
    if example.startswith("?"):
        return f"{prefix}{example[1:]}"
    return example



def _humanize(text: str) -> str:
    return text.replace("_", " ")



def param_label_for_command(command: Optional[commands.Command], param_name: str) -> str:
    meta = command_meta(command)
    labels = meta.get("param_labels", {}) or {}
    label = labels.get(param_name)
    if label:
        return str(label)
    return _humanize(param_name)



def _issue_override(meta: dict, issue_key: str) -> dict:
    raw = meta.get(issue_key, {}) or {}
    return dict(raw)



def build_public_info_for_command(
    command: Optional[commands.Command],
    *,
    family: str,
    group: str,
    slot: str,
    issue_family: str,
    issue_variant: str,
    prefix: str = "?",
) -> PublicErrorInfo:
    base = ISSUE_DEFINITIONS[(issue_family, issue_variant)]
    issue_key = base["key"]
    meta = command_meta(command)
    override = _issue_override(meta, issue_key)
    command_name = command.qualified_name if command else None
    syntax = syntax_for_command(command, prefix=prefix) if command else None
    examples = meta.get("examples", []) or []
    example = localize_example(override.get("example") or (examples[0] if examples else None), prefix)

    if command_name:
        default_summary = f"This usually means `{command_name}` was used with the wrong input or in the wrong way."
        default_fix = f"Run `{syntax}` again and make sure every value matches what the command expects."
    else:
        default_summary = base["summary"]
        default_fix = base["fix"]

    return PublicErrorInfo(
        code=make_public_code(family, slot, issue_family, issue_variant),
        title=override.get("title") or base["title"],
        summary=override.get("summary") or default_summary,
        fix=override.get("fix") or default_fix,
        example=example,
        group=group,
        family=family,
        slot=slot,
        issue_family=issue_family,
        issue_variant=issue_variant,
        issue_key=issue_key,
        command_name=command_name,
        syntax=syntax,
        details=override.get("details"),
    )



def public_info_for_context_error(ctx: commands.Context, error: Exception) -> Optional[PublicErrorInfo]:
    descriptor = issue_descriptor_for_error(error)
    if descriptor is None:
        return None
    issue_family, issue_variant, _issue_key = descriptor
    command = _command_from_ctx(ctx)
    family, group = resolve_family_code(ctx)
    slot = resolve_slot_code(ctx)
    return build_public_info_for_command(
        command,
        family=family,
        group=group,
        slot=slot,
        issue_family=issue_family,
        issue_variant=issue_variant,
        prefix=ctx.clean_prefix,
    )



def public_registry_for_bot(bot, prefix: str = "?") -> dict[str, PublicErrorInfo]:
    registry: dict[str, PublicErrorInfo] = {}

    seen_families: dict[str, str] = dict(DEFAULT_FAMILIES)
    for cog_name, cog in bot.cogs.items():
        family = getattr(cog, "__vantage_error_family__", None)
        family_name = getattr(cog, "__vantage_error_family_name__", None)
        if family:
            seen_families[str(family).upper()[:2]] = str(family_name or cog_name)

    # Generic family-level entries.
    for family, group in seen_families.items():
        for issue_family, issue_variant in ISSUE_DEFINITIONS:
            info = build_public_info_for_command(
                None,
                family=family,
                group=group,
                slot="00",
                issue_family=issue_family,
                issue_variant=issue_variant,
                prefix=prefix,
            )
            registry[info.code] = info

    # Command-specific entries when slots are declared.
    for command in bot.walk_commands():
        slot = slot_for_command(command)
        if slot == "00":
            continue
        family, group = resolve_family_for_command(command)
        for issue_family, issue_variant in ISSUE_DEFINITIONS:
            info = build_public_info_for_command(
                command,
                family=family,
                group=group,
                slot=slot,
                issue_family=issue_family,
                issue_variant=issue_variant,
                prefix=prefix,
            )
            registry[info.code] = info
    return registry



def usage_for_command(ctx: commands.Context) -> str:
    return syntax_for_command(_command_from_ctx(ctx), prefix=ctx.clean_prefix)



def missing_argument_name(error: Exception) -> Optional[str]:
    if isinstance(error, commands.MissingRequiredArgument):
        return getattr(error.param, "name", None)
    return None



def internal_error_embed(command_display: str, code: str) -> discord.Embed:
    embed = discord.Embed(
        title="Internal Error",
        description=(
            f"Hmm, looks like `{command_display}` has failed. I'll let the devs know.\n\n"
            f"**Error code:** `{code}`"
        ),
        color=discord.Color.red(),
    )
    return embed



def public_error_embed(info: PublicErrorInfo) -> discord.Embed:
    embed = discord.Embed(
        title=f"Error {info.code}",
        description=f"**{info.title}**\n{SEPARATOR}",
        color=discord.Color.green(),
    )
    if info.command_name:
        embed.add_field(name="Command", value=f"`{info.command_name}`", inline=True)
    embed.add_field(name="Group", value=info.group, inline=True)
    embed.add_field(name="What happened", value=info.summary, inline=False)
    if info.details:
        embed.add_field(name="Details", value=info.details, inline=False)
    embed.add_field(name="How to fix it", value=info.fix, inline=False)
    if info.syntax:
        embed.add_field(name="Syntax", value=f"```\n{info.syntax}\n```", inline=False)
    if info.example:
        embed.add_field(name="Example", value=f"```\n{info.example}\n```", inline=False)
    embed.set_footer(text=f"Family: {info.group} • Slot: {info.slot}")
    return embed



def internal_lookup_embed(code: str) -> discord.Embed:
    return discord.Embed(
        title=f"Error {code}",
        description=(
            "If you got this error, it means that an internal error with Vantage has occurred.\n"
            "Our developers should have been notified of this error and will fix it as soon as possible.\n\n"
            "We apologise for the inconvenience this may cause."
        ),
        color=discord.Color.red(),
    )



def not_found_embed(code: str) -> discord.Embed:
    return discord.Embed(
        title="Unknown Error Code",
        description=f"I couldn't find any information for `{code}`.",
        color=discord.Color.orange(),
    )



def _runtime_detail(ctx: commands.Context, error: Exception) -> str:
    command = _command_from_ctx(ctx)
    meta = command_meta(command)
    descriptor = issue_descriptor_for_error(error)
    issue_key = descriptor[2] if descriptor else None
    override = _issue_override(meta, issue_key) if issue_key else {}

    if isinstance(error, commands.MissingRequiredArgument):
        missing = getattr(error.param, "name", "something")
        label = param_label_for_command(command, missing)
        return f"`{command.qualified_name}` still needs **{label}** before it can run."
    if isinstance(error, commands.BotMissingPermissions):
        missing = ", ".join(getattr(error, "missing_permissions", []) or []) or "unknown permissions"
        return f"The bot is missing: `{missing}`."
    if isinstance(error, commands.CommandOnCooldown):
        retry_after = getattr(error, "retry_after", None)
        if retry_after is not None:
            return f"That command is on cooldown for about `{round(retry_after, 1)}` more seconds."
    text = override.get("runtime_detail") or str(error).strip()
    if text:
        return text
    return "The command could not use the values you provided."



def fixable_error_reply(ctx: commands.Context, error: Exception, code: str) -> discord.Embed:
    info = public_info_for_context_error(ctx, error)
    if info is None:
        return discord.Embed(
            title="Command Error",
            description=f"For more info on this error, run `{ctx.clean_prefix}error {code}`",
            color=discord.Color.orange(),
        )

    embed = discord.Embed(
        title=info.title,
        description=f"**{ctx.clean_prefix}{ctx.command.qualified_name if ctx.command else 'command'}**\n{SEPARATOR}",
        color=discord.Color.green(),
    )
    embed.add_field(name="What went wrong", value=_runtime_detail(ctx, error), inline=False)
    embed.add_field(name="How to fix it", value=info.fix, inline=False)
    if info.syntax:
        embed.add_field(name="Try this", value=f"```\n{info.syntax}\n```", inline=False)
    if info.example:
        embed.add_field(name="Example", value=f"```\n{info.example}\n```", inline=False)
    embed.add_field(
        name="Need more help?",
        value=f"Run `{ctx.clean_prefix}error {code}` for a full breakdown of this error.",
        inline=False,
    )
    embed.set_footer(text=f"Error code: {code}")
    return embed



def command_display(ctx: commands.Context) -> str:
    if ctx.command:
        return f"{ctx.clean_prefix}{ctx.command.qualified_name}"
    return f"{ctx.clean_prefix}command"
