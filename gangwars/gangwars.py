"""
Gang Wars — A street gang management and PvP combat game for Red-DiscordBot.

Inspired by the classic BBS-era PimpWars game. Players hustle for cash,
recruit gang members, upgrade weapons and armor, rob banks, and wage war
against rival gangs to climb the leaderboard.

Mechanics summary:
  - Turn-based economy: every meaningful action costs turns, which regenerate
    hourly (5 per hour, cap 50).
  - Cash earned via Hustle (safe, low yield) or Rob Bank (risky, high yield).
  - Gang members multiply both income and combat power but can be killed in battle.
  - Weapons (attack) and Armor (defense) each have 10 levels with exponentially
    increasing upgrade costs.
  - PvP combat uses a power formula with randomness; winner steals 15% of the
    loser's cash and kills some of their members.
  - Critical hits (10% chance) double one side's power roll.
  - Knocked-out players (0 HP) cannot act until healed.
  - Net-worth leaderboard: cash + members + upgrade values.
  - Admins can run seasonal resets to keep competition fresh.
"""

import asyncio
import math
import random
from datetime import datetime, timezone
from typing import Optional

import discord
from redbot.core import Config, checks, commands
from redbot.core.utils.chat_formatting import box, humanize_number, pagify
from redbot.core.utils.menus import DEFAULT_CONTROLS, menu


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STARTING_CASH = 1_000
STARTING_MEMBERS = 5
STARTING_HEALTH = 100
MAX_HEALTH = 100
STARTING_TURNS = 20
MAX_TURNS = 50
TURNS_PER_REGEN = 5          # turns restored each regen tick
REGEN_INTERVAL = 3_600       # seconds between regen ticks (1 hour)

MEMBER_COST = 200            # cash to recruit a single member
MEMBER_INCOME = 50           # cash earned per member per hustle
MEMBER_COMBAT_WEIGHT = 1.0   # scaling factor for members in combat

WEAPON_BASE_COST = 500
WEAPON_COST_MULTIPLIER = 2.0
ARMOR_BASE_COST = 500
ARMOR_COST_MULTIPLIER = 2.0
MAX_UPGRADE_LEVEL = 10

HEAL_COST_PER_HP = 10

BASE_ATK = 10
BASE_DEF = 8
CRIT_CHANCE = 0.10           # 10% chance per side per fight
STEAL_PERCENTAGE = 0.15      # fraction of defender's cash stolen on win
COUNTER_DAMAGE_FACTOR = 0.40 # fraction of def_power applied as counter-damage
MEMBER_KILL_DIVISOR = 30     # higher = fewer members die per fight

HUSTLE_BASE_INCOME = 100
HUSTLE_TURNS_COST = 1

ROB_SUCCESS_RATE = 0.55
ROB_BASE_REWARD = 500
ROB_REWARD_VARIANCE = 1_000
ROB_FAIL_PENALTY = 200
ROB_FAIL_HP_LOSS = 10
ROB_TURNS_COST = 3

ATTACK_TURNS_COST = 2
RECRUIT_TURNS_COST = 1
HEAL_TURNS_COST = 1
UPGRADE_TURNS_COST = 1

# Net-worth valuation weights for leaderboard
NW_MEMBER_VALUE = 200
NW_WEAPON_VALUE = 1_000
NW_ARMOR_VALUE = 1_000

# Embed colour (dark red / gang red)
EMBED_COLOR = 0xC0392B

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _upgrade_cost(base: int, multiplier: float, current_level: int) -> int:
    """Return the cash cost to upgrade from current_level to current_level+1."""
    return int(base * (multiplier ** current_level))


def _net_worth(data: dict) -> int:
    return (
        data["cash"]
        + data["members"] * NW_MEMBER_VALUE
        + data["weapons_level"] * NW_WEAPON_VALUE
        + data["armor_level"] * NW_ARMOR_VALUE
    )


def _status_embed(member: discord.Member, data: dict, rank: Optional[int] = None) -> discord.Embed:
    """Build a rich embed displaying a player's full stats."""
    gang_name = data["gang_name"] or member.display_name
    hp_bar = _hp_bar(data["health"])
    knocked_out = data["health"] <= 0
    status_str = "**KNOCKED OUT**" if knocked_out else "Active"

    embed = discord.Embed(
        title=f"Gang: {gang_name}",
        color=EMBED_COLOR,
        description=f"Run by {member.mention} | Status: {status_str}",
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    embed.add_field(name="Health", value=f"{hp_bar} {data['health']}/{MAX_HEALTH}", inline=False)
    embed.add_field(name="Cash", value=f"${humanize_number(data['cash'])}", inline=True)
    embed.add_field(name="Gang Members", value=str(data["members"]), inline=True)
    embed.add_field(name="Turns Left", value=f"{data['turns']}/{MAX_TURNS}", inline=True)
    embed.add_field(name="Weapons Level", value=f"Lvl {data['weapons_level']}/10 ⚔️", inline=True)
    embed.add_field(name="Armor Level", value=f"Lvl {data['armor_level']}/10 🛡️", inline=True)
    nw = _net_worth(data)
    rank_str = f"#{rank}" if rank else "N/A"
    embed.add_field(name="Net Worth", value=f"${humanize_number(nw)} (Rank {rank_str})", inline=True)
    embed.add_field(name="W / L", value=f"{data['wins']} W / {data['losses']} L", inline=True)
    embed.add_field(
        name="Members Killed / Lost",
        value=f"{data['kills']} killed / {data['deaths']} lost",
        inline=True,
    )

    # Next upgrade costs
    next_wpn_lvl = data["weapons_level"]
    next_arm_lvl = data["armor_level"]
    if next_wpn_lvl < MAX_UPGRADE_LEVEL:
        wpn_cost = _upgrade_cost(WEAPON_BASE_COST, WEAPON_COST_MULTIPLIER, next_wpn_lvl)
        wpn_str = f"${humanize_number(wpn_cost)} → Lvl {next_wpn_lvl + 1}"
    else:
        wpn_str = "MAX LEVEL"
    if next_arm_lvl < MAX_UPGRADE_LEVEL:
        arm_cost = _upgrade_cost(ARMOR_BASE_COST, ARMOR_COST_MULTIPLIER, next_arm_lvl)
        arm_str = f"${humanize_number(arm_cost)} → Lvl {next_arm_lvl + 1}"
    else:
        arm_str = "MAX LEVEL"
    embed.add_field(name="Next Weapons Upgrade", value=wpn_str, inline=True)
    embed.add_field(name="Next Armor Upgrade", value=arm_str, inline=True)

    return embed


def _hp_bar(hp: int, length: int = 10) -> str:
    filled = max(0, round((hp / MAX_HEALTH) * length))
    return "█" * filled + "░" * (length - filled)


def _combat_power(members: int, upgrade_level: int, base: int) -> int:
    """Calculate raw combat power before randomness."""
    return int(members * MEMBER_COMBAT_WEIGHT * upgrade_level * base + base)


# ---------------------------------------------------------------------------
# Cog definition
# ---------------------------------------------------------------------------


class GangWars(commands.Cog):
    """
    Gang Wars — Build your street empire, crush your rivals, rule the city.

    A persistent multiplayer strategy game inspired by the classic PimpWars
    BBS game. Hustle for cash, recruit soldiers, upgrade your arsenal, rob
    banks, and attack rival gangs to become the most powerful crew on the
    server.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=7_777_777_777, force_registration=True
        )

        default_guild = {
            "game_active": True,
            "channel_id": None,
            "season": 1,
            "announce_attacks": True,  # broadcast fight results in the game channel
        }

        default_member = {
            "registered": False,
            "gang_name": "",
            "cash": STARTING_CASH,
            "health": STARTING_HEALTH,
            "members": STARTING_MEMBERS,
            "weapons_level": 1,
            "armor_level": 1,
            "turns": STARTING_TURNS,
            "last_regen": None,      # ISO timestamp of last turn regen
            "wins": 0,
            "losses": 0,
            "kills": 0,              # enemy members eliminated
            "deaths": 0,             # own members lost
            "total_earned": 0,
            "times_robbed": 0,       # times this player was successfully robbed
        }

        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)

        self._regen_task = self.bot.loop.create_task(self._turn_regen_loop())

    def cog_unload(self):
        self._regen_task.cancel()

    # ------------------------------------------------------------------
    # Background task — turn regeneration
    # ------------------------------------------------------------------

    async def _turn_regen_loop(self):
        """Every REGEN_INTERVAL seconds, give all registered players more turns."""
        await self.bot.wait_until_ready()
        while True:
            await asyncio.sleep(REGEN_INTERVAL)
            try:
                await self._regen_all_turns()
            except Exception:
                pass  # never let the loop die silently crashing the bot

    async def _regen_all_turns(self):
        all_guilds = await self.config.all_guilds()
        for guild_id, guild_data in all_guilds.items():
            if not guild_data.get("game_active", True):
                continue
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            all_members = await self.config.all_members(guild)
            for member_id, member_data in all_members.items():
                if not member_data.get("registered", False):
                    continue
                current_turns = member_data.get("turns", 0)
                if current_turns < MAX_TURNS:
                    new_turns = min(MAX_TURNS, current_turns + TURNS_PER_REGEN)
                    await self.config.member_from_ids(guild_id, member_id).turns.set(new_turns)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_rank(self, guild: discord.Guild, member_id: int) -> int:
        """Return 1-based rank by net worth for the given member."""
        all_members = await self.config.all_members(guild)
        registered = [
            (mid, _net_worth(d))
            for mid, d in all_members.items()
            if d.get("registered", False)
        ]
        registered.sort(key=lambda x: x[1], reverse=True)
        for idx, (mid, _) in enumerate(registered, start=1):
            if mid == member_id:
                return idx
        return len(registered)

    async def _ensure_registered(self, ctx: commands.Context) -> Optional[dict]:
        """Return member data or send an error and return None."""
        data = await self.config.member(ctx.author).all()
        if not data["registered"]:
            await ctx.send(
                f"You haven't joined Gang Wars yet! Use `{ctx.clean_prefix}gangwars join <gang name>` to start."
            )
            return None
        return data

    async def _game_channel_check(self, ctx: commands.Context) -> bool:
        """Return True if the command is being used in the correct channel (or none is set)."""
        channel_id = await self.config.guild(ctx.guild).channel_id()
        if channel_id and ctx.channel.id != channel_id:
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                await ctx.send(f"Gang Wars commands must be used in {channel.mention}.")
            return False
        return True

    async def _announce(self, guild: discord.Guild, embed: discord.Embed):
        """Post an announcement embed to the configured game channel, if any."""
        channel_id = await self.config.guild(guild).channel_id()
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    pass

    # ------------------------------------------------------------------
    # Top-level command group
    # ------------------------------------------------------------------

    @commands.group(name="gangwars", aliases=["gw"], invoke_without_command=True)
    @commands.guild_only()
    async def gangwars(self, ctx: commands.Context):
        """Gang Wars — Build your crew, stack cash, destroy your rivals."""
        await ctx.send_help(ctx.command)

    # ------------------------------------------------------------------
    # Player registration
    # ------------------------------------------------------------------

    @gangwars.command(name="join")
    @commands.guild_only()
    async def gw_join(self, ctx: commands.Context, *, gang_name: str):
        """
        Join Gang Wars and found your crew.

        Example: `[p]gangwars join The Iron Saints`
        """
        if not await self._game_channel_check(ctx):
            return

        data = await self.config.member(ctx.author).all()
        if data["registered"]:
            await ctx.send(f"You're already running **{data['gang_name']}**. You can't join twice!")
            return

        if len(gang_name) > 32:
            await ctx.send("Gang name must be 32 characters or fewer.")
            return

        # Check for duplicate gang name in this guild
        all_members = await self.config.all_members(ctx.guild)
        taken_names = {
            d["gang_name"].lower()
            for d in all_members.values()
            if d.get("registered", False)
        }
        if gang_name.lower() in taken_names:
            await ctx.send(f"The gang name **{gang_name}** is already taken. Choose another.")
            return

        await self.config.member(ctx.author).set_raw("registered", value=True)
        await self.config.member(ctx.author).set_raw("gang_name", value=gang_name)
        await self.config.member(ctx.author).set_raw("cash", value=STARTING_CASH)
        await self.config.member(ctx.author).set_raw("health", value=STARTING_HEALTH)
        await self.config.member(ctx.author).set_raw("members", value=STARTING_MEMBERS)
        await self.config.member(ctx.author).set_raw("weapons_level", value=1)
        await self.config.member(ctx.author).set_raw("armor_level", value=1)
        await self.config.member(ctx.author).set_raw("turns", value=STARTING_TURNS)
        await self.config.member(ctx.author).set_raw("wins", value=0)
        await self.config.member(ctx.author).set_raw("losses", value=0)
        await self.config.member(ctx.author).set_raw("kills", value=0)
        await self.config.member(ctx.author).set_raw("deaths", value=0)
        await self.config.member(ctx.author).set_raw("total_earned", value=0)
        await self.config.member(ctx.author).set_raw("times_robbed", value=0)

        embed = discord.Embed(
            title="A New Gang Has Risen!",
            description=(
                f"**{gang_name}** has hit the streets!\n\n"
                f"You start with:\n"
                f"• ${humanize_number(STARTING_CASH)} cash\n"
                f"• {STARTING_MEMBERS} gang members\n"
                f"• {STARTING_HEALTH} HP\n"
                f"• {STARTING_TURNS} turns\n"
                f"• Weapons Lvl 1 / Armor Lvl 1\n\n"
                f"Use `{ctx.clean_prefix}gangwars help` for a full command list."
            ),
            color=EMBED_COLOR,
        )
        embed.set_footer(text="Stay dangerous. Stay alive.")
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Status / profile
    # ------------------------------------------------------------------

    @gangwars.command(name="status", aliases=["me", "stats"])
    @commands.guild_only()
    async def gw_status(self, ctx: commands.Context):
        """Check your gang's current stats and standing."""
        if not await self._game_channel_check(ctx):
            return
        data = await self._ensure_registered(ctx)
        if data is None:
            return
        rank = await self._get_rank(ctx.guild, ctx.author.id)
        embed = _status_embed(ctx.author, data, rank)
        await ctx.send(embed=embed)

    @gangwars.command(name="profile")
    @commands.guild_only()
    async def gw_profile(self, ctx: commands.Context, target: discord.Member):
        """View another player's gang profile."""
        if not await self._game_channel_check(ctx):
            return
        data = await self.config.member(target).all()
        if not data["registered"]:
            await ctx.send(f"**{target.display_name}** hasn't joined Gang Wars.")
            return
        rank = await self._get_rank(ctx.guild, target.id)
        embed = _status_embed(target, data, rank)
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Hustle — safe income
    # ------------------------------------------------------------------

    @gangwars.command(name="hustle")
    @commands.guild_only()
    async def gw_hustle(self, ctx: commands.Context):
        """
        Put your crew to work on the streets for steady income.

        Costs {turns} turn. Income scales with your gang size.
        """.format(
            turns=HUSTLE_TURNS_COST
        )
        if not await self._game_channel_check(ctx):
            return
        data = await self._ensure_registered(ctx)
        if data is None:
            return

        if data["health"] <= 0:
            await ctx.send("Your gang is knocked out! Heal up before you can hustle.")
            return

        if data["turns"] < HUSTLE_TURNS_COST:
            await ctx.send(
                f"You need at least {HUSTLE_TURNS_COST} turn to hustle. You only have {data['turns']}. "
                f"Turns regenerate {TURNS_PER_REGEN} per hour (max {MAX_TURNS})."
            )
            return

        earned = HUSTLE_BASE_INCOME + data["members"] * MEMBER_INCOME + random.randint(0, 100)
        new_cash = data["cash"] + earned
        new_turns = data["turns"] - HUSTLE_TURNS_COST
        new_total = data["total_earned"] + earned

        await self.config.member(ctx.author).cash.set(new_cash)
        await self.config.member(ctx.author).turns.set(new_turns)
        await self.config.member(ctx.author).total_earned.set(new_total)

        embed = discord.Embed(
            title="Hustle Complete",
            description=(
                f"Your {data['members']} soldiers hit the streets.\n\n"
                f"**Earned:** ${humanize_number(earned)}\n"
                f"**Cash:** ${humanize_number(new_cash)}\n"
                f"**Turns remaining:** {new_turns}/{MAX_TURNS}"
            ),
            color=0x2ECC71,
        )
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Rob Bank — risky high-yield income
    # ------------------------------------------------------------------

    @gangwars.command(name="rob")
    @commands.guild_only()
    async def gw_rob(self, ctx: commands.Context):
        """
        Rob a bank for a massive payout — but the cops hit back hard on failure.

        Costs {turns} turns. 55% success rate.
        """.format(
            turns=ROB_TURNS_COST
        )
        if not await self._game_channel_check(ctx):
            return
        data = await self._ensure_registered(ctx)
        if data is None:
            return

        if data["health"] <= 0:
            await ctx.send("Your gang is knocked out! Heal up before planning a heist.")
            return

        if data["turns"] < ROB_TURNS_COST:
            await ctx.send(
                f"Robbing a bank costs {ROB_TURNS_COST} turns. You only have {data['turns']}."
            )
            return

        new_turns = data["turns"] - ROB_TURNS_COST
        await self.config.member(ctx.author).turns.set(new_turns)

        if random.random() < ROB_SUCCESS_RATE:
            # Scale reward slightly with weapons level
            reward = ROB_BASE_REWARD + random.randint(0, ROB_REWARD_VARIANCE)
            reward = int(reward * (1 + (data["weapons_level"] - 1) * 0.05))
            new_cash = data["cash"] + reward
            new_total = data["total_earned"] + reward
            await self.config.member(ctx.author).cash.set(new_cash)
            await self.config.member(ctx.author).total_earned.set(new_total)

            embed = discord.Embed(
                title="Bank Job — SUCCESS",
                description=(
                    f"Your crew storms the vault and makes it out clean!\n\n"
                    f"**Stolen:** ${humanize_number(reward)}\n"
                    f"**Cash:** ${humanize_number(new_cash)}\n"
                    f"**Turns remaining:** {new_turns}/{MAX_TURNS}"
                ),
                color=0x27AE60,
            )
        else:
            # Failure: lose cash and HP
            penalty = min(ROB_FAIL_PENALTY, data["cash"])
            hp_loss = ROB_FAIL_HP_LOSS
            new_cash = max(0, data["cash"] - penalty)
            new_hp = max(0, data["health"] - hp_loss)
            await self.config.member(ctx.author).cash.set(new_cash)
            await self.config.member(ctx.author).health.set(new_hp)

            embed = discord.Embed(
                title="Bank Job — BUSTED",
                description=(
                    f"The police were waiting. Your crew scatters!\n\n"
                    f"**Lost:** ${humanize_number(penalty)}\n"
                    f"**HP lost:** {hp_loss} (now {new_hp}/{MAX_HEALTH})\n"
                    f"**Cash:** ${humanize_number(new_cash)}\n"
                    f"**Turns remaining:** {new_turns}/{MAX_TURNS}"
                ),
                color=0xE74C3C,
            )
            if new_hp == 0:
                embed.add_field(
                    name="KNOCKED OUT",
                    value="You're flat on the pavement. Use `gangwars heal` to get back in action.",
                    inline=False,
                )
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Recruit gang members
    # ------------------------------------------------------------------

    @gangwars.command(name="recruit")
    @commands.guild_only()
    async def gw_recruit(self, ctx: commands.Context, amount: int):
        """
        Recruit new gang members to strengthen your crew.

        Each member costs $200. More members = more income and combat power.
        Costs 1 turn.

        Example: `[p]gangwars recruit 10`
        """
        if not await self._game_channel_check(ctx):
            return
        data = await self._ensure_registered(ctx)
        if data is None:
            return

        if amount <= 0:
            await ctx.send("You must recruit at least 1 member.")
            return

        if data["health"] <= 0:
            await ctx.send("Your gang is knocked out! Heal before recruiting.")
            return

        if data["turns"] < RECRUIT_TURNS_COST:
            await ctx.send(f"Recruiting costs {RECRUIT_TURNS_COST} turn. You have {data['turns']}.")
            return

        total_cost = amount * MEMBER_COST
        if data["cash"] < total_cost:
            max_affordable = data["cash"] // MEMBER_COST
            await ctx.send(
                f"Recruiting {amount} members costs ${humanize_number(total_cost)}, "
                f"but you only have ${humanize_number(data['cash'])}. "
                f"You can afford at most {max_affordable} members right now."
            )
            return

        new_cash = data["cash"] - total_cost
        new_members = data["members"] + amount
        new_turns = data["turns"] - RECRUIT_TURNS_COST

        await self.config.member(ctx.author).cash.set(new_cash)
        await self.config.member(ctx.author).members.set(new_members)
        await self.config.member(ctx.author).turns.set(new_turns)

        embed = discord.Embed(
            title="New Blood Recruited",
            description=(
                f"**{amount}** new soldiers join **{data['gang_name']}**!\n\n"
                f"**Cost:** ${humanize_number(total_cost)}\n"
                f"**Cash:** ${humanize_number(new_cash)}\n"
                f"**Gang members:** {new_members}\n"
                f"**Turns remaining:** {new_turns}/{MAX_TURNS}"
            ),
            color=0x3498DB,
        )
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Heal
    # ------------------------------------------------------------------

    @gangwars.command(name="heal")
    @commands.guild_only()
    async def gw_heal(self, ctx: commands.Context):
        """
        Patch up your gang to full health.

        Costs $10 per missing HP and 1 turn.
        """
        if not await self._game_channel_check(ctx):
            return
        data = await self._ensure_registered(ctx)
        if data is None:
            return

        if data["health"] >= MAX_HEALTH:
            await ctx.send("Your gang is already at full health — no need to heal.")
            return

        if data["turns"] < HEAL_TURNS_COST:
            await ctx.send(f"Healing costs {HEAL_TURNS_COST} turn. You have {data['turns']}.")
            return

        missing_hp = MAX_HEALTH - data["health"]
        heal_cost = missing_hp * HEAL_COST_PER_HP

        if data["cash"] < heal_cost:
            # Partial heal with available cash
            partial_hp = data["cash"] // HEAL_COST_PER_HP
            if partial_hp == 0:
                await ctx.send(
                    f"Full heal costs ${humanize_number(heal_cost)} but you have "
                    f"${humanize_number(data['cash'])}. You can't afford even partial healing right now."
                )
                return
            actual_cost = partial_hp * HEAL_COST_PER_HP
            new_hp = data["health"] + partial_hp
            new_cash = data["cash"] - actual_cost
            heal_msg = f"Partially healed (+{partial_hp} HP) for ${humanize_number(actual_cost)}."
        else:
            new_hp = MAX_HEALTH
            new_cash = data["cash"] - heal_cost
            heal_msg = f"Fully healed to {MAX_HEALTH} HP for ${humanize_number(heal_cost)}."

        new_turns = data["turns"] - HEAL_TURNS_COST
        await self.config.member(ctx.author).health.set(new_hp)
        await self.config.member(ctx.author).cash.set(new_cash)
        await self.config.member(ctx.author).turns.set(new_turns)

        embed = discord.Embed(
            title="Healed Up",
            description=(
                f"{heal_msg}\n\n"
                f"**HP:** {new_hp}/{MAX_HEALTH} {_hp_bar(new_hp)}\n"
                f"**Cash:** ${humanize_number(new_cash)}\n"
                f"**Turns remaining:** {new_turns}/{MAX_TURNS}"
            ),
            color=0x1ABC9C,
        )
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Upgrades
    # ------------------------------------------------------------------

    @gangwars.group(name="upgrade", invoke_without_command=True)
    @commands.guild_only()
    async def gw_upgrade(self, ctx: commands.Context):
        """Upgrade your gang's weapons or armor."""
        await ctx.send_help(ctx.command)

    @gw_upgrade.command(name="weapons", aliases=["weapon", "wpn"])
    @commands.guild_only()
    async def gw_upgrade_weapons(self, ctx: commands.Context):
        """
        Upgrade your weapons to deal more damage in combat.

        Weapon level directly multiplies your gang's attack power.
        Upgrade cost doubles each level (starts at $500).
        Costs 1 turn.
        """
        if not await self._game_channel_check(ctx):
            return
        data = await self._ensure_registered(ctx)
        if data is None:
            return
        await self._do_upgrade(ctx, data, "weapons")

    @gw_upgrade.command(name="armor", aliases=["armour"])
    @commands.guild_only()
    async def gw_upgrade_armor(self, ctx: commands.Context):
        """
        Upgrade your armor to absorb more damage in combat.

        Armor level directly multiplies your gang's defense power.
        Upgrade cost doubles each level (starts at $500).
        Costs 1 turn.
        """
        if not await self._game_channel_check(ctx):
            return
        data = await self._ensure_registered(ctx)
        if data is None:
            return
        await self._do_upgrade(ctx, data, "armor")

    async def _do_upgrade(self, ctx: commands.Context, data: dict, kind: str):
        """Shared logic for weapon and armor upgrades."""
        if data["health"] <= 0:
            await ctx.send("Your gang is knocked out! Heal before upgrading.")
            return

        if data["turns"] < UPGRADE_TURNS_COST:
            await ctx.send(f"Upgrading costs {UPGRADE_TURNS_COST} turn. You have {data['turns']}.")
            return

        level_key = f"{kind}s_level" if kind == "weapon" else f"{kind}_level"
        # Normalise key name
        if kind == "weapons":
            level_key = "weapons_level"
            base_cost = WEAPON_BASE_COST
            mult = WEAPON_COST_MULTIPLIER
            icon = "⚔️"
        else:
            level_key = "armor_level"
            base_cost = ARMOR_BASE_COST
            mult = ARMOR_COST_MULTIPLIER
            icon = "🛡️"

        current_level = data[level_key]
        if current_level >= MAX_UPGRADE_LEVEL:
            await ctx.send(f"Your {kind} is already at the maximum level ({MAX_UPGRADE_LEVEL})!")
            return

        cost = _upgrade_cost(base_cost, mult, current_level)
        if data["cash"] < cost:
            await ctx.send(
                f"Upgrading {kind} to level {current_level + 1} costs ${humanize_number(cost)}, "
                f"but you only have ${humanize_number(data['cash'])}."
            )
            return

        new_level = current_level + 1
        new_cash = data["cash"] - cost
        new_turns = data["turns"] - UPGRADE_TURNS_COST

        await self.config.member(ctx.author).set_raw(level_key, value=new_level)
        await self.config.member(ctx.author).cash.set(new_cash)
        await self.config.member(ctx.author).turns.set(new_turns)

        embed = discord.Embed(
            title=f"{kind.title()} Upgraded! {icon}",
            description=(
                f"**{data['gang_name']}** now wields Lvl {new_level} {kind}!\n\n"
                f"**Cost:** ${humanize_number(cost)}\n"
                f"**Cash:** ${humanize_number(new_cash)}\n"
                f"**Turns remaining:** {new_turns}/{MAX_TURNS}"
            ),
            color=0xF39C12,
        )
        if new_level < MAX_UPGRADE_LEVEL:
            next_cost = _upgrade_cost(base_cost, mult, new_level)
            embed.add_field(
                name="Next Upgrade",
                value=f"Lvl {new_level + 1} will cost ${humanize_number(next_cost)}",
                inline=False,
            )
        else:
            embed.add_field(name="MAX LEVEL REACHED", value="Your arsenal is legendary.", inline=False)
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Attack
    # ------------------------------------------------------------------

    @gangwars.command(name="attack", aliases=["raid", "hit"])
    @commands.guild_only()
    async def gw_attack(self, ctx: commands.Context, target: discord.Member):
        """
        Attack a rival gang to steal their cash and cripple their crew.

        Combat formula:
          Attack power = members × weapons_level × 10 + base
          Defense power = members × armor_level × 8 + base
          Both sides get a random bonus (0–50 / 0–40).
          10% chance of a CRITICAL HIT (doubles power roll).
          Winner steals 15% of loser's cash.
          Both sides lose members proportional to damage taken.

        Costs 2 turns. Cannot attack knocked-out players.
        """
        if not await self._game_channel_check(ctx):
            return

        if target == ctx.author:
            await ctx.send("You can't attack yourself.")
            return

        attacker_data = await self._ensure_registered(ctx)
        if attacker_data is None:
            return

        defender_data = await self.config.member(target).all()
        if not defender_data["registered"]:
            await ctx.send(f"**{target.display_name}** hasn't joined Gang Wars.")
            return

        if attacker_data["health"] <= 0:
            await ctx.send("Your gang is knocked out! Heal up before starting a war.")
            return

        if defender_data["health"] <= 0:
            await ctx.send(
                f"**{defender_data['gang_name']}** is already knocked out and can't be attacked. "
                f"They're no threat right now — find someone standing."
            )
            return

        if attacker_data["turns"] < ATTACK_TURNS_COST:
            await ctx.send(
                f"Attacking costs {ATTACK_TURNS_COST} turns. You only have {attacker_data['turns']}."
            )
            return

        # --- Calculate combat power ---
        atk_base = _combat_power(attacker_data["members"], attacker_data["weapons_level"], BASE_ATK)
        def_base = _combat_power(defender_data["members"], defender_data["armor_level"], BASE_DEF)

        atk_roll = random.randint(0, 50)
        def_roll = random.randint(0, 40)

        atk_crit = random.random() < CRIT_CHANCE
        def_crit = random.random() < CRIT_CHANCE

        atk_power = (atk_base + atk_roll) * (2 if atk_crit else 1)
        def_power = (def_base + def_roll) * (2 if def_crit else 1)

        # --- Apply damage ---
        # Damage dealt to defender = net difference (floored at 1)
        dmg_to_defender = max(1, atk_power - def_power)
        # Attacker always takes counter-damage
        counter_dmg = max(1, int(def_power * COUNTER_DAMAGE_FACTOR))

        new_def_hp = max(0, defender_data["health"] - dmg_to_defender)
        new_atk_hp = max(0, attacker_data["health"] - counter_dmg)

        # Members killed proportional to damage (attacker kills defender's members)
        def_members_killed = min(
            defender_data["members"],
            max(0, dmg_to_defender // MEMBER_KILL_DIVISOR),
        )
        atk_members_lost = min(
            attacker_data["members"],
            max(0, counter_dmg // MEMBER_KILL_DIVISOR),
        )

        new_def_members = defender_data["members"] - def_members_killed
        new_atk_members = attacker_data["members"] - atk_members_lost
        new_atk_turns = attacker_data["turns"] - ATTACK_TURNS_COST

        attacker_wins = atk_power > def_power

        # --- Cash transfer on win ---
        stolen = 0
        if attacker_wins:
            stolen = int(defender_data["cash"] * STEAL_PERCENTAGE)
            new_atk_cash = attacker_data["cash"] + stolen
            new_def_cash = defender_data["cash"] - stolen
        else:
            new_atk_cash = attacker_data["cash"]
            new_def_cash = defender_data["cash"]

        # --- Persist all changes atomically ---
        await self.config.member(ctx.author).health.set(new_atk_hp)
        await self.config.member(ctx.author).cash.set(new_atk_cash)
        await self.config.member(ctx.author).members.set(max(0, new_atk_members))
        await self.config.member(ctx.author).turns.set(new_atk_turns)
        await self.config.member(ctx.author).kills.set(attacker_data["kills"] + def_members_killed)
        await self.config.member(ctx.author).deaths.set(attacker_data["deaths"] + atk_members_lost)

        await self.config.member(target).health.set(new_def_hp)
        await self.config.member(target).cash.set(new_def_cash)
        await self.config.member(target).members.set(max(0, new_def_members))

        if attacker_wins:
            await self.config.member(ctx.author).wins.set(attacker_data["wins"] + 1)
            await self.config.member(target).losses.set(defender_data["losses"] + 1)
            await self.config.member(target).times_robbed.set(defender_data["times_robbed"] + 1)
        else:
            await self.config.member(ctx.author).losses.set(attacker_data["losses"] + 1)
            await self.config.member(target).wins.set(defender_data["wins"] + 1)

        # --- Build result embed ---
        outcome_color = 0x27AE60 if attacker_wins else 0xE74C3C
        outcome_title = (
            f"⚔️ VICTORY — {attacker_data['gang_name']} raids {defender_data['gang_name']}!"
            if attacker_wins
            else f"💀 DEFEAT — {attacker_data['gang_name']} gets repelled by {defender_data['gang_name']}!"
        )

        embed = discord.Embed(title=outcome_title, color=outcome_color)
        embed.add_field(
            name=f"⚔️ {attacker_data['gang_name']} (Attacker)",
            value=(
                f"Power: **{atk_power}**{'  💥 CRIT!' if atk_crit else ''}\n"
                f"HP: {attacker_data['health']} → {new_atk_hp} (-{counter_dmg})\n"
                f"Members: {attacker_data['members']} → {max(0, new_atk_members)} (-{atk_members_lost})\n"
                f"Cash: ${humanize_number(new_atk_cash)}"
                + (f" (+${humanize_number(stolen)} stolen)" if attacker_wins else "")
            ),
            inline=True,
        )
        embed.add_field(
            name=f"🛡️ {defender_data['gang_name']} (Defender)",
            value=(
                f"Power: **{def_power}**{'  💥 CRIT!' if def_crit else ''}\n"
                f"HP: {defender_data['health']} → {new_def_hp} (-{dmg_to_defender})\n"
                f"Members: {defender_data['members']} → {max(0, new_def_members)} (-{def_members_killed})\n"
                f"Cash: ${humanize_number(new_def_cash)}"
                + (f" (-${humanize_number(stolen)} stolen)" if attacker_wins else "")
            ),
            inline=True,
        )

        ko_notes = []
        if new_atk_hp == 0:
            ko_notes.append(f"💀 **{attacker_data['gang_name']} has been KNOCKED OUT!**")
        if new_def_hp == 0:
            ko_notes.append(f"💀 **{defender_data['gang_name']} has been KNOCKED OUT!**")
        if ko_notes:
            embed.add_field(name="Casualties", value="\n".join(ko_notes), inline=False)

        embed.set_footer(text=f"Turns remaining: {new_atk_turns}/{MAX_TURNS}")
        await ctx.send(embed=embed)

        # Announce to game channel if configured and command was elsewhere
        announce = await self.config.guild(ctx.guild).announce_attacks()
        channel_id = await self.config.guild(ctx.guild).channel_id()
        if announce and channel_id and ctx.channel.id != channel_id:
            await self._announce(ctx.guild, embed)

        # DM the defender
        try:
            dm_embed = discord.Embed(
                title=f"Your gang was attacked by {attacker_data['gang_name']}!",
                description=(
                    f"{'You were raided and lost cash!' if attacker_wins else 'You held your ground!'}\n"
                    f"HP: {defender_data['health']} → {new_def_hp}\n"
                    f"Members: {defender_data['members']} → {max(0, new_def_members)}\n"
                    f"Cash: ${humanize_number(new_def_cash)}"
                ),
                color=outcome_color,
            )
            await target.send(embed=dm_embed)
        except discord.Forbidden:
            pass  # DMs disabled — that's fine

    # ------------------------------------------------------------------
    # Rankings / Leaderboard
    # ------------------------------------------------------------------

    @gangwars.command(name="rankings", aliases=["leaderboard", "lb", "top"])
    @commands.guild_only()
    async def gw_rankings(self, ctx: commands.Context):
        """Display the Gang Wars leaderboard, ranked by net worth."""
        if not await self._game_channel_check(ctx):
            return

        all_members = await self.config.all_members(ctx.guild)
        registered = []
        for member_id, data in all_members.items():
            if not data.get("registered", False):
                continue
            member = ctx.guild.get_member(member_id)
            display = data["gang_name"] or (member.display_name if member else f"<{member_id}>")
            nw = _net_worth(data)
            registered.append((display, data, nw))

        if not registered:
            await ctx.send("No gangs are registered yet! Use `gangwars join` to start.")
            return

        registered.sort(key=lambda x: x[2], reverse=True)

        # Season info
        season = await self.config.guild(ctx.guild).season()

        pages = []
        per_page = 10
        for page_start in range(0, len(registered), per_page):
            page_entries = registered[page_start: page_start + per_page]
            lines = [f"**Gang Wars — Season {season} Leaderboard**\n"]
            for rank, (name, data, nw) in enumerate(page_entries, start=page_start + 1):
                medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"`#{rank}`")
                hp_indicator = "💀" if data["health"] <= 0 else "✅"
                lines.append(
                    f"{medal} **{name}** {hp_indicator} — "
                    f"${humanize_number(nw)} NW | "
                    f"{data['members']} members | "
                    f"W{data['wins']}/L{data['losses']}"
                )
            embed = discord.Embed(
                description="\n".join(lines),
                color=EMBED_COLOR,
            )
            embed.set_footer(
                text=f"Page {page_start // per_page + 1}/{math.ceil(len(registered) / per_page)}"
            )
            pages.append(embed)

        if len(pages) == 1:
            await ctx.send(embed=pages[0])
        else:
            await menu(ctx, pages, DEFAULT_CONTROLS)

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    @gangwars.command(name="help", aliases=["commands", "howto"])
    @commands.guild_only()
    async def gw_help(self, ctx: commands.Context):
        """Show a full Gang Wars command reference and game guide."""
        prefix = ctx.clean_prefix
        embed = discord.Embed(
            title="Gang Wars — Command Reference",
            description=(
                "Build your criminal empire. Crush your rivals. Rule the streets.\n"
                "All commands begin with `" + prefix + "gangwars` (alias: `" + prefix + "gw`)."
            ),
            color=EMBED_COLOR,
        )

        embed.add_field(
            name="Getting Started",
            value=(
                f"`{prefix}gw join <name>` — Found your gang\n"
                f"`{prefix}gw status` — View your stats\n"
                f"`{prefix}gw profile @user` — View someone else's stats\n"
                f"`{prefix}gw rankings` — Leaderboard"
            ),
            inline=False,
        )
        embed.add_field(
            name="Making Money",
            value=(
                f"`{prefix}gw hustle` — Earn cash (1 turn, safe)\n"
                f"`{prefix}gw rob` — Rob a bank (3 turns, 55% success, high reward)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Building Your Crew",
            value=(
                f"`{prefix}gw recruit <amount>` — Hire members ($200 each, 1 turn)\n"
                f"`{prefix}gw heal` — Restore HP ($10/HP, 1 turn)\n"
                f"`{prefix}gw upgrade weapons` — Boost attack power (1 turn)\n"
                f"`{prefix}gw upgrade armor` — Boost defense (1 turn)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Combat",
            value=(
                f"`{prefix}gw attack @user` — Raid a rival gang (2 turns)\n"
                "• Win → steal 15% of their cash, kill some members\n"
                "• Lose → take counter-damage, no loot\n"
                "• 10% crit chance doubles your power roll\n"
                "• Knocked-out gangs (0 HP) cannot be attacked"
            ),
            inline=False,
        )
        embed.add_field(
            name="Economy",
            value=(
                f"Turns regenerate **{TURNS_PER_REGEN}/hour** (max {MAX_TURNS})\n"
                f"Net Worth = Cash + Members×$200 + Weapons Lvl×$1000 + Armor Lvl×$1000\n"
                f"Upgrade costs double each level (Weapons & Armor: $500 base)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Admin Commands",
            value=(
                f"`{prefix}gw setup` — Set the game channel\n"
                f"`{prefix}gw seasonreset` — Wipe all data and start a new season\n"
                f"`{prefix}gw addturns @user <n>` — Grant turns to a player\n"
                f"`{prefix}gw addcash @user <n>` — Grant cash to a player\n"
                f"`{prefix}gw wipe @user` — Delete a player's data\n"
                f"`{prefix}gw toggleannounce` — Toggle attack announcements in game channel"
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Admin commands
    # ------------------------------------------------------------------

    @gangwars.command(name="setup")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def gw_setup(self, ctx: commands.Context):
        """Set the current channel as the Gang Wars game channel."""
        await self.config.guild(ctx.guild).channel_id.set(ctx.channel.id)
        await ctx.send(
            f"Gang Wars game channel set to {ctx.channel.mention}. "
            f"All game commands should be used here."
        )

    @gangwars.command(name="seasonreset")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def gw_season_reset(self, ctx: commands.Context):
        """
        **[ADMIN]** Wipe all player data and start a new season.

        This is irreversible. A confirmation prompt will be shown.
        """
        await ctx.send(
            "⚠️ **Are you sure you want to reset all Gang Wars data and start a new season?**\n"
            "This will delete every player's gang, cash, stats, and progress.\n"
            "Type `CONFIRM RESET` within 30 seconds to proceed."
        )

        def check(m):
            return (
                m.author == ctx.author
                and m.channel == ctx.channel
                and m.content.strip().upper() == "CONFIRM RESET"
            )

        try:
            await self.bot.wait_for("message", check=check, timeout=30)
        except asyncio.TimeoutError:
            await ctx.send("Season reset cancelled — timed out.")
            return

        # Clear all member data in this guild
        all_members = await self.config.all_members(ctx.guild)
        for member_id in all_members:
            await self.config.member_from_ids(ctx.guild.id, member_id).clear()

        current_season = await self.config.guild(ctx.guild).season()
        new_season = current_season + 1
        await self.config.guild(ctx.guild).season.set(new_season)

        embed = discord.Embed(
            title=f"Season {new_season} Has Begun!",
            description=(
                "All gangs have been wiped. The streets are empty.\n"
                "It's time to build your empire from scratch.\n\n"
                f"Use `{ctx.clean_prefix}gangwars join <name>` to start your new crew."
            ),
            color=EMBED_COLOR,
        )
        await ctx.send(embed=embed)

    @gangwars.command(name="addturns")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def gw_add_turns(self, ctx: commands.Context, target: discord.Member, amount: int):
        """**[ADMIN]** Grant extra turns to a player."""
        data = await self.config.member(target).all()
        if not data["registered"]:
            await ctx.send(f"{target.display_name} hasn't joined Gang Wars.")
            return
        new_turns = min(MAX_TURNS, data["turns"] + amount)
        await self.config.member(target).turns.set(new_turns)
        await ctx.send(
            f"Gave **{amount}** turns to **{data['gang_name']}**. "
            f"They now have {new_turns}/{MAX_TURNS} turns."
        )

    @gangwars.command(name="addcash")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def gw_add_cash(self, ctx: commands.Context, target: discord.Member, amount: int):
        """**[ADMIN]** Grant cash to a player."""
        data = await self.config.member(target).all()
        if not data["registered"]:
            await ctx.send(f"{target.display_name} hasn't joined Gang Wars.")
            return
        new_cash = data["cash"] + amount
        await self.config.member(target).cash.set(new_cash)
        await ctx.send(
            f"Gave **${humanize_number(amount)}** to **{data['gang_name']}**. "
            f"They now have ${humanize_number(new_cash)}."
        )

    @gangwars.command(name="wipe")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def gw_wipe(self, ctx: commands.Context, target: discord.Member):
        """**[ADMIN]** Delete a specific player's Gang Wars data."""
        data = await self.config.member(target).all()
        if not data["registered"]:
            await ctx.send(f"{target.display_name} has no Gang Wars data to delete.")
            return
        gang_name = data["gang_name"]
        await self.config.member(target).clear()
        await ctx.send(f"Deleted all Gang Wars data for **{gang_name}** ({target.display_name}).")

    @gangwars.command(name="toggleannounce")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def gw_toggle_announce(self, ctx: commands.Context):
        """**[ADMIN]** Toggle whether attack results are announced in the game channel."""
        current = await self.config.guild(ctx.guild).announce_attacks()
        new_val = not current
        await self.config.guild(ctx.guild).announce_attacks.set(new_val)
        state = "enabled" if new_val else "disabled"
        await ctx.send(f"Attack announcements in the game channel are now **{state}**.")
