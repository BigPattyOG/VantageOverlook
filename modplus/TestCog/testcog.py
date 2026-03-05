from redbot.core import commands
# from ..modplus import ModPlus


class TestCog():
    """Hello World test cog"""

    @commands.command()
    async def hworld(self, ctx):
        """Prints hello world"""
        modplus = ctx.bot.get_cog("ModPlus")
        if not await modplus.action_check(ctx, "kick"):
            return
        await ctx.send("Hello World")
        await modplus.notify('kick', "PAYLOAD")