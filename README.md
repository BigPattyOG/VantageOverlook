# VantageOverlook

A modular Discord bot framework built on [discord.py](https://discordpy.readthedocs.io/), designed for self-hosting on Ubuntu servers. Install once, manage everything from the terminal with `vmanage` or from Discord with `!vmanage`.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Quick Install](#quick-install)
3. [vmanage CLI](#vmanage-cli)
4. [launcher.py CLI](#launcherpy-cli)
5. [In-Discord Commands](#in-discord-commands)
6. [Configuration](#configuration)
7. [Cog System](#cog-system)
8. [Per-Guild Data](#per-guild-data)
9. [Project Structure](#project-structure)
10. [Service Management](#service-management)
11. [Writing Cogs](#writing-cogs)
12. [Multi-Bot Setup](#multi-bot-setup)

---

## Architecture Overview

```
install.sh          One-shot Ubuntu installer (Python 3.13, venv, systemd service,
                    vmanage CLI, Discord API owner detection)
vmanage.py          Standalone system-wide CLI — zero venv dependency
launcher.py         Bot-scoped CLI (start, setup, repos, cogs, system)
core/
  bot.py            VantageBot — subclasses discord.ext.commands.Bot
  config.py         data/config.json reader/writer
  cog_manager.py    Repo registry + cog install tracker (data/cog_data.json)
  guild_data.py     Per-guild JSON storage (data/guilds/{id}.json)
  help_command.py   Paginated help with buttons and live search modal
cogs/
  admin.py          Built-in always-loaded admin cog
data/               Runtime data (gitignored)
  config.json       Token, prefix, owner IDs, bot name, service name
  cog_data.json     Repo/cog registry
  repos/            Cloned GitHub repos (on sys.path at startup)
  guilds/           Per-guild JSON files
vantage.service     systemd unit template (patched by install.sh)
```

**Boot sequence:**
1. `systemd` starts `launcher.py start` as the `vantage` user
2. `load_config()` reads `data/config.json`
3. `VantageBot.__init__` sets up intents, owner IDs, prefix, and the custom help command
4. `setup_hook()` — adds `data/repos/` to `sys.path`, loads `cogs.admin`, then autoloads all cogs listed in `cog_data.json → autoload`
5. `on_ready()` — sets `start_time`, updates bot presence

---

## Quick Install

```bash
# One-liner (Ubuntu 22.04+)
curl -sSL https://raw.githubusercontent.com/BigPattyOG/VantageOverlook/main/install.sh | sudo bash

# Or manually
git clone https://github.com/BigPattyOG/VantageOverlook.git
cd VantageOverlook
sudo ./install.sh
```

The installer:
1. Installs Python 3.13 via deadsnakes PPA + git + build tools
2. Creates a `vantage` system user at `/opt/vantage`
3. Clones the repo to `/opt/vantage/<BotName>/`
4. Creates a Python venv and installs all dependencies
5. Calls `GET /oauth2/applications/@me` via the Discord API to auto-detect owner IDs
6. Writes `data/config.json` (with Override / Update / Keep if it already exists)
7. Installs a systemd service as `vantage-<botname>.service`
8. Writes a sudoers entry so the bot user can restart its own service
9. Starts the service immediately
10. Installs `vmanage` to `/usr/local/bin/vmanage`

---

## vmanage CLI

`vmanage.py` is installed system-wide at `/usr/local/bin/vmanage`. It uses **only the Python standard library** — no venv needed.

```bash
vmanage                         # list all installed bot instances
vmanage MyBot                   # status dashboard
vmanage MyBot --start           # start service
vmanage MyBot --stop            # stop service
vmanage MyBot --restart         # restart service
vmanage MyBot --status          # full systemctl status
vmanage MyBot --logs            # stream live logs  (Ctrl+C to stop)
vmanage MyBot --logs --lines 50 # last 50 lines (non-streaming)
vmanage MyBot --update          # git pull + pip upgrade + restart
vmanage MyBot --update --yes    # same, skip confirmation
vmanage MyBot --setup           # re-run interactive setup wizard
vmanage MyBot --cogs            # list installed cogs
vmanage MyBot --repos           # list cog repositories
vmanage MyBot --debug           # show debug resolution info
```

Bot discovery: scans `/opt/vantage/` for subdirectories that contain `data/config.json`. Name matching is case-insensitive and supports prefix matching (`vmanage my` matches `MyBot` if unambiguous).

---

## launcher.py CLI

Run as the bot user (`sudo -u vantage`) or from within the install directory:

```bash
# Bot lifecycle
python launcher.py start                    # start the bot (used by systemd)
python launcher.py setup                    # interactive config wizard

# Repository management
python launcher.py repos list
python launcher.py repos add <URL>          # clone a GitHub repo
python launcher.py repos add <PATH>         # link a local directory
python launcher.py repos remove <NAME>
python launcher.py repos update [NAME]      # git pull

# Cog management
python launcher.py cogs list
python launcher.py cogs install <REPO> <COG>
python launcher.py cogs uninstall <COG_PATH>
python launcher.py cogs autoload <COG_PATH>  # toggle autoload on/off

# System setup (require root)
sudo python launcher.py system status
sudo python launcher.py system create-user [--username NAME] [--home PATH]
sudo python launcher.py system install-service [--user USER] [--install-dir PATH]
```

---

## In-Discord Commands

All commands use the configured prefix (default `!`).  Bot mention also works (`@BotName command`).

### Available to everyone
| Command | Description |
|---------|-------------|
| `!ping` | Latency check |
| `!botinfo` | Basic bot information |
| `!help [command]` | Paginated help with search |

### Owner-only
| Command | Description |
|---------|-------------|
| `!vmanage [BotName]` | Interactive management panel (buttons: Restart / Stop / Update / Logs / Refresh) |
| `!stats` | Detailed bot stats: guilds, users, latency, uptime, runtime info |
| `!servers` | Paginated list of all guilds |
| `!announce <msg>` | Broadcast embed to all guild system channels |
| `!setactivity <type> <text>` | Change bot presence (playing/watching/listening/competing) |
| `!prefix [new]` | Get or change the command prefix |
| `!load <ext>` | Load an extension |
| `!unload <ext>` | Unload an extension |
| `!reload <ext>` | Reload an extension (picks up code changes live) |
| `!cogs` | List all loaded extensions |
| `!shutdown` | Graceful shutdown (will not auto-restart unless systemd does it) |

The `!vmanage` panel calls `sudo systemctl` on the server; the sudoers entry created by `install.sh` allows this without a password.

---

## Configuration

**`data/config.json`** (permissions: `600`):

```json
{
  "name":         "MyBot",
  "service_name": "vantage-mybot",
  "token":        "MTI…",
  "prefix":       "!",
  "owner_ids":    [123456789],
  "description":  "Vantage — a custom Discord bot framework",
  "status":       "online",
  "activity":     "!help for commands"
}
```

- `name` / `service_name` are written by `install.sh` and used by `vmanage` + the `!vmanage` Discord command
- `activity` supports the `{prefix}` template token
- Reload with `!reload cogs.admin` (for prefix changes) or restart the service

**Changing prefix at runtime:**
```
!prefix >
```

**Changing activity at runtime:**
```
!setactivity watching over {guild_count} servers
```

---

## Cog System

Cogs are Python extensions.  The loader (`CogManager`) stores state in `data/cog_data.json`.

### Module resolution

`data/repos/` is inserted into `sys.path` at bot startup.  This means:

```
data/repos/
  my_cogs/
    greet.py          → importable as  my_cogs.greet
    welcome/
      __init__.py     → importable as  my_cogs.welcome
```

### Adding a GitHub repo

```bash
python launcher.py repos add https://github.com/user/my-cogs
python launcher.py cogs install my_cogs greet
python launcher.py cogs autoload my_cogs.greet
# restart the bot, or:
!load my_cogs.greet
```

### Adding a local repo

```bash
python launcher.py repos add /home/user/my-cogs --name my_cogs
```

This creates a symlink at `data/repos/my_cogs → /home/user/my-cogs`.

### Autoload

Cogs in the `autoload` list are loaded automatically on every bot start.  Toggle with:

```bash
python launcher.py cogs autoload my_cogs.greet
```

---

## Per-Guild Data

`core/guild_data.py` provides simple per-guild JSON persistence:

```python
from core.guild_data import load_guild, save_guild, get_guild_value, set_guild_value

# In a cog command:
data = load_guild(ctx.guild.id)          # returns dict
data["welcome_channel"] = channel.id
save_guild(ctx.guild.id, data)

# Shorthand helpers:
set_guild_value(ctx.guild.id, "muted_role", role.id)
role_id = get_guild_value(ctx.guild.id, "muted_role")
```

Files live at `data/guilds/{guild_id}.json`.

---

## Project Structure

```
VantageOverlook/
├── vmanage.py           System-wide CLI management tool
├── launcher.py          Bot-scoped CLI (start, setup, repos, cogs, system)
├── install.sh           Ubuntu one-shot installer
├── vantage.service      systemd unit template
├── requirements.txt     Python dependencies
├── .env.example         Environment variable template
├── README.md            This file
├── OWNER_GUIDE.md       Plain-English owner guide
├── COGS.md              Cog authoring reference
│
├── core/
│   ├── bot.py           VantageBot class
│   ├── config.py        data/config.json helpers
│   ├── cog_manager.py   Repo + cog registry
│   ├── guild_data.py    Per-guild JSON storage
│   └── help_command.py  Paginated help with Discord UI
│
├── cogs/
│   └── admin.py         Built-in admin cog (always loaded)
│
└── data/                Runtime data (gitignored)
    ├── config.json
    ├── cog_data.json
    ├── repos/
    └── guilds/
```

---

## Service Management

The systemd service is named `vantage-<botname>` (e.g. `vantage-mybot`).

```bash
# Using vmanage (recommended)
vmanage MyBot --restart
vmanage MyBot --logs
vmanage MyBot --status

# Direct systemctl
sudo systemctl start   vantage-mybot
sudo systemctl stop    vantage-mybot
sudo systemctl restart vantage-mybot
sudo systemctl status  vantage-mybot
sudo journalctl -u vantage-mybot -f        # live logs
sudo journalctl -u vantage-mybot -n 100    # last 100 lines
```

---

## Writing Cogs

See **[COGS.md](COGS.md)** for a complete cog authoring guide.

Minimal example:

```python
# my_cogs/greet.py
from discord.ext import commands

class Greet(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @commands.command()
    async def hello(self, ctx):
        """Say hello!"""
        await ctx.send(f"Hello, {ctx.author.mention}! 👋")

async def setup(bot):
    await bot.add_cog(Greet(bot))
```

---

## Multi-Bot Setup

Run multiple independent Vantage instances on one server:

```bash
# Install bot 1
sudo ./install.sh        # name it "Alpha" → /opt/vantage/Alpha, service vantage-alpha

# Install bot 2
sudo ./install.sh        # name it "Beta"  → /opt/vantage/Beta,  service vantage-beta

# Manage them independently
vmanage Alpha --restart
vmanage Beta  --logs
vmanage                  # shows both with status
```

Each installation has its own venv, config, cog registry, and guild data.  The `!vmanage` Discord command filters by the bot's configured `name` field, so `!vmanage Alpha` only responds from the Alpha bot.

