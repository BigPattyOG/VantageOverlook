from .welcomer import Welcomer

async def setup(bot):
    cog = Welcomer(bot=bot)
    await cog.crtoken()
    await cog.load_menu_module()
    bot.add_cog(cog)