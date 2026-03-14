# Owner Guide — Vantage Bot (Plain English Edition)

This guide is written for **you**, the person who owns the bot but doesn't want to read a technical manual. No jargon. If something breaks, start here.

---

## What even is this?

Vantage is your personal Discord bot. It lives on a Linux server (like a VPS), runs 24/7, and you control it either by:

1. **Typing commands in a terminal** on the server (`vmanage MyBot --restart`)
2. **Typing commands in Discord** (`!vmanage`, `!stats`, etc.)

The bot is "modular" — the core bot is tiny, but you can add extra features (called **cogs**) from GitHub or from your own files.

---

## The three things you need to know about

### 1. `vmanage` — your terminal remote control

After the bot is installed, you have a command called `vmanage` on your server. It replaces the old `run.sh` menu.

```bash
# See all your bots and their status
vmanage

# See detailed info about a specific bot
vmanage MyBot

# Start / stop / restart the bot
vmanage MyBot --start
vmanage MyBot --stop
vmanage MyBot --restart

# Watch the bot's live output (Ctrl+C to stop)
vmanage MyBot --logs

# See the last 50 lines of logs without streaming
vmanage MyBot --logs --lines 50

# Pull updates from GitHub and restart the bot
vmanage MyBot --update

# If you messed up the config, redo the setup questions
vmanage MyBot --setup
```

That's it. You don't need to remember any systemd commands.

---

### 2. Discord commands — control the bot from Discord itself

Type these in any server channel the bot can see. Replace `!` with your prefix if you changed it.

**These work for everyone:**
- `!ping` — checks if the bot is alive and how fast it's responding
- `!botinfo` — shows basic info about the bot
- `!help` — shows all commands with navigation buttons

**These only work for you (the owner):**
- `!vmanage` — opens a management panel right in Discord with buttons to Restart, Stop, Update, and see Logs
- `!vmanage MyBot` — same, but filters to a specific bot (useful if you have multiple)
- `!stats` — shows how many servers the bot is in, user counts, latency, uptime
- `!servers` — lists every server the bot is in
- `!announce Hello everyone!` — sends that message to every server's system channel
- `!setactivity playing chess` — changes what the bot shows as its status (playing/watching/listening/competing)
- `!prefix >` — changes the command prefix from `!` to `>`
- `!shutdown` — turns the bot off (it won't come back on until you restart it with `vmanage MyBot --start`)
- `!load my_cogs.greet` — turns on an extra cog (plugin)
- `!reload my_cogs.greet` — reloads a cog to pick up code changes without restarting the whole bot
- `!unload my_cogs.greet` — turns off a cog

---

### 3. The config file — where your settings live

All your bot settings are in a file called `data/config.json`. It looks like this:

```json
{
  "name": "MyBot",
  "token": "your-secret-token-here",
  "prefix": "!",
  "owner_ids": [123456789],
  "description": "My awesome bot"
}
```

**You should never share this file** — it contains your bot token, which is basically the bot's password.

To change settings, run:
```bash
vmanage MyBot --setup
```
It will ask you the questions again and save your answers.

---

## Installing the bot for the first time

Run this one command on your Ubuntu server:

```bash
curl -sSL https://raw.githubusercontent.com/BigPattyOG/VantageOverlook/main/install.sh | sudo bash
```

It will:
1. Ask you what to **name** your bot (just a label for you, like "MyBot")
2. Ask for your **bot token** (get it from https://discord.com/developers/applications)
3. Try to **automatically find your Discord ID** from the token — if it works, just press Enter
4. Ask for a **command prefix** (default is `!`, so commands are like `!ping`)
5. Set everything up and start the bot

After it's done, test it with `vmanage` and try `!ping` in Discord.

---

## Day-to-day management

### Bot crashed or acting weird?
```bash
vmanage MyBot --restart
vmanage MyBot --logs       # see what went wrong
```

### Update the bot to the latest version?
```bash
vmanage MyBot --update
```
This pulls the latest code from GitHub, upgrades packages, and restarts automatically.

### Bot not responding in Discord?

Check if it's running:
```bash
vmanage MyBot
```

If it says "stopped", start it:
```bash
vmanage MyBot --start
```

If it starts but immediately stops, read the logs:
```bash
vmanage MyBot --logs --lines 50
```

Common causes:
- **Invalid token** — your token expired or was reset. Go to discord.com/developers, regenerate it, and run `vmanage MyBot --setup`
- **Missing intents** — go to the developer portal, find your bot, enable "Message Content Intent" and "Server Members Intent"
- **Python error** — check the logs for a traceback

---

## Adding extra features (cogs)

Cogs are plugins that add commands and features to your bot. You can add them from GitHub or write your own.

### Adding a cog from GitHub

```bash
# From your bot's install directory
cd /opt/MyBot

# Add the repo (replace with actual URL)
sudo -u vantage ./venv/bin/python launcher.py repos add https://github.com/someone/cool-cogs

# Install a specific cog from that repo
sudo -u vantage ./venv/bin/python launcher.py cogs install cool_cogs some_feature

# Make it load automatically when the bot starts
sudo -u vantage ./venv/bin/python launcher.py cogs autoload cool_cogs.some_feature

# Load it right now without restarting
# (just type this in Discord:)
!load cool_cogs.some_feature
```

### Seeing what cogs are loaded
```bash
vmanage MyBot --cogs      # from terminal
!cogs                     # from Discord
```

---

## Running multiple bots

You can run more than one Vantage bot on the same server. Just run `install.sh` again and give the new bot a different name (e.g. "Beta"). Then:

```bash
vmanage            # shows both bots
vmanage Alpha      # manage Alpha
vmanage Beta       # manage Beta
```

In Discord, `!vmanage Alpha` will only get a response from the Alpha bot (even if both bots are in the same server).

---

## Where things live on the server

| What | Where |
|------|-------|
| Bot files | `/opt/MyBot/` |
| Config (token, prefix, etc.) | `/var/lib/MyBot/config.json` |
| Cog registry | `/var/lib/MyBot/cog_data.json` |
| Downloaded cog repos | `/var/lib/MyBot/repos/` |
| Per-server data | `/var/lib/MyBot/guilds/` |
| Log viewer | `vmanage MyBot --logs` or `journalctl -u vantage-mybot` |
| Python install | `/opt/MyBot/venv/` |

---

## Something went completely wrong — nuclear option

If the bot is broken and you can't figure it out:

```bash
# 1. Stop the bot
vmanage MyBot --stop

# 2. Delete just the code (keeps your config and data)
sudo rm -rf /opt/MyBot
# (But keep a copy of data/config.json first if you want to preserve settings)

# 3. Re-install
curl -sSL https://raw.githubusercontent.com/BigPattyOG/VantageOverlook/main/install.sh | sudo bash
```

Or if you just want to reset the configuration:
```bash
vmanage MyBot --setup
```

---

## Quick troubleshooting checklist

| Symptom | First thing to try |
|---------|--------------------|
| Bot offline | `vmanage MyBot --start` |
| Bot starts then crashes | `vmanage MyBot --logs --lines 50` |
| Commands not working | Check prefix with `!ping` or `@BotName ping` |
| "Not owner" error | Make sure your Discord ID is in `owner_ids` in config |
| Token invalid error | Regenerate token in developer portal, run `vmanage MyBot --setup` |
| Want new features | `vmanage MyBot --update` |
| Config got messed up | `vmanage MyBot --setup` |
