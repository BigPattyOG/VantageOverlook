"""Logging configuration for vprod.

Features
--------
* Console handler with ANSI colours:

  - DEBUG    → grey
  - INFO     → cyan
  - WARNING  → yellow
  - ERROR    → red
  - CRITICAL → bold bright-red

* Rotating file handler — writes plain text to ``{log_dir}/vprod.log``.
  Each file is at most 10 MB; 7 backups are kept (≈ 70 MB total).
* Noisy library loggers (``discord.http``, ``discord.gateway``, ``asyncio``,
  ``aiohttp``) are silenced to WARNING when not in debug mode.
* Falls back gracefully: if the log directory cannot be created, console
  logging still works normally.

Usage
-----
Call once at process startup before anything else logs::

    from framework.log_setup import setup_logging
    from framework.config import DATA_DIR

    log_file = setup_logging(debug=False, log_dir=DATA_DIR / "logs")
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional

# ── ANSI colour codes ─────────────────────────────────────────────────────────

_RESET  = "\x1b[0m"
_GREY   = "\x1b[38;5;240m"
_CYAN   = "\x1b[36m"
_YELLOW = "\x1b[33m"
_RED    = "\x1b[31m"
_BRED   = "\x1b[1;31m"   # bold bright red

_LEVEL_COLOUR = {
    logging.DEBUG:    _GREY,
    logging.INFO:     _CYAN,
    logging.WARNING:  _YELLOW,
    logging.ERROR:    _RED,
    logging.CRITICAL: _BRED,
}

# ── Formatters ────────────────────────────────────────────────────────────────

_DATE_FMT  = "%Y-%m-%d %H:%M:%S"
_PLAIN_FMT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"


class _ColorFormatter(logging.Formatter):
    """Console formatter that colours each record by its level."""

    def format(self, record: logging.LogRecord) -> str:
        colour = _LEVEL_COLOUR.get(record.levelno, _RESET)
        fmt = (
            f"%(asctime)s {colour}[%(levelname)-8s]{_RESET}"
            " %(name)s: %(message)s"
        )
        return logging.Formatter(fmt, datefmt=_DATE_FMT).format(record)


_plain_formatter = logging.Formatter(_PLAIN_FMT, datefmt=_DATE_FMT)

# ── Noisy library loggers to quiet in non-debug mode ─────────────────────────

_QUIET_LOGGERS = (
    "discord",
    "discord.http",
    "discord.gateway",
    "discord.client",
    "discord.state",
    "discord.webhook",
    "asyncio",
    "aiohttp",
    "aiohttp.access",
)


# ── Public API ────────────────────────────────────────────────────────────────

def setup_logging(
    debug: bool = False,
    log_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Configure the root logger for vprod.

    Parameters
    ----------
    debug:
        When ``True`` the root level is ``DEBUG`` and all library loggers are
        left at their default levels.  When ``False`` (default) the root level
        is ``INFO`` and noisy library loggers are quieted to ``WARNING``.
    log_dir:
        Directory to write rotating log files into.  Created automatically if
        it does not exist.  Pass ``None`` (or omit) to disable file logging.

    Returns
    -------
    Path | None
        Absolute path of the active log file, or ``None`` if file logging
        could not be configured.
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    # Clear handlers set by any previous basicConfig call (e.g. in tests).
    root.handlers.clear()

    # ── Console handler ───────────────────────────────────────────────────────
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG)
    # Use colours only when attached to a real terminal (not piped / journald).
    use_colour = sys.stdout.isatty() or bool(os.environ.get("FORCE_COLOR"))
    console.setFormatter(_ColorFormatter() if use_colour else _plain_formatter)
    root.addHandler(console)

    # ── Rotating file handler ─────────────────────────────────────────────────
    log_file: Optional[Path] = None
    if log_dir is not None:
        try:
            log_dir = Path(log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "vprod.log"
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,   # 10 MB per file
                backupCount=7,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)  # capture everything to disk
            file_handler.setFormatter(_plain_formatter)
            root.addHandler(file_handler)
        except OSError as exc:
            logging.getLogger("vprod").warning(
                "File logging disabled — could not create log directory %s: %s",
                log_dir,
                exc,
            )

    # ── Silence noisy library loggers in non-debug mode ───────────────────────
    if not debug:
        for name in _QUIET_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)

    return log_file
