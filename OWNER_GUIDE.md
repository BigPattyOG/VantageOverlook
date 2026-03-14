# Owner Guide — vprod Bot (Plain English Edition)

This guide is written for **you**, the person who owns the bot. No jargon. If something breaks, start here.

For the full first-time setup walkthrough (Discord portal, server setup, adding devs), see **[SETUP.md](SETUP.md)**.

---

## What even is this?

vprod is your personal Discord bot. It lives on a Linux server, runs 24/7, and you control it either by:

1. **Typing commands in a terminal** on the server (`vmanage vprod --restart`)
2. **Typing commands in Discord** (`!vmanage`, `!stats`, etc.)

The bot is "modular" — the core is tiny, but you can add extra features (called **cogs**) from GitHub or your own files.

---

## The three things you need to know about

### 1. `vmanage` — your terminal remote control

After the bot is installed, you have a command called `vmanage` on your server.

```bash
# See all your bots and their status
vmanage

# See detailed info about a specific bot
vmanage vprod

# Start / stop / restart the bot
vmanage vprod --start
vmanage vprod --stop
vmanage vprod --restart

# Watch the bot's live output (Ctrl+C to stop)
vmanage vprod --logs

# See the last 50 lines of logs without streaming
vmanage vprod --logs --lines 50

# Pull updates from GitHub and restart the bot
vmanage vprod --update
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
- `!vmanage vprod` — same, but filters to a specific bot (useful if you have multiple)
- `!stats` — shows how many servers the bot is in, user counts, latency, uptime
- `!servers` — lists every server the bot is in
- `!announce Hello everyone!` — sends that message to every server's system channel
- `!setactivity playing chess` — changes what the bot shows as its status
- `!prefix >` — changes the command prefix from `!` to `>`
- `!shutdown` — turns the bot off (it won't come back on until you restart it with `vmanage vprod --start`)
- `!load my_cogs.greet` — turns on an extra cog (plugin)
- `!reload my_cogs.greet` — reloads a cog to pick up code changes without restarting
- `!unload my_cogs.greet` — turns off a cog

---

### 3. Configuration — where your settings live

**`/var/lib/vprod/config.json`** — bot settings (prefix, name, etc.):

```json
{
  "name": "vprod",
  "service_name": "vprod",
  "prefix": "!",
  "owner_ids": [],
  "description": "vprod — Vantage Discord Bot"
}
```

**`/opt/vprod/.env`** — your bot token (never share this file, permissions: `600`):

```
DISCORD_TOKEN=your-secret-token-here
```

The token is stored separately in `.env` and never written to `config.json`. Lock it down:
```bash
sudo chmod 600 /opt/vprod/vprod/.env
sudo chown vprodbot:vprodbot /opt/vprod/vprod/.env
```

To update your token, edit `/opt/vprod/vprod/.env` directly and restart the bot.

---

## Managing your team (group peers)

### Discord Team — who can run owner commands in Discord

Owner-level Discord commands (`!vmanage`, `!shutdown`, `!stats`, etc.) are available to every **accepted member** of your Discord application team. The bot checks this automatically at startup.

To invite someone to the team:
1. Go to [https://discord.com/developers/teams](https://discord.com/developers/teams)
2. Open your team and click **Invite Member**
3. Enter their Discord username — they must accept the invite in their Discord notifications

To remove someone: go to the team page, click the three-dot menu next to their name and select **Remove**, then restart the bot.

### vprodadmins — who can manage the bot on the server

The `vprodadmins` Linux group controls who can read/edit bot files and run `vmanage` on the server.

```bash
# Add a developer (they must log out and back in after)
sudo usermod -aG vprodadmins <linux_username>

# See who is in the group
getent group vprodadmins

# Remove a developer
sudo gpasswd -d <linux_username> vprodadmins
```

---

## Day-to-day management

### Bot crashed or acting weird?
```bash
vmanage vprod --restart
vmanage vprod --logs       # see what went wrong
```

### Update the bot to the latest version?
```bash
vmanage vprod --update
```
This pulls the latest code from GitHub, upgrades packages, and restarts automatically.

### Bot not responding in Discord?

Check if it's running:
```bash
vmanage vprod
```

If it says "stopped", start it:
```bash
vmanage vprod --start
```

If it starts but immediately stops, read the logs:
```bash
vmanage vprod --logs --lines 50
```

Common causes:
- **Invalid token** — your token expired or was reset. Go to discord.com/developers, regenerate it, update `/opt/vprod/vprod/.env`, and restart the bot.
- **Missing intents** — go to the developer portal, find your bot, enable "Message Content Intent" and "Server Members Intent"
- **Python error** — check the logs for a traceback

---

## Adding extra features (cogs)

Cogs are plugins that add commands and features to your bot.

### Adding a cog from GitHub

```bash
# From your bot's install directory
cd /opt/vprod/vprod

# Add the repo (replace with actual URL)
sudo -u vprodbot ./venv/bin/python launcher.py repos add https://github.com/someone/cool-cogs

# Install a specific cog from that repo
sudo -u vprodbot ./venv/bin/python launcher.py cogs install cool_cogs some_feature

# Make it load automatically when the bot starts
sudo -u vprodbot ./venv/bin/python launcher.py cogs autoload cool_cogs.some_feature

# Load it right now without restarting (type this in Discord):
!load cool_cogs.some_feature
```

### Seeing what cogs are loaded
```bash
vmanage vprod --cogs      # from terminal
!cogs                     # from Discord
```

---

## Where things live on the server

| What | Where |
|------|-------|
| Bot code | `/opt/vprod/vprod/` |
| Bot token | `/opt/vprod/vprod/.env` |
| Config (prefix, name, etc.) | `/var/lib/vprod/vprod/config.json` |
| Cog registry | `/var/lib/vprod/vprod/cog_data.json` |
| Downloaded cog repos | `/var/lib/vprod/vprod/repos/` |
| Per-server data | `/var/lib/vprod/vprod/guilds/` |
| Log viewer | `vmanage vprod --logs` or `journalctl -u vprod@vprod` |
| Python install | `/opt/vprod/vprod/venv/` |

---

## Quick troubleshooting checklist

| Symptom | First thing to try |
|---------|--------------------|
| Bot offline | `vmanage vprod --start` |
| Bot starts then crashes | `vmanage vprod --logs --lines 50` |
| Commands not working | Check prefix with `!ping` or `@vprod ping` |
| "Not owner" error | Check Discord application team membership |
| Token invalid | Update DISCORD_TOKEN in `/opt/vprod/vprod/.env` and restart |
| Want new features | `vmanage vprod --update` |
