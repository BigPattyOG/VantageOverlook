"""Package entrypoint for the VHelp cog."""

from .vhelp import VHelp


async def setup(bot):
    """Load the cog into Red."""
    await bot.add_cog(VHelp(bot))
