from .gangwars import GangWars


async def setup(bot):
    await bot.add_cog(GangWars(bot))
