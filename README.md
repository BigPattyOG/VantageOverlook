# VantageOverlook — vprod

Self-hosted Discord bot framework. Modular, runs on Ubuntu via systemd.

---

## Quick Start

### Production server (recommended)

SSH into your server and run one command. The script handles everything — packages, system user, venv, permissions, config, systemd service — and prompts you for the Discord token at the end.

```bash
sudo bash <(curl -fsSL https://raw.githubusercontent.com/BigPattyOG/VantageOverlook/main/scripts/install-vprod.sh)
```

Your token is stored in `/var/lib/vprod/.env` (chmod 600, owned by the bot user only). It never touches GitHub.

### Local development

```bash
git clone https://github.com/BigPattyOG/VantageOverlook.git vprod && cd vprod
bash scripts/install-vdev.sh
venv/bin/python launcher.py start
```

Token goes to `data/.env` (gitignored). No sudo, no systemd.

---

## Structure

```
framework/          Core bot engine (bot, config, health, embeds, loaders)
plugins/            Built-in admin plugin (always loaded)
scripts/            Install scripts
docs/               Documentation
data/               Runtime data — gitignored (config, token, plugins, logs)
launcher.py         Bot CLI  (start, repos, plugins, system)
vmanage.py          System management CLI
vprod.service       Systemd service unit
VERSION             Current version number
```

---

## Docs

- [Setup guide](docs/SETUP.md) — full walkthrough (production + dev)
- [Token management](docs/TOKEN_MANAGEMENT.md) — where the token lives and how to rotate it
- [Plugin authoring](docs/PLUGINS.md) — write and install external plugins
- [Owner guide](docs/OWNER_GUIDE.md) — all Discord commands
