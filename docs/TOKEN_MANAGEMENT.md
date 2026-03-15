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
              sudo bash <(curl -fsSL …/install-vprod.sh)
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
sudo bash <(curl -fsSL https://raw.githubusercontent.com/BigPattyOG/VantageOverlook/main/scripts/install-vprod.sh)
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

Token handling for local dev is even simpler:

```bash
bash scripts/install-vdev.sh
```

The dev installer prompts for the token and stores it in `./data/.env` (which is gitignored). No systemd, no server, no sudo.

To change the token later:
```bash
nano data/.env   # edit DISCORD_TOKEN= line
# Restart the bot process
```

---

## Automated Deploys — GitHub Actions (optional)

If you **want** GitHub to deploy automatically on every push to `main` (without you SSHing in), the repo includes workflow files in `.github/workflows/`. This requires adding an SSH key to GitHub Secrets so the runner can reach your server.

This is **entirely optional** — the curl install method above is simpler and does not require any GitHub access to your server.

### When the GitHub Actions approach makes sense

- You have a team pushing code frequently and want zero-touch deploys
- You want the token rotation workflow (update secret → trigger workflow → done)
- You're comfortable with GitHub holding a deploy-only SSH key

### Setup (if you want it)

**Required GitHub Secrets** (Settings → Secrets and variables → Actions):

| Secret | Value |
|--------|-------|
| `DISCORD_TOKEN` | Bot token from Discord Developer Portal |
| `SSH_HOST` | Server IP or hostname |
| `SSH_USER` | Linux user with sudo access |
| `SSH_KEY` | Private SSH key (paste the private key file contents) |
| `SSH_PORT` | *(optional)* — omit for port 22 |

For dev, add the same set with `_DEV` suffix.

**Generate a deploy-only SSH key** (on your local machine):
```bash
ssh-keygen -t ed25519 -C "vprod-deploy-key" -f ~/.ssh/vprod_deploy
# Add the public key to the server:
ssh-copy-id -i ~/.ssh/vprod_deploy.pub your-user@your.server.ip
# Paste the private key into the SSH_KEY GitHub Secret
```

Once configured, every push to `main` triggers `deploy-vprod.yml`, which SSHes in and runs `install-vprod.sh` with the token from GitHub Secrets.

### Token rotation with GitHub Actions

1. Reset token on Discord Developer Portal
2. Update `DISCORD_TOKEN` GitHub Secret
3. **Actions → Deploy — Production → Run workflow**

The workflow overwrites `/var/lib/vprod/.env` and restarts the bot (~30 seconds total).
