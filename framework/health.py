"""Health-check HTTP server for vprod.

Starts a lightweight aiohttp web server inside the bot's asyncio event loop.
Designed for third-party status checkers (UptimeRobot, BetterStack, Freshping,
etc.) as well as internal monitoring.

Endpoints
---------
``GET /ping``
    Plain-text ``OK``.  Use this for simple TCP/HTTP monitors that only check
    for a 200 response and don't parse the body.

``GET /health``  (also ``GET /``, ``GET /status``)
    JSON payload with full status details.  Returns HTTP 200 when the bot is
    healthy, HTTP 503 when starting or in maintenance mode.

Configuration (in config.json)
-------------------------------
``health_port``  — Port to listen on.  Default 8080.  Set to 0 to disable.
``health_host``  — Bind address.  Default ``0.0.0.0`` (all interfaces).
                   Use ``127.0.0.1`` to restrict to localhost.

Example JSON response
---------------------
.. code-block:: json

    {
        "status": "ok",
        "version": "1.0.0",
        "bot": "vprod",
        "uptime_seconds": 3600,
        "guilds": 5,
        "users": 312,
        "latency_ms": 38,
        "extensions_loaded": 4,
        "ext_plugins_loaded": 2,
        "ext_plugins_failed": 0,
        "maintenance": false,
        "timestamp": "2025-01-01T00:00:00+00:00"
    }
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from .bot import VantageBot

log = logging.getLogger("vprod.health")


# ── shared helpers ─────────────────────────────────────────────────────────────

def _build_payload(bot: "VantageBot") -> tuple[dict, int]:
    """Build the health JSON payload and determine HTTP status code."""
    from .embeds import get_version

    now = datetime.now(timezone.utc)
    maintenance: bool = bot.config.get("maintenance", False)

    if bot.start_time is not None:
        uptime_seconds: int | None = int((now - bot.start_time).total_seconds())
        status = "maintenance" if maintenance else "ok"
    else:
        uptime_seconds = None
        status = "starting"

    failed_count = len(getattr(bot, "failed_ext_plugins", []))
    ext_loaded = len([
        ext for ext in bot.extensions
        if ext.startswith("_vp_ext.")
    ])

    payload = {
        "status": status,
        "version": get_version(),
        "bot": bot.config.get("name", "vprod"),
        "uptime_seconds": uptime_seconds,
        "guilds": len(bot.guilds),
        "users": sum(g.member_count or 0 for g in bot.guilds),
        "latency_ms": round(bot.latency * 1000) if bot.latency != float("inf") else None,
        "extensions_loaded": len(bot.extensions),
        "ext_plugins_loaded": ext_loaded,
        "ext_plugins_failed": failed_count,
        "maintenance": maintenance,
        "timestamp": now.isoformat(),
    }

    # HTTP 503 while starting or in maintenance (lets monitors alert properly).
    http_status = 200 if status == "ok" else 503
    return payload, http_status


# ── request handlers ───────────────────────────────────────────────────────────

async def _handle_health(request: web.Request) -> web.Response:
    """Return a full JSON health payload."""
    bot: VantageBot = request.app["bot"]
    payload, http_status = _build_payload(bot)
    return web.Response(
        status=http_status,
        text=json.dumps(payload),
        content_type="application/json",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


async def _handle_ping(request: web.Request) -> web.Response:
    """Return a plain OK for simple TCP/HTTP uptime monitors."""
    return web.Response(
        text="OK",
        content_type="text/plain",
        headers={"Cache-Control": "no-cache"},
    )


# ── server wrapper ─────────────────────────────────────────────────────────────

class HealthServer:
    """Wraps an aiohttp AppRunner so it can be started and stopped cleanly."""

    def __init__(self, bot: "VantageBot", port: int) -> None:
        self._bot = bot
        self._port = port
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        """Start the HTTP server.  Call once from setup_hook."""
        app = web.Application()
        app["bot"] = self._bot

        # Full JSON health report
        app.router.add_get("/",       _handle_health)
        app.router.add_get("/health", _handle_health)
        app.router.add_get("/status", _handle_health)

        # Plain-text ping for simple monitors
        app.router.add_get("/ping", _handle_ping)

        host = self._bot.config.get("health_host", "0.0.0.0")
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, self._port)
        await site.start()
        log.info("Health endpoint: http://%s:%d/health  •  ping: http://%s:%d/ping",
                 host, self._port, host, self._port)

    async def stop(self) -> None:
        """Stop the HTTP server.  Called automatically when the bot closes."""
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            log.info("Health endpoint stopped.")

