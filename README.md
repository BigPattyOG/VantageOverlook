# VantageOverlook — vprod

Private Discord bot framework. Modular, self-hosted, runs on Ubuntu via systemd.

---

## Structure

```
framework/          Core bot engine (bot, config, health, embeds, loaders)
plugins/            Built-in admin plugin (always loaded)
scripts/            Install scripts
docs/               Documentation
data/               Runtime data — gitignored (config, token, plugins, logs)
.github/workflows/  Automated deploy pipelines
launcher.py         Bot CLI  (start, repos, plugins, system)
vmanage.py          System management CLI
vprod.service       Systemd service unit
VERSION             Current version number
```

---

## Quick Start

### Automated (recommended) — GitHub Actions

1. Add secrets in GitHub: `DISCORD_TOKEN`, `SSH_HOST`, `SSH_USER`, `SSH_KEY`
2. Push to `main` — the bot deploys automatically

See [docs/TOKEN_MANAGEMENT.md](docs/TOKEN_MANAGEMENT.md) for the full explanation.

### Manual — production server

```bash
sudo bash scripts/install-vprod.sh
```

### Local development

```bash
bash scripts/install-vdev.sh
venv/bin/python launcher.py start
```

---

## Docs

- [Token management](docs/TOKEN_MANAGEMENT.md) — how the token gets from GitHub to the server
- [Setup guide](docs/SETUP.md) — full production + dev walkthrough
- [Plugin authoring](docs/PLUGINS.md) — write and install external plugins
- [Owner guide](docs/OWNER_GUIDE.md) — all Discord commands
