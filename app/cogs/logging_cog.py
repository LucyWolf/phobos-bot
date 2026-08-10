import discord
from discord.ext import commands
from database import get_guild_config


class Logging(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _log(self, guild_id: int, embed: discord.Embed):
        channel_id = await get_guild_config(guild_id, "log_channel")
        if not channel_id:
            return
        channel = self.bot.get_channel(int(channel_id))
        if channel:
            await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        embed = discord.Embed(title="Member beigetreten", color=0x22c55e)
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.add_field(name="Account erstellt", value=discord.utils.format_dt(member.created_at, "R"))
        embed.add_field(name="ID", value=str(member.id))
        await self._log(member.guild.id, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        embed = discord.Embed(title="Member verlassen", color=0xef4444)
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.add_field(name="ID", value=str(member.id))
        roles = [r.mention for r in member.roles if r.name != "@everyone"]
        if roles:
            embed.add_field(name="Rollen", value=" ".join(roles), inline=False)
        await self._log(member.guild.id, embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        embed = discord.Embed(title="Nachricht gelöscht", color=0xf97316)
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        embed.add_field(name="Kanal", value=message.channel.mention)
        if message.content:
            embed.add_field(name="Inhalt", value=message.content[:1000], inline=False)
        await self._log(message.guild.id, embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild or before.content == after.content:
            return
        embed = discord.Embed(title="Nachricht bearbeitet", color=0xeab308)
        embed.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)
        embed.add_field(name="Kanal", value=before.channel.mention)
        embed.add_field(name="Vorher", value=before.content[:500] or "—", inline=False)
        embed.add_field(name="Nachher", value=after.content[:500] or "—", inline=False)
        embed.add_field(name="Link", value=f"[Zur Nachricht]({after.jump_url})")
        await self._log(before.guild.id, embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        embed = discord.Embed(title="Member gebannt", color=0xef4444)
        embed.set_author(name=str(user), icon_url=user.display_avatar.url)
        embed.add_field(name="ID", value=str(user.id))
        await self._log(guild.id, embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        embed = discord.Embed(title="Member entbannt", color=0x22c55e)
        embed.set_author(name=str(user), icon_url=user.display_avatar.url)
        await self._log(guild.id, embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles == after.roles:
            return
        added = [r for r in after.roles if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if not added and not removed:
            return
        embed = discord.Embed(title="Rollen aktualisiert", color=0x3b82f6)
        embed.set_author(name=str(after), icon_url=after.display_avatar.url)
        if added:
            embed.add_field(name="Hinzugefügt", value=" ".join(r.mention for r in added))
        if removed:
            embed.add_field(name="Entfernt", value=" ".join(r.mention for r in removed))
        await self._log(after.guild.id, embed)


async def setup(bot):
    await bot.add_cog(Logging(bot))
