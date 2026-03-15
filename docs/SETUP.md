# Setup Guide

Full walkthrough from Discord portal to running bot.

---

## 1. Create the Discord Application

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. **New Application** → name it → **Create**
3. Left sidebar → **Bot**
4. Enable both **Privileged Gateway Intents**:
   - Server Members Intent
   - Message Content Intent
5. **Reset Token** → copy it — you need this shortly

---

## 2. Set Up a Discord Team (for owner permissions)

The bot automatically treats all accepted team members as owners — no hardcoded IDs needed.

1. Go to [discord.com/developers/teams](https://discord.com/developers/teams) → **New Team**
2. Open your application → **General Information** → **App Team** → select your team
3. **Invite Member** → enter each collaborator's Discord username
4. They must accept the invite for owner access to activate

---

## 3. Server Setup

### 3a. Install (production)

```bash
# Run on the server as root or with sudo
sudo bash scripts/install-vprod.sh
```

The script handles everything: packages, system user, venv, permissions, token storage, config, service.

Your token is stored in `/var/lib/vprod/.env` — **outside the git directory** — so `git pull` can never wipe it.

### 3b. Development (local machine)

```bash
bash scripts/install-vdev.sh
venv/bin/python launcher.py start
```

Token goes to `data/.env` which is gitignored.

---

## 4. Add the Bot to Your Server

Use the `!invite` command (owner only) to generate an invite URL with Administrator permission, or build one manually:

1. Discord Developer Portal → your app → **OAuth2 → URL Generator**
2. Scopes: `bot`, `applications.commands`
3. Bot Permissions: **Administrator**
4. Copy the URL, open it in browser, select your server

---

## 5. File Layout

| Path | Purpose |
|------|---------|
| `/opt/vprod/` | Git clone (code, venv) |
| `/var/lib/vprod/.env` | Discord token — 600, bot user only |
| `/var/lib/vprod/config.json` | Bot config — 660 |
| `/var/lib/vprod/ext_plugins/` | Your custom plugins (from your private repo) |
| `/var/lib/vprod/logs/vprod.log` | Rotating log file |
| `/var/lib/vprod/repos/` | Community plugin repos |

---

## 6. Managing the Service

```bash
# Quick control via vmanage
vmanage               # status dashboard
vmanage --restart     # restart service
vmanage --logs        # stream live logs
vmanage --update      # git pull + pip install + restart

# Or directly with systemctl
sudo systemctl start   vprod
sudo systemctl stop    vprod
sudo systemctl restart vprod
sudo journalctl -u vprod -f
```

---

## 7. Adding External (Private) Plugins

Your custom plugins live in `/var/lib/vprod/ext_plugins/`.  
Clone your plugin repo there, then register via Discord:

```
!plugin install /var/lib/vprod/ext_plugins/my_feature
!load _vp_ext.my_feature
```

See [PLUGINS.md](PLUGINS.md) for the full plugin guide.

---

## 8. Health Check

The bot exposes an HTTP health endpoint for third-party status checkers:

| URL | Response |
|-----|---------|
| `/ping` | Plain `OK` — for simple TCP/HTTP monitors |
| `/health` | JSON with full status — for detailed monitors |

Configure in `config.json`:
```json
"health_port": 8080,
"health_host": "0.0.0.0"
```

JSON response fields:
```json
{
  "status": "ok",
  "version": "1.0.0",
  "bot": "vprod",
  "uptime_seconds": 3600,
  "guilds": 5,
  "latency_ms": 38,
  "extensions_loaded": 4,
  "ext_plugins_loaded": 2,
  "ext_plugins_failed": 0,
  "maintenance": false
}
```

`status` is `"ok"` (200), `"starting"` (503), or `"maintenance"` (503).

---

## 9. Keeping the Bot Updated

```bash
# Code update (does not touch token or config)
vmanage --update

# Or manually
sudo -u vprodbot git -C /opt/vprod pull --ff-only
sudo -u vprodbot /opt/vprod/venv/bin/pip install -r /opt/vprod/requirements.txt
sudo systemctl restart vprod
```

To update your private plugins:
```bash
cd /var/lib/vprod/ext_plugins/my_feature
git pull
# Then in Discord:
# !plugin reload my_feature
```
