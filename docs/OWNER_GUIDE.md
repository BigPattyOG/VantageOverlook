# Owner Guide

This guide covers everything you need to run the bot day-to-day. No jargon.

Owner commands are restricted to **Discord Team members**. Add someone to your Team at [discord.com/developers/teams](https://discord.com/developers/teams) and they automatically get access on next bot start.

---

## Terminal Commands (on the server)

```bash
vmanage               # status dashboard
vmanage --restart     # restart the bot
vmanage --stop        # stop the bot
vmanage --start       # start the bot
vmanage --logs        # stream live logs  (Ctrl+C to stop)
vmanage --logs --lines 50   # last 50 lines without streaming
vmanage --update      # git pull + pip install + restart
vmanage --plugins     # list installed plugins
vmanage --repos       # list plugin repos
```

---

## Discord Commands

Use your configured prefix (default `!`). Replace `[prefix]` below.

### Public — anyone can run these

| Command | What it does |
|---------|-------------|
| `!ping` | Check if the bot is alive and its latency |
| `!botinfo` | Bot name, prefix, guild count |
| `!help` | Browse all commands with navigation buttons |
| `!version` | Current version, git branch, commit |

### Owner only

**Bot management**

| Command | What it does |
|---------|-------------|
| `!vmanage` | Management panel with Restart / Stop / Update / Logs buttons |
| `!stats` | Guilds, users, latency, uptime, memory |
| `!shutdown` | Graceful shutdown (systemd will restart it automatically) |
| `!invite` | Generate an invite URL with Administrator permission |
| `!maintenance on` | Block non-owner commands with a maintenance notice |
| `!maintenance off` | Bring the bot back online |

**Extensions**

| Command | What it does |
|---------|-------------|
| `!plugins` | List all loaded extensions |
| `!load <ext>` | Load an extension |
| `!unload <ext>` | Unload an extension |
| `!reload <ext>` | Reload (picks up code changes without restart) |

**Server management**

| Command | What it does |
|---------|-------------|
| `!servers` | Paginated list of all guilds |
| `!announce <message>` | Broadcast embed to all guild system channels |
| `!prefix [new]` | Show or change the command prefix |
| `!setactivity <type> <text>` | Change bot presence (playing/watching/listening/competing) |

**External plugin management**

| Command | What it does |
|---------|-------------|
| `!plugin list` | All registered external plugins + status |
| `!plugin install <path>` | Register a new local plugin |
| `!plugin reload <name>` | Hot-reload after a code change |
| `!plugin verify` | Check integrity hashes |
| `!plugin enable/disable <name>` | Toggle without removing |
| `!plugin remove <name>` | Unregister (files untouched) |

---

## Maintenance Mode

When maintenance is on, everyone except owners gets a branded notice instead of command responses. You can still use all commands normally.

```
!maintenance on
!maintenance off
!maintenance       ← shows current state
```

---

## Adding the Bot to a New Server

```
!invite
```

This generates an invite URL with Administrator permission. Only share it with people you trust.

---

## Updating the Bot

```bash
# Easiest way
vmanage --update

# Updates private plugins separately (no restart needed)
cd /var/lib/vprod/ext_plugins/my_features && git pull
# Then in Discord:
# !plugin reload my_feature
```

---

## Viewing Logs

```bash
# Live stream
vmanage --logs
sudo journalctl -u vprod -f

# Last 100 lines
sudo journalctl -u vprod -n 100

# Rotating file log
tail -f /var/lib/vprod/logs/vprod.log
```

---

## Adding Another Owner

Two ways:

1. **Discord Team** (recommended) — add them at [discord.com/developers/teams](https://discord.com/developers/teams). They need to accept the invite. Restart the bot for it to take effect.

2. **config.json** — add their Discord user ID to `owner_ids`:
   ```json
   "owner_ids": [123456789012345678]
   ```
   Then `!reload plugins.admin` or restart.

---

## Health Check for Status Pages

The bot exposes a health endpoint for monitoring services (UptimeRobot, BetterStack, Freshping, etc.):

- Simple check: `http://your-server:8080/ping` → `OK`
- Full status: `http://your-server:8080/health` → JSON

Returns HTTP 200 when healthy, 503 when starting or in maintenance.
