# Plugin Guide

vprod has three tiers of commands and two types of plugins.

---

## Command Tiers

| Tier | Who can use | Examples |
|------|-------------|---------|
| **Public** | Everyone | `!ping`, `!botinfo`, `!help`, `!version` |
| **Owner** | Discord Team members | `!vmanage`, `!stats`, `!maintenance`, `!load`, etc. |
| **External plugins** | Defined by each plugin | Whatever your plugin implements |

Owner access is automatic — add someone to your Discord application's Team and they get owner permissions on next bot start.

---

## Two Types of Plugins

### 1. Community Plugins (GitHub repos)

Cloned from public GitHub repos into `data/repos/`.  
Managed via the `launcher.py plugins` CLI.

```bash
# Add a GitHub repo
python launcher.py repos add https://github.com/user/my-plugins

# Install a plugin from that repo
python launcher.py plugins install my_plugins welcome

# Enable autoload (loads on every bot start)
python launcher.py plugins autoload my_plugins.welcome

# Or load immediately without restarting
# !load my_plugins.welcome
```

### 2. External Plugins (your private repo)

Your own custom plugins live in `data/ext_plugins/` (or configured by `ext_plugins_dir`).  
Managed via `!plugin` Discord commands.

```bash
# Clone your private plugin repo
cd /var/lib/vprod/ext_plugins
git clone git@github.com:BigPattyOG/my-private-plugins.git my_features
```

Then in Discord (owner only):
```
!plugin install /var/lib/vprod/ext_plugins/my_features/welcome
!load _vp_ext.welcome
```

External plugins are loaded in the `_vp_ext` namespace, keeping them isolated from community plugins.

---

## Writing a Plugin

Every plugin needs a class extending `commands.Cog` and an async `setup()` function.

### Minimal public command

```python
# /var/lib/vprod/ext_plugins/my_feature/hello.py
from discord.ext import commands

class Hello(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def hello(self, ctx):
        """Say hello."""
        await ctx.send(f"Hello, {ctx.author.mention}!")

async def setup(bot):
    await bot.add_cog(Hello(bot))
```

### Owner-only command

```python
@commands.command()
@commands.is_owner()
async def secret(self, ctx):
    """Only Discord Team members can run this."""
    await ctx.send("This is an owner command.")
```

### Using branded embeds

```python
from framework.embeds import VantageEmbed

@commands.command()
async def status(self, ctx):
    embed = VantageEmbed.info("Status", "Everything is running fine.")
    await ctx.send(embed=embed)
```

Available embed types:
- `VantageEmbed.info(title, description)` — teal
- `VantageEmbed.ok(description)` — green (success)
- `VantageEmbed.error(title, description)` — red
- `VantageEmbed.warn(title, description)` — gold

### Using per-guild data

```python
from framework.guild_data import get_guild_value, set_guild_value

@commands.command()
async def setgreeting(self, ctx, *, message):
    set_guild_value(ctx.guild.id, "greeting", message)
    await ctx.send("Greeting saved.")

@commands.command()
async def greeting(self, ctx):
    msg = get_guild_value(ctx.guild.id, "greeting", "No greeting set.")
    await ctx.send(msg)
```

---

## Plugin Manifest (optional)

Create a `vantage.toml` in your plugin directory for metadata:

```toml
[plugin]
name          = "Welcome"
version       = "1.2.0"
description   = "Greets new members with a custom message"
author        = "BigPatty"
min_framework = "1.0.0"
```

This shows up in `!plugin list` and `!version`.

---

## Security

External plugins go through these checks:

1. **Path containment** — the plugin path must be inside `ext_plugins_dir`.  
   A symlink pointing outside is rejected automatically.

2. **SHA-256 integrity** — a hash of all `.py` files is computed at install time  
   and verified at load time. A mismatch triggers a warning (but still loads).  
   Run `!plugin verify` to see all hashes.

3. **Isolated error handling** — if a plugin crashes at import, only that  
   plugin fails. The bot and all other plugins keep running.

---

## Managing External Plugins (Discord Commands)

All `!plugin` sub-commands are owner-only.

| Command | What it does |
|---------|-------------|
| `!plugin list` | Show all registered external plugins |
| `!plugin install <path>` | Register a local plugin (path must be inside ext_plugins dir) |
| `!plugin remove <name>` | Remove from registry (files untouched) |
| `!plugin enable <name>` | Enable a disabled plugin |
| `!plugin disable <name>` | Unload and disable |
| `!plugin reload <name>` | Hot-reload after a code change (no restart needed) |
| `!plugin verify` | Check SHA-256 hashes for all plugins |

---

## Hot-Reloading

Update a plugin without restarting the bot:

```bash
# Pull changes on the server
cd /var/lib/vprod/ext_plugins/my_features
git pull
```

Then in Discord:
```
!plugin reload welcome
```

Or for community plugins:
```
!reload my_plugins.welcome
```
