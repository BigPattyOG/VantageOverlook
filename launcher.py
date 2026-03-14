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

    python launcher.py system status               # Check system readiness
    python launcher.py system create-user          # Create 'vantage' Linux user (root)
    python launcher.py system install-service      # Install systemd service (root)
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import click

# Ensure the project root is importable regardless of working directory.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.config import CONFIG_PATH, DATA_DIR, load_config, save_config
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
            click.style("No bot token found.", fg="red")
            + "\n\nRun "
            + click.style("python launcher.py setup", bold=True)
            + " to configure the bot."
        )
        sys.exit(1)

    click.echo(click.style("Starting Vantage Bot...", fg="green"))
    bot = VantageBot(config)

    async def _run() -> None:
        async with bot:
            await bot.start(token)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        click.echo(click.style("\nBot stopped.", fg="yellow"))


# ── setup ─────────────────────────────────────────────────────────────────────


@cli.command()
def setup() -> None:
    """Interactive first-run setup wizard."""
    click.echo(click.style("\nVantage Bot — Setup Wizard\n", bold=True, fg="cyan"))

    config = load_config()

    # Step 1 — bot name
    click.echo("Step 1: Bot Name")
    click.echo("  This name identifies the bot instance (shown in vmanage, used for the service).\n")
    name = click.prompt(
        "  Bot name",
        default=config.get("name", "Vantage"),
        prompt_suffix=" > ",
    )
    config["name"] = name.strip()

    # Step 2 — token
    click.echo("\nStep 2: Bot Token")
    click.echo("  Get your token from https://discord.com/developers/applications\n")
    token = click.prompt(
        "  Bot token",
        default=config.get("token", ""),
        hide_input=True,
        show_default=False,
        prompt_suffix=" > ",
    )
    config["token"] = token.strip()

    # Step 3 — prefix
    click.echo("\nStep 3: Command Prefix")
    prefix = click.prompt(
        "  Command prefix",
        default=config.get("prefix", "!"),
        prompt_suffix=" > ",
    )
    config["prefix"] = prefix

    # Step 4 — owner IDs
    click.echo("\nStep 4: Bot Owner(s)")
    click.echo("  Enable Developer Mode in Discord → right-click your name → Copy ID.")
    existing = ", ".join(str(i) for i in config.get("owner_ids", []))
    raw = click.prompt(
        "  Owner IDs (comma-separated)",
        default=existing or "",
        prompt_suffix=" > ",
    )
    config["owner_ids"] = [int(i.strip()) for i in raw.split(",") if i.strip().isdigit()]

    # Step 5 — description
    click.echo("\nStep 5: Bot Description")
    desc = click.prompt(
        "  Description",
        default=config.get("description", "Vantage — a custom Discord bot framework"),
        prompt_suffix=" > ",
    )
    config["description"] = desc

    save_config(config)

    click.echo(
        click.style("\nConfig saved to ", fg="green")
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

    click.echo(click.style(f"\nRepositories ({len(data)})\n", bold=True))
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
            click.echo(click.style(f"Local repo '{repo_name}' added.", fg="green"))
            click.echo(f"   Path: {path.resolve()}")
        except ValueError as exc:
            click.echo(click.style(f"{exc}", fg="red"))
    else:
        # GitHub URL
        url = url_or_path
        repo_name = _normalize_module_name(name or _name_from_url(url))
        click.echo(f"Cloning {url} as '{repo_name}'...")
        try:
            dest = mgr.add_github_repo(repo_name, url)
            click.echo(click.style(f"Repo '{repo_name}' cloned to {dest}", fg="green"))
        except Exception as exc:
            click.echo(click.style(f"Failed to clone: {exc}", fg="red"))


@repos.command("remove")
@click.argument("name")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def repos_remove(name: str, yes: bool) -> None:
    """Remove a registered repository."""
    mgr = CogManager()

    if name not in mgr.list_repos():
        click.echo(click.style(f"Repo '{name}' not found.", fg="red"))
        return

    if not yes:
        click.confirm(
            f"Remove '{name}'? Cloned data will be deleted from disk.", abort=True
        )

    mgr.remove_repo(name)
    click.echo(click.style(f"Repo '{name}' removed.", fg="green"))


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
        click.echo(f"Updating '{rname}'...")
        try:
            mgr.update_github_repo(rname)
            click.echo(click.style(f"  '{rname}' updated.", fg="green"))
        except Exception as exc:
            click.echo(click.style(f"  Failed: {exc}", fg="red"))


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

    click.echo(click.style(f"\nInstalled Cogs ({len(installed)})\n", bold=True))
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
        click.echo(click.style(f"'{cog}' installed as '{cog_path}'.", fg="green"))
        click.echo(
            "\nEnable autoload: "
            + click.style(f"python launcher.py cogs autoload {cog_path}", bold=True)
        )
    except (ValueError, FileNotFoundError) as exc:
        click.echo(click.style(f"{exc}", fg="red"))


@cogs.command("uninstall")
@click.argument("cog_path")
def cogs_uninstall(cog_path: str) -> None:
    """Uninstall an installed cog (removes from registry, not from disk)."""
    mgr = CogManager()
    try:
        mgr.uninstall_cog(cog_path)
        click.echo(click.style(f"'{cog_path}' uninstalled.", fg="green"))
    except ValueError as exc:
        click.echo(click.style(f"{exc}", fg="red"))


@cogs.command("autoload")
@click.argument("cog_path")
def cogs_autoload(cog_path: str) -> None:
    """Toggle whether a cog loads automatically on bot start."""
    mgr = CogManager()
    try:
        enabled = mgr.toggle_autoload(cog_path)
        if enabled:
            click.echo(click.style(f"'{cog_path}' will autoload on bot start.", fg="green"))
        else:
            click.echo(click.style(f"'{cog_path}' will NOT autoload on bot start.", fg="yellow"))
    except ValueError as exc:
        click.echo(click.style(f"{exc}", fg="red"))


# ── system ────────────────────────────────────────────────────────────────────

_BOT_USER = "vantage"
_INSTALL_DIR = Path("/opt")
_SERVICE_SRC = Path(__file__).resolve().parent / "vantage@.service"
_SERVICE_DEST = Path("/etc/systemd/system/vantage@.service")


@cli.group()
def system() -> None:
    """System-level setup commands (user creation, service install).

    Most commands here require root / sudo.
    """


@system.command("status")
def system_status() -> None:
    """Show system readiness: Linux user, service, config, and data directory."""
    click.echo(click.style("\nVantage System Status\n", bold=True))

    # 1 — Linux user
    user_ok = _user_exists(_BOT_USER)
    _status_line(f"Linux user '{_BOT_USER}'", user_ok,
                 ok_detail="exists",
                 fail_detail=f"not found — run: sudo python launcher.py system create-user")

    # 2 — install directory
    dir_ok = _INSTALL_DIR.exists()
    _status_line(f"Install directory ({_INSTALL_DIR})", dir_ok,
                 ok_detail="exists",
                 fail_detail="not found — deploy manually (see README.md)")

    # 3 — systemd service file
    svc_ok = _SERVICE_DEST.exists()
    _status_line("systemd service template", svc_ok,
                 ok_detail=str(_SERVICE_DEST),
                 fail_detail=f"not installed — run: sudo python launcher.py system install-service")

    # 4 — service enabled/running
    if shutil.which("systemctl"):
        # With the template unit (vantage@.service) we check the instance name from config
        from core.config import load_config as _lc
        try:
            _cfg = _lc()
            _svc_name = f"vantage@{_cfg.get('name', 'vantage')}"
        except Exception:
            _svc_name = "vantage@vantage"
        enabled = subprocess.run(
            ["systemctl", "is-enabled", _svc_name], capture_output=True, text=True
        ).returncode == 0
        running = subprocess.run(
            ["systemctl", "is-active", _svc_name], capture_output=True, text=True
        ).returncode == 0
        _status_line(f"systemd service enabled ({_svc_name})", enabled,
                     ok_detail="yes", fail_detail="no")
        _status_line(f"systemd service running ({_svc_name})", running,
                     ok_detail="yes", fail_detail=f"no — run: sudo systemctl start {_svc_name}")
    else:
        click.echo("  " + click.style("[WARN]", fg="yellow") + " systemctl not found — not running on systemd")

    # 5 — config
    from core.config import CONFIG_PATH
    cfg_ok = CONFIG_PATH.exists()
    _status_line(f"Bot config ({CONFIG_PATH})", cfg_ok,
                 ok_detail="found",
                 fail_detail="missing — run: python launcher.py setup")

    if cfg_ok:
        from core.config import load_config
        cfg = load_config()
        token_ok = bool(cfg.get("token", "").strip())
        _status_line("Bot token configured", token_ok,
                     ok_detail="yes",
                     fail_detail="no — run: python launcher.py setup")

    click.echo()


@system.command("create-user")
@click.option("--username", default=_BOT_USER, show_default=True,
              help="Name of the Linux user to create.")
@click.option("--home", default="/opt", show_default=True,
              help="Home directory for the new user.")
def system_create_user(username: str, home: str) -> None:
    """Create the 'vantage' Linux system user for running the bot.

    Requires root (sudo).

    The user is created as a system account with a home directory at
    /opt (by default). The virtual environment and code clone
    live inside this home directory; mutable data lives in /var/lib/<BotName>/.

    Example:
        sudo python launcher.py system create-user
    """
    if os.geteuid() != 0:
        click.echo(click.style("This command must be run as root.", fg="red"))
        click.echo("     Try: " + click.style(f"sudo python launcher.py system create-user", bold=True))
        sys.exit(1)

    if _user_exists(username):
        click.echo(click.style(f"User '{username}' already exists.", fg="green"))
        _print_user_info(username)
        return

    home_path = Path(home)
    click.echo(click.style(f"\nCreating system user '{username}'...\n", bold=True))
    click.echo(f"   Username  : {username}")
    click.echo(f"   Home dir  : {home_path / username}")
    click.echo(f"   Shell     : /bin/bash")
    click.echo(f"   Type      : system account (no login password)\n")

    try:
        home_path.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "useradd",
                "--system",
                "--shell", "/bin/bash",
                "--home-dir", str(home_path / username),
                "--create-home",
                username,
            ],
            check=True,
        )
        click.echo(click.style(f"User '{username}' created successfully.", fg="green"))
        _print_user_info(username)
    except subprocess.CalledProcessError as exc:
        click.echo(click.style(f"Failed to create user: {exc}", fg="red"))
        sys.exit(1)


@system.command("install-service")
@click.option("--user", default=_BOT_USER, show_default=True,
              help="Linux user the service will run as.")
@click.option("--bot-name", "bot_name", default=None,
              help="Bot instance name (used for the service instance and data dir).")
@click.option("--install-dir", "install_dir", default=str(_INSTALL_DIR), show_default=True,
              help="Base install directory (default: /opt). Bot code lives at <install-dir>/<BotName>/.")
def system_install_service(user: str, bot_name: str | None, install_dir: str) -> None:
    """Install (or update) the vantage@ template systemd service.

    Requires root (sudo).

    Copies vantage@.service into /etc/systemd/system/, patches the User field,
    then enables the instance for this bot so it starts automatically on boot.

    The service uses the split-path layout:
      - Code:  /opt/<BotName>/
      - Data:  /var/lib/<BotName>/   (via VANTAGE_DATA_DIR env var)
      - Logs:  journald (view with journalctl -u vantage@<BotName>)

    Example:
        sudo python launcher.py system install-service --bot-name MyBot
        sudo systemctl start vantage@MyBot
    """
    if os.geteuid() != 0:
        click.echo(click.style("This command must be run as root.", fg="red"))
        click.echo("     Try: " + click.style("sudo python launcher.py system install-service", bold=True))
        sys.exit(1)

    if not _SERVICE_SRC.exists():
        click.echo(click.style(f"Service template not found: {_SERVICE_SRC}", fg="red"))
        sys.exit(1)

    install_path = Path(install_dir)

    # Determine bot name for the instance
    if not bot_name:
        try:
            from core.config import load_config as _lc
            bot_name = _lc().get("name", install_path.name)
        except Exception:
            bot_name = install_path.name

    data_dir = Path("/var/lib") / bot_name
    working_dir = install_path / bot_name
    venv_python = working_dir / "venv" / "bin" / "python"
    instance_svc = f"vantage@{bot_name}"

    click.echo(click.style("\nInstalling systemd service...\n", bold=True))
    click.echo(f"   Template file : {_SERVICE_DEST}")
    click.echo(f"   Instance      : {instance_svc}")
    click.echo(f"   Run as user   : {user}")
    click.echo(f"   Working dir   : {working_dir}")
    click.echo(f"   Data dir      : {data_dir}")
    click.echo(f"   Python        : {venv_python}\n")

    # Read the template and only patch the User= field.
    # WorkingDirectory, ExecStart, and Environment already use %i placeholders
    # in the template file and need no further patching.
    content = _SERVICE_SRC.read_text(encoding="utf-8")
    patched_lines = []
    for line in content.splitlines():
        if line.startswith("User="):
            patched_lines.append(f"User={user}")
        else:
            patched_lines.append(line)

    _SERVICE_DEST.write_text("\n".join(patched_lines) + "\n", encoding="utf-8")

    # Create the data directory if it doesn't exist
    data_dir.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", instance_svc], check=True)
        click.echo(click.style(f"Service {instance_svc} installed and enabled.", fg="green"))
        click.echo("\nStart the bot now with:")
        click.echo("  " + click.style(f"sudo systemctl start {instance_svc}", bold=True))
        click.echo("Watch the logs:")
        click.echo("  " + click.style(f"sudo journalctl -u {instance_svc} -f", bold=True))
    except FileNotFoundError:
        click.echo(click.style("systemctl not found — are you on a systemd system?", fg="yellow"))
    except subprocess.CalledProcessError as exc:
        click.echo(click.style(f"systemctl error: {exc}", fg="red"))
        sys.exit(1)


# ── system helpers ────────────────────────────────────────────────────────────


def _user_exists(username: str) -> bool:
    """Return True if a Linux user with the given name exists."""
    try:
        import pwd
        pwd.getpwnam(username)
        return True
    except KeyError:
        return False


def _print_user_info(username: str) -> None:
    """Print a brief summary of the user's home directory and next steps."""
    try:
        import pwd
        pw = pwd.getpwnam(username)
        click.echo(f"\n   Home directory : {pw.pw_dir}")
        click.echo(f"   UID            : {pw.pw_uid}\n")
    except KeyError:
        pass
    click.echo("Next steps:")
    click.echo(f"  Switch to the user : " + click.style(f"sudo -u {username} bash", bold=True))
    click.echo(f"  Run the setup wizard: " + click.style("python launcher.py setup", bold=True))


def _status_line(label: str, ok: bool, ok_detail: str = "", fail_detail: str = "") -> None:
    icon = click.style("[OK]", fg="green") if ok else click.style("[FAIL]", fg="red")
    detail = ok_detail if ok else click.style(fail_detail, fg="yellow")
    click.echo(f"  {icon}  {label}" + (f" — {detail}" if detail else ""))


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
