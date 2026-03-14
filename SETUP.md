# vprod — Complete Setup Guide

This guide walks through everything needed to get vprod running on an Ubuntu server — from creating the Discord application to locking down every file permission.

---

## Table of Contents

1. [What you need before you start](#1-what-you-need-before-you-start)
2. [Create the Discord application and bot](#2-create-the-discord-application-and-bot)
3. [Set up a Discord Team and add peers](#3-set-up-a-discord-team-and-add-peers)
4. [Prepare the server](#4-prepare-the-server)
5. [Create the system user and dev group](#5-create-the-system-user-and-dev-group)
6. [Clone the repository](#6-clone-the-repository)
7. [Server permissions — the full picture](#7-server-permissions--the-full-picture)
8. [Set up the Python environment](#8-set-up-the-python-environment)
9. [Configure the bot](#9-configure-the-bot)
10. [Install and start the systemd service](#10-install-and-start-the-systemd-service)
11. [Install vmanage system-wide](#11-install-vmanage-system-wide)
12. [Add the bot to your Discord server](#12-add-the-bot-to-your-discord-server)
13. [Test that everything works](#13-test-that-everything-works)
14. [Managing the vprodadmins group](#14-managing-the-vprodadmins-group)
15. [What each path is for](#15-what-each-path-is-for)
16. [Keeping the bot up to date](#16-keeping-the-bot-up-to-date)

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

This is how owner permissions work. When vprod starts, it fetches the **accepted members of your Discord Team** and treats all of them as bot owners automatically — no hardcoded IDs needed.

### 3a. Create a team

1. Go to [https://discord.com/developers/teams](https://discord.com/developers/teams)
2. Click **New Team**
3. Give the team a name (e.g. `vprod-devs`) and click **Create**

### 3b. Transfer the application to the team

1. Go back to [https://discord.com/developers/applications](https://discord.com/developers/applications)
2. Open the `vprod` application → **General Information**
3. Scroll down to **App Team** and select the team you just created
4. Click **Save Changes**

### 3c. Invite peers to the team

1. Go to [https://discord.com/developers/teams](https://discord.com/developers/teams)
2. Open your team and click **Invite Member**
3. Enter the Discord username of the person you want to add (e.g. `alice#0001`)
4. They will receive a notification in Discord — they must **accept** the invite for owner permissions to activate
5. Repeat for each peer developer

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

The bot runs under a dedicated system account (`vprodbot`) with its own isolated permissions. Developers who need to manage the bot are added to the `vprodadmins` group.

### 5a. Clone the repository first

The launcher needs to be present to create the user:

```bash
sudo git clone https://github.com/BigPattyOG/VantageOverlook.git /opt/vprod
```

> The bot code lives directly at `/opt/vprod/`. Data lives separately at `/var/lib/vprod/`.

### 5b. Create the system user and dev group

```bash
sudo python3 /opt/vprod/launcher.py system create-user
```

This single command creates both:
- `vprodbot` — the system account that runs the bot (no login password)
- `vprodadmins` — the developer group

### 5c. Add yourself (and other developers) to the dev group

```bash
sudo usermod -aG vprodadmins YOUR_LINUX_USERNAME
```

Repeat for each peer developer:

```bash
sudo usermod -aG vprodadmins alice
sudo usermod -aG vprodadmins bob
```

**Log out and back in** (or run `newgrp vprodadmins`) for the group membership to take effect in your current session.

---

## 6. Clone the repository

The repository was already cloned in step 5a. If you skipped ahead or need to re-clone:

```bash
sudo rm -rf /opt/vprod
sudo git clone https://github.com/BigPattyOG/VantageOverlook.git /opt/vprod
```

---

## 7. Server permissions — the full picture

This is the most important section. Getting permissions right means:
- The bot can read/write its own files
- Developers in `vprodadmins` can deploy code and read config without `sudo`
- The bot token stays private (no one but `vprodbot` can read it)
- New files created by either `vprodbot` or any group member automatically inherit the right group

### Why `2775` (setgid)?

The octal `2775` breaks down as:

| Bit | Meaning |
|-----|---------|
| `2` | **setgid** — new files/dirs created inside inherit the directory's group (`vprodadmins`) automatically |
| `7` | owner (`vprodbot`) has read + write + execute |
| `7` | group (`vprodadmins`) has read + write + execute |
| `5` | others have read + execute (no write) |

Without setgid, if `vprodbot` creates a file it gets `vprodbot:vprodbot` as owner:group. With setgid, it gets `vprodbot:vprodadmins`, so all group members can read and write it without `sudo`.

### 7a. Set up `/opt/vprod/` (code directory)

```bash
# Ownership: vprodbot owns it, vprodadmins group can read/write/execute
sudo chown -R vprodbot:vprodadmins /opt/vprod

# 2775 = setgid + rwxrwxr-x on the directory
# All subdirectories also get 2775 so new files always inherit vprodadmins
sudo find /opt/vprod -type d -exec chmod 2775 {} \;

# Files: 664 = rw-rw-r-- (owner and group can read/write, others read-only)
sudo find /opt/vprod -type f -exec chmod 664 {} \;

# Executable scripts need execute permission too
sudo chmod 775 /opt/vprod/launcher.py /opt/vprod/vmanage.py
```

### 7b. Set up `/var/lib/vprod/` (data directory)

```bash
# Create the data directory
sudo mkdir -p /var/lib/vprod

# Same ownership and setgid permissions as the code directory
sudo chown -R vprodbot:vprodadmins /var/lib/vprod
sudo find /var/lib/vprod -type d -exec chmod 2775 {} \;
sudo find /var/lib/vprod -type f -exec chmod 664 {} \;
```

### 7c. Lock down the bot token (`.env`)

The bot token is the most sensitive file. Only `vprodbot` should be able to read it — not even other group members.

```bash
# 600 = rw------- (only the owner can read or write)
sudo chown vprodbot:vprodbot /opt/vprod/.env
sudo chmod 600 /opt/vprod/.env
```

### 7d. After setup — full permission reference table

| Path | Owner | Group | Permissions | Notes |
|------|-------|-------|-------------|-------|
| `/opt/vprod/` | `vprodbot` | `vprodadmins` | `2775` | setgid — new files inherit group |
| `/opt/vprod/launcher.py` | `vprodbot` | `vprodadmins` | `775` | executable |
| `/opt/vprod/vmanage.py` | `vprodbot` | `vprodadmins` | `775` | executable |
| `/opt/vprod/.env` | `vprodbot` | `vprodbot` | `600` | token — private, no group read |
| `/opt/vprod/venv/` | `vprodbot` | `vprodadmins` | `2775` | Python virtual environment |
| `/opt/vprod/core/` | `vprodbot` | `vprodadmins` | `2775` | source code |
| `/opt/vprod/cogs/` | `vprodbot` | `vprodadmins` | `2775` | built-in cogs |
| `/var/lib/vprod/` | `vprodbot` | `vprodadmins` | `2775` | data root — setgid |
| `/var/lib/vprod/config.json` | `vprodbot` | `vprodadmins` | `660` | bot config — no world read |
| `/var/lib/vprod/cog_data.json` | `vprodbot` | `vprodadmins` | `660` | cog registry |
| `/var/lib/vprod/repos/` | `vprodbot` | `vprodadmins` | `2775` | cloned cog repos |
| `/var/lib/vprod/guilds/` | `vprodbot` | `vprodadmins` | `2775` | per-server data |

### 7e. Verify permissions

Run these to check everything looks right:

```bash
# Check the code directory
ls -la /opt/vprod/

# Check the data directory
ls -la /var/lib/vprod/

# Check the .env file specifically
ls -la /opt/vprod/.env
# Should show: -rw------- 1 vprodbot vprodbot

# Check that the setgid bit is set on directories
stat -c "%a %n" /opt/vprod /var/lib/vprod
# Should show: 2775 /opt/vprod  and  2775 /var/lib/vprod

# Check your group membership
groups
# vprodadmins should appear in the list
```

### 7f. umask for the bot user

To make sure `vprodbot` creates files with the right permissions automatically, set its umask to `002` (which gives `664` for files and `775` for directories):

```bash
sudo -u vprodbot bash -c "echo 'umask 002' >> ~/.bashrc"
```

---

## 8. Set up the Python environment

Create a virtual environment inside the bot's code directory and install dependencies:

```bash
sudo -u vprodbot bash -c "
    cd /opt/vprod
    python3 -m venv venv
    venv/bin/pip install --upgrade pip
    venv/bin/pip install -r requirements.txt
"
```

Fix venv permissions so group members can use it:

```bash
sudo find /opt/vprod/venv -type d -exec chmod 2775 {} \;
sudo find /opt/vprod/venv -type f -exec chmod 664 {} \;
# Restore execute bits on binaries
sudo find /opt/vprod/venv/bin -type f -exec chmod 775 {} \;
```

Verify the install:

```bash
sudo -u vprodbot /opt/vprod/venv/bin/python -c "import discord; print('discord.py', discord.__version__)"
```

---

## 9. Configure the bot

### 9a. Create the .env file (bot token)

```bash
sudo -u vprodbot cp /opt/vprod/.env.example /opt/vprod/.env
sudo -u vprodbot nano /opt/vprod/.env
```

The file should contain (replace the placeholder with your actual token from step 2b):

```
DISCORD_TOKEN=your_bot_token_from_the_discord_developer_portal
```

Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X` in nano). Then lock it down immediately:

```bash
sudo chown vprodbot:vprodbot /opt/vprod/.env
sudo chmod 600 /opt/vprod/.env
```

### 9b. Create config.json

```bash
sudo -u vprodbot tee /var/lib/vprod/config.json > /dev/null << 'EOF'
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
sudo chmod 660 /var/lib/vprod/config.json
sudo chown vprodbot:vprodadmins /var/lib/vprod/config.json
```

> `owner_ids` can be left empty. Owners are resolved automatically from your Discord Team (step 3). You can add extra Discord user IDs here if you want to grant owner access to someone outside the team.

---

## 10. Install and start the systemd service

### 10a. Install the service

```bash
sudo python3 /opt/vprod/launcher.py system install-service
```

This copies `vprod.service` to `/etc/systemd/system/vprod.service` and enables it.

### 10b. Start the bot

```bash
sudo systemctl start vprod
```

### 10c. Check that it started correctly

```bash
sudo systemctl status vprod
```

You should see `active (running)`. If not, check the logs:

```bash
sudo journalctl -u vprod -n 50
```

### 10d. Enable autostart on boot

```bash
sudo systemctl enable vprod
```

This is done automatically by `install-service`, but double-check with:

```bash
sudo systemctl is-enabled vprod
# should print: enabled
```

### 10e. Optional — sudoers entry for the Discord management panel

The `!vmanage` Discord panel sends `sudo systemctl` commands on the server. Add this so it works without a password prompt:

```bash
sudo tee /etc/sudoers.d/vprod > /dev/null << 'EOF'
vprodbot ALL=(ALL) NOPASSWD: /bin/systemctl restart vprod, \
    /bin/systemctl stop vprod, \
    /bin/systemctl start vprod
EOF
sudo chmod 440 /etc/sudoers.d/vprod
```

---

## 11. Install vmanage system-wide

`vmanage` is the CLI tool for managing the bot. Install it so any user (including `vprodadmins` members) can run it without a venv:

```bash
sudo ln -sf /opt/vprod/vmanage.py /usr/local/bin/vmanage
sudo chmod +x /opt/vprod/vmanage.py
```

Test it:

```bash
vmanage
```

You should see the vprod status dashboard.

---

## 12. Add the bot to your Discord server

### 12a. Build the invite URL

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

### 12b. Authorise the bot

Select the Discord server you want to add the bot to and click **Authorise**.

### 12c. Verify it joined

Go to your Discord server. The bot should appear in the member list. Type `!ping` — if it responds with a latency embed, everything is working.

---

## 13. Test that everything works

Run through these checks after setup:

```bash
# 1. Check overall system status
sudo python3 /opt/vprod/launcher.py system status

# 2. View the status dashboard
vmanage

# 3. Tail the logs
vmanage --logs
```

In Discord:
- `!ping` — should respond with API latency
- `!botinfo` — should show bot name, prefix, and guild count
- `!help` — should open the paginated help embed with navigation buttons

If you are an accepted member of the Discord Team linked to the application:
- `!stats` — should show detailed statistics
- `!vmanage` — should open the management panel with Restart/Stop/Update/Logs buttons

---

## 14. Managing the vprodadmins group

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

| Action | Group needed? | sudo needed? |
|--------|:---:|:---:|
| View the status dashboard (`vmanage`) | No | No |
| Read bot logs (`vmanage --logs`) | No | No |
| Start / stop / restart via `vmanage` | No | Yes (vmanage handles it) |
| Edit `/var/lib/vprod/config.json` | Yes | No |
| Edit `/opt/vprod/cogs/` or `core/` | Yes | No |
| Deploy code changes (`git pull`) | Yes | No |
| Add cogs / repos via `launcher.py` | Yes | No |
| Edit `/opt/vprod/.env` (token) | No | Yes (root only by design) |

> **Discord owner vs Linux group member** — these are independent. Linux group membership controls server file access. Discord Team membership controls which users can run `!vmanage`, `!shutdown`, `!stats`, etc. in Discord.

### Discord Team vs Linux group — summary

| What it controls | How to manage |
|-----------------|--------------|
| Who can run owner bot commands in Discord | Discord Team at discord.com/developers/teams |
| Who can read/edit bot files on the server | `vprodadmins` Linux group via `usermod` |

---

## 15. What each path is for

```
/opt/vprod/                       Bot code — git clone lives here
  launcher.py      (775)          Bot-scoped CLI (start, repos, cogs, system)
  vmanage.py       (775)          System-wide management CLI
  vprod.service    (664)          systemd service unit
  requirements.txt (664)          Python dependencies
  .env             (600)          Bot token — private to vprodbot only
  .env.example     (664)          Template for .env
  venv/            (2775)         Python virtual environment
  core/            (2775)         Framework source code
  cogs/            (2775)         Built-in cogs

/var/lib/vprod/                   Mutable data — separate from code
  config.json      (660)          Bot config (prefix, name, owner_ids)
  cog_data.json    (660)          Cog registry (autoload list, repo index)
  repos/           (2775)         Cloned cog repositories
  guilds/          (2775)         Per-server JSON data files

/etc/systemd/system/
  vprod.service                   systemd service definition

/usr/local/bin/
  vmanage                         Symlink → /opt/vprod/vmanage.py
```

---

## 16. Keeping the bot up to date

### Update via vmanage (recommended)

```bash
vmanage --update
```

This runs `git pull`, upgrades pip packages, and restarts the bot automatically.

### Update manually

```bash
cd /opt/vprod

# Pull the latest code
sudo -u vprodbot git pull --ff-only

# Upgrade dependencies
sudo -u vprodbot venv/bin/pip install --upgrade pip
sudo -u vprodbot venv/bin/pip install -r requirements.txt

# Restart the service
sudo systemctl restart vprod
```

### Re-deploy from scratch (keeping your data)

Your config and guild data live in `/var/lib/vprod/` which is separate from the code. You can safely delete and re-clone the code without losing any bot state:

```bash
# Stop the bot
sudo systemctl stop vprod

# Wipe the code directory only (data is safe in /var/lib/vprod/)
sudo rm -rf /opt/vprod

# Re-clone
sudo git clone https://github.com/BigPattyOG/VantageOverlook.git /opt/vprod
sudo chown -R vprodbot:vprodadmins /opt/vprod
sudo find /opt/vprod -type d -exec chmod 2775 {} \;
sudo find /opt/vprod -type f -exec chmod 664 {} \;
sudo chmod 775 /opt/vprod/launcher.py /opt/vprod/vmanage.py

# Re-create the .env (data dir still has your config.json)
sudo -u vprodbot cp /opt/vprod/.env.example /opt/vprod/.env
sudo -u vprodbot nano /opt/vprod/.env   # add your DISCORD_TOKEN
sudo chown vprodbot:vprodbot /opt/vprod/.env
sudo chmod 600 /opt/vprod/.env

# Rebuild the venv
sudo -u vprodbot bash -c "
    cd /opt/vprod
    python3 -m venv venv
    venv/bin/pip install --upgrade pip
    venv/bin/pip install -r requirements.txt
"
sudo find /opt/vprod/venv -type d -exec chmod 2775 {} \;
sudo find /opt/vprod/venv -type f -exec chmod 664 {} \;
sudo find /opt/vprod/venv/bin -type f -exec chmod 775 {} \;

# Start the bot
sudo systemctl start vprod
```
