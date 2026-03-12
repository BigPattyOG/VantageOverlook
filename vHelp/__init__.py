"""Package entrypoint for the VHelp cog."""

from .vhelp import VHelp


async def setup(bot):
    await bot.add_cog(VHelp(bot))
