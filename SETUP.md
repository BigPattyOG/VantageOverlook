# vprod — Complete Setup Guide

This guide walks through everything needed to get vprod running on an Ubuntu server, from creating the Discord application to adding your dev team to the `vprodadmins` group.

---

## Table of Contents

1. [What you need before you start](#1-what-you-need-before-you-start)
2. [Create the Discord application and bot](#2-create-the-discord-application-and-bot)
3. [Set up a Discord Team and add peers](#3-set-up-a-discord-team-and-add-peers)
4. [Prepare the server](#4-prepare-the-server)
5. [Create the system user and dev group](#5-create-the-system-user-and-dev-group)
6. [Clone the repository](#6-clone-the-repository)
7. [Set up the Python environment](#7-set-up-the-python-environment)
8. [Configure the bot](#8-configure-the-bot)
9. [Install and start the systemd service](#9-install-and-start-the-systemd-service)
10. [Install vmanage system-wide](#10-install-vmanage-system-wide)
11. [Add the bot to your Discord server](#11-add-the-bot-to-your-discord-server)
12. [Test that everything works](#12-test-that-everything-works)
13. [Managing the vprodadmins group](#13-managing-the-vprodadmins-group)
14. [What each directory is for](#14-what-each-directory-is-for)
15. [Keeping the bot up to date](#15-keeping-the-bot-up-to-date)

---

## 1. What you need before you start

- An Ubuntu 22.04+ server (AWS EC2, DigitalOcean, etc.) with a public IP or DNS name
- SSH access to that server with `sudo` privileges
- A Discord account

---

## 2. Create the Discord application and bot

### 2a. Create the application

1. Go to [https://discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application** in the top right
3. Name it `vprod` (or whatever you like) and click **Create**

### 2b. Add a bot user

1. On the left sidebar, click **Bot**
2. Click **Add Bot** then **Yes, do it!**
3. Under the bot's username, click **Reset Token** then copy the token — save it somewhere safe, you will need it shortly
4. Enable the following **Privileged Gateway Intents**:
   - **Server Members Intent** — lets the bot see who is in each server
   - **Message Content Intent** — lets the bot read message content for prefix commands

### 2c. Note the Application ID

1. On the left sidebar, click **General Information**
2. Copy the **Application ID** — you will use this when creating the invite link

---

## 3. Set up a Discord Team and add peers

This is how owner permissions work. When vprod starts, it fetches the **accepted members of your Discord Team** and treats all of them as bot owners automatically. No need to hardcode user IDs.

### 3a. Create a team

1. Go to [https://discord.com/developers/teams](https://discord.com/developers/teams)
2. Click **New Team**
3. Give the team a name (e.g. `vprod-devs`) and click **Create**

### 3b. Transfer the application to the team

1. Go back to [https://discord.com/developers/applications](https://discord.com/developers/applications)
2. Open the `vprod` application
3. On the left sidebar, click **General Information**
4. Scroll down to **App Team** and select the team you just created
5. Click **Save Changes**

### 3c. Invite peers to the team

1. Go to [https://discord.com/developers/teams](https://discord.com/developers/teams)
2. Open your team
3. Click **Invite Member**
4. Enter the Discord username of the person you want to add (e.g. `alice#0001`)
5. They will receive a notification in Discord — they must **accept** the invite for owner permissions to activate
6. Repeat for each peer developer

> Each accepted team member gets full owner-level access to bot commands (`!vmanage`, `!shutdown`, etc.). They do not need any special role in Discord itself.

---

## 4. Prepare the server

SSH into your server and run the following as a user with `sudo` access.

### 4a. Update the system

```bash
sudo apt update && sudo apt upgrade -y
```

### 4b. Install system dependencies

```bash
sudo apt install -y git python3 python3-pip python3-venv build-essential
```

### 4c. Verify Python 3.11+

```bash
python3 --version
```

If the version shown is below 3.11, install a newer version:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.12 python3.12-venv
```

Then replace `python3` with `python3.12` in subsequent commands.

---

## 5. Create the system user and dev group

The bot runs under a dedicated system account (`vprodbot`) so it has its own isolated permissions. Developers who need to manage the bot are added to the `vprodadmins` group.

### 5a. Clone the repository first

The launcher needs to be present to create the user:

```bash
sudo mkdir -p /opt/vprod
sudo git clone https://github.com/BigPattyOG/VantageOverlook.git /opt/vprod/vprod
```

> The bot code lives at `/opt/vprod/vprod/` — this is the **instance directory**. The outer `/opt/vprod/` is the base that can hold multiple bot instances.

### 5b. Create the system user and dev group

```bash
sudo python3 /opt/vprod/vprod/launcher.py system create-user
```

This single command creates both:
- `vprodbot` — the system account that runs the bot (no password, no login shell by default)
- `vprodadmins` — the developer group

### 5c. Set ownership of the code directory

```bash
sudo chown -R vprodbot:vprodadmins /opt/vprod/vprod
sudo chmod -R 750 /opt/vprod/vprod
```

### 5d. Add yourself (and other developers) to the dev group

```bash
sudo usermod -aG vprodadmins YOUR_LINUX_USERNAME
```

Replace `YOUR_LINUX_USERNAME` with your actual Linux username. Repeat for each developer:

```bash
sudo usermod -aG vprodadmins alice
sudo usermod -aG vprodadmins bob
```

**Log out and back in** (or run `newgrp vprodadmins`) for the group membership to take effect in your current session.

Group members can now:
- Read and edit files in `/opt/vprod/vprod/` and `/var/lib/vprod/vprod/`
- Run `vmanage` to manage the bot

---

## 6. Clone the repository

The repository was already cloned in step 5a. If you skipped ahead or need to re-clone:

```bash
sudo rm -rf /opt/vprod/vprod
sudo git clone https://github.com/BigPattyOG/VantageOverlook.git /opt/vprod/vprod
sudo chown -R vprodbot:vprodadmins /opt/vprod/vprod
sudo chmod -R 750 /opt/vprod/vprod
```

---

## 7. Set up the Python environment

Create a virtual environment inside the bot's code directory and install dependencies:

```bash
sudo -u vprodbot bash -c "
    cd /opt/vprod/vprod
    python3 -m venv venv
    venv/bin/pip install --upgrade pip
    venv/bin/pip install -r requirements.txt
"
```

Verify the install:

```bash
sudo -u vprodbot /opt/vprod/vprod/venv/bin/python -c "import discord; print('discord.py', discord.__version__)"
```

---

## 8. Configure the bot

### 8a. Create the .env file (bot token)

```bash
sudo -u vprodbot cp /opt/vprod/vprod/.env.example /opt/vprod/vprod/.env
```

Open the file and fill in your token:

```bash
sudo -u vprodbot nano /opt/vprod/vprod/.env
```

The file should look like this (replace the placeholder with your actual token from step 2b):

```
DISCORD_TOKEN=MTI3NTQxMzk2N...your_full_token_here
```

Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X` in nano). Then lock down the file:

```bash
sudo chmod 600 /opt/vprod/vprod/.env
sudo chown vprodbot:vprodbot /opt/vprod/vprod/.env
```

### 8b. Create the data directory

```bash
sudo mkdir -p /var/lib/vprod/vprod
sudo chown -R vprodbot:vprodadmins /var/lib/vprod/vprod
sudo chmod 750 /var/lib/vprod/vprod
```

### 8c. Create config.json

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

> `owner_ids` can be left empty. Owners are resolved automatically from your Discord Team (step 3). You can add extra Discord user IDs here if you want to grant owner access to someone outside the team.

---

## 9. Install and start the systemd service

### 9a. Install the service

```bash
sudo python3 /opt/vprod/vprod/launcher.py system install-service
```

This copies `vprod@.service` to `/etc/systemd/system/` and enables the `vprod@vprod` instance.

### 9b. Start the bot

```bash
sudo systemctl start vprod@vprod
```

### 9c. Check that it started correctly

```bash
sudo systemctl status vprod@vprod
```

You should see `active (running)`. If not, check the logs:

```bash
sudo journalctl -u vprod@vprod -n 50
```

### 9d. Enable autostart on boot

```bash
sudo systemctl enable vprod@vprod
```

This is done automatically by `install-service`, but double-check with:

```bash
sudo systemctl is-enabled vprod@vprod
# should print: enabled
```

### 9e. Optional — sudoers entry for the Discord management panel

The `!vmanage` Discord panel sends `sudo systemctl` commands on the server. Add this so it works without a password prompt:

```bash
sudo tee /etc/sudoers.d/vprod > /dev/null << 'EOF'
vprodbot ALL=(ALL) NOPASSWD: /bin/systemctl restart vprod@vprod, \
    /bin/systemctl stop vprod@vprod, \
    /bin/systemctl start vprod@vprod
EOF
sudo chmod 440 /etc/sudoers.d/vprod
```

---

## 10. Install vmanage system-wide

`vmanage` is the CLI tool for managing the bot. Install it so any user (including `vprodadmins` members) can run it without a venv:

```bash
sudo ln -sf /opt/vprod/vprod/vmanage.py /usr/local/bin/vmanage
sudo chmod +x /usr/local/bin/vmanage
```

Test it:

```bash
vmanage
```

You should see the vprod banner and a list of installed bots.

---

## 11. Add the bot to your Discord server

### 11a. Build the invite URL

Go to [https://discord.com/developers/applications](https://discord.com/developers/applications), open the `vprod` application, then click **OAuth2 → URL Generator** in the left sidebar.

Select the following **Scopes**:
- `bot`
- `applications.commands`

Select the following **Bot Permissions**:
- `Send Messages`
- `Embed Links`
- `Read Message History`
- `View Channels`
- `Use External Emojis`
- Any additional permissions your cogs will need

Copy the generated URL at the bottom and open it in your browser.

### 11b. Authorise the bot

Select the Discord server you want to add the bot to and click **Authorise**.

### 11c. Verify it joined

Go to your Discord server. The bot should appear in the member list. Type `!ping` — if it responds with a latency embed, everything is working.

---

## 12. Test that everything works

Run through these checks after setup:

```bash
# 1. Check overall system status
sudo python3 /opt/vprod/vprod/launcher.py system status

# 2. View the status dashboard
vmanage vprod

# 3. Tail the logs
vmanage vprod --logs
```

In Discord:
- `!ping` — should respond with API latency
- `!botinfo` — should show bot name, prefix, and guild count
- `!help` — should open the paginated help embed with navigation buttons

If you are an accepted member of the Discord Team linked to the application:
- `!stats` — should show detailed statistics
- `!vmanage` — should open the management panel with Restart/Stop/Update/Logs buttons

---

## 13. Managing the vprodadmins group

The `vprodadmins` Linux group lets your developers manage files and use `vmanage` without needing `sudo` for every action.

### Add a developer

```bash
sudo usermod -aG vprodadmins <linux_username>
```

The developer must log out and back in (or run `newgrp vprodadmins`) for the change to take effect.

### Check who is in the group

```bash
getent group vprodadmins
```

Output example:

```
vprodadmins:x:999:alice,bob,charlie
```

### Remove a developer

```bash
sudo gpasswd -d <linux_username> vprodadmins
```

### What group members can do

| Action | Requires group? | Requires sudo? |
|--------|----------------|----------------|
| Read bot logs (`vmanage vprod --logs`) | No | No |
| Start / stop / restart via `vmanage` | No (uses sudo internally) | For `vmanage` actions |
| Edit config.json | Yes (group member) | No |
| Edit .env (token) | No (owned by vprodbot) | Yes |
| Deploy code changes (`git pull`) | Yes (group member) | No |
| Add cogs / repos | Yes (group member) | No |

> **Bot owner vs group member:** Linux group membership controls server-level access to files and the `vmanage` tool. Discord ownership (via the Team) controls which users can run owner-only bot commands like `!vmanage`, `!shutdown`, `!stats`. These are independent.

### Discord Team vs Linux group — summary

| What it controls | How to manage |
|-----------------|--------------|
| Who can run `!vmanage`, `!shutdown`, etc. in Discord | Discord Team at discord.com/developers/teams |
| Who can read/edit bot files and use `vmanage` on the server | `vprodadmins` Linux group via `usermod` |

---

## 14. What each directory is for

```
/opt/vprod/                    Base directory for all bot instances
  vprod/                       This bot's code (git clone lives here)
    launcher.py                Bot-scoped CLI
    vmanage.py                 System-wide management CLI
    vprod@.service             systemd service template
    .env                       Bot token — chmod 600, never committed
    venv/                      Python virtual environment
    core/                      Framework core (bot.py, config.py, etc.)
    cogs/                      Built-in cogs (admin.py)

/var/lib/vprod/                Mutable data directory (separate from code)
  vprod/                       Data for this bot instance
    config.json                Bot configuration (prefix, name, etc.)
    cog_data.json              Cog registry (autoload list, repos)
    repos/                     Cloned cog repositories
    guilds/                    Per-server JSON data files

/etc/systemd/system/
  vprod@.service               systemd template unit

/usr/local/bin/
  vmanage                      Symlink to /opt/vprod/vprod/vmanage.py
```

---

## 15. Keeping the bot up to date

### Update via vmanage (recommended)

```bash
vmanage vprod --update
```

This runs `git pull`, upgrades pip packages, and restarts the bot automatically.

### Update manually

```bash
cd /opt/vprod/vprod

# Pull the latest code
sudo -u vprodbot git pull --ff-only

# Upgrade dependencies
sudo -u vprodbot venv/bin/pip install --upgrade pip
sudo -u vprodbot venv/bin/pip install -r requirements.txt

# Restart the service
sudo systemctl restart vprod@vprod
```

### Re-deploy from scratch (keeping your data)

Your config and guild data live in `/var/lib/vprod/vprod/` which is separate from the code. You can safely delete and re-clone the code directory without losing any bot state:

```bash
# Stop the bot
sudo systemctl stop vprod@vprod

# Wipe the code directory only (data is safe)
sudo rm -rf /opt/vprod/vprod

# Re-clone
sudo git clone https://github.com/BigPattyOG/VantageOverlook.git /opt/vprod/vprod
sudo chown -R vprodbot:vprodadmins /opt/vprod/vprod
sudo chmod -R 750 /opt/vprod/vprod

# Re-create the .env (data dir still has your config.json)
sudo -u vprodbot cp /opt/vprod/vprod/.env.example /opt/vprod/vprod/.env
# Then edit and add your DISCORD_TOKEN again
sudo nano /opt/vprod/vprod/.env
sudo chmod 600 /opt/vprod/vprod/.env

# Rebuild the venv
sudo -u vprodbot bash -c "
    cd /opt/vprod/vprod
    python3 -m venv venv
    venv/bin/pip install --upgrade pip
    venv/bin/pip install -r requirements.txt
"

# Start the bot
sudo systemctl start vprod@vprod
```
