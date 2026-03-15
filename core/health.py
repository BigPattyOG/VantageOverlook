"""Health-check HTTP server for vprod.

Starts a lightweight aiohttp web server inside the bot's asyncio event loop.
Responds to ``GET /`` and ``GET /health`` with a JSON status payload so that
external monitoring tools (uptime robots, load balancers, etc.) can verify
the bot process is alive and connected.

Configuration
-------------
Set ``health_port`` in ``config.json`` to the port you want to listen on.
The default is ``8080``.  Set it to ``0`` to disable the server entirely.

Set ``health_host`` in ``config.json`` to control the bind address.
The default is ``127.0.0.1`` (localhost only).  Set to ``0.0.0.0`` to
expose the endpoint to external network interfaces (e.g. for a remote
monitoring service or a reverse proxy on the same host).

Example response
----------------
.. code-block:: json

    {
        "status": "ok",
        "bot": "MyBot",
        "uptime_seconds": 3600,
        "guilds": 5,
        "users": 312,
        "latency_ms": 38,
        "extensions": 3
    }

If the bot has not yet emitted ``on_ready`` (i.e. it is still connecting),
``uptime_seconds`` will be ``null`` and ``status`` will be ``"starting"``.
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


# ── request handler ────────────────────────────────────────────────────────────

async def _handle(request: web.Request) -> web.Response:
    bot: VantageBot = request.app["bot"]
    now = datetime.now(timezone.utc)

    if bot.start_time is not None:
        uptime_seconds: int | None = int((now - bot.start_time).total_seconds())
        status = "ok"
    else:
        uptime_seconds = None
        status = "starting"

    payload = {
        "status": status,
        "bot": bot.config.get("name", "vprod"),
        "uptime_seconds": uptime_seconds,
        "guilds": len(bot.guilds),
        "users": sum(g.member_count or 0 for g in bot.guilds),
        "latency_ms": round(bot.latency * 1000) if bot.latency != float("inf") else None,
        "extensions": len(bot.extensions),
    }
    return web.Response(
        text=json.dumps(payload),
        content_type="application/json",
    )


# ── server wrapper ─────────────────────────────────────────────────────────────

class HealthServer:
    """Wraps an aiohttp ``AppRunner`` so it can be started and stopped cleanly."""

    def __init__(self, bot: VantageBot, port: int) -> None:
        self._bot = bot
        self._port = port
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        """Start the HTTP server.  Call once from ``setup_hook``."""
        app = web.Application()
        app["bot"] = self._bot
        app.router.add_get("/", _handle)
        app.router.add_get("/health", _handle)

        host = self._bot.config.get("health_host", "127.0.0.1")
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, self._port)
        await site.start()
        log.info(
            "Health endpoint listening on http://%s:%d/health", host, self._port
        )

    async def stop(self) -> None:
        """Stop the HTTP server.  Called automatically when the bot closes."""
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            log.info("Health endpoint stopped.")
