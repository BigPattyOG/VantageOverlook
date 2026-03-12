"""Package entrypoint for the VMod cog."""

from .vmod import VMod


async def setup(bot):
    """Load the cog into Red."""
    await bot.add_cog(VMod(bot))
