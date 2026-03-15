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
    vmanage --motd                   Print compact status block (used by MOTD script)
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

VERSION = "2.0.0"

# INSTALL_DIR is always the directory that contains this file.  When vmanage is
# called via the /usr/local/bin/vmanage symlink, Path(__file__).resolve()
# follows the symlink so _SCRIPT_DIR is always the real app directory
# (e.g. /opt/vprod or /opt/vdev).  In a dev checkout it is the repo root.
_SCRIPT_DIR = Path(__file__).resolve().parent
INSTALL_DIR = _SCRIPT_DIR

# DATA_DIR is resolved in order:
#   1. VPROD_DATA_DIR env var — set by the systemd unit (EnvironmentFile path)
#   2. /var/lib/<install_dir_name>  — conventional server layout for both prod
#      and dev server installs without an active service environment
#   3. INSTALL_DIR/data — local dev checkout fallback
_env_data_dir = os.environ.get("VPROD_DATA_DIR", "")
if _env_data_dir:
    DATA_DIR: Path = Path(_env_data_dir)
else:
    _candidate = Path("/var/lib") / _SCRIPT_DIR.name
    DATA_DIR = _candidate if _candidate.exists() else _SCRIPT_DIR / "data"

# BOT_USER fallback — used when systemctl cannot return the service User= field.
# On a server install the correct user is always read from the systemd unit at
# runtime (see _run_bot_cmd / BotInstance.bot_user), so this value only matters
# for local dev checkouts where sudo operations are not performed anyway.
BOT_USER = os.environ.get("VPROD_BOT_USER", "vprodbot")

# Discord bot token format: three base64url segments separated by dots.
# This regex is intentionally duplicated in scripts/install-vprod.sh and
# scripts/install-vdev.sh (validate_token_format) — keep all three in sync.
_TOKEN_RE = re.compile(
    r"^[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}$"
)

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
    "  ██╗   ██╗ █████╗ ███╗   ██╗████████╗ █████╗  ██████╗ ███████╗",
    "  ██║   ██║██╔══██╗████╗  ██║╚══██╔══╝██╔══██╗██╔════╝ ██╔════╝",
    "  ██║   ██║███████║██╔██╗ ██║   ██║   ███████║██║  ███╗█████╗  ",
    "  ╚██╗ ██╔╝██╔══██║██║╚██╗██║   ██║   ██╔══██║██║   ██║██╔══╝  ",
    "   ╚████╔╝ ██║  ██║██║ ╚████║   ██║   ██║  ██║╚██████╔╝███████╗",
    "    ╚═══╝  ╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝",
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
        self.service_name: str = self.config.get("service_name", "vprod")
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

    def bot_version(self) -> Optional[str]:
        """Read the bot framework version from VERSION in the install directory."""
        try:
            return (self.install_dir / "VERSION").read_text(encoding="utf-8").strip()
        except Exception:
            return None

    def active_since(self) -> Optional[str]:
        """Return the service start time as a readable string (e.g. '2026-03-15 08:00:05 UTC')."""
        if not shutil.which("systemctl"):
            return None
        r = self._systemctl(
            "show", "-p", "ActiveEnterTimestamp", "--value", self.service_name
        )
        ts = r.stdout.strip()
        if not ts or ts == "0":
            return None
        for fmt in ("%a %Y-%m-%d %H:%M:%S %Z", "%a %Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.datetime.strptime(ts, fmt).replace(
                    tzinfo=datetime.timezone.utc
                )
                return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            except ValueError:
                continue
        return ts  # fallback: return raw string if parsing fails

    def git_commit(self) -> Optional[str]:
        """Return the short hash + subject of the current HEAD commit."""
        if not shutil.which("git"):
            return None
        try:
            r = subprocess.run(
                ["git", "-C", str(self.install_dir), "log", "--oneline", "-1"],
                capture_output=True, text=True, timeout=5,
            )
            return r.stdout.strip() or None
        except Exception:
            return None

    def recent_errors(self, n: int = 3) -> List[tuple]:
        """Return the last *n* error/critical lines from the service journal.

        Each item is a ``(timestamp, message)`` tuple where both values are plain
        strings already trimmed to fit the MOTD display width.
        """
        if not shutil.which("journalctl"):
            return []
        try:
            r = subprocess.run(
                [
                    "journalctl", "-u", self.service_name,
                    "-p", "err",          # err and above (crit, alert, emerg)
                    "-n", str(n),
                    "--no-pager",
                    "-o", "short",        # "Mar 15 08:42:11 host unit[PID]: msg"
                ],
                capture_output=True, text=True, timeout=6,
            )
        except Exception:
            return []

        lines: List[tuple] = []
        for raw in r.stdout.strip().splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("--"):
                # journalctl separator / "No entries" line
                continue
            # Format: "Mar 15 08:42:11 hostname unit[PID]: message"
            # Split into at most 6 tokens: month day time host unit msg
            parts = raw.split(None, 5)
            if len(parts) >= 6:
                ts  = " ".join(parts[:3])   # "Mar 15 08:42:11"  (15 chars)
                msg = parts[5]
            elif len(parts) >= 4:
                ts  = " ".join(parts[:3])
                msg = " ".join(parts[3:])
            else:
                ts  = ""
                msg = raw
            # Trim long messages to stay within display width (W=68).
            # Layout per line: "  " (2) + ts (15) + "  " (2) + msg → max_msg = 68 - 19 = 49
            max_msg = 49
            if len(msg) > max_msg:
                msg = msg[:max_msg - 1] + "…"
            lines.append((ts, msg))
        return lines


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
    # Derive the bot user from the systemd unit so this works correctly for
    # both vprod (vprodbot) and vdev (vdevbot) without hard-coding the user.
    bot_user = BOT_USER
    if shutil.which("systemctl"):
        r = subprocess.run(
            ["systemctl", "show", "-p", "User", "--value", bot.service_name],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            bot_user = r.stdout.strip()
    quoted_parts = " ".join(shlex.quote(str(p)) for p in cmd_parts)
    subprocess.run(
        ["sudo", "-u", bot_user, "bash", "-c",
         f"cd {shlex.quote(str(bot.install_dir))} && {quoted_parts}"]
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
    # Derive the bot user from the systemd unit (same as _run_bot_cmd).
    bot_user = BOT_USER
    if shutil.which("systemctl"):
        r_u = subprocess.run(
            ["systemctl", "show", "-p", "User", "--value", bot.service_name],
            capture_output=True, text=True,
        )
        if r_u.returncode == 0 and r_u.stdout.strip():
            bot_user = r_u.stdout.strip()
    info("Pulling latest code from GitHub...")
    r = subprocess.run(
        ["sudo", "-u", bot_user, "git", "-C", str(bot.install_dir), "pull", "--ff-only"]
    )
    if r.returncode != 0:
        warn("git pull did not fast-forward — repository may be up-to-date or have local changes.")
    else:
        ok("Code updated.")
    print()
    if bot.has_venv():
        info("Upgrading Python dependencies...")
        subprocess.run(["sudo", "-u", bot_user, str(bot.venv_pip),
                        "install", "-q", "--upgrade", "pip"])
        subprocess.run(["sudo", "-u", bot_user, str(bot.venv_pip),
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

    # The env file is always DATA_DIR/.env regardless of prod/dev layout;
    # DATA_DIR is already resolved correctly at module load (from VPROD_DATA_DIR
    # env var, conventional /var/lib/<name> path, or local ./data fallback).
    env_file = DATA_DIR / ".env"
    # Use sudo when the current process cannot write to DATA_DIR directly
    # (server installs owned by the bot user / root).
    needs_sudo = not os.access(DATA_DIR, os.W_OK)

    # Derive the bot user that should own the file (for chown in sudo path).
    bot_user = BOT_USER
    if shutil.which("systemctl"):
        r_u = subprocess.run(
            ["systemctl", "show", "-p", "User", "--value", bot.service_name],
            capture_output=True, text=True,
        )
        if r_u.returncode == 0 and r_u.stdout.strip():
            bot_user = r_u.stdout.strip()

    info(f"Token file: {bold(str(env_file))}")
    print()

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
        safe_user = shlex.quote(bot_user)
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


# ── MOTD status block ─────────────────────────────────────────────────────────

def _count_apt_updates() -> Optional[int]:
    """Return the number of upgradable packages, or None if apt is unavailable.

    Uses ``/var/lib/update-notifier/updates-available`` (written by
    ``apt-get update`` / the ``update-notifier-common`` package) when present
    so that the MOTD script does not trigger a slow ``apt list`` call on every
    SSH login.  Falls back to a quick ``apt-get -s upgrade`` count if the cache
    file is missing.  Returns None if apt is not installed on this system.
    """
    if not shutil.which("apt-get"):
        return None

    # Fast path: pre-computed cache file written by apt hooks.
    cache_file = Path("/var/lib/update-notifier/updates-available")
    if cache_file.exists():
        try:
            text = cache_file.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                parts = line.split()
                if parts and parts[0].isdigit():
                    return int(parts[0])
        except Exception:
            pass

    # Slow fallback: simulate an upgrade and count "Inst" lines.
    # Use -q (not -qq) so that "Inst ..." lines are not suppressed.
    try:
        r = subprocess.run(
            ["apt-get", "--simulate", "-q", "upgrade"],
            capture_output=True, text=True, timeout=30,
            env={"DEBIAN_FRONTEND": "noninteractive", "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
        if r.returncode != 0:
            return None
        count = sum(1 for line in r.stdout.splitlines() if line.startswith("Inst "))
        return count
    except Exception:
        return None


def do_motd(bot: BotInstance) -> None:
    """Print a rich status panel for display at SSH login (/etc/update-motd.d/)."""
    W    = 70
    sep  = teal("━" * W)
    hsep = dim("─" * W)
    LW   = 16   # label column width

    # ── Banner ────────────────────────────────────────────────────────────────
    print()
    print(sep)
    for line in _BANNER_LINES:
        print(teal(bold(line)))

    bot_ver  = bot.bot_version()
    ver_str  = f"  {dim('v' + bot_ver)}" if bot_ver else ""
    print(
        f"  {dim('Bot:')} {bold(bot.name)}{ver_str}"
        f"   {dim('vmanage')} {dim(VERSION)}"
    )
    print(sep)

    # ── Service ───────────────────────────────────────────────────────────────
    print()
    print(f"  {bold('Service')}")
    print(f"  {hsep}")

    if shutil.which("systemctl"):
        running = bot.is_running()
        state   = bot.active_state()
        uptime  = bot.uptime() if running else None
        since   = bot.active_since() if running else None

        if running:
            status_str = f"{teal('●')} {teal(bold('running'))}"
            if uptime:
                status_str += f"  {dim('up ' + uptime)}"
        elif state in ("activating", "deactivating", "reloading"):
            status_str = f"{yellow('●')} {yellow(bold(state))}"
        else:
            status_str = f"{red('●')} {red(bold(state or 'stopped'))}"

        print(f"  {'Status':<{LW}} {status_str}")
        if since:
            print(f"  {'Since':<{LW}} {dim(since)}")
    else:
        print(f"  {'Status':<{LW}} {dim('systemd unavailable')}")

    commit = bot.git_commit()
    if commit:
        max_commit = W - LW - 4
        display_commit = commit if len(commit) <= max_commit else commit[:max_commit - 1] + "…"
        print(f"  {'Commit':<{LW}} {dim(display_commit)}")

    print(f"  {'Unit':<{LW}} {dim(bot.service_name + '.service')}")
    print()

    # ── Bot configuration ─────────────────────────────────────────────────────
    print(f"  {bold('Bot')}")
    print(f"  {hsep}")

    description = bot.config.get("description", "")
    if description:
        print(f"  {'Description':<{LW}} {dim(description)}")

    activity = bot.config.get("activity", "")
    if activity:
        print(f"  {'Activity':<{LW}} {dim(activity)}")

    owners      = bot.config.get("owner_ids", [])
    maintenance = bot.config.get("maintenance", False)
    health_port = bot.config.get("health_port")

    print(f"  {'Prefix':<{LW}} {bold(bot.prefix)}")
    print(f"  {'Owners':<{LW}} {dim(str(len(owners)) + ' configured')}")

    if maintenance:
        maint_msg = bot.config.get("maintenance_message", "")
        maint_str = yellow(bold("ON"))
        if maint_msg:
            maint_str += f"  {dim(maint_msg)}"
        print(f"  {'Maintenance':<{LW}} {maint_str}")

    if bot.has_token():
        print(f"  {'Token':<{LW}} {teal('set')}")
    else:
        print(f"  {'Token':<{LW}} {red('NOT SET')}  {dim('→ vmanage --update-token')}")

    py_ver = bot.python_version()
    if py_ver:
        print(f"  {'Python':<{LW}} {teal(py_ver)}  {dim('(venv)')}")
    else:
        print(f"  {'Python':<{LW}} {red('venv not found')}")

    if health_port:
        print(f"  {'Health':<{LW}} {dim('http://localhost:' + str(health_port) + '/health')}")

    print()

    # ── Paths ─────────────────────────────────────────────────────────────────
    print(f"  {bold('Paths')}")
    print(f"  {hsep}")
    print(f"  {'Code':<{LW}} {dim(str(bot.install_dir))}")
    print(f"  {'Data / token':<{LW}} {dim(str(DATA_DIR))}")
    print()

    # ── System updates ────────────────────────────────────────────────────────
    print(f"  {bold('System')}")
    print(f"  {hsep}")

    # Reboot required?
    reboot_required = Path("/var/run/reboot-required").exists()
    if reboot_required:
        print(f"  {'Reboot':<{LW}} {yellow(bold('REQUIRED'))}  {dim('→ sudo reboot')}")
    else:
        print(f"  {'Reboot':<{LW}} {teal('not required')}")

    # Available apt package updates
    update_count = _count_apt_updates()
    if update_count is None:
        print(f"  {'Updates':<{LW}} {dim('apt unavailable')}")
    elif update_count == 0:
        print(f"  {'Updates':<{LW}} {teal('up to date')}")
    else:
        noun = "update" if update_count == 1 else "updates"
        print(
            f"  {'Updates':<{LW}} {yellow(bold(str(update_count) + ' ' + noun + ' available'))}"
            f"  {dim('→ sudo apt upgrade')}"
        )

    print()

    # ── Recent errors ─────────────────────────────────────────────────────────
    print(f"  {bold('Recent Errors')}")
    print(f"  {hsep}")
    errors = bot.recent_errors(n=3)
    if errors:
        for ts, msg in errors:
            print(f"  {red(ts)}  {msg}")
    else:
        print(f"  {teal('no errors in journal')}")
    print()

    # ── Commands quick-reference ──────────────────────────────────────────────
    print(f"  {bold('Commands')}")
    print(f"  {hsep}")
    cmd_pairs = [
        ("Dashboard",    "vmanage"),
        ("Restart",      "vmanage --restart"),
        ("Logs",         "vmanage --logs"),
        ("Update",       "vmanage --update"),
        ("Rotate token", "vmanage --update-token"),
    ]
    lw = max(len(lb) for lb, _ in cmd_pairs)
    for label, cmd in cmd_pairs:
        print(f"  {dim(label + ':'):<{lw + 8}} {bold(cmd)}")

    print(sep)
    print()


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
  vmanage --motd                Print the SSH login status block (preview)
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
    mx.add_argument("--motd",    action="store_true",
                    help="Print compact SSH-login status block (used by /etc/update-motd.d/)")
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

    # --motd is handled before get_bot() so that SSH login never fails if the
    # install directory is missing (e.g. during initial setup).
    if args.motd:
        try:
            bot = get_bot()
            do_motd(bot)
        except SystemExit:
            pass  # not installed — show nothing at login
        return

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
