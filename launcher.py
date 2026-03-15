#!/usr/bin/env python3
"""vprod Bot Launcher — CLI entry point.

Usage
-----
::

    python launcher.py start              # Run the bot

    python launcher.py repos list         # List registered repositories
    python launcher.py repos add URL      # Clone a GitHub repo
    python launcher.py repos add PATH     # Link a local repo
    python launcher.py repos remove NAME
    python launcher.py repos update [NAME]

    python launcher.py plugins list                    # List installed plugins
    python launcher.py plugins install REPO PLUGIN     # Install a plugin
    python launcher.py plugins uninstall PLUGIN_PATH   # Uninstall a plugin
    python launcher.py plugins autoload PLUGIN_PATH    # Toggle autoload

    python launcher.py system status               # Check system readiness
    python launcher.py system create-user          # Create system user and dev group (root)
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

from framework.config import CONFIG_PATH, DATA_DIR, get_token, load_config, save_config
from framework.plugin_manager import PluginManager
from framework.log_setup import setup_logging as _setup_logging_core


# ── CLI root ──────────────────────────────────────────────────────────────────


@click.group()
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
@click.pass_context
def cli(ctx: click.Context, debug: bool) -> None:
    """vprod — Vantage Discord Bot framework."""
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug


# ── start ─────────────────────────────────────────────────────────────────────


@cli.command()
@click.pass_context
def start(ctx: click.Context) -> None:
    """Start the vprod bot."""
    debug = ctx.obj.get("debug", False)
    log_file = _setup_logging_core(debug=debug, log_dir=DATA_DIR / "logs")
    log = logging.getLogger("vprod")
    if log_file:
        log.info("Logging to file: %s", log_file)
    from framework.bot import VantageBot

    config = load_config()

    try:
        token = get_token()
    except RuntimeError as exc:
        click.echo(click.style(str(exc), fg="red"))
        click.echo(
            "\nSet DISCORD_TOKEN in your .env file or environment and try again."
        )
        sys.exit(1)

    click.echo(click.style("Starting vprod...", fg="cyan"))
    bot = VantageBot(config)

    async def _run() -> None:
        async with bot:
            await bot.start(token)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        click.echo(click.style("\nBot stopped.", fg="yellow"))


# ── repos ─────────────────────────────────────────────────────────────────────


@cli.group()
def repos() -> None:
    """Manage cog repositories."""


@repos.command("list")
def repos_list() -> None:
    """List all registered repositories."""
    mgr = PluginManager()
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
        plugins = info.get("installed_plugins", [])
        click.echo(f"   Plugins : {', '.join(plugins) if plugins else '(none installed)'}\n")


@repos.command("add")
@click.argument("url_or_path")
@click.option("--name", default=None, help="Custom name for the repository (must be a valid Python identifier).")
def repos_add(url_or_path: str, name: str | None) -> None:
    """Add a repository — GitHub URL or local directory path."""
    mgr = PluginManager()
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
    mgr = PluginManager()

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
    mgr = PluginManager()
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


# ── plugins ───────────────────────────────────────────────────────────────────


@cli.group()
def plugins() -> None:
    """Manage plugins (extensions)."""


@plugins.command("list")
def plugins_list() -> None:
    """List all installed plugins and their autoload status."""
    mgr = PluginManager()
    installed = mgr.get_installed_plugins()
    autoload = set(mgr.get_autoload())

    if not installed:
        click.echo("No plugins installed.\n")
        click.echo("Install one with: " + click.style("python launcher.py plugins install <repo> <plugin>", bold=True))
        return

    click.echo(click.style(f"\nInstalled Plugins ({len(installed)})\n", bold=True))
    for plugin_path in sorted(installed):
        flag = click.style(" [autoload]", fg="green") if plugin_path in autoload else ""
        click.echo(f"  {click.style(plugin_path, bold=True)}{flag}")

    click.echo()
    click.echo("Toggle autoload: " + click.style("python launcher.py plugins autoload <plugin_path>", bold=True))


@plugins.command("install")
@click.argument("repo")
@click.argument("plugin")
def plugins_install(repo: str, plugin: str) -> None:
    """Install a plugin from a registered repo.

    REPO is the registered repo name, PLUGIN is the plugin file/package name.
    """
    mgr = PluginManager()
    try:
        plugin_path = mgr.install_plugin(repo, plugin)
        click.echo(click.style(f"'{plugin}' installed as '{plugin_path}'.", fg="green"))
        click.echo(
            "\nEnable autoload: "
            + click.style(f"python launcher.py plugins autoload {plugin_path}", bold=True)
        )
    except (ValueError, FileNotFoundError) as exc:
        click.echo(click.style(f"{exc}", fg="red"))


@plugins.command("uninstall")
@click.argument("plugin_path")
def plugins_uninstall(plugin_path: str) -> None:
    """Uninstall a plugin (removes from registry, not from disk)."""
    mgr = PluginManager()
    try:
        mgr.uninstall_plugin(plugin_path)
        click.echo(click.style(f"'{plugin_path}' uninstalled.", fg="green"))
    except ValueError as exc:
        click.echo(click.style(f"{exc}", fg="red"))


@plugins.command("autoload")
@click.argument("plugin_path")
def plugins_autoload(plugin_path: str) -> None:
    """Toggle whether a plugin loads automatically on bot start."""
    mgr = PluginManager()
    try:
        enabled = mgr.toggle_autoload(plugin_path)
        if enabled:
            click.echo(click.style(f"'{plugin_path}' will autoload on bot start.", fg="green"))
        else:
            click.echo(click.style(f"'{plugin_path}' will NOT autoload on bot start.", fg="yellow"))
    except ValueError as exc:
        click.echo(click.style(f"{exc}", fg="red"))


# ── system ────────────────────────────────────────────────────────────────────

_BOT_USER = "vprodbot"
_DEV_GROUP = "vprodadmins"
_INSTALL_DIR = Path("/opt/vprod")
_SERVICE_SRC = Path(__file__).resolve().parent / "vprod.service"
_SERVICE_DEST = Path("/etc/systemd/system/vprod.service")


@cli.group()
def system() -> None:
    """System-level setup commands (user creation, service install).

    Most commands here require root / sudo.
    """


@system.command("status")
def system_status() -> None:
    """Show system readiness: Linux user, dev group, service, config, and data directory."""
    click.echo(click.style("\nvprod System Status\n", bold=True))

    # 1 — Linux user
    user_ok = _user_exists(_BOT_USER)
    _status_line(f"Linux user '{_BOT_USER}'", user_ok,
                 ok_detail="exists",
                 fail_detail=f"not found — run: sudo python launcher.py system create-user")

    # 2 — dev group
    group_ok = _group_exists(_DEV_GROUP)
    _status_line(f"Dev group '{_DEV_GROUP}'", group_ok,
                 ok_detail="exists",
                 fail_detail=f"not found — run: sudo python launcher.py system create-user")

    # 3 — install directory
    dir_ok = _INSTALL_DIR.exists()
    _status_line(f"Install directory ({_INSTALL_DIR})", dir_ok,
                 ok_detail="exists",
                 fail_detail="not found — deploy manually (see README.md)")

    # 4 — systemd service file
    svc_ok = _SERVICE_DEST.exists()
    _status_line("systemd service file", svc_ok,
                 ok_detail=str(_SERVICE_DEST),
                 fail_detail=f"not installed — run: sudo python launcher.py system install-service")

    # 5 — service enabled/running
    if shutil.which("systemctl"):
        _svc_name = "vprod"
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

    # 6 — config
    from framework.config import CONFIG_PATH
    cfg_ok = CONFIG_PATH.exists()
    _status_line(f"Bot config ({CONFIG_PATH})", cfg_ok,
                 ok_detail="found",
                 fail_detail="missing — create config.json in the data directory")

    # 7 — DISCORD_TOKEN in environment
    import os as _os
    token_ok = bool(_os.environ.get("DISCORD_TOKEN", "").strip())
    _status_line("DISCORD_TOKEN set", token_ok,
                 ok_detail="yes",
                 fail_detail="no — set DISCORD_TOKEN in your .env file")

    click.echo()


@system.command("create-user")
@click.option("--username", default=_BOT_USER, show_default=True,
              help="Name of the Linux system user to create.")
@click.option("--group", "dev_group", default=_DEV_GROUP, show_default=True,
              help="Name of the developer group to create.")
@click.option("--home", default=str(_INSTALL_DIR), show_default=True,
              help="Home directory for the new user.")
def system_create_user(username: str, dev_group: str, home: str) -> None:
    """Create the 'vprodbot' system user and 'vprodadmins' dev group.

    Requires root (sudo).

    The user is created as a system account with home at /opt/vprod.
    The dev group allows authorised developers to manage the bot without root.
    Mutable data lives in /var/lib/vprod/.

    Example:
        sudo python launcher.py system create-user
    """
    if os.geteuid() != 0:
        click.echo(click.style("This command must be run as root.", fg="red"))
        click.echo("     Try: " + click.style(f"sudo python launcher.py system create-user", bold=True))
        sys.exit(1)

    # Create dev group first
    if _group_exists(dev_group):
        click.echo(click.style(f"Group '{dev_group}' already exists.", fg="cyan"))
    else:
        click.echo(f"Creating dev group '{dev_group}'...")
        try:
            subprocess.run(["groupadd", "--system", dev_group], check=True)
            click.echo(click.style(f"Group '{dev_group}' created.", fg="green"))
        except subprocess.CalledProcessError as exc:
            click.echo(click.style(f"Failed to create group: {exc}", fg="red"))
            sys.exit(1)

    # Create bot user
    if _user_exists(username):
        click.echo(click.style(f"User '{username}' already exists.", fg="cyan"))
        _print_user_info(username)
        return

    home_path = Path(home)
    click.echo(click.style(f"\nCreating system user '{username}'...\n", bold=True))
    click.echo(f"   Username  : {username}")
    click.echo(f"   Home dir  : {home_path}")
    click.echo(f"   Shell     : /bin/bash")
    click.echo(f"   Type      : system account (no login password)\n")

    try:
        home_path.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "useradd",
                "--system",
                "--shell", "/bin/bash",
                "--home-dir", str(home_path),
                "--create-home",
                username,
            ],
            check=True,
        )
        click.echo(click.style(f"User '{username}' created successfully.", fg="green"))
        click.echo(f"\nTo add a developer to the '{dev_group}' group:")
        click.echo(click.style(f"  sudo usermod -aG {dev_group} <username>", bold=True))
        _print_user_info(username)
    except subprocess.CalledProcessError as exc:
        click.echo(click.style(f"Failed to create user: {exc}", fg="red"))
        sys.exit(1)


@system.command("install-service")
@click.option("--user", default=_BOT_USER, show_default=True,
              help="Linux user the service will run as.")
def system_install_service(user: str) -> None:
    """Install (or update) the vprod systemd service.

    Requires root (sudo).

    Copies vprod.service into /etc/systemd/system/, patches the User field,
    then enables it so the bot starts automatically on boot.

    Layout:
      - Code:  /opt/vprod/
      - Data:  /var/lib/vprod/   (via VPROD_DATA_DIR env var)
      - Token: /opt/vprod/.env   (DISCORD_TOKEN)
      - Logs:  journald (journalctl -u vprod -f)

    Example:
        sudo python launcher.py system install-service
        sudo systemctl start vprod
    """
    if os.geteuid() != 0:
        click.echo(click.style("This command must be run as root.", fg="red"))
        click.echo("     Try: " + click.style("sudo python launcher.py system install-service", bold=True))
        sys.exit(1)

    if not _SERVICE_SRC.exists():
        click.echo(click.style(f"Service file not found: {_SERVICE_SRC}", fg="red"))
        sys.exit(1)

    venv_python = _INSTALL_DIR / "venv" / "bin" / "python"
    data_dir = Path("/var/lib/vprod")

    click.echo(click.style("\nInstalling systemd service...\n", bold=True))
    click.echo(f"   Service file  : {_SERVICE_DEST}")
    click.echo(f"   Service name  : vprod")
    click.echo(f"   Run as user   : {user}")
    click.echo(f"   Working dir   : {_INSTALL_DIR}")
    click.echo(f"   Data dir      : {data_dir}")
    click.echo(f"   Python        : {venv_python}\n")

    # Read the service file and patch the User= field.
    content = _SERVICE_SRC.read_text(encoding="utf-8")
    patched_lines = []
    for line in content.splitlines():
        if line.startswith("User="):
            patched_lines.append(f"User={user}")
        else:
            patched_lines.append(line)

    _SERVICE_DEST.write_text("\n".join(patched_lines) + "\n", encoding="utf-8")

    # Ensure the data directory exists
    data_dir.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "vprod"], check=True)
        click.echo(click.style("Service 'vprod' installed and enabled.", fg="green"))
        click.echo("\nStart the bot now with:")
        click.echo("  " + click.style("sudo systemctl start vprod", bold=True))
        click.echo("Watch the logs:")
        click.echo("  " + click.style("sudo journalctl -u vprod -f", bold=True))
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


def _group_exists(groupname: str) -> bool:
    """Return True if a Linux group with the given name exists."""
    try:
        import grp
        grp.getgrnam(groupname)
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
    click.echo(f"  Deploy the bot code : " + click.style(f"sudo git clone <repo> /opt/vprod", bold=True))


def _status_line(label: str, ok: bool, ok_detail: str = "", fail_detail: str = "") -> None:
    icon = click.style("[OK]", fg="cyan") if ok else click.style("[FAIL]", fg="red")
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
