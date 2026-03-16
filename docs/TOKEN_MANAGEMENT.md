# Token Management

Where the Discord bot token lives, how it gets onto the server, and how to rotate it.

---

## The short version

The token **cannot be stored in the git repository** — Discord's scanner monitors GitHub and invalidates any token found in a repo (public or private) within seconds.

The token lives in **one place on your server**:

```
/var/lib/vprod/.env
```

- Permissions: `600` (owner read/write only)
- Owner: `vprodbot` (the system user that runs the bot)
- Location: **outside** the git checkout (`/opt/vprod/`) so `git pull` can never touch it

You never need to put the token in GitHub at all.

---

## How it works (curl install — no GitHub access to server)

The simplest and most private approach. GitHub only serves the install script — it never connects to your server.

```
discord.com/developers  ──→  You copy the token to your clipboard
                                        │
                        SSH into your server
                                        │
              curl -fsSL …/install-vprod.sh | sudo bash
                                        │
                     Script prompts: "Enter DISCORD_TOKEN:"
                                        │
                              /var/lib/vprod/.env  (chmod 600, vprodbot only)
                                        │
                         systemd EnvironmentFile=
                                        │
                         Bot process (DISCORD_TOKEN env var)
```

The token:
- Goes from your clipboard directly into the server's `.env` file
- Is never written to the installer's terminal output
- Is never sent to GitHub
- Cannot be seen by any other Linux user (chmod 600)
- Cannot be overwritten by `git pull` (different directory)

---

## Installing / updating the token

### First install

```bash
curl -fsSL https://raw.githubusercontent.com/BigPattyOG/VantageOverlook/main/scripts/install-vprod.sh | sudo bash
```

The script prompts you interactively:
```
  Enter DISCORD_TOKEN: ████████████████  (input hidden)
  ✔  Token written to /var/lib/vprod/.env (permissions: 600, owner: vprodbot only)
```

### Rotating after a Discord token reset

**Option A — `vmanage --update-token`** (recommended — fastest):
```bash
vmanage --update-token
```
Prompts for the new token (input hidden), validates the format, writes it to `/var/lib/vprod/.env`, and offers to restart the bot — all in one step. Sudo is used internally to write the file; the token is never exposed in process arguments.

**Option B — re-run the installer**:
```bash
sudo bash /opt/vprod/scripts/install-vprod.sh
```
The script detects the existing install, updates the code, and prompts for a new token. When asked `Overwrite it with a new token?`, answer `y`.

**Option C — edit the file directly**:
```bash
sudo -u vprodbot nano /var/lib/vprod/.env
# Change DISCORD_TOKEN=old  →  DISCORD_TOKEN=new
# Save and exit
sudo systemctl restart vprod
```

**Option D — one-liner** (useful for scripting):
```bash
sudo DISCORD_TOKEN=your_new_token bash /opt/vprod/scripts/install-vprod.sh
```

---

## Checking the token is set

Without revealing the value:
```bash
sudo -u vprodbot grep -c 'DISCORD_TOKEN=.' /var/lib/vprod/.env
# Prints 1 if set, 0 if placeholder/empty
```

To see the actual value (emergency only):
```bash
sudo -u vprodbot cat /var/lib/vprod/.env
```

---

## Why `git pull` is always safe

The data directory and the code directory are completely separate on the filesystem:

```
/opt/vprod/          ← git pull touches this (code only)
/var/lib/vprod/      ← git pull NEVER touches this
  .env               ← your token, always safe
  config.json        ← your config, always safe
  ext_plugins/       ← your plugins, always safe
  logs/              ← log files
```

`vmanage --update` runs `git pull` on `/opt/vprod/` — it cannot reach `/var/lib/vprod/`.

---

## What the bot reads at startup

The systemd service file (`vprod.service`) contains:

```ini
EnvironmentFile=-/var/lib/vprod/.env
```

This tells systemd to read `/var/lib/vprod/.env` and inject each `KEY=value` line as an environment variable before starting the bot. The bot process sees `DISCORD_TOKEN` as a normal env var — it is never logged or printed.

---

## Local development

Token handling for a dev server install uses `install-vdev.sh` (requires sudo):

```bash
sudo bash scripts/install-vdev.sh
```

The dev installer prompts for the token and stores it in `/var/lib/vdev/.env`
(chmod 600, owned by `vdevbot`). It installs a `vdev` systemd service
mirroring prod, isolated under `/opt/vdev` and `/var/lib/vdev`.

To rotate the token later:
```bash
vmanage --update-token
```

---

