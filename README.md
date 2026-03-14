# VantageOverlook

A modular Discord bot framework built on [discord.py](https://discordpy.readthedocs.io/), designed for self-hosting on Ubuntu servers. Deploy once, manage everything from the terminal with `vmanage` or from Discord with `!vmanage`.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Manual Setup — AWS Ubuntu](#manual-setup--aws-ubuntu)
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
vmanage.py          Standalone system-wide CLI — zero venv dependency
launcher.py         Bot-scoped CLI (start, setup, repos, cogs, system)
core/
  bot.py            VantageBot — subclasses discord.ext.commands.Bot
  config.py         Config reader/writer with resolve_data_dir()
  cog_manager.py    Repo registry + cog install tracker
  guild_data.py     Per-guild JSON storage
  help_command.py   Paginated help with buttons and live search modal
cogs/
  admin.py          Built-in always-loaded admin cog
vantage@.service    systemd template unit (multi-bot support)
```

**Filesystem layout on the server:**

| Path | Purpose |
|------|---------|
| `/opt/<BotName>/` | Git clone (code, venv) |
| `/var/lib/<BotName>/` | Mutable data (config.json, cog_data.json, guild files, cloned repos) |
| `/var/log/<BotName>/` | Log files (via journald) |
| `/usr/local/bin/vmanage` | System-wide CLI (symlink or copy) |

**Data directory resolution** (checked in order):
1. `VANTAGE_DATA_DIR` environment variable
2. `/var/lib/<BotName>/` when code is under `/opt/<BotName>/`
3. `data/` relative to the project root (local development fallback)

**Boot sequence:**
1. `systemd` starts `launcher.py start` as the `vbot` user
2. `load_config()` reads `<data_dir>/config.json`
3. `VantageBot.__init__` sets up intents, owner IDs, prefix, and the custom help command
4. `setup_hook()` — adds `<data_dir>/repos/` to `sys.path`, loads `cogs.admin`, then autoloads all cogs listed in `cog_data.json → autoload`
5. `on_ready()` — sets `start_time`, updates bot presence

---

## Manual Setup — AWS Ubuntu

These steps assume a fresh Ubuntu 22.04+ EC2 instance. The example bot name is `vprod`; replace it with your preferred name throughout.

### Step 1 — Create group and user

```bash
# Group and user
sudo groupadd vbots
sudo useradd -r -s /usr/sbin/nologin -g vbots vbot
```

### Step 2 — Add human users to the group

```bash
# Add yourself and the other person
sudo usermod -aG vbots yourname
sudo usermod -aG vbots theirname

# Log out and back in, then check
groups yourname
```

### Step 3 — Create directories

```bash
sudo mkdir -p /opt/vprod
sudo mkdir -p /var/lib/vprod
sudo mkdir -p /var/log/vprod

# Ownership
sudo chown -R vbot:vbots /opt/vprod
sudo chown -R vbot:vbots /var/lib/vprod
sudo chown -R vbot:vbots /var/log/vprod

# Permissions (SGID so new files inherit the group)
sudo chmod 2775 /opt/vprod
sudo chmod 2775 /var/lib/vprod
sudo chmod 2775 /var/log/vprod
```

### Step 4 — Set umask (both of you)

```bash
echo 'umask 002' >> ~/.bashrc
source ~/.bashrc
```

### Step 5 — Install system packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git
```

### Step 6 — Clone the repository

```bash
sudo -u vbot git clone https://github.com/BigPattyOG/VantageOverlook.git /opt/vprod
```

### Step 7 — Create the Python virtual environment

```bash
sudo -u vbot bash -c "
    cd /opt/vprod
    python3 -m venv venv
    venv/bin/pip install --upgrade pip
    venv/bin/pip install -r requirements.txt
"
```

### Step 8 — Data directory

The `/var/lib/vprod` directory was already created with the correct ownership in Step 3 — nothing more to do here.

### Step 9 — Run the setup wizard

```bash
sudo -u vbot bash -c "
    cd /opt/vprod
    VANTAGE_DATA_DIR=/var/lib/vprod venv/bin/python launcher.py setup
"
```

This writes `/var/lib/vprod/config.json` with your token, prefix, and owner IDs. Lock it down after:

```bash
sudo chmod 600 /var/lib/vprod/config.json
```

### Step 10 — Install the systemd service

```bash
sudo cp /opt/vprod/vantage@.service /etc/systemd/system/vantage@.service
sudo systemctl daemon-reload
sudo systemctl enable vantage@vprod
sudo systemctl start  vantage@vprod
```

Check service status:

```bash
sudo systemctl status vantage@vprod
sudo journalctl -u vantage@vprod -f
```

### Step 11 — Install vmanage system-wide

```bash
sudo ln -sf /opt/vprod/vmanage.py /usr/local/bin/vmanage
sudo chmod +x /usr/local/bin/vmanage
```

Now any user can run `vmanage vprod --status`.

### Step 12 — Optional: sudoers entry for Discord management panel

The `!vmanage` Discord panel uses `sudo systemctl` to restart/stop the bot. Add a sudoers entry so this works without a password:

```bash
echo "vbot ALL=(ALL) NOPASSWD: /bin/systemctl restart vantage@vprod, \
    /bin/systemctl stop vantage@vprod, \
    /bin/systemctl start vantage@vprod" \
    | sudo tee /etc/sudoers.d/vantage-vprod
sudo chmod 440 /etc/sudoers.d/vantage-vprod
```

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

Bot discovery: scans `/opt/` for subdirectories containing `launcher.py`. Name matching is case-insensitive and supports prefix matching (`vmanage my` matches `MyBot` if unambiguous).

---

## launcher.py CLI

Run as the bot user (`sudo -u vbot`) or from within the install directory:

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
sudo python launcher.py system install-service [--user USER] [--bot-name NAME]
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

The `!vmanage` panel calls `sudo systemctl` on the server; the sudoers entry from step 9 allows this without a password.

---

## Configuration

**`/var/lib/<BotName>/config.json`** (permissions: `600`):

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

- `name` — used by `vmanage` + the `!vmanage` Discord command
- `service_name` — systemd unit name suffix (e.g. `vantage-mybot`)
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

Cogs are Python extensions.  The loader (`CogManager`) stores state in `<data_dir>/cog_data.json`.

### Module resolution

`<data_dir>/repos/` is inserted into `sys.path` at bot startup.  This means:

```
/var/lib/MyBot/repos/
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

This creates a symlink at `<data_dir>/repos/my_cogs → /home/user/my-cogs`.

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

Files live at `<data_dir>/guilds/{guild_id}.json`.

---

## Project Structure

```
VantageOverlook/                  → /opt/MyBot/  (git clone)
├── vmanage.py           System-wide CLI management tool
├── launcher.py          Bot-scoped CLI (start, setup, repos, cogs, system)
├── vantage@.service     systemd template unit (multi-bot support via %i)
├── requirements.txt     Python dependencies
├── .env.example         Environment variable template
├── README.md            This file
├── OWNER_GUIDE.md       Plain-English owner guide
├── COGS.md              Cog authoring reference
│
├── core/
│   ├── bot.py           VantageBot class
│   ├── config.py        Config helpers + resolve_data_dir()
│   ├── cog_manager.py   Repo + cog registry
│   ├── guild_data.py    Per-guild JSON storage
│   └── help_command.py  Paginated help with Discord UI
│
└── cogs/
    └── admin.py         Built-in admin cog (always loaded)

/var/lib/MyBot/           (mutable data — gitignored)
├── config.json
├── cog_data.json
├── repos/
└── guilds/
```

---

## Service Management

The systemd service is a template unit `vantage@.service`. Each bot runs as its own instance:

```bash
# Using vmanage (recommended)
vmanage MyBot --restart
vmanage MyBot --logs
vmanage MyBot --status

# Direct systemctl
sudo systemctl start   vantage@MyBot
sudo systemctl stop    vantage@MyBot
sudo systemctl restart vantage@MyBot
sudo systemctl status  vantage@MyBot
sudo journalctl -u vantage@MyBot -f        # live logs
sudo journalctl -u vantage@MyBot -n 100    # last 100 lines
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
        await ctx.send(f"Hello, {ctx.author.mention}!")

async def setup(bot):
    await bot.add_cog(Greet(bot))
```

---

## Multi-Bot Setup

Run multiple independent Vantage instances on one server using the `vantage@.service` template:

```bash
# Clone bot 1 to /opt/Alpha
sudo git clone https://github.com/BigPattyOG/VantageOverlook.git /opt/Alpha
sudo mkdir -p /var/lib/Alpha
# ... follow steps 4-6 for Alpha ...
sudo systemctl enable --now vantage@Alpha

# Clone bot 2 to /opt/Beta
sudo git clone https://github.com/BigPattyOG/VantageOverlook.git /opt/Beta
sudo mkdir -p /var/lib/Beta
# ... follow steps 4-6 for Beta ...
sudo systemctl enable --now vantage@Beta

# Manage them independently
vmanage Alpha --restart
vmanage Beta  --logs
vmanage                  # shows both with status
```

Each installation has its own venv, config, cog registry, and guild data. The `!vmanage` Discord command filters by the bot's configured `name` field, so `!vmanage Alpha` only responds from the Alpha bot.

