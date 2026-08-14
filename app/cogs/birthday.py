import datetime
import discord
from discord.ext import commands, tasks
from database import db_rows, db_exec, db_exec_rowcount, get_guild_config


class Birthday(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._check.start()

    def cog_unload(self):
        self._check.cancel()

    @tasks.loop(minutes=30)
    async def _check(self):
        now = datetime.datetime.now()
        # Only run between 08:00 and 08:29
        if now.hour != 8:
            return
        today = now.strftime("%m-%d")
        year = now.year

        rows = await db_rows("SELECT * FROM birthdays WHERE birthday=?", (today,))
        for row in rows:
            uid, gid = row["user_id"], row["guild_id"]
            # Optimistisch reservieren — INSERT schlägt fehl wenn anderer Bot schon gesendet hat
            inserted = await db_exec_rowcount(
                "INSERT OR IGNORE INTO birthday_sent (user_id, guild_id, year) VALUES (?,?,?)",
                (uid, gid, year),
            )
            if inserted == 0:
                continue

            guild = self.bot.get_guild(int(gid))
            if not guild:
                continue
            channel_id = await get_guild_config(int(gid), "birthday_channel")
            if not channel_id:
                continue
            channel = guild.get_channel(int(channel_id))
            if not channel:
                continue
            member = guild.get_member(int(uid))
            if not member:
                continue

            tpl = await get_guild_config(int(gid), "birthday_message") or "🎂 Alles Gute zum Geburtstag, {user}! 🎉"
            text = tpl.replace("{user}", member.mention)
            try:
                embed = discord.Embed(description=text, color=0xff73fa)
                embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
                embed.set_thumbnail(url=member.display_avatar.url)
                await channel.send(embed=embed)
            except Exception:
                pass

    @_check.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    @commands.command(name="geburtstag")
    async def birthday_set(self, ctx: commands.Context, datum: str = ""):
        """Geburtstag eintragen: !geburtstag TT.MM  |  löschen: !geburtstag löschen"""
        if datum.lower() in ("löschen", "entfernen", "delete", "remove"):
            await db_exec(
                "DELETE FROM birthdays WHERE user_id=? AND guild_id=?",
                (str(ctx.author.id), str(ctx.guild.id)),
            )
            await ctx.reply("✅ Geburtstag gelöscht.", mention_author=False)
            return

        try:
            parts = datum.strip().split(".")
            if len(parts) != 2:
                raise ValueError
            day, month = int(parts[0]), int(parts[1])
            datetime.date(2000, month, day)  # prüft ob Datum wirklich existiert (z.B. kein 30.02)
            bday = f"{month:02d}-{day:02d}"
        except (ValueError, IndexError):
            await ctx.reply("❌ Format: `!geburtstag TT.MM` (z.B. `!geburtstag 15.06`)", mention_author=False)
            return

        await db_exec(
            "INSERT OR REPLACE INTO birthdays (user_id, guild_id, birthday) VALUES (?,?,?)",
            (str(ctx.author.id), str(ctx.guild.id), bday),
        )
        await ctx.reply(f"✅ Geburtstag gespeichert: **{day:02d}.{month:02d}**", mention_author=False)


async def setup(bot):
    await bot.add_cog(Birthday(bot))
