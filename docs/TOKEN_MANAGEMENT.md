# Token Management

This document explains exactly where the Discord bot token lives, how it gets onto the server, and how to handle resets.

---

## The short answer

The token **cannot be stored in the git repository** — Discord's scanner monitors GitHub continuously and invalidates any token it finds in a public or private repo within seconds.

The token lives in **two places**:

| Location | What lives there |
|----------|-----------------|
| **GitHub Secrets** | The authoritative copy. Encrypted. Only readable by GitHub Actions runners — never exposed to humans or external systems. |
| **`/var/lib/vprod/.env`** on the server | The working copy. Written by the deploy workflow. File permissions `600`, owned by `vprodbot` only. Outside the git checkout so `git pull` can never touch it. |

---

## How the token gets from GitHub to the server

```
You  ──→  GitHub Secrets  ──→  GitHub Actions runner (encrypted, in-memory)
                                        │
                                        │  SSH (encrypted channel)
                                        ▼
                              /var/lib/vprod/.env  (chmod 600, vprodbot only)
                                        │
                                        │  EnvironmentFile= in vprod.service
                                        ▼
                              Bot process (DISCORD_TOKEN env var)
```

Step by step:

1. You add `DISCORD_TOKEN` to GitHub Secrets (Settings → Secrets and variables → Actions).
2. A push to `main` triggers the `deploy-vprod.yml` workflow (or you run it manually).
3. GitHub's runner decrypts the secret **in memory** — it is never written to the runner's disk.
4. The runner SSHes into your server and runs `install-vprod.sh` with `DISCORD_TOKEN` exported for that single command.
5. `install-vprod.sh` writes the token to `/var/lib/vprod/.env` and sets permissions to `600` (`vprodbot` read-only).
6. The deploy script immediately drops the variable from the environment.
7. `systemd` starts `vprod.service` which reads `EnvironmentFile=/var/lib/vprod/.env` — the token is injected into the bot process as `DISCORD_TOKEN`.

The token is **never** in:
- The git repository (code or history)
- GitHub Actions logs (GitHub redacts secrets from log output)
- Any file readable by users other than `vprodbot`

---

## Setting up GitHub Secrets

Go to your repository on GitHub:

**Settings → Secrets and variables → Actions → New repository secret**

Add the following secrets:

### Production (`deploy-vprod.yml`)

| Secret name | Value |
|-------------|-------|
| `DISCORD_TOKEN` | Bot token from discord.com/developers/applications |
| `SSH_HOST` | Server IP address or hostname |
| `SSH_USER` | Linux user that can run `sudo` on the server |
| `SSH_KEY` | Private SSH key (contents of `~/.ssh/id_ed25519`, not the `.pub` file) |
| `SSH_PORT` | *(optional)* SSH port — omit to use the default 22 |

### Dev (`deploy-vdev.yml`)

| Secret name | Value |
|-------------|-------|
| `DISCORD_TOKEN_DEV` | A **separate** bot token for a different Discord application |
| `SSH_HOST_DEV` | Dev server IP or hostname |
| `SSH_USER_DEV` | Linux user on the dev server |
| `SSH_KEY_DEV` | Private SSH key for the dev server |
| `SSH_PORT_DEV` | *(optional)* SSH port |

> **Always use a separate bot application for dev.**  
> If both environments share a token and Discord resets it, both go down at once.  
> Two applications means independent tokens, independent resets, zero shared blast radius.

---

## Generating an SSH key pair

On your local machine (not the server):

```bash
ssh-keygen -t ed25519 -C "vprod-github-deploy" -f ~/.ssh/vprod_deploy
```

Two files are created:
- `~/.ssh/vprod_deploy` — **private key** → paste this into `SSH_KEY` GitHub Secret
- `~/.ssh/vprod_deploy.pub` — **public key** → add this to the server

Add the public key to the server:

```bash
# Replace with your actual server user and IP
ssh-copy-id -i ~/.ssh/vprod_deploy.pub ubuntu@your.server.ip
# Or manually:
cat ~/.ssh/vprod_deploy.pub | ssh ubuntu@your.server.ip 'cat >> ~/.ssh/authorized_keys'
```

---

## Triggering a deploy

### Automatic (push to main)

Every push to the `main` branch triggers `deploy-vprod.yml` automatically.

### Manual (token rotation or on-demand)

1. Go to your repo on GitHub
2. Click **Actions**
3. Click **Deploy — Production** (or **Deploy — Dev**)
4. Click **Run workflow** (top right)
5. Choose options if needed → **Run workflow**

Use this for:
- Deploying after a token reset
- Testing the deploy pipeline
- Deploying a specific commit without merging to main

---

## Rotating the token

Discord occasionally invalidates tokens (or you may reset it manually).

1. **Reset the token** — Discord Developer Portal → your application → Bot → Reset Token → copy the new token
2. **Update the GitHub Secret** — Settings → Secrets → Actions → `DISCORD_TOKEN` → Update → paste new token
3. **Re-deploy** — Run the `Deploy — Production` workflow manually (see above)

The workflow will overwrite `/var/lib/vprod/.env` with the new token and restart the bot. Takes about 30–60 seconds total.

---

## Viewing the token on the server (emergency only)

If you need to check the token directly on the server:

```bash
# Only vprodbot can read this file
sudo -u vprodbot cat /var/lib/vprod/.env
```

Or to check it's set without revealing the full value:

```bash
sudo -u vprodbot grep -c DISCORD_TOKEN /var/lib/vprod/.env  # prints 1 if set
```

---

## What happens during `git pull` / `vmanage --update`

The data directory (`/var/lib/vprod/`) and the code directory (`/opt/vprod/`) are completely separate.

```
/opt/vprod/      ← git pull touches this
/var/lib/vprod/  ← git pull NEVER touches this
  .env           ← your token, always safe
  config.json    ← your config, always safe
  ext_plugins/   ← your plugins, always safe
```

`git pull` on `/opt/vprod/` cannot overwrite `/var/lib/vprod/.env` because they are different directories on the filesystem.

---

## Local development (no server, no CI)

Use `install-vdev.sh` instead:

```bash
bash scripts/install-vdev.sh
```

This prompts you for the token and stores it in `./data/.env` (which is gitignored). No GitHub Secrets, no SSH, no deployment pipeline needed.
