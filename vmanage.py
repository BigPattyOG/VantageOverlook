#!/usr/bin/env python3
"""vmanage — vprod Bot CLI management tool.

Manage the installed vprod bot from the command line.
Uses only the Python standard library so it works without activating a venv.

Usage
-----
::

    vmanage                          Show status dashboard
    vmanage --start                  Start the bot service
    vmanage --stop                   Stop the bot service
    vmanage --restart                Restart the bot service
    vmanage --status                 Show full systemctl service status
    vmanage --logs                   Stream live logs  (Ctrl+C to stop)
    vmanage --logs --lines 50        Show last 50 log lines (non-streaming)
    vmanage --update                 git pull + pip upgrade + restart
    vmanage --update-token           Update the Discord token in .env + restart
    vmanage --repos                  List plugin repositories
    vmanage --plugins                List installed plugins
    vmanage --debug                  Show verbose debug output
    vmanage --yes                    Skip confirmation prompts
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── constants ──────────────────────────────────────────────────────────────────

INSTALL_DIR = Path("/opt/vprod")
DATA_DIR = Path("/var/lib/vprod")
BOT_USER = "vprodbot"
VERSION = "2.0.0"

# ── colour helpers ─────────────────────────────────────────────────────────────

_USE_COLOR = sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def bold(t: str) -> str:    return _c(t, "1")
def dim(t: str) -> str:     return _c(t, "2")
def red(t: str) -> str:     return _c(t, "31")
def green(t: str) -> str:   return _c(t, "32")
def yellow(t: str) -> str:  return _c(t, "33")
def teal(t: str) -> str:    return _c(t, "36")  # ANSI cyan is closest to teal in terminals
def blue(t: str) -> str:    return _c(t, "34")


def ok(msg: str) -> None:   print(f"  {teal('[ok]')}  {msg}")
def warn(msg: str) -> None: print(f"  {yellow('[!]')}  {msg}")
def err(msg: str) -> None:  print(f"  {red('[x]')}  {msg}", file=sys.stderr)
def info(msg: str) -> None: print(f"  {teal('>')}  {msg}")


def die(msg: str) -> None:
    err(msg)
    sys.exit(1)


# ── ASCII banner ───────────────────────────────────────────────────────────────

_BANNER_LINES = [
    "  ██╗   ██╗██████╗ ██████╗  ██████╗ ██████╗ ",
    "  ██║   ██║██╔══██╗██╔══██╗██╔═══██╗██╔══██╗",
    "  ██║   ██║██████╔╝██████╔╝██║   ██║██║  ██║",
    "  ╚██╗ ██╔╝██╔═══╝ ██╔══██╗██║   ██║██║  ██║",
    "   ╚████╔╝ ██║     ██║  ██║╚██████╔╝██████╔╝",
    "    ╚═══╝  ╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ",
]


def print_banner(subtitle: str = "Bot Manager") -> None:
    print(teal(bold("\n".join(_BANNER_LINES))))
    print(f"\n  {bold('vmanage')} {dim('—')} {subtitle}\n")


# ── bot instance ───────────────────────────────────────────────────────────────

class BotInstance:
    """Represents the installed vprod bot at ``/opt/vprod/``."""

    def __init__(self) -> None:
        self.install_dir = INSTALL_DIR
        self.config: Dict[str, Any] = self._load_config()
        self.name: str = self.config.get("name", "vprod")
        self.service_name: str = "vprod"
        self.prefix: str = self.config.get("prefix", "!")
        self.venv_python: Path = INSTALL_DIR / "venv" / "bin" / "python"
        self.venv_pip: Path = INSTALL_DIR / "venv" / "bin" / "pip"

    # ── helpers ───────────────────────────────────────────────────────────────

    def _load_config(self) -> Dict[str, Any]:
        # Production layout: data lives in /var/lib/vprod/
        varlib_cfg = DATA_DIR / "config.json"
        # Dev layout: data/ next to the install dir
        local_cfg = INSTALL_DIR / "data" / "config.json"

        for cfg in (varlib_cfg, local_cfg):
            if cfg.exists():
                try:
                    with open(cfg, encoding="utf-8") as fh:
                        return json.load(fh)
                except Exception:
                    pass
        return {}

    def has_venv(self) -> bool:
        return self.venv_python.exists() and os.access(str(self.venv_python), os.X_OK)

    def has_token(self) -> bool:
        """Return True if DISCORD_TOKEN is set in the .env file or environment."""
        # Production layout: token is in DATA_DIR/.env (/var/lib/vprod/.env)
        # Dev layout: token is in INSTALL_DIR/data/.env (./data/.env)
        candidates = [
            DATA_DIR / ".env",
            INSTALL_DIR / "data" / ".env",
        ]
        for env_file in candidates:
            if env_file.exists():
                try:
                    content = env_file.read_text(encoding="utf-8")
                    for line in content.splitlines():
                        line = line.strip()
                        if line.startswith("DISCORD_TOKEN=") and len(line) > len("DISCORD_TOKEN="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val and not val.startswith("your_"):
                                return True
                except Exception:
                    pass
        # Fall back to environment
        return bool(os.environ.get("DISCORD_TOKEN", "").strip())

    # ── systemd queries ───────────────────────────────────────────────────────

    def _systemctl(self, *args: str, capture: bool = True) -> subprocess.CompletedProcess:
        cmd = ["systemctl"] + list(args)
        if capture:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        return subprocess.run(cmd, timeout=15)

    def is_running(self) -> bool:
        if not shutil.which("systemctl"):
            return False
        r = self._systemctl("is-active", "--quiet", self.service_name)
        return r.returncode == 0

    def active_state(self) -> str:
        if not shutil.which("systemctl"):
            return "unknown"
        r = self._systemctl("show", "-p", "ActiveState", "--value", self.service_name)
        return r.stdout.strip() or "unknown"

    def uptime(self) -> Optional[str]:
        """Return a human-readable uptime string, or None if unavailable."""
        if not shutil.which("systemctl"):
            return None
        r = self._systemctl(
            "show", "-p", "ActiveEnterTimestamp", "--value", self.service_name
        )
        ts = r.stdout.strip()
        if not ts or ts == "0":
            return None
        # systemd format: "Thu 2026-03-14 02:49:43 UTC"
        for fmt in ("%a %Y-%m-%d %H:%M:%S %Z", "%a %Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.datetime.strptime(ts, fmt).replace(
                    tzinfo=datetime.timezone.utc
                )
                delta = datetime.datetime.now(datetime.timezone.utc) - dt
                total = int(delta.total_seconds())
                if total < 0:
                    return None
                h, rem = divmod(total, 3600)
                m, s = divmod(rem, 60)
                return f"{h}h {m}m {s}s"
            except ValueError:
                continue
        return None

    def python_version(self) -> Optional[str]:
        if not self.has_venv():
            return None
        try:
            r = subprocess.run(
                [str(self.venv_python), "--version"],
                capture_output=True, text=True, timeout=5,
            )
            ver = (r.stdout or r.stderr).strip()
            # "Python 3.13.2" → "3.13.2"
            return ver.split()[-1] if ver.startswith("Python") else ver
        except Exception:
            return None


def get_bot() -> BotInstance:
    """Return the single installed vprod bot instance."""
    if not INSTALL_DIR.exists():
        die(
            f"Install directory {INSTALL_DIR} not found.\n"
            f"  Deploy the bot with: sudo git clone <repo> {INSTALL_DIR}"
        )
    return BotInstance()

# ── service control helpers ────────────────────────────────────────────────────

def _need_systemctl() -> None:
    if not shutil.which("systemctl"):
        die("systemctl not found — vmanage requires a systemd-based system.")


def _run_bot_cmd(bot: BotInstance, *cmd_parts: str) -> None:
    """Run a command as the bot user inside the install directory."""
    import shlex
    quoted_parts = " ".join(shlex.quote(str(p)) for p in cmd_parts)
    subprocess.run(
        ["sudo", "-u", BOT_USER, "bash", "-c",
         f"cd {shlex.quote(str(INSTALL_DIR))} && {quoted_parts}"]
    )


# ── actions ────────────────────────────────────────────────────────────────────

def do_start(bot: BotInstance, debug: bool = False) -> None:
    _need_systemctl()
    info(f"Starting {bold(bot.service_name)}...")
    r = subprocess.run(["sudo", "systemctl", "start", bot.service_name])
    if r.returncode != 0:
        die(
            f"Failed to start service.\n"
            f"  Check logs: {bold('vmanage --logs')}\n"
            f"  Or try:    {bold(f'sudo systemctl start {bot.service_name}')}"
        )
    time.sleep(1.5)
    if bot.is_running():
        ok(f"{bold(bot.name)} is {teal(bold('running'))}.")
    else:
        warn(
            "Service started but may not be active yet.\n"
            f"  Check logs: {bold('vmanage --logs')}"
        )


def do_stop(bot: BotInstance, debug: bool = False) -> None:
    _need_systemctl()
    info(f"Stopping {bold(bot.service_name)}...")
    r = subprocess.run(["sudo", "systemctl", "stop", bot.service_name])
    if r.returncode != 0:
        die(
            f"Failed to stop service.\n"
            f"  Try: {bold(f'sudo systemctl stop {bot.service_name}')}"
        )
    ok(f"{bold(bot.name)} stopped.")


def do_restart(bot: BotInstance, debug: bool = False) -> None:
    _need_systemctl()
    info(f"Restarting {bold(bot.service_name)}...")
    r = subprocess.run(["sudo", "systemctl", "restart", bot.service_name])
    if r.returncode != 0:
        die(
            f"Failed to restart service.\n"
            f"  Check logs: {bold('vmanage --logs')}\n"
            f"  Or try:    {bold(f'sudo systemctl restart {bot.service_name}')}"
        )
    time.sleep(1.5)
    if bot.is_running():
        ok(f"{bold(bot.name)} restarted — {teal(bold('running'))}.")
    else:
        warn(
            "Service restarted but may not be active yet.\n"
            f"  Check logs: {bold('vmanage --logs')}"
        )


def do_status(bot: BotInstance, debug: bool = False) -> None:
    _need_systemctl()
    print()
    subprocess.run(
        ["systemctl", "status", bot.service_name, "--no-pager"],
    )
    print()


def do_logs(bot: BotInstance, lines: Optional[int] = None, debug: bool = False) -> None:
    if not shutil.which("journalctl"):
        die("journalctl not found.")
    cmd = ["journalctl", "-u", bot.service_name, "--no-pager"]
    if lines is not None:
        cmd += ["-n", str(lines)]
        info(f"Last {lines} log lines — {bold(bot.name)}:")
        print()
        subprocess.run(cmd)
    else:
        info(f"Streaming live logs for {bold(bot.name)}  (Ctrl+C to stop)...")
        print()
        try:
            subprocess.run(cmd + ["-f"])
        except KeyboardInterrupt:
            print()
            ok("Log stream ended.")


def do_update(bot: BotInstance, debug: bool = False, yes: bool = False) -> None:
    if not yes:
        try:
            ans = input(
                f"\n  Update {bold(bot.name)}? "
                f"This will git pull + pip upgrade + restart. [y/N] "
            )
        except EOFError:
            ans = ""
        if ans.strip().lower() not in ("y", "yes"):
            info("Update cancelled.")
            return
    print()
    info("Pulling latest code from GitHub...")
    r = subprocess.run(
        ["sudo", "-u", BOT_USER, "git", "-C", str(bot.install_dir), "pull", "--ff-only"]
    )
    if r.returncode != 0:
        warn("git pull did not fast-forward -- repository may be up-to-date or have local changes.")
    else:
        ok("Code updated.")
    print()
    if bot.has_venv():
        info("Upgrading Python dependencies...")
        subprocess.run(["sudo", "-u", BOT_USER, str(bot.venv_pip),
                        "install", "-q", "--upgrade", "pip"])
        subprocess.run(["sudo", "-u", BOT_USER, str(bot.venv_pip),
                        "install", "-q", "-r", str(bot.install_dir / "requirements.txt")])
        ok("Dependencies upgraded.")
    else:
        warn("Virtual environment not found — skipping pip upgrade.")
    print()
    do_restart(bot, debug)


def do_repos(bot: BotInstance, debug: bool = False) -> None:
    if not bot.has_venv():
        die("Virtual environment not found.")
    info(f"Plugin repositories — {bold(bot.name)}:")
    print()
    _run_bot_cmd(bot, str(bot.venv_python), "launcher.py", "repos", "list")


def do_update_token(bot: BotInstance, debug: bool = False, yes: bool = False) -> None:
    """Interactively update the Discord token in the .env file, then restart."""
    import getpass
    import shlex

    # Determine which .env to update: production layout first, dev layout second.
    prod_env = DATA_DIR / ".env"
    dev_env = INSTALL_DIR / "data" / ".env"

    if prod_env.exists():
        env_file = prod_env
        needs_sudo = True
    elif dev_env.exists():
        env_file = dev_env
        needs_sudo = False
    elif DATA_DIR.exists():
        # Production data dir exists but .env not yet written
        env_file = prod_env
        needs_sudo = True
    else:
        # Fall back to dev layout
        env_file = dev_env
        needs_sudo = False

    info(f"Token file: {bold(str(env_file))}")
    print()

    # Token format: three base64url segments separated by dots (same regex as install-vprod.sh)
    _TOKEN_RE = re.compile(
        r"^[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}$"
    )

    token = ""
    while True:
        try:
            token = getpass.getpass("  Enter new DISCORD_TOKEN (input hidden): ")
        except (KeyboardInterrupt, EOFError):
            print()
            info("Cancelled.")
            return

        token = token.strip()
        if not token:
            warn("Token cannot be empty. Try again.")
            continue

        if _TOKEN_RE.match(token):
            break

        warn("That doesn't look like a valid Discord bot token.")
        warn("Expected format: <24+chars>.<6chars>.<27+chars>")
        info("Get your token: https://discord.com/developers/applications")
        try:
            again = input("  Try again? [Y/n]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            info("Cancelled.")
            return
        if again in ("n", "no"):
            info("Cancelled.")
            return
        print()

    content = f"DISCORD_TOKEN={token}\n"

    if needs_sudo:
        # Write via stdin piped to `sudo tee` so the token never appears in
        # the process argument list (visible to other users via `ps`).
        safe_path = shlex.quote(str(env_file))
        safe_user = shlex.quote(BOT_USER)
        cmd = (
            f"tee {safe_path} >/dev/null"
            f" && chmod 600 {safe_path}"
            f" && chown {safe_user}:{safe_user} {safe_path}"
        )
        r = subprocess.run(
            ["sudo", "bash", "-c", cmd],
            input=content,
            text=True,
        )
        if r.returncode != 0:
            die("Failed to write token file. Make sure you have sudo access.")
    else:
        # Dev layout — write directly (current user owns the file).
        try:
            env_file.parent.mkdir(parents=True, exist_ok=True)
            env_file.write_text(content, encoding="utf-8")
            env_file.chmod(0o600)
        except Exception as exc:
            die(f"Failed to write {env_file}: {exc}")

    ok(f"Token updated in {bold(str(env_file))}  {dim('(permissions: 600)')}")
    print()

    # Offer to restart the service so the new token takes effect.
    if shutil.which("systemctl"):
        restart = True
        if not yes:
            try:
                ans = input(
                    f"  Restart {bold(bot.service_name)} now so the new token takes effect? [Y/n]: "
                ).strip().lower()
                restart = ans not in ("n", "no")
            except (KeyboardInterrupt, EOFError):
                print()
                restart = False

        if restart:
            do_restart(bot, debug)
        else:
            info(f"Skipping restart. Run {bold('vmanage --restart')} when ready.")
    else:
        info("No systemd found — restart the bot process manually.")


def do_plugins(bot: BotInstance, debug: bool = False) -> None:
    if not bot.has_venv():
        die("Virtual environment not found.")
    info(f"Installed plugins — {bold(bot.name)}:")
    print()
    _run_bot_cmd(bot, str(bot.venv_python), "launcher.py", "plugins", "list")


# ── status dashboard ───────────────────────────────────────────────────────────

def do_dashboard(bot: BotInstance, debug: bool = False) -> None:
    """Print a rich single-page status dashboard for the bot."""
    print_banner(f"{bold(bot.name)}  {dim('—')}  {str(bot.install_dir)}")

    W = 60
    SEP = dim("─" * W)

    # ── Service status ────────────────────────────────────────────────────────
    running = bot.is_running()
    state   = bot.active_state()

    if running:
        status_str = f"{teal('●')} {teal(bold('running'))}"
    elif state in ("activating", "deactivating", "reloading"):
        status_str = f"{yellow('●')} {yellow(bold(state))}"
    else:
        status_str = f"{red('●')} {red(bold(state or 'stopped'))}"

    print(f"  {SEP}")
    print(f"  {bold('Status')}")
    print(f"  {SEP}")
    print(f"  {'Service status':<18} {status_str}")

    if running:
        uptime = bot.uptime()
        if uptime:
            print(f"  {'Uptime':<18} {teal(uptime)}")

    print(f"  {'Service unit':<18} {dim(bot.service_name + '.service')}")
    print()

    # ── Paths ─────────────────────────────────────────────────────────────────
    print(f"  {bold('Paths')}")
    print(f"  {SEP}")
    print(f"  {'Install dir':<18} {dim(str(bot.install_dir))}")
    print(f"  {'Data dir':<18} {dim(str(DATA_DIR))}")
    print()

    # ── Config ────────────────────────────────────────────────────────────────
    print(f"  {bold('Configuration')}")
    print(f"  {SEP}")
    if bot.config:
        owners = bot.config.get("owner_ids", [])
        description = bot.config.get("description", "")
        print(
            f"  {'Config':<18} {teal('found')}  "
            f"{dim(f'prefix={bold(bot.prefix)}, owners={len(owners)}')}"
        )
        if description:
            print(f"  {'Description':<18} {dim(description)}")
    else:
        print(
            f"  {'Config':<18} {red('missing')}  "
            f"{dim('create /var/lib/vprod/config.json')}"
        )

    # Python / venv
    py_ver = bot.python_version()
    if py_ver:
        print(f"  {'Python':<18} {teal(py_ver)}  {dim('(venv active)')}")
    else:
        print(f"  {'Python':<18} {red('venv not found')}  {dim('run: install.sh or create venv manually')}")

    # Token check
    if bot.has_token():
        print(f"  {'Discord token':<18} {teal('set')}")
    else:
        print(f"  {'Discord token':<18} {red('NOT SET')}  {dim('run: vmanage --update-token')}")

    print()

    # ── Quick reference ───────────────────────────────────────────────────────
    print(f"  {bold('Commands')}")
    print(f"  {SEP}")
    pairs = [
        ("Start",            "vmanage --start"),
        ("Stop",             "vmanage --stop"),
        ("Restart",          "vmanage --restart"),
        ("Full status",      "vmanage --status"),
        ("Stream logs",      "vmanage --logs"),
        ("Last N lines",     "vmanage --logs --lines 50"),
        ("Update & restart", "vmanage --update"),
        ("Update token",     "vmanage --update-token"),
        ("List plugins",     "vmanage --plugins"),
        ("List repos",       "vmanage --repos"),
        ("Debug info",       "vmanage --debug"),
    ]
    label_w = max(len(lb) for lb, _ in pairs)
    for label, cmd in pairs:
        print(f"  {dim(label + ':'):<{label_w + 10}} {bold(cmd)}")
    print(f"  {SEP}")
    print()


# ── status dashboard (single bot) ─────────────────────────────────────────────

# do_dashboard is defined above


# ── argument parser ────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vmanage",
        description="vprod Bot CLI — manage the installed bot.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  vmanage                       Show status dashboard
  vmanage --start               Start the bot service
  vmanage --restart             Restart the bot service
  vmanage --logs                Stream live logs  (Ctrl+C to stop)
  vmanage --logs --lines 100    Show last 100 lines, non-streaming
  vmanage --update              Pull latest code and restart
  vmanage --update --yes        Same, skip confirmation
  vmanage --update-token        Change the Discord token and restart
  vmanage --plugins             List installed plugins
  vmanage --repos               List plugin repositories
  vmanage --debug               Show verbose debug information
""",
    )

    p.add_argument("--version", action="version", version=f"vmanage {VERSION}")

    # ── action flags (mutually exclusive) ─────────────────────────────────────
    act = p.add_argument_group("actions  (mutually exclusive)")
    mx = act.add_mutually_exclusive_group()
    mx.add_argument("--start",   action="store_true", help="Start the bot service")
    mx.add_argument("--stop",    action="store_true", help="Stop the bot service")
    mx.add_argument("--restart", action="store_true", help="Restart the bot service")
    mx.add_argument("--status",  action="store_true", help="Show full systemctl status output")
    mx.add_argument("--logs",    action="store_true",
                    help="Stream live logs (combine with --lines for non-streaming)")
    mx.add_argument("--update",  action="store_true",
                    help="git pull + pip upgrade + restart")
    mx.add_argument("--update-token", action="store_true",
                    help="Update the Discord token in .env and restart")
    mx.add_argument("--repos",   action="store_true", help="List plugin repositories")
    mx.add_argument("--plugins",    action="store_true", help="List installed plugins")

    # ── modifiers ─────────────────────────────────────────────────────────────
    mod = p.add_argument_group("modifiers")
    mod.add_argument(
        "--lines", "-n", type=int, metavar="N", default=None,
        help="Number of log lines to show (used with --logs, makes it non-streaming)",
    )
    mod.add_argument("--debug", action="store_true", help="Show verbose debug information")
    mod.add_argument("--yes",   "-y", action="store_true", help="Skip confirmation prompts")

    return p


# ── entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.debug:
        print(f"\n  {dim('vmanage')} {VERSION}  {dim('—')}  {dim('debug mode')}")
        print(f"  {dim('INSTALL_DIR:')} {INSTALL_DIR}")
        print(f"  {dim('DATA_DIR:   ')} {DATA_DIR}")
        print()

    bot = get_bot()

    if args.debug:
        print(f"  {dim('Bot name:   ')}  {bot.name}")
        print(f"  {dim('Service:    ')}  {bot.service_name}")
        print(f"  {dim('Has venv:   ')}  {bot.has_venv()}")
        print(f"  {dim('Has token:  ')}  {bot.has_token()}")
        print()

    # Dispatch
    if args.start:
        do_start(bot, args.debug)
    elif args.stop:
        do_stop(bot, args.debug)
    elif args.restart:
        do_restart(bot, args.debug)
    elif args.status:
        do_status(bot, args.debug)
    elif args.logs:
        do_logs(bot, lines=args.lines, debug=args.debug)
    elif args.update:
        do_update(bot, debug=args.debug, yes=args.yes)
    elif args.update_token:
        do_update_token(bot, debug=args.debug, yes=args.yes)
    elif args.repos:
        do_repos(bot, args.debug)
    elif args.plugins:
        do_plugins(bot, args.debug)
    else:
        # No action flag → show status dashboard
        do_dashboard(bot, args.debug)


if __name__ == "__main__":
    main()
