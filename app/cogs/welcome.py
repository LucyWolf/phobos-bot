import discord
from discord.ext import commands
from database import get_guild_config


def fill(template: str, member: discord.Member) -> str:
    return (
        template
        .replace("{user}", member.mention)
        .replace("{username}", str(member))
        .replace("{server}", member.guild.name)
        .replace("{count}", str(member.guild.member_count))
    )


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        channel_id = await get_guild_config(member.guild.id, "welcome_channel")
        message = await get_guild_config(member.guild.id, "welcome_message")
        if not channel_id or not message:
            return
        channel = self.bot.get_channel(int(channel_id))
        if channel:
            embed = discord.Embed(description=fill(message, member), color=0x22c55e)
            embed.set_author(name=str(member), icon_url=member.display_avatar.url)
            await channel.send(embed=embed)

        role_id = await get_guild_config(member.guild.id, "autorole")
        if role_id:
            role = member.guild.get_role(int(role_id))
            if role:
                await member.add_roles(role, reason="Autorole")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        channel_id = await get_guild_config(member.guild.id, "leave_channel")
        message = await get_guild_config(member.guild.id, "leave_message")
        if not channel_id or not message:
            return
        channel = self.bot.get_channel(int(channel_id))
        if channel:
            embed = discord.Embed(description=fill(message, member), color=0xef4444)
            embed.set_author(name=str(member), icon_url=member.display_avatar.url)
            await channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Welcome(bot))
