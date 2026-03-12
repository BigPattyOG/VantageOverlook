from .verrors import VErrors
from .safeui import VErrorSafeView
from .decorators import error_family, error_meta, error_slot


async def setup(bot):
    await bot.add_cog(VErrors(bot))
