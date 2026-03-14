#!/usr/bin/env python3
"""vmanage — Vantage Bot CLI management tool.

Manage any installed Vantage bot instance from the command line.
Uses only the Python standard library so it works without activating a venv.

Usage
-----
::

    vmanage                          List all installed bot instances
    vmanage BOTNAME                  Show status dashboard for BOTNAME
    vmanage BOTNAME --start          Start the bot service
    vmanage BOTNAME --stop           Stop the bot service
    vmanage BOTNAME --restart        Restart the bot service
    vmanage BOTNAME --status         Show full systemctl service status
    vmanage BOTNAME --logs           Stream live logs  (Ctrl+C to stop)
    vmanage BOTNAME --logs --lines 50  Show last 50 log lines (non-streaming)
    vmanage BOTNAME --update         git pull + pip upgrade + restart
    vmanage BOTNAME --setup          Re-run the interactive setup wizard
    vmanage BOTNAME --repos          List cog repositories
    vmanage BOTNAME --cogs           List installed cogs
    vmanage BOTNAME --debug          Show verbose debug output
    vmanage BOTNAME --yes            Skip confirmation prompts
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

INSTALL_BASE = Path("/opt")
BOT_USER = "vantage"
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
def cyan(t: str) -> str:    return _c(t, "36")
def blue(t: str) -> str:    return _c(t, "34")
def magenta(t: str) -> str: return _c(t, "35")


def ok(msg: str) -> None:   print(f"  {green('[ok]')}  {msg}")
def warn(msg: str) -> None: print(f"  {yellow('[!]')}  {msg}")
def err(msg: str) -> None:  print(f"  {red('[x]')}  {msg}", file=sys.stderr)
def info(msg: str) -> None: print(f"  {cyan('>')}  {msg}")


def die(msg: str) -> None:
    err(msg)
    sys.exit(1)


# ── ASCII banner ───────────────────────────────────────────────────────────────

_BANNER_LINES = [
    "  ██╗   ██╗ █████╗ ███╗   ██╗████████╗ █████╗  ██████╗ ███████╗",
    "  ██║   ██║██╔══██╗████╗  ██║╚══██╔══╝██╔══██╗██╔════╝ ██╔════╝",
    "  ██║   ██║███████║██╔██╗ ██║   ██║   ███████║██║  ███╗█████╗  ",
    "  ╚██╗ ██╔╝██╔══██║██║╚██╗██║   ██║   ██╔══██║██║   ██║██╔══╝  ",
    "   ╚████╔╝ ██║  ██║██║ ╚████║   ██║   ██║  ██║╚██████╔╝███████╗",
    "    ╚═══╝  ╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝",
]


def print_banner(subtitle: str = "Bot Manager") -> None:
    print(cyan(bold("\n".join(_BANNER_LINES))))
    print(f"\n  {bold('vmanage')} {dim('—')} {subtitle}\n")


# ── bot discovery ──────────────────────────────────────────────────────────────

class BotInstance:
    """Represents one installed Vantage bot under ``/opt/<Name>/``."""

    def __init__(self, install_dir: Path) -> None:
        self.install_dir = install_dir
        self.config: Dict[str, Any] = self._load_config()
        self.name: str = self.config.get("name", install_dir.name)
        self.service_name: str = self.config.get(
            "service_name", f"vantage-{install_dir.name.lower()}"
        )
        self.prefix: str = self.config.get("prefix", "!")
        self.venv_python: Path = install_dir / "venv" / "bin" / "python"
        self.venv_pip: Path = install_dir / "venv" / "bin" / "pip"

    # ── helpers ───────────────────────────────────────────────────────────────

    def _load_config(self) -> Dict[str, Any]:
        # Production split layout: data lives in /var/lib/<Name>/
        varlib_cfg = Path("/var/lib") / self.install_dir.name / "config.json"
        # Legacy / dev layout: data/ next to the install dir
        local_cfg = self.install_dir / "data" / "config.json"

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
        return bool(self.config.get("token", "").strip())

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


def find_all_bots() -> List[BotInstance]:
    """Return every Vantage installation found under ``INSTALL_BASE``.

    A directory is considered a Vantage installation only if it contains a
    ``launcher.py`` file, which avoids picking up unrelated software under
    ``/opt/``.
    """
    bots: List[BotInstance] = []
    if not INSTALL_BASE.exists():
        return bots
    for d in sorted(INSTALL_BASE.iterdir()):
        if not d.is_dir():
            continue
        # Only consider directories that contain launcher.py (Vantage marker)
        if not (d / "launcher.py").exists():
            continue
        varlib_cfg = Path("/var/lib") / d.name / "config.json"
        local_cfg = d / "data" / "config.json"
        if varlib_cfg.exists() or local_cfg.exists():
            bots.append(BotInstance(d))
    return bots


def find_bot(name: str) -> BotInstance:
    """Locate a bot by name (case-insensitive, supports prefix matching)."""
    bots = find_all_bots()
    nl = name.lower()

    # Exact match on config name or directory name
    for b in bots:
        if b.name.lower() == nl or b.install_dir.name.lower() == nl:
            return b

    # Prefix match
    for b in bots:
        if b.name.lower().startswith(nl) or b.install_dir.name.lower().startswith(nl):
            return b

    avail = ", ".join(b.name for b in bots) or "(none)"
    die(
        f"No bot matching '{name}' found under {INSTALL_BASE}.\n"
        f"  Available: {avail}\n"
        f"  Run {bold('vmanage')} (no arguments) to list all bots."
    )


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
         f"cd {shlex.quote(str(bot.install_dir))} && {quoted_parts}"]
    )


# ── actions ────────────────────────────────────────────────────────────────────

def do_start(bot: BotInstance, debug: bool = False) -> None:
    _need_systemctl()
    info(f"Starting {bold(bot.service_name)}…")
    r = subprocess.run(["sudo", "systemctl", "start", bot.service_name])
    if r.returncode != 0:
        die(f"Failed to start service.  Try manually:\n  sudo systemctl start {bot.service_name}")
    time.sleep(1.5)
    if bot.is_running():
        ok(f"{bold(bot.name)} is {green(bold('running'))}.")
    else:
        warn(f"Service started but may not be active yet.\n"
             f"  Check logs: vmanage {bot.install_dir.name} --logs")


def do_stop(bot: BotInstance, debug: bool = False) -> None:
    _need_systemctl()
    info(f"Stopping {bold(bot.service_name)}…")
    r = subprocess.run(["sudo", "systemctl", "stop", bot.service_name])
    if r.returncode != 0:
        die(f"Failed to stop service.  Try:\n  sudo systemctl stop {bot.service_name}")
    ok(f"{bold(bot.name)} stopped.")


def do_restart(bot: BotInstance, debug: bool = False) -> None:
    _need_systemctl()
    info(f"Restarting {bold(bot.service_name)}…")
    r = subprocess.run(["sudo", "systemctl", "restart", bot.service_name])
    if r.returncode != 0:
        die(f"Failed to restart service.")
    time.sleep(1.5)
    if bot.is_running():
        ok(f"{bold(bot.name)} restarted — {green(bold('running'))}.")
    else:
        warn(f"Service restarted but may not be active yet.\n"
             f"  Check logs: vmanage {bot.install_dir.name} --logs")


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
        info(f"Streaming live logs for {bold(bot.name)}  (Ctrl+C to stop)…")
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
                f"\n  Update {bold(bot.name)}? This will git pull + pip upgrade + restart. [y/N] "
            )
        except EOFError:
            ans = ""
        if ans.strip().lower() not in ("y", "yes"):
            info("Update cancelled.")
            return
    print()
    info("Pulling latest code from GitHub…")
    r = subprocess.run(
        ["sudo", "-u", BOT_USER, "git", "-C", str(bot.install_dir), "pull", "--ff-only"]
    )
    if r.returncode != 0:
        warn("git pull failed — repository may be up-to-date or have local changes.")
    print()
    if bot.has_venv():
        info("Upgrading Python dependencies…")
        subprocess.run(["sudo", "-u", BOT_USER, str(bot.venv_pip),
                        "install", "-q", "--upgrade", "pip"])
        subprocess.run(["sudo", "-u", BOT_USER, str(bot.venv_pip),
                        "install", "-q", "-r", str(bot.install_dir / "requirements.txt")])
        ok("Dependencies upgraded.")
    else:
        warn("Virtual environment not found — skipping pip upgrade.")
    print()
    do_restart(bot, debug)


def do_setup(bot: BotInstance, debug: bool = False) -> None:
    if not bot.has_venv():
        die(f"Virtual environment not found at {bot.install_dir}/venv\n"
            f"  Set up the venv manually — see README.md for instructions.")
    info(f"Launching setup wizard for {bold(bot.name)}...")
    print()
    _run_bot_cmd(bot, str(bot.venv_python), "launcher.py setup")


def do_repos(bot: BotInstance, debug: bool = False) -> None:
    if not bot.has_venv():
        die("Virtual environment not found.")
    info(f"Cog repositories — {bold(bot.name)}:")
    print()
    _run_bot_cmd(bot, str(bot.venv_python), "launcher.py repos list")


def do_cogs(bot: BotInstance, debug: bool = False) -> None:
    if not bot.has_venv():
        die("Virtual environment not found.")
    info(f"Installed cogs — {bold(bot.name)}:")
    print()
    _run_bot_cmd(bot, str(bot.venv_python), "launcher.py cogs list")


# ── status dashboard ───────────────────────────────────────────────────────────

def do_dashboard(bot: BotInstance, debug: bool = False) -> None:
    """Print a rich single-page status dashboard for the given bot."""
    print_banner(f"{bold(bot.name)}  {dim('—')}  {str(bot.install_dir)}")

    SEP = dim("─" * 58)
    print(f"  {SEP}")

    # Service status
    running = bot.is_running()
    state   = bot.active_state()
    if running:
        status_str = f"{green('●')} {green(bold('running'))}"
    elif state in ("activating", "deactivating", "reloading"):
        status_str = f"{yellow('●')} {yellow(bold(state))}"
    else:
        status_str = f"{red('●')} {red(bold(state or 'stopped'))}"

    print(f"  Service status : {status_str}")

    if running:
        uptime = bot.uptime()
        if uptime:
            print(f"  Uptime         : {green(uptime)}")

    print(f"  Service unit   : {dim(bot.service_name + '.service')}")
    print(f"  Install dir    : {dim(str(bot.install_dir))}")

    # Config
    if bot.config:
        owners = bot.config.get("owner_ids", [])
        print(
            f"  Config         : {green('found')}  "
            f"{dim(f'prefix: {bold(bot.prefix)}, owners: {len(owners)}')}"
        )
    else:
        print(
            f"  Config         : {red('missing')}  "
            f"{dim('run: vmanage ' + bot.install_dir.name + ' --setup')}"
        )

    # Python / venv
    py_ver = bot.python_version()
    if py_ver:
        print(f"  Python         : {green(py_ver)}  {dim('(venv active)')}")
    else:
        print(f"  Python         : {red('venv not found')}  {dim('— set up venv manually')}")

    # Token
    if not bot.has_token():
        print(f"  Token          : {red('NOT SET')}  {dim('— run --setup')}")

    print(f"  {SEP}\n")

    # Quick reference
    n = bot.install_dir.name
    print(f"  {bold('Commands:')}\n")
    pairs = [
        ("Start",          f"vmanage {n} --start"),
        ("Stop",           f"vmanage {n} --stop"),
        ("Restart",        f"vmanage {n} --restart"),
        ("Full status",    f"vmanage {n} --status"),
        ("Stream logs",    f"vmanage {n} --logs"),
        ("Last 50 lines",  f"vmanage {n} --logs --lines 50"),
        ("Update & restart", f"vmanage {n} --update"),
        ("Setup wizard",   f"vmanage {n} --setup"),
        ("List cogs",      f"vmanage {n} --cogs"),
        ("List repos",     f"vmanage {n} --repos"),
    ]
    label_w = max(len(lb) for lb, _ in pairs)
    for label, cmd in pairs:
        print(f"  {dim(label + ':'):<{label_w + 10}} {bold(cmd)}")
    print()


# ── list all bots ──────────────────────────────────────────────────────────────

def do_list() -> None:
    """List every installed Vantage bot instance."""
    print_banner("Installed Bots")

    bots = find_all_bots()
    if not bots:
        info("No bot instances found. Deploy manually — see README.md for setup steps.")
        print()
        return

    print(f"  {bold(f'{len(bots)} bot instance(s)')}  {dim(str(INSTALL_BASE))}\n")
    for bot in bots:
        running = bot.is_running()
        icon  = green("●") if running else red("●")
        state = green(bold("running")) if running else red(bold("stopped"))
        print(f"  {icon}  {bold(bot.name):<22} {state}")
        print(f"       {dim('dir:')} {bot.install_dir}  {dim('svc:')} {bot.service_name}.service")
        print(f"       {dim('pfx:')} {bot.prefix}"
              + (f"  {dim('uptime:')} {bot.uptime()}" if running and bot.uptime() else ""))
        print()

    print(f"  {dim('Manage a bot:  ')} {bold('vmanage BOTNAME [--start|--stop|--restart|--logs|...]')}")
    print()


# ── argument parser ────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vmanage",
        description="Vantage Bot CLI — manage any installed bot instance.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  vmanage                       List all installed bots
  vmanage MyBot                 Show status dashboard
  vmanage MyBot --start         Start the bot service
  vmanage MyBot --restart       Restart the bot service
  vmanage MyBot --logs          Stream live logs  (Ctrl+C to stop)
  vmanage MyBot --logs --lines 100   Show last 100 lines, non-streaming
  vmanage MyBot --update        Pull latest code and restart
  vmanage MyBot --update --yes  Same, skip confirmation
  vmanage MyBot --setup         Re-run the interactive setup wizard
  vmanage MyBot --cogs          List installed cogs
  vmanage MyBot --repos         List cog repositories
  vmanage MyBot --debug         Show verbose debug information
""",
    )

    p.add_argument(
        "botname", nargs="?", metavar="BOTNAME",
        help="Bot instance name (e.g. MyBot).  Omit to list all installed bots.",
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
    mx.add_argument("--setup",   action="store_true",
                    help="Re-run the interactive setup wizard")
    mx.add_argument("--repos",   action="store_true", help="List cog repositories")
    mx.add_argument("--cogs",    action="store_true", help="List installed cogs")

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
        print(f"  {dim('INSTALL_BASE:')} {INSTALL_BASE}")
        if args.botname:
            print(f"  {dim('Looking for bot:')} {args.botname}")
        print()

    # No botname → show all bots
    if not args.botname:
        do_list()
        return

    bot = find_bot(args.botname)

    if args.debug:
        print(f"  {dim('Resolved bot:')}  {bot.name}")
        print(f"  {dim('Install dir:')}  {bot.install_dir}")
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
    elif args.setup:
        do_setup(bot, args.debug)
    elif args.repos:
        do_repos(bot, args.debug)
    elif args.cogs:
        do_cogs(bot, args.debug)
    else:
        # No action flag → show status dashboard
        do_dashboard(bot, args.debug)


if __name__ == "__main__":
    main()
