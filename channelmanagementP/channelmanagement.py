from redbot.core import commands, Config, checks, modlog
import discord
from typing import Union
class ChannelManagement(commands.Cog):
    """Channel Management part of ModPlus"""
    def __init__(self, bot):
        self.bot = bot
        self.modplus = bot.get_cog("ModPlus")

    @commands.group()
    @commands.guild_only() # check this
    async def channel(self, ctx):
        """Channel Management Base Command Group"""
    
    # Create
    @channel.command()
    async def create(self, ctx, *, name: str):
        """Create a channel with everyone perms denied in no category. Use !channel move to move to desired location"""
        if not await self.modplus.action_check(ctx, 'editchannel'):
            return
        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            ctx.author: discord.PermissionOverwrite(read_messages=True)
        }
        channel : discord.TextChannel = await ctx.guild.create_text_channel(name, overwrites=overwrites)
        await ctx.send(f"Channel created: {channel.mention}")
        await self.modplus.notify('editchannel', f"Channel created: {channel.mention}")


    # Edit
    @channel.command()
    async def rename(self, ctx, channel: discord.TextChannel, *, name: str):
        """Rename the given the channel"""
        if not await self.modplus.action_check(ctx, 'editchannel'):
            return
        await channel.edit(name=name)
        await ctx.send(f"Channel renamed: {channel.mention}")
        await self.modplus.notify('editchannel', f"Channel renamed: {channel.mention}")

    @channel.command()
    async def category(self, ctx, channel: discord.TextChannel, category: discord.CategoryChannel = None):
        """Change category, use category id for category. Leave blank to set to no category"""
        if not await self.modplus.action_check(ctx, 'editchannel'):
            return
        await channel.edit(category=category)
        await ctx.send(f"Channel moved: {channel.mention} to {category.name}")
        await self.modplus.notify('editchannel', f"Channel moved: {channel.mention} to {category.name}")

    @channel.command()
    async def position(self, ctx, channel: discord.TextChannel, pos: int):
        """Change category position. First channel in category = 0"""
        if not await self.modplus.action_check(ctx, 'editchannel'):
            return
        try:
            await channel.edit(position=pos)
        except discord.InvalidArgument:
            return await ctx.send("Position number invalid")
        await ctx.send(f"Channel moved position :{channel.mention}")
        await self.modplus.notify('editchannel', f"Channel moved position :{channel.mention}")


    # Add / Remove
    @channel.group()
    async def perms(self, ctx):
        """Add or remove someone from a channel; Target can be a role, a user or everyone"""
        pass

    @perms.group()
    async def read(self, ctx):
        """Add / Remove someone to reading a channel. Sending messages will be set to Neutral"""
        pass

    @read.command(name="add")
    async def readadd(self, ctx, channel: discord.TextChannel, target: Union[discord.Role, discord.Member, str]):
        """Add a role / member to viewing a channel"""
        if not await self.modplus.action_check(ctx, 'channelperms'):
            return

        if isinstance(target, str):
            if target != 'everyone':
                return await ctx.send("Invalid Target")
            target = ctx.guild.default_role
        
        overwrites = channel.overwrites
        if target in overwrites:
            overwrites[target].read_messages = True
        else:
            overwrites[target] = discord.PermissionOverwrite(read_messages=True)
        await channel.edit(overwrites=overwrites)
        await ctx.send("Done")
        await self.modplus.notify('channelperms', f"Permissions Added in {channel.id} ({channel.guild.name}) - {target} can now read.")

    @read.command(name="deny")
    async def readdeny(self, ctx, channel: discord.TextChannel, target: Union[discord.Role, discord.Member, str]):
        """Deny a role / member from viewing a channel"""
        if not await self.modplus.action_check(ctx, 'channelperms'):
            return

        if isinstance(target, str):
            if target != 'everyone':
                return await ctx.send("Invalid Target")
            target = ctx.guild.default_role
        overwrites = channel.overwrites
        if target in overwrites:
            overwrites[target].read_messages = False
        else:
            overwrites[target] = discord.PermissionOverwrite(read_messages=False)
        await channel.edit(overwrites=overwrites)
        await ctx.send("Done")
        await self.modplus.notify('channelperms', f"Permissions Added in {channel.id} ({channel.guild.name}) - {target} can now not read.")

    @perms.group()
    async def send(self, ctx):
        """Add / Remove someone to sending messages in a channel"""
        pass

    @send.command(name="add")
    async def sendadd(self, ctx, channel: discord.TextChannel, target: Union[discord.Role, discord.Member, str]):
        """Add a role / member to sending messages in a channel"""
        if not await self.modplus.action_check(ctx, 'channelperms'):
            return
        
        if isinstance(target, str):
            if target != 'everyone':
                return await ctx.send("Invalid Target")
            target = ctx.guild.default_role

        overwrites = channel.overwrites
        if target in overwrites:
            overwrites[target].send_messages = True
        else:
            overwrites[target] = discord.PermissionOverwrite(send_messages=True)
        await channel.edit(overwrites=overwrites)
        await ctx.send("Done")
        await self.modplus.notify('channelperms', f"Permissions Added in {channel.id} ({channel.guild.name}) - {target} can now send message.")

    @send.command(name="deny")
    async def senddeny(self, ctx, channel: discord.TextChannel, target: Union[discord.Role, discord.Member, str]):
        """Deny a role / member from sending messages in a channel. This is really the same as a channel mute."""
        if not await self.modplus.action_check(ctx, 'channelperms'):
            return
        
        if isinstance(target, str):
            if target != 'everyone':
                return await ctx.send("Invalid Target")
            target = ctx.guild.default_role

        overwrites = channel.overwrites
        if target in overwrites:
            overwrites[target].send_messages = False
        else:
            overwrites[target] = discord.PermissionOverwrite(send_messages=False)
        await channel.edit(overwrites=overwrites)
        await ctx.send("Done")
        await self.modplus.notify('channelperms', f"Permissions Added in {channel.id} ({channel.guild.name}) - {target} can now not send messages.")


    # Move (reorder)

    