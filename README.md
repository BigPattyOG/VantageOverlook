# VantageOverlook — vprod

A modular Discord bot framework built on [discord.py](https://discordpy.readthedocs.io/), designed for self-hosting on Ubuntu servers. Deploy once, manage everything from the terminal with `vmanage` or from Discord with `!vmanage`.

**New here? Start with [SETUP.md](SETUP.md) — a complete step-by-step guide from Discord portal to running bot.**

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

---

## Architecture Overview

```
vmanage.py          Standalone system-wide CLI — zero venv dependency
launcher.py         Bot-scoped CLI (start, repos, cogs, system)
core/
  bot.py            VantageBot — subclasses discord.ext.commands.Bot
  config.py         Config reader/writer with resolve_data_dir()
  cog_manager.py    Repo registry + cog install tracker
  guild_data.py     Per-guild JSON storage
  help_command.py   Paginated help with buttons and live search modal
cogs/
  admin.py          Built-in always-loaded admin cog
vprod@.service      systemd template unit
```

**Filesystem layout on the server:**

| Path | Purpose |
|------|---------|
| `/opt/vprod/vprod/` | Git clone (code, venv, .env) |
| `/var/lib/vprod/vprod/` | Mutable data (config.json, cog_data.json, guild files, repos) |
| `/usr/local/bin/vmanage` | System-wide CLI (symlink) |

**Data directory resolution** (checked in order):
1. `VPROD_DATA_DIR` environment variable
2. `/var/lib/vprod/` when code is under `/opt/vprod/`
3. `data/` relative to the project root (local development fallback)

**Token management:**
- `DISCORD_TOKEN` is read from the `.env` file in the working directory (or from the shell environment).
- The token is never stored in `config.json` — it lives only in `.env`.

**Boot sequence:**
1. `systemd` starts `launcher.py start` as the `vprodbot` user
2. `python-dotenv` loads `.env` (sets `DISCORD_TOKEN`, etc.)
3. `load_config()` reads `<data_dir>/config.json`
4. `VantageBot.__init__` sets up intents, owner IDs, prefix, and the custom help command
5. `setup_hook()` — fetches owners from Discord API/team, adds `<data_dir>/repos/` to `sys.path`, loads `cogs.admin`, then autoloads cogs from `cog_data.json`
6. `on_ready()` — sets `start_time`, updates bot presence

**Owner resolution:**
- Owners are fetched automatically from the Discord application's team (accepted members) via `application_info()`.
- No manual owner ID configuration is required when using a Discord Team.

---

## Manual Setup — AWS Ubuntu

These steps assume a fresh Ubuntu 22.04+ EC2 instance. Run all commands as root (or with sudo) unless stated otherwise. For a complete step-by-step walkthrough including the Discord developer portal and group peer setup, see **[SETUP.md](SETUP.md)**.

### 1. Install system dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3 python3-pip python3-venv build-essential
```

### 2. Clone and create the system user + dev group

```bash
# The bot code lives at /opt/vprod/vprod/ (a subdirectory of the install base)
sudo mkdir -p /opt/vprod
sudo git clone https://github.com/BigPattyOG/VantageOverlook.git /opt/vprod/vprod
sudo python3 /opt/vprod/vprod/launcher.py system create-user
sudo chown -R vprodbot:vprodadmins /opt/vprod/vprod
sudo chmod -R 750 /opt/vprod/vprod
```

This creates the `vprodbot` system account and the `vprodadmins` developer group.

To add a developer to the group:
```bash
sudo usermod -aG vprodadmins <yourusername>
```

### 3. Set up the virtual environment

```bash
sudo -u vprodbot bash -c "
    cd /opt/vprod/vprod
    python3 -m venv venv
    venv/bin/pip install --upgrade pip
    venv/bin/pip install -r requirements.txt
"
```

### 4. Create the data directory

```bash
sudo mkdir -p /var/lib/vprod/vprod
sudo chown -R vprodbot:vprodadmins /var/lib/vprod/vprod
sudo chmod 750 /var/lib/vprod/vprod
```

### 5. Configure the bot

Create the `.env` file with your bot token:

```bash
sudo -u vprodbot cp /opt/vprod/vprod/.env.example /opt/vprod/vprod/.env
sudo nano /opt/vprod/vprod/.env   # add your DISCORD_TOKEN
sudo chmod 600 /opt/vprod/vprod/.env
sudo chown vprodbot:vprodbot /opt/vprod/vprod/.env
```

Your `.env` file should contain:

```
DISCORD_TOKEN=your_discord_bot_token_here
```

Create `config.json` in the data directory:

```bash
sudo -u vprodbot tee /var/lib/vprod/vprod/config.json > /dev/null << 'EOF'
{
  "name": "vprod",
  "service_name": "vprod",
  "prefix": "!",
  "owner_ids": [],
  "description": "vprod — Vantage Discord Bot",
  "status": "online",
  "activity": "{prefix}help for commands"
}
EOF
sudo chmod 640 /var/lib/vprod/vprod/config.json
sudo chown vprodbot:vprodadmins /var/lib/vprod/vprod/config.json
```

Note: `owner_ids` is optional. Owners are resolved automatically from your Discord application team.

### 6. Install the systemd service

```bash
sudo python3 /opt/vprod/vprod/launcher.py system install-service
sudo systemctl start vprod@vprod
sudo systemctl enable vprod@vprod
```

Check service status:

```bash
sudo systemctl status vprod@vprod
sudo journalctl -u vprod@vprod -f
```

### 7. Install vmanage system-wide

```bash
sudo ln -sf /opt/vprod/vprod/vmanage.py /usr/local/bin/vmanage
sudo chmod +x /usr/local/bin/vmanage
```

Now any user can run `vmanage vprod --status`.

### 8. Optional — sudoers entry for the Discord management panel

The `!vmanage` Discord panel uses `sudo systemctl` to restart/stop the bot. Add a sudoers entry so this works without a password:

```bash
sudo tee /etc/sudoers.d/vprod > /dev/null << 'EOF'
vprodbot ALL=(ALL) NOPASSWD: /bin/systemctl restart vprod@vprod, \
    /bin/systemctl stop vprod@vprod, \
    /bin/systemctl start vprod@vprod
EOF
sudo chmod 440 /etc/sudoers.d/vprod
```

---

## vmanage CLI

`vmanage.py` is installed system-wide at `/usr/local/bin/vmanage`. It uses **only the Python standard library** — no venv needed.

```bash
vmanage                         # list all installed bot instances
vmanage vprod                   # status dashboard
vmanage vprod --start           # start service
vmanage vprod --stop            # stop service
vmanage vprod --restart         # restart service
vmanage vprod --status          # full systemctl status
vmanage vprod --logs            # stream live logs  (Ctrl+C to stop)
vmanage vprod --logs --lines 50 # last 50 lines (non-streaming)
vmanage vprod --update          # git pull + pip upgrade + restart
vmanage vprod --update --yes    # same, skip confirmation
vmanage vprod --cogs            # list installed cogs
vmanage vprod --repos           # list cog repositories
vmanage vprod --debug           # show debug resolution info
```

Bot discovery: scans `/opt/vprod/` for subdirectories that contain a `config.json`. Name matching is case-insensitive and supports prefix matching.

---

## launcher.py CLI

Run as the bot user (`sudo -u vprodbot`) or from within the install directory:

```bash
# Bot lifecycle
python launcher.py start                    # start the bot (used by systemd)

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
sudo python launcher.py system create-user  # creates vprodbot user and vprodadmins group
sudo python launcher.py system install-service
```

---

## In-Discord Commands

All commands use the configured prefix (default `!`).  Bot mention also works (`@vprod command`).

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

The `!vmanage` panel calls `sudo systemctl` on the server; the sudoers entry from step 8 allows this without a password.

---

## Configuration

**`/var/lib/vprod/vprod/config.json`** (permissions: `640`):

```json
{
  "name":        "vprod",
  "service_name": "vprod",
  "prefix":      "!",
  "owner_ids":   [],
  "description": "vprod — Vantage Discord Bot",
  "status":      "online",
  "activity":    "!help for commands"
}
```

**`/opt/vprod/vprod/.env`** (permissions: `600`):

```
DISCORD_TOKEN=your_discord_bot_token_here
```

- `owner_ids` — optional additional owner IDs beyond those in the Discord application team.
- `activity` supports the `{prefix}` template token.
- Reload with `!reload cogs.admin` (for prefix changes) or restart the service.

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

Cogs are Python extensions. The loader (`CogManager`) stores state in `<data_dir>/cog_data.json`.

### Module resolution

`<data_dir>/repos/` is inserted into `sys.path` at bot startup. This means:

```
/var/lib/vprod/vprod/repos/
  my_cogs/
    greet.py          -> importable as  my_cogs.greet
    welcome/
      __init__.py     -> importable as  my_cogs.welcome
```

### Adding a GitHub repo

```bash
cd /opt/vprod/vprod
sudo -u vprodbot ./venv/bin/python launcher.py repos add https://github.com/user/my-cogs
sudo -u vprodbot ./venv/bin/python launcher.py cogs install my_cogs greet
sudo -u vprodbot ./venv/bin/python launcher.py cogs autoload my_cogs.greet
# restart the bot, or load immediately in Discord:
!load my_cogs.greet
```

### Adding a local repo

```bash
cd /opt/vprod/vprod
sudo -u vprodbot ./venv/bin/python launcher.py repos add /home/user/my-cogs --name my_cogs
```

This creates a symlink at `<data_dir>/repos/my_cogs -> /home/user/my-cogs`.

### Autoload

Cogs in the `autoload` list are loaded automatically on every bot start. Toggle with:

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

Files live at `<data_dir>/guilds/{guild_id}.json`, i.e. `/var/lib/vprod/vprod/guilds/{guild_id}.json` in production.

---

## Project Structure

```
/opt/vprod/                       (install base — can hold multiple bot instances)
  vprod/                          (this bot's code — git clone)
    vmanage.py           System-wide CLI management tool
    launcher.py          Bot-scoped CLI (start, repos, cogs, system)
    vprod@.service       systemd template unit
    requirements.txt     Python dependencies
    .env                 Bot token and env vars (gitignored, chmod 600)
    .env.example         Environment variable template
    README.md            Technical reference
    SETUP.md             Full setup guide (Discord portal, peers, all steps)
    OWNER_GUIDE.md       Plain-English owner guide
    COGS.md              Cog authoring reference
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

/var/lib/vprod/vprod/             (mutable data — separate from code, gitignored)
├── config.json
├── cog_data.json
├── repos/
└── guilds/
```

---

## Service Management

The systemd service is a template unit `vprod@.service`. Manage the bot with vmanage or systemctl:

```bash
# Using vmanage (recommended)
vmanage vprod --restart
vmanage vprod --logs
vmanage vprod --status

# Direct systemctl
sudo systemctl start   vprod@vprod
sudo systemctl stop    vprod@vprod
sudo systemctl restart vprod@vprod
sudo systemctl status  vprod@vprod
sudo journalctl -u vprod@vprod -f        # live logs
sudo journalctl -u vprod@vprod -n 100    # last 100 lines
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
