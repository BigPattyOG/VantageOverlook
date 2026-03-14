# VantageOverlook

A custom Discord bot framework built with [discord.py](https://discordpy.readthedocs.io/), designed for easy self-hosting on Ubuntu servers. Inspired by Red-DiscordBot but built from scratch for full control.

---

## Features

- **Modular cog system** — load extensions from GitHub repos or local directories
- **Paginated help command** — embeds with navigation buttons and live search
- **CLI management tools** — manage repos and cogs from the command line
- **Systemd integration** — runs as a proper system service with auto-restart
- **Owner-only admin commands** — load, unload, reload cogs at runtime without restarting

---

## Quick Start (Ubuntu Server)

### 1. One-shot install

```bash
git clone https://github.com/BigPattyOG/VantageOverlook.git
cd VantageOverlook
chmod +x install.sh
sudo ./install.sh
```

The script installs Python 3.11, creates a dedicated `vantage` system user, sets up a virtual environment, installs dependencies, and registers a systemd service.

### 2. Configure the bot

```bash
sudo -u vantage bash
cd /opt/vantage/VantageOverlook
source venv/bin/activate
python launcher.py setup
```

You'll be prompted for:
- Your **bot token** (from [Discord Developer Portal](https://discord.com/developers/applications))
- **Command prefix** (default: `!`)
- Your **Discord user ID(s)** (enable Developer Mode → right-click name → Copy ID)
- A **bot description**

### 3. Start the bot

```bash
sudo systemctl start vantage
sudo journalctl -u vantage -f   # watch live logs
```

---

## Manual Setup (Development)

```bash
git clone https://github.com/BigPattyOG/VantageOverlook.git
cd VantageOverlook

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python launcher.py setup
python launcher.py start
```

---

## CLI Reference

### `python launcher.py start`
Start the bot.

### `python launcher.py setup`
Interactive wizard to configure token, prefix, and owner IDs.

---

### Repo Management

```bash
# Add a GitHub repository
python launcher.py repos add https://github.com/user/my-cogs

# Add a local directory as a repo
python launcher.py repos add /home/user/my-local-cogs

# Add with a custom name (must be a valid Python identifier)
python launcher.py repos add https://github.com/user/my-cogs --name my_cogs

# List all registered repos
python launcher.py repos list

# Pull latest changes from all GitHub repos
python launcher.py repos update

# Update a specific repo
python launcher.py repos update my_cogs

# Remove a repo (cloned data is deleted)
python launcher.py repos remove my_cogs
```

---

### Cog Management

```bash
# List installed cogs
python launcher.py cogs list

# Install a cog from a registered repo
python launcher.py cogs install my_cogs welcome

# Enable autoload (cog loads automatically when bot starts)
python launcher.py cogs autoload my_cogs.welcome

# Disable autoload
python launcher.py cogs autoload my_cogs.welcome

# Uninstall a cog (removes from registry, not from disk)
python launcher.py cogs uninstall my_cogs.welcome
```

---

### In-Discord Admin Commands

These commands are available to bot **owners only**:

| Command | Description |
|---------|-------------|
| `!ping` | Check bot latency |
| `!load <ext>` | Load an extension (e.g. `my_cogs.welcome`) |
| `!unload <ext>` | Unload a running extension |
| `!reload <ext>` | Reload an extension (picks up code changes) |
| `!cogs` | List all loaded extensions |
| `!prefix [new]` | Get or change the command prefix |
| `!shutdown` | Gracefully shut down the bot |
| `!help` | Paginated help — shows all commands |

---

## Writing a Cog

A cog is a Python file (or package) that exports a `setup(bot)` coroutine. Example:

```python
# my_cogs/greet.py
from discord.ext import commands

class Greet(commands.Cog):
    """Fun greeting commands."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def hello(self, ctx):
        """Say hello!"""
        await ctx.send(f"Hello, {ctx.author.mention}! 👋")

async def setup(bot):
    await bot.add_cog(Greet(bot))
```

Then install and enable it:

```bash
python launcher.py repos add /path/to/my_cogs
python launcher.py cogs install my_cogs greet
python launcher.py cogs autoload my_cogs.greet
```

Or load it at runtime (no restart needed):

```
!load my_cogs.greet
```

---

## Project Structure

```
VantageOverlook/
├── launcher.py          CLI entry point
├── requirements.txt     Python dependencies
├── install.sh           Ubuntu one-shot setup script
├── vantage.service      systemd service unit
├── .env.example         Example environment file
├── core/
│   ├── bot.py           VantageBot class
│   ├── cog_manager.py   Repo & cog registry
│   ├── help_command.py  Custom paginated help
│   └── config.py        JSON config management
├── cogs/
│   └── admin.py         Built-in admin cog (always loaded)
└── data/                Runtime data (gitignored)
    ├── config.json       Bot configuration
    ├── cog_data.json     Repo/cog registry
    └── repos/            Cloned/linked cog repos
```

---

## Service Management

```bash
sudo systemctl start vantage     # Start
sudo systemctl stop vantage      # Stop
sudo systemctl restart vantage   # Restart
sudo systemctl status vantage    # Status
sudo journalctl -u vantage -f    # Live logs
sudo journalctl -u vantage -n 100  # Last 100 log lines
```

---

## Updating the Bot

```bash
sudo systemctl stop vantage
sudo -u vantage git -C /opt/vantage/VantageOverlook pull
sudo -u vantage /opt/vantage/VantageOverlook/venv/bin/pip install -r /opt/vantage/VantageOverlook/requirements.txt
sudo systemctl start vantage
```
