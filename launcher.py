#!/usr/bin/env python3
"""Vantage Bot Launcher — CLI entry point.

Usage
-----
::

    python launcher.py start            # Run the bot
    python launcher.py setup            # Interactive first-run wizard

    python launcher.py repos list       # List registered repositories
    python launcher.py repos add URL    # Clone a GitHub repo
    python launcher.py repos add PATH   # Link a local repo
    python launcher.py repos remove NAME
    python launcher.py repos update [NAME]

    python launcher.py cogs list                   # List installed cogs
    python launcher.py cogs install REPO COG       # Install a cog
    python launcher.py cogs uninstall COG_PATH     # Uninstall a cog
    python launcher.py cogs autoload COG_PATH      # Toggle autoload
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click

# Ensure the project root is importable regardless of working directory.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.config import CONFIG_PATH, load_config, save_config
from core.cog_manager import CogManager


# ── Logging setup ─────────────────────────────────────────────────────────────


def _setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ── CLI root ──────────────────────────────────────────────────────────────────


@click.group()
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
@click.pass_context
def cli(ctx: click.Context, debug: bool) -> None:
    """Vantage — a custom Discord bot framework."""
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug


# ── start ─────────────────────────────────────────────────────────────────────


@cli.command()
@click.pass_context
def start(ctx: click.Context) -> None:
    """Start the Vantage bot."""
    _setup_logging(ctx.obj.get("debug", False))
    from core.bot import VantageBot

    config = load_config()
    token = config.get("token", "").strip()

    if not token:
        click.echo(
            click.style("❌  No bot token found.", fg="red")
            + "\n\nRun "
            + click.style("python launcher.py setup", bold=True)
            + " to configure the bot."
        )
        sys.exit(1)

    click.echo(click.style("🚀  Starting Vantage Bot…", fg="green"))
    bot = VantageBot(config)

    async def _run() -> None:
        async with bot:
            await bot.start(token)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        click.echo(click.style("\n👋  Bot stopped.", fg="yellow"))


# ── setup ─────────────────────────────────────────────────────────────────────


@cli.command()
def setup() -> None:
    """Interactive first-run setup wizard."""
    click.echo(click.style("\n🔧  Vantage Bot — Setup Wizard\n", bold=True, fg="cyan"))

    config = load_config()

    # Step 1 — token
    click.echo("Step 1: Bot Token")
    click.echo("  Get your token from https://discord.com/developers/applications\n")
    token = click.prompt(
        "  Bot token",
        default=config.get("token", ""),
        hide_input=True,
        show_default=False,
        prompt_suffix=" > ",
    )
    config["token"] = token.strip()

    # Step 2 — prefix
    click.echo("\nStep 2: Command Prefix")
    prefix = click.prompt(
        "  Command prefix",
        default=config.get("prefix", "!"),
        prompt_suffix=" > ",
    )
    config["prefix"] = prefix

    # Step 3 — owner IDs
    click.echo("\nStep 3: Bot Owner(s)")
    click.echo("  Enable Developer Mode in Discord → right-click your name → Copy ID.")
    existing = ", ".join(str(i) for i in config.get("owner_ids", []))
    raw = click.prompt(
        "  Owner IDs (comma-separated)",
        default=existing or "",
        prompt_suffix=" > ",
    )
    config["owner_ids"] = [int(i.strip()) for i in raw.split(",") if i.strip().isdigit()]

    # Step 4 — description
    click.echo("\nStep 4: Bot Description")
    desc = click.prompt(
        "  Description",
        default=config.get("description", "Vantage — a custom Discord bot framework"),
        prompt_suffix=" > ",
    )
    config["description"] = desc

    save_config(config)

    click.echo(
        click.style("\n✅  Config saved to ", fg="green")
        + click.style(str(CONFIG_PATH), bold=True)
    )
    click.echo(
        "\nRun "
        + click.style("python launcher.py start", bold=True)
        + " to launch the bot.\n"
    )


# ── repos ─────────────────────────────────────────────────────────────────────


@cli.group()
def repos() -> None:
    """Manage cog repositories."""


@repos.command("list")
def repos_list() -> None:
    """List all registered repositories."""
    mgr = CogManager()
    data = mgr.list_repos()

    if not data:
        click.echo("No repositories registered.\n")
        click.echo("Add a GitHub repo:  " + click.style("python launcher.py repos add <URL>", bold=True))
        click.echo("Add a local repo:   " + click.style("python launcher.py repos add <PATH>", bold=True))
        return

    click.echo(click.style(f"\n📦  Repositories ({len(data)})\n", bold=True))
    for name, info in data.items():
        tag = (
            click.style("[local]", fg="blue")
            if info["type"] == "local"
            else click.style("[github]", fg="green")
        )
        click.echo(f"  {tag} {click.style(name, bold=True)}")
        if info.get("url"):
            click.echo(f"       URL : {info['url']}")
        click.echo(f"      Path : {info['path']}")
        cogs = info.get("installed_cogs", [])
        click.echo(f"      Cogs : {', '.join(cogs) if cogs else '(none installed)'}\n")


@repos.command("add")
@click.argument("url_or_path")
@click.option("--name", default=None, help="Custom name for the repository (must be a valid Python identifier).")
def repos_add(url_or_path: str, name: str | None) -> None:
    """Add a repository — GitHub URL or local directory path."""
    mgr = CogManager()
    path = Path(url_or_path)

    if path.exists() and path.is_dir():
        # Local repo
        repo_name = _normalize_module_name(name or path.name)
        try:
            mgr.add_local_repo(repo_name, str(path.resolve()))
            click.echo(click.style(f"✅  Local repo '{repo_name}' added.", fg="green"))
            click.echo(f"   Path: {path.resolve()}")
        except ValueError as exc:
            click.echo(click.style(f"❌  {exc}", fg="red"))
    else:
        # GitHub URL
        url = url_or_path
        repo_name = _normalize_module_name(name or _name_from_url(url))
        click.echo(f"⬇️   Cloning {url} as '{repo_name}'…")
        try:
            dest = mgr.add_github_repo(repo_name, url)
            click.echo(click.style(f"✅  Repo '{repo_name}' cloned to {dest}", fg="green"))
        except Exception as exc:
            click.echo(click.style(f"❌  Failed to clone: {exc}", fg="red"))


@repos.command("remove")
@click.argument("name")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def repos_remove(name: str, yes: bool) -> None:
    """Remove a registered repository."""
    mgr = CogManager()

    if name not in mgr.list_repos():
        click.echo(click.style(f"❌  Repo '{name}' not found.", fg="red"))
        return

    if not yes:
        click.confirm(
            f"Remove '{name}'? Cloned data will be deleted from disk.", abort=True
        )

    mgr.remove_repo(name)
    click.echo(click.style(f"✅  Repo '{name}' removed.", fg="green"))


@repos.command("update")
@click.argument("name", required=False, default=None)
def repos_update(name: str | None) -> None:
    """Pull latest changes for GitHub repos."""
    mgr = CogManager()
    all_repos = mgr.list_repos()

    targets = (
        {name: all_repos[name]}
        if name
        else {k: v for k, v in all_repos.items() if v["type"] == "github"}
    )

    if not targets:
        click.echo("No GitHub repos to update.")
        return

    for rname in targets:
        click.echo(f"⬆️   Updating '{rname}'…")
        try:
            mgr.update_github_repo(rname)
            click.echo(click.style(f"  ✅  '{rname}' updated.", fg="green"))
        except Exception as exc:
            click.echo(click.style(f"  ❌  Failed: {exc}", fg="red"))


# ── cogs ──────────────────────────────────────────────────────────────────────


@cli.group()
def cogs() -> None:
    """Manage cogs (extensions)."""


@cogs.command("list")
def cogs_list() -> None:
    """List all installed cogs and their autoload status."""
    mgr = CogManager()
    installed = mgr.get_installed_cogs()
    autoload = set(mgr.get_autoload())

    if not installed:
        click.echo("No cogs installed.\n")
        click.echo("Install one with: " + click.style("python launcher.py cogs install <repo> <cog>", bold=True))
        return

    click.echo(click.style(f"\n🧩  Installed Cogs ({len(installed)})\n", bold=True))
    for cog_path in sorted(installed):
        flag = click.style(" [autoload]", fg="green") if cog_path in autoload else ""
        click.echo(f"  {click.style(cog_path, bold=True)}{flag}")

    click.echo()
    click.echo("Toggle autoload: " + click.style("python launcher.py cogs autoload <cog_path>", bold=True))


@cogs.command("install")
@click.argument("repo")
@click.argument("cog")
def cogs_install(repo: str, cog: str) -> None:
    """Install a cog from a registered repo.

    REPO is the registered repo name, COG is the cog file/package name.
    """
    mgr = CogManager()
    try:
        cog_path = mgr.install_cog(repo, cog)
        click.echo(click.style(f"✅  '{cog}' installed as '{cog_path}'.", fg="green"))
        click.echo(
            "\nEnable autoload: "
            + click.style(f"python launcher.py cogs autoload {cog_path}", bold=True)
        )
    except (ValueError, FileNotFoundError) as exc:
        click.echo(click.style(f"❌  {exc}", fg="red"))


@cogs.command("uninstall")
@click.argument("cog_path")
def cogs_uninstall(cog_path: str) -> None:
    """Uninstall an installed cog (removes from registry, not from disk)."""
    mgr = CogManager()
    try:
        mgr.uninstall_cog(cog_path)
        click.echo(click.style(f"✅  '{cog_path}' uninstalled.", fg="green"))
    except ValueError as exc:
        click.echo(click.style(f"❌  {exc}", fg="red"))


@cogs.command("autoload")
@click.argument("cog_path")
def cogs_autoload(cog_path: str) -> None:
    """Toggle whether a cog loads automatically on bot start."""
    mgr = CogManager()
    try:
        enabled = mgr.toggle_autoload(cog_path)
        if enabled:
            click.echo(click.style(f"✅  '{cog_path}' will autoload on bot start.", fg="green"))
        else:
            click.echo(click.style(f"✅  '{cog_path}' will NOT autoload on bot start.", fg="yellow"))
    except ValueError as exc:
        click.echo(click.style(f"❌  {exc}", fg="red"))


# ── helpers ───────────────────────────────────────────────────────────────────


def _name_from_url(url: str) -> str:
    """Derive a repo name from a GitHub URL."""
    return url.rstrip("/").split("/")[-1].removesuffix(".git")


def _normalize_module_name(name: str) -> str:
    """Convert a string into a valid Python identifier for use as a module name."""
    return name.replace("-", "_").replace(" ", "_").lower()


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()
