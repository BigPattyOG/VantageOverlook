# Writing Cogs for Vantage

A **cog** is a self-contained Python module (or package) that adds commands, event listeners, and background tasks to a Vantage bot. Cogs are loaded and unloaded at runtime without restarting the bot.

---

## Table of Contents

1. [Concepts](#concepts)
2. [Minimal Cog](#minimal-cog)
3. [Commands](#commands)
4. [Subcommands (Groups)](#subcommands-groups)
5. [Event Listeners](#event-listeners)
6. [Background Tasks](#background-tasks)
7. [Per-Guild Data](#per-guild-data)
8. [Error Handling](#error-handling)
9. [Permission Checks](#permission-checks)
10. [Embeds & Formatting](#embeds--formatting)
11. [Cog as a Package](#cog-as-a-package)
12. [Installing Your Cog](#installing-your-cog)
13. [Hot-Reloading](#hot-reloading)
14. [Full Example Cog](#full-example-cog)

---

## Concepts

| Term | What it means |
|------|--------------|
| **Cog** | A Python class that groups related commands and listeners |
| **Command** | A function that runs when a user types `!commandname` |
| **Listener** | A function that runs when a Discord event happens (e.g. member joins) |
| **Extension** | The Python module that contains the cog — what discord.py actually loads |
| **setup()** | The async function that discord.py calls to register your cog |
| **Autoload** | Cogs marked to load automatically every time the bot starts |

---

## Minimal Cog

Every cog needs three things:
1. A class that inherits from `commands.Cog`
2. An `__init__` that accepts `bot`
3. An async `setup(bot)` function at the **module** level

```python
# my_cogs/hello.py
from discord.ext import commands

class Hello(commands.Cog):
    """Simple greeting commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command()
    async def hello(self, ctx: commands.Context) -> None:
        """Say hello to someone."""
        await ctx.send(f"Hello, {ctx.author.mention}! 👋")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Hello(bot))
```

That's it. Install and load:

```bash
python launcher.py repos add /path/to/my_cogs
python launcher.py cogs install my_cogs hello
python launcher.py cogs autoload my_cogs.hello
```

Or at runtime from Discord (no restart needed):
```
!load my_cogs.hello
```

---

## Commands

### Basic command

```python
@commands.command()
async def greet(self, ctx: commands.Context, member: discord.Member) -> None:
    """Greet a specific member.
    
    Usage: !greet @someone
    """
    await ctx.send(f"Hey {member.mention}! 👋")
```

The docstring becomes the help text shown in `!help greet`.

### Command with optional argument

```python
@commands.command()
async def say(self, ctx: commands.Context, *, message: str = "nothing") -> None:
    """Make the bot say something. Use * to capture the whole message."""
    await ctx.send(message)
```

- `*` before a parameter captures everything the user types after the command name
- `= "nothing"` makes it optional with a default

### Command with aliases

```python
@commands.command(name="flip", aliases=["coinflip", "cf"])
async def coin_flip(self, ctx: commands.Context) -> None:
    """Flip a coin."""
    import random
    result = random.choice(["Heads", "Tails"])
    await ctx.send(f"🪙 {result}!")
```

Now `!flip`, `!coinflip`, and `!cf` all work.

### Deleting the trigger message

```python
@commands.command()
async def secret(self, ctx: commands.Context, *, msg: str) -> None:
    """Send a message and delete the command."""
    await ctx.message.delete()
    await ctx.send(msg)
```

---

## Subcommands (Groups)

Group multiple related commands under one parent:

```python
@commands.group(invoke_without_command=True)
async def settings(self, ctx: commands.Context) -> None:
    """Manage server settings. Run without arguments to see sub-commands."""
    await ctx.send_help(ctx.command)

@settings.command(name="prefix")
async def settings_prefix(self, ctx: commands.Context, new: str) -> None:
    """Change the bot prefix for this server."""
    # your code here
    await ctx.send(f"Prefix set to `{new}`")

@settings.command(name="show")
async def settings_show(self, ctx: commands.Context) -> None:
    """Show current settings."""
    await ctx.send("Here are your settings…")
```

Usage: `!settings prefix >`, `!settings show`

---

## Event Listeners

Listen to Discord events using `@commands.Cog.listener()`:

```python
@commands.Cog.listener()
async def on_member_join(self, member: discord.Member) -> None:
    """Runs whenever someone joins a server the bot is in."""
    channel = member.guild.system_channel
    if channel:
        await channel.send(f"Welcome to {member.guild.name}, {member.mention}! 🎉")

@commands.Cog.listener()
async def on_message(self, message: discord.Message) -> None:
    """Runs on every message. Be careful — this fires a LOT."""
    if message.author.bot:
        return  # ignore bots
    if "good bot" in message.content.lower():
        await message.add_reaction("❤️")

@commands.Cog.listener()
async def on_member_remove(self, member: discord.Member) -> None:
    """Runs when someone leaves or is kicked."""
    print(f"{member} left {member.guild.name}")
```

Common events: `on_member_join`, `on_member_remove`, `on_message`, `on_message_delete`, `on_message_edit`, `on_reaction_add`, `on_guild_join`, `on_guild_remove`.

---

## Background Tasks

Run code on a schedule using `discord.ext.tasks`:

```python
from discord.ext import commands, tasks

class StatusCog(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.rotate_status.start()   # start the loop when the cog loads

    def cog_unload(self) -> None:
        self.rotate_status.cancel()  # stop the loop when the cog unloads

    @tasks.loop(minutes=10)
    async def rotate_status(self) -> None:
        """Changes bot status every 10 minutes."""
        import random
        options = ["chess", "with fire", "the markets"]
        await self.bot.change_presence(
            activity=discord.Game(random.choice(options))
        )

    @rotate_status.before_loop
    async def before_rotate(self) -> None:
        await self.bot.wait_until_ready()  # don't run until bot is logged in
```

Available intervals: `seconds=`, `minutes=`, `hours=`.

---

## Per-Guild Data

Store settings or data separately for each Discord server:

```python
from core.guild_data import load_guild, save_guild, get_guild_value, set_guild_value

class WelcomeCog(commands.Cog):

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setwelcome(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        """Set the welcome channel for this server."""
        set_guild_value(ctx.guild.id, "welcome_channel", channel.id)
        await ctx.send(f"✅ Welcome messages will be sent to {channel.mention}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        channel_id = get_guild_value(member.guild.id, "welcome_channel")
        if not channel_id:
            return
        channel = member.guild.get_channel(channel_id)
        if channel:
            await channel.send(f"Welcome {member.mention}!")
```

Data is stored in `data/guilds/{guild_id}.json`. Each guild gets its own file.

For more complex data:

```python
# Load the whole dict, modify it, save it back
data = load_guild(ctx.guild.id)
data.setdefault("warnings", {})
uid = str(ctx.user.id)
data["warnings"][uid] = data["warnings"].get(uid, 0) + 1
save_guild(ctx.guild.id, data)
```

---

## Error Handling

Handle errors inside a specific command:

```python
@commands.command()
async def divide(self, ctx: commands.Context, a: float, b: float) -> None:
    """Divide two numbers."""
    if b == 0:
        await ctx.send(embed=discord.Embed(
            description="❌ Cannot divide by zero.",
            color=discord.Color.red(),
        ))
        return
    await ctx.send(f"{a} ÷ {b} = {a/b:.4f}")

@divide.error
async def divide_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Usage: `!divide <number> <number>`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Both arguments must be numbers.")
    else:
        raise error  # re-raise so the global handler catches it
```

The global error handler in `core/bot.py` catches any re-raised errors and sends a user-friendly embed.

---

## Permission Checks

### Built-in checks

```python
@commands.command()
@commands.is_owner()                          # only the bot owner(s)
async def owner_cmd(self, ctx): ...

@commands.command()
@commands.has_permissions(administrator=True) # user must be server admin
async def admin_cmd(self, ctx): ...

@commands.command()
@commands.has_permissions(manage_messages=True, kick_members=True)  # multiple
async def mod_cmd(self, ctx): ...

@commands.command()
@commands.guild_only()                        # can't be used in DMs
async def server_cmd(self, ctx): ...

@commands.command()
@commands.dm_only()                           # only usable in DMs
async def dm_cmd(self, ctx): ...

@commands.command()
@commands.cooldown(rate=1, per=30, type=commands.BucketType.user)  # once per 30s per user
async def limited_cmd(self, ctx): ...
```

### Custom check

```python
def is_mod():
    """Custom check: user must have 'Moderator' role."""
    async def predicate(ctx: commands.Context) -> bool:
        return any(r.name == "Moderator" for r in ctx.author.roles)
    return commands.check(predicate)

@commands.command()
@is_mod()
async def mute(self, ctx: commands.Context, member: discord.Member) -> None:
    ...
```

---

## Embeds & Formatting

Embeds look much nicer than plain text:

```python
import discord
from datetime import datetime, timezone

@commands.command()
async def profile(self, ctx: commands.Context, member: discord.Member = None) -> None:
    """Show a user's profile."""
    target = member or ctx.author

    embed = discord.Embed(
        title=f"👤 {target.display_name}",
        description=f"Info about {target.mention}",
        color=discord.Color.from_str("#5865F2"),  # Discord blurple
        timestamp=datetime.now(timezone.utc),
    )

    embed.set_thumbnail(url=target.display_avatar.url)

    embed.add_field(name="Account created", value=discord.utils.format_dt(target.created_at, "R"), inline=True)
    embed.add_field(name="Joined server",   value=discord.utils.format_dt(target.joined_at, "R"),   inline=True)
    embed.add_field(name="Roles",           value=", ".join(r.mention for r in target.roles[1:]) or "None", inline=False)

    embed.set_footer(text=f"ID: {target.id}")

    await ctx.send(embed=embed)
```

**`discord.utils.format_dt(dt, style)` styles:**
- `"f"` — full date/time: `14 March 2026 03:00`
- `"R"` — relative: `2 hours ago`
- `"D"` — date only: `14 March 2026`

**Common colours:**
```python
discord.Color.green()
discord.Color.red()
discord.Color.gold()
discord.Color.blurple()
discord.Color.from_str("#FF5733")  # any hex code
```

---

## Cog as a Package

For larger cogs, turn the file into a folder:

```
my_cogs/
  __init__.py    ← empty (just marks it as a package)
  welcome/
    __init__.py  ← contains the cog class AND setup()
    helpers.py   ← helper functions imported by __init__.py
    config.py    ← cog-specific constants
```

`my_cogs/welcome/__init__.py`:

```python
from discord.ext import commands
from .helpers import format_welcome_message

class Welcome(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        msg = format_welcome_message(member)
        if member.guild.system_channel:
            await member.guild.system_channel.send(msg)

async def setup(bot):
    await bot.add_cog(Welcome(bot))
```

Install it the same way:
```bash
python launcher.py cogs install my_cogs welcome
```

---

## Installing Your Cog

### From a local directory

```bash
# Register the parent folder as a repo (once)
python launcher.py repos add /home/user/my_cogs --name my_cogs

# Install a specific cog from that repo
python launcher.py cogs install my_cogs hello

# Make it autoload (so it loads every time the bot starts)
python launcher.py cogs autoload my_cogs.hello
```

### From GitHub

```bash
python launcher.py repos add https://github.com/yourname/my-cogs
python launcher.py cogs install my_cogs hello
python launcher.py cogs autoload my_cogs.hello
```

### Load it right now (without restarting)

Type this in Discord (owner only):
```
!load my_cogs.hello
```

### See all installed cogs

```bash
python launcher.py cogs list   # or:
vmanage MyBot --cogs
```

---

## Hot-Reloading

While developing, you can reload a cog after editing its code without restarting the whole bot:

```
!reload my_cogs.hello
```

If the reload fails, the previous version keeps running and the error is shown in the embed.

After adding a brand new cog that wasn't loaded before:
```
!load my_cogs.hello
```

---

## Full Example Cog

Here's a realistic cog that uses commands, listeners, guild data, embeds, and cooldowns:

```python
# my_cogs/moderation.py
"""Basic moderation commands."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

from core.guild_data import get_guild_value, set_guild_value

log = logging.getLogger("my_cogs.moderation")

EMBED_COLOR = discord.Color.from_str("#FF6B6B")


class Moderation(commands.Cog, name="Moderation"):
    """Server moderation tools."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── helpers ───────────────────────────────────────────────────────────────

    def _ok(self, desc: str) -> discord.Embed:
        return discord.Embed(description=f"✅ {desc}", color=discord.Color.green())

    def _err(self, desc: str) -> discord.Embed:
        return discord.Embed(description=f"❌ {desc}", color=discord.Color.red())

    # ── commands ──────────────────────────────────────────────────────────────

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    async def kick(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: str = "No reason given",
    ) -> None:
        """Kick a member from the server.

        **Requires:** Kick Members permission
        """
        if member == ctx.author:
            await ctx.send(embed=self._err("You can't kick yourself."))
            return
        if member.top_role >= ctx.author.top_role:
            await ctx.send(embed=self._err("You can't kick someone with an equal or higher role."))
            return

        try:
            await member.kick(reason=f"{ctx.author}: {reason}")
        except discord.Forbidden:
            await ctx.send(embed=self._err("I don't have permission to kick that member."))
            return

        log.info("Kicked %s from %s — reason: %s", member, ctx.guild.name, reason)

        embed = discord.Embed(
            title="👢 Member Kicked",
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Member",    value=f"{member.mention} ({member})", inline=False)
        embed.add_field(name="Reason",    value=reason,                         inline=False)
        embed.add_field(name="Moderator", value=ctx.author.mention,             inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    async def purge(self, ctx: commands.Context, count: int) -> None:
        """Delete the last N messages in this channel (max 100).

        **Requires:** Manage Messages permission
        **Cooldown:** Once every 5 seconds per server
        """
        count = min(count, 100)
        deleted = await ctx.channel.purge(limit=count + 1)  # +1 to include the command itself
        msg = await ctx.send(embed=self._ok(f"Deleted {len(deleted) - 1} messages."))
        await msg.delete(delay=5)

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def setlogchannel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        """Set a channel to log moderation actions.

        **Requires:** Administrator
        """
        set_guild_value(ctx.guild.id, "log_channel", channel.id)
        await ctx.send(embed=self._ok(f"Moderation log channel set to {channel.mention}"))

    # ── listeners ─────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        """Log bans to the configured log channel."""
        channel_id = get_guild_value(guild.id, "log_channel")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return

        embed = discord.Embed(
            title="🔨 Member Banned",
            description=f"{user.mention} ({user}) was banned.",
            color=discord.Color.dark_red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"ID: {user.id}")
        await channel.send(embed=embed)

    # ── error handlers ────────────────────────────────────────────────────────

    @purge.error
    async def purge_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(embed=self._err(f"Slow down! Try again in {error.retry_after:.1f}s."))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=self._err("Usage: `!purge <number>`"))
        else:
            raise error


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
```

Install it:
```bash
python launcher.py repos add /path/to/my_cogs
python launcher.py cogs install my_cogs moderation
python launcher.py cogs autoload my_cogs.moderation
```

---

## Quick Reference

| Decorator | What it does |
|-----------|-------------|
| `@commands.command()` | Registers a basic command |
| `@commands.group()` | Registers a command group (parent of subcommands) |
| `@commands.Cog.listener()` | Registers a Discord event listener |
| `@commands.is_owner()` | Restricts to bot owner(s) set in config.json |
| `@commands.has_permissions(kick_members=True)` | Requires user to have a permission |
| `@commands.bot_has_permissions(...)` | Requires the bot to have a permission |
| `@commands.guild_only()` | Prevents use in DMs |
| `@commands.dm_only()` | Restricts to DMs only |
| `@commands.cooldown(rate, per, type)` | Rate-limits the command |

| Type hint | What it accepts |
|-----------|----------------|
| `discord.Member` | A server member (@mention or ID) |
| `discord.User` | Any Discord user |
| `discord.TextChannel` | A text channel (#mention or ID) |
| `discord.Role` | A role (@mention or ID) |
| `int` | An integer |
| `float` | A decimal number |
| `str` | A single word |
| `*, text: str` | Everything the user typed (must be last argument) |

| Useful `ctx` attributes | Value |
|-------------------------|-------|
| `ctx.author` | The user who ran the command |
| `ctx.guild` | The server the command was run in |
| `ctx.channel` | The channel it was run in |
| `ctx.message` | The full message object |
| `ctx.bot` | The bot instance |
| `ctx.clean_prefix` | The prefix used (e.g. `!`) |
| `ctx.command` | The command that was invoked |
