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
5. **Reset Token** → copy it — you'll need it during the install

---

## 2. Set Up a Discord Team (optional — for shared owner permissions)

If you want collaborators to have owner-level bot access without hardcoding their Discord IDs:

1. [discord.com/developers/teams](https://discord.com/developers/teams) → **New Team**
2. Your application → **General Information** → **App Team** → select your team
3. **Invite Member** → enter each collaborator's username
4. They must **accept** the invite for owner access to activate

The bot automatically fetches all accepted team members on startup and treats them as owners — no config file edits needed.

---

## 3. Install on Your Server

SSH into your server, then run the one-line installer:

```bash
sudo bash <(curl -fsSL https://raw.githubusercontent.com/BigPattyOG/VantageOverlook/main/scripts/install-vprod.sh)
```

The script will:

1. Install system packages (`git`, `python3`, `python3-venv`, etc.)
2. Create a dedicated system user (`vprodbot`) and admin group (`vprodadmins`)
3. Clone the repository to `/opt/vprod/`
4. Set all file permissions correctly
5. Create a Python virtual environment and install requirements
6. **Prompt you for your Discord token** → write it to `/var/lib/vprod/.env` (chmod 600, readable only by `vprodbot`)
7. Write a default `config.json` to `/var/lib/vprod/`
8. Install and start the `vprod` systemd service

> **Your token never touches GitHub.** It goes straight from your clipboard into the server's `.env` file. The git checkout at `/opt/vprod/` and the data directory at `/var/lib/vprod/` are completely separate — `git pull` can never overwrite your token.

### Re-running after a token reset

If Discord invalidates your token, the quickest fix is:

```bash
vmanage --update-token
```

This prompts for the new token (hidden input), validates it, writes it to `/var/lib/vprod/.env`, and restarts the bot automatically. No need to re-run the full installer.

Alternatively, re-run the full installer (updates code too):

```bash
sudo bash /opt/vprod/scripts/install-vprod.sh
```

Or pass the new token directly without a prompt:

```bash
sudo DISCORD_TOKEN=your_new_token_here bash /opt/vprod/scripts/install-vprod.sh
```

### Installer options

All options can be set as environment variables before the script:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DISCORD_TOKEN` | *(prompt)* | Skip the interactive token prompt |
| `APP_DIR` | `/opt/vprod` | Where the code lives |
| `DATA_DIR` | `/var/lib/vprod` | Where the token + config live |
| `BOT_USER` | `vprodbot` | System user that runs the bot |
| `ADMIN_GROUP` | `vprodadmins` | Group with read access to data dir |
| `SERVICE_NAME` | `vprod` | Systemd service name |
| `PREFIX` | `!` | Default command prefix |
| `FORCE_RECLONE` | `0` | Set to `1` to wipe `/opt/vprod` and re-clone |
| `SKIP_START` | `0` | Set to `1` to install without starting |

---

## 4. Local Development

No server or sudo needed:

```bash
git clone https://github.com/BigPattyOG/VantageOverlook.git vprod
cd vprod
bash scripts/install-vdev.sh
```

The dev installer:
1. Creates a virtualenv in `./venv/`
2. Installs requirements
3. Creates `./data/` with the right layout
4. Prompts for your token → stores it in `./data/.env` (gitignored, chmod 600)
5. Writes a dev `config.json`

Start the bot:
```bash
venv/bin/python launcher.py start
# Or with debug logging:
venv/bin/python launcher.py --debug start
```

---

## 5. Add the Bot to Your Server

Use `!invite` in Discord (owner only) to get a link with Administrator permission.

Or build one manually:
1. Discord Developer Portal → your app → **OAuth2 → URL Generator**
2. Scopes: `bot`, `applications.commands`
3. Bot Permissions: **Administrator**
4. Copy the URL, open in browser, select your server

---

## 6. File Layout

| Path | Purpose |
|------|---------|
| `/opt/vprod/` | Git clone — code, venv (updated by `vmanage --update`) |
| `/var/lib/vprod/.env` | Discord token — `600`, `vprodbot` only |
| `/var/lib/vprod/config.json` | Bot configuration — `660` |
| `/var/lib/vprod/ext_plugins/` | Your private plugins |
| `/var/lib/vprod/logs/vprod.log` | Rotating log (10 MB × 7 files) |
| `/var/lib/vprod/repos/` | Community plugin repos |

---

## 7. Managing the Service

```bash
# Quick control via vmanage
vmanage               # status dashboard
vmanage --restart     # restart the bot
vmanage --logs        # stream live logs
vmanage --update      # git pull + pip install + restart (never touches .env)

# Or directly with systemctl
sudo systemctl status  vprod
sudo systemctl restart vprod
sudo journalctl -u vprod -f
```

---

## 8. Adding External (Private) Plugins

Clone your private plugin repo into the data directory, then register it:

```bash
cd /var/lib/vprod/ext_plugins
git clone git@github.com:yourname/my-plugins.git my_features
```

Then in Discord (owner only):
```
!plugin install /var/lib/vprod/ext_plugins/my_features/welcome
!load _vp_ext.welcome
```

See [PLUGINS.md](PLUGINS.md) for the full plugin authoring guide.

---

## 9. Health Check

Configure external status monitors (UptimeRobot, BetterStack, Freshping):

| URL | Response |
|-----|---------|
| `http://server:8080/ping` | Plain `OK` — for simple TCP/HTTP monitors |
| `http://server:8080/health` | Full JSON — for detailed monitors |

HTTP 200 when healthy, 503 when starting or in maintenance mode.

Configure in `/var/lib/vprod/config.json`:
```json
"health_port": 8080,
"health_host": "0.0.0.0"
```

---

## 10. Keeping the Bot Updated

```bash
# Update code without touching token or config:
vmanage --update

# Or manually:
sudo -u vprodbot git -C /opt/vprod pull --ff-only
sudo -u vprodbot /opt/vprod/venv/bin/pip install -r /opt/vprod/requirements.txt
sudo systemctl restart vprod
```

To update private plugins:
```bash
cd /var/lib/vprod/ext_plugins/my_features
git pull
# Then in Discord:
!plugin reload my_feature
```

---

## Appendix: Automated CI/CD with GitHub Actions (optional)

If you want code pushes to automatically deploy to your server without you SSHing in manually, the repo includes GitHub Actions workflow files. This requires giving GitHub an SSH key to reach your server.

**This is completely optional.** The curl install approach above is recommended for most people.

See the workflows in `.github/workflows/` and [TOKEN_MANAGEMENT.md](TOKEN_MANAGEMENT.md#automated-deploys-github-actions-optional) if you want to set this up.
