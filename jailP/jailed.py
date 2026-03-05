from redbot.core import checks, Config, commands, modlog
import discord

class Jail(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=2345664456)
        default_member = {"roles":[],
                          "is_jailed": False,
                          "has_no_role": False}

        default_guild = {'jailed_role': None}
        self.config.register_member(**default_member)
        self.config.register_guild(**default_guild)

    async def initialize(self, bot):
        await self.register_casetypes()

    @staticmethod
    async def register_casetypes():
        jail_cases = [
        
            {
            "name": "jailed",
            "default_setting": True,
            "image": "<:pandacop:375143122474369046>",
            "case_str": "**Jailed**",
            },
            {
            "name": "bailed",
            "default_setting": True,
            "image": "<:pandacop:375143122474369046>",
            "case_str": "**Bailed**",
            }
        ]
        try:
            await modlog.register_casetypes(jail_cases)
        except RuntimeError:
            pass

    @commands.command()
    # @checks.mod_or_permissions()
    async def jail(self, ctx, user: discord.Member, *,reason:str = None):
        """Send a member to jail, removing all their roles and adding the jailed role"""
        modplus = ctx.bot.get_cog("ModPlus")
        if not await modplus.action_check(ctx, "jail"):
            return
        if ctx.author != user:
            if ctx.me.top_role < user.top_role:
                return await ctx.send("I can't jail this person. They have a higher role than me.")
            if ctx.author.top_role > user.top_role:

                jail_id = await self.config.guild(ctx.guild).jailed_role()
                if jail_id is None:
                    return await ctx.send("Cannot jail as not jailed role has been set. Please do `!setjailrole @Role`")

                lst = await self.config.member(user).roles()


                user_is_jailed = await self.config.member(user).is_jailed()

                jailed_role = ctx.guild.get_role(jail_id)

                user_roles = user.roles

                if user_is_jailed:
                    await ctx.send("The user is jailed")

                else:
                    
                    await modlog.create_case(
                    ctx.bot, ctx.guild, ctx.message.created_at, action_type="jailed",
                    user=user, moderator=ctx.author, reason=reason
                )
            
                    if len(user_roles) == 1:
                        await user.add_roles(jailed_role) 
                        await self.config.member(user).is_jailed.set(True)
                        await self.config.member(user).has_no_role.set(True)
                        await ctx.send("Done, the member has been jailed")

                    else:
                        for role in user_roles:
                            if role.name == "@everyone":
                                continue
                            lst.append(role.id)
                            await user.remove_roles(role)
                        await self.config.member(user).roles.set(lst)
                        await user.add_roles(jailed_role)
                        await self.config.member(user).is_jailed.set(True)
                        await self.config.member(user).has_no_role.set(False)
                        await ctx.send("Done, the member has been jailed")
                        await modplus.notify('jail', f"{user.display_name} has been jailed for reason {reason}.")
                        
            else:
                await ctx.send("You can't jail a user who has a role greater than or equal to yours")
        else:
            await ctx.send("Please don't try these things for fun.")
                

    @commands.command()
    # @checks.mod_or_permissions()
    async def bailout(self, ctx, user: discord.Member, *, reason:str = None):
        """Bailout a member from jail, removing jailed role and adding back all previous roles"""
        modplus = ctx.bot.get_cog("ModPlus")
        if not await modplus.action_check(ctx, "jail"):
            return
        jail_id = await self.config.guild(ctx.guild).jailed_role()
        lst = await self.config.member(user).roles()
        jailed_role = ctx.guild.get_role(jail_id)
        user_has_no_roles = await self.config.member(user).has_no_role()
        user_is_jailed = await self.config.member(user).is_jailed()

        if user_is_jailed:
            await modlog.create_case(
            ctx.bot, ctx.guild, ctx.message.created_at, action_type="bailed",
            user=user, moderator=ctx.author, reason=reason
            )

            if user_has_no_roles:
                await self.config.member(user).is_jailed.set(False)
                await self.config.member(user).has_no_role.set(False)
                await user.remove_roles(jailed_role)
                await ctx.send("The user had no roles so Jailed role has been removed")

            else:
                for roleid in lst:
                    role =  ctx.guild.get_role(roleid)
                    await user.add_roles(role)
                await self.config.member(user).is_jailed.set(False)
                await self.config.member(user).roles.clear()
                await user.remove_roles(jailed_role)
                await ctx.send("The user has been released from jail, roles have been added")
                await modplus.notify('jail', f"{user.display_name} has been bailed out from jail for reason {reason}.")
        else:
            await ctx.send("The user isn't in jail.")

    @commands.command()
    @checks.admin_or_permissions()
    async def setjailrole(self, ctx, role: discord.Role):
        """Set the jail role (if already made) otherwise it's recommended to do `!createjailedrole`"""
        role_id = role.id
        await self.config.guild(ctx.guild).jailed_role.set(role_id)
        await ctx.send("Done!")

    @commands.command()
    @checks.admin_or_permissions()
    async def forcebail(self, ctx, user: discord.Member):
        """This command is if any runtime error caused during bailing or jailing, this might not work"""
        lst = await self.config.member(user).roles()
        await self.config.member(user).is_jailed.set(False)
        for roleid in lst:
            role =  ctx.guild.get_role(roleid)
            await user.add_roles(role)
        await self.config.member(user).roles.clear()
        await ctx.send("Done... this might not have worked")

    
    @commands.command()
    async def createjailedrole(self, ctx, jailChannel: discord.TextChannel):
        """Create a jailed role with all channel overrides. This will override an already set jailed role."""
        async with ctx.typing():
            guild: discord.Guild = ctx.guild
            jailedrole : discord.Role = await guild.create_role(name="Jailed", reason="Jailed Role Creation")
            for channel in guild.text_channels:
                if channel == jailChannel:
                    await channel.set_permissions(jailedrole, read_messages=True, send_messages=True)
                    continue
                await channel.set_permissions(jailedrole, read_messages=False)
        await self.config.guild(ctx.guild).jailed_role.set(jailedrole.id)
        await ctx.send("Done!")

