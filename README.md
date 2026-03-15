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
launcher.py         Bot CLI  (start, repos, plugins, system)
vmanage.py          System management CLI (start/stop/restart/logs/update)
vprod.service       Systemd service unit
VERSION             Current version number
```

## Quick Start

**Production (server)**
```bash
sudo bash scripts/install-vprod.sh
```

**Development (local)**
```bash
bash scripts/install-vdev.sh
venv/bin/python launcher.py start
```

## Docs

- [Setup guide](docs/SETUP.md) — full production walkthrough
- [Plugin authoring](docs/PLUGINS.md) — write and install plugins
- [Owner guide](docs/OWNER_GUIDE.md) — Discord commands reference
