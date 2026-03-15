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

> **Create two applications** — one for production (`vprod`), one for development (`vdev`).  
> Each gets its own token. They are completely independent. If one token resets, the other keeps running.

---

## 2. Set Up a Discord Team (owner permissions)

The bot automatically treats all accepted team members as owners — no hardcoded IDs needed.

1. [discord.com/developers/teams](https://discord.com/developers/teams) → **New Team**
2. Your application → **General Information** → **App Team** → select your team
3. **Invite Member** → enter each collaborator's username
4. They must **accept** the invite for owner access to activate

---

## 3a. Automated Deploy via GitHub Actions (recommended)

This is the cleanest approach. The token lives in GitHub Secrets and is deployed to your server automatically on every push to `main` — you never handle it directly.

### Step 1 — Add GitHub Secrets

Go to: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Value |
|--------|-------|
| `DISCORD_TOKEN` | Production bot token |
| `SSH_HOST` | Server IP or hostname |
| `SSH_USER` | Linux user with sudo access |
| `SSH_KEY` | Private SSH key (see below) |
| `SSH_PORT` | *(optional)* — omit for port 22 |

For dev, add the same set with `_DEV` suffix: `DISCORD_TOKEN_DEV`, `SSH_HOST_DEV`, etc.

**Generate the SSH key** (run this on your local machine, not the server):
```bash
ssh-keygen -t ed25519 -C "vprod-deploy" -f ~/.ssh/vprod_deploy
# Add the .pub file to your server:
ssh-copy-id -i ~/.ssh/vprod_deploy.pub your-user@your.server.ip
# Paste the private key (no .pub) into the SSH_KEY GitHub Secret
```

### Step 2 — First deploy

Push to `main` — the workflow runs automatically.  
Or: **Actions → Deploy — Production → Run workflow**

The workflow:
1. SSHes into your server
2. Clones the repo to `/opt/vprod/` (or updates it)
3. Creates the system user, venv, data directory
4. Writes the token to `/var/lib/vprod/.env` (chmod 600 — only the bot user can read it)
5. Installs and starts the systemd service

See [TOKEN_MANAGEMENT.md](TOKEN_MANAGEMENT.md) for the full explanation of how this works.

### Rotating the token

1. Reset token on Discord Developer Portal
2. Update the `DISCORD_TOKEN` GitHub Secret
3. **Actions → Deploy — Production → Run workflow** (manual trigger)

---

## 3b. Manual Install (no CI/CD)

If you prefer to set up manually:

```bash
# SSH into your server
ssh ubuntu@your.server.ip

# Run the production installer
sudo bash <(curl -fsSL https://raw.githubusercontent.com/BigPattyOG/VantageOverlook/main/scripts/install-vprod.sh)
```

Or clone first then run:
```bash
sudo git clone https://github.com/BigPattyOG/VantageOverlook.git /opt/vprod
sudo bash /opt/vprod/scripts/install-vprod.sh
```

The script will prompt you for the token and store it in `/var/lib/vprod/.env`.

To pass the token non-interactively:
```bash
sudo DISCORD_TOKEN=your_token_here bash /opt/vprod/scripts/install-vprod.sh
```

---

## 3c. Local Development

```bash
# Clone the repo
git clone https://github.com/BigPattyOG/VantageOverlook.git vprod
cd vprod

# Run the dev installer (no sudo needed)
bash scripts/install-vdev.sh

# Start the bot
venv/bin/python launcher.py start
```

Token is stored in `./data/.env` (gitignored). No server, no systemd.

---

## 4. Add the Bot to Your Server

Use `!invite` in Discord (owner only) to generate an invite link with Administrator permission.

Or build it manually:
1. Discord Developer Portal → your app → **OAuth2 → URL Generator**
2. Scopes: `bot`, `applications.commands`
3. Bot Permissions: **Administrator**
4. Copy the URL, open in browser, select your server

---

## 5. File Layout

| Path | Purpose |
|------|---------|
| `/opt/vprod/` | Git clone — code, venv |
| `/var/lib/vprod/.env` | Discord token — `600`, `vprodbot` only |
| `/var/lib/vprod/config.json` | Bot configuration — `660` |
| `/var/lib/vprod/ext_plugins/` | Your private plugins |
| `/var/lib/vprod/logs/vprod.log` | Rotating log (10 MB × 7) |
| `/var/lib/vprod/repos/` | Community plugin repos |

---

## 6. Managing the Service

```bash
vmanage               # status dashboard
vmanage --restart     # restart
vmanage --logs        # stream live logs
vmanage --update      # git pull + pip install + restart (safe — never touches .env)
```

---

## 7. Adding External (Private) Plugins

Clone your private plugin repo into the data directory, then register it:

```bash
cd /var/lib/vprod/ext_plugins
git clone git@github.com:BigPattyOG/my-private-plugins.git my_features
```

Then in Discord (owner only):
```
!plugin install /var/lib/vprod/ext_plugins/my_features/welcome
!load _vp_ext.welcome
```

See [PLUGINS.md](PLUGINS.md) for full plugin authoring guide.

---

## 8. Health Check

Third-party status checkers (UptimeRobot, BetterStack, Freshping):

| URL | Use |
|-----|-----|
| `http://server:8080/ping` | Simple TCP/HTTP check — returns plain `OK` |
| `http://server:8080/health` | Full JSON status |

Returns HTTP 200 when healthy, 503 when starting or in maintenance.

---

## 9. Keeping the Bot Updated

```bash
# Via GitHub Actions (recommended) — just push to main
# Via CLI:
vmanage --update

# To update private plugins without restarting:
cd /var/lib/vprod/ext_plugins/my_features && git pull
# Then in Discord:
!plugin reload my_feature
```
