from .channelmanagement import ChannelManagement

def setup(bot):
    bot.add_cog(ChannelManagement(bot))