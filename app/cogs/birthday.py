"""Birthday reminders: a configurable "!<wort> TT.MM" sets/clears a member's birthday, a daily check
around 08:00 posts a congratulations message for anyone whose birthday matches today
(birthday_sent tracks who's already been congratulated this year, cleared if the date is
later corrected)."""
import datetime
import discord
from discord.ext import commands, tasks
from database import (db_rows, db_exec, db_exec_rowcount, get_guild_config,
                      parse_command_triggers, DEFAULT_BIRTHDAY_TRIGGERS,
                      DEFAULT_BIRTHDAY_DELETE_WORDS, DEFAULT_BIRTHDAY_REPLY_SAVED,
                      DEFAULT_BIRTHDAY_REPLY_DELETED, DEFAULT_BIRTHDAY_REPLY_ERROR)
from cogs.log_utils import log_bot_event

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from pytz import timezone as ZoneInfo


class Birthday(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._check.start()

    def cog_unload(self):
        self._check.cancel()

    @tasks.loop(minutes=30)
    async def _check(self):
        # Comparing against a naive datetime.now() only happened to work because the reference
        # docker-compose.yml sets TZ=Europe/Berlin; a container running under a different
        # timezone (e.g. a hosted customer's own deployment) would fire this at the wrong
        # local hour and could miscompute "today" near a midnight boundary.
        now = datetime.datetime.now(ZoneInfo("Europe/Berlin"))
        # Only run between 08:00 and 08:29
        if now.hour != 8:
            return
        today = now.strftime("%m-%d")
        year = now.year

        match_dates = [today]
        if today == "02-28" and not (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
            # Feb 29 birthdays (a valid, storable date via !geburtstag - 2000 is a leap year
            # so the validation lets it through) would otherwise never match in the 3 out of 4
            # years that aren't leap years, since "02-29" never occurs as `today`. Celebrate on
            # Feb 28 instead, the common convention.
            match_dates.append("02-29")
        placeholders = ",".join("?" for _ in match_dates)
        rows = await db_rows(f"SELECT * FROM birthdays WHERE birthday IN ({placeholders})", tuple(match_dates))
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
                await log_bot_event(
                    self.bot, int(gid), "🎂", "Geburtstags-Glückwunsch gesendet", "birthday",
                    plain=f"{member.display_name} · #{channel.name}",
                )
            except Exception:
                pass

    @_check.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """The birthday command, matched against words THIS server configured.

        Was a plain @commands.command(name="geburtstag") before, which binds one hard-coded
        German word for every guild the token serves. A server that doesn't speak German had
        no way to reach the feature at all, and a mixed-language one no way to offer more than
        one word - hence guild_configs key birthday_commands, and this listener. Modelled on
        cogs/custom_commands.py, the project's other "!word" handler.

        Never reached via DM: message.guild is None there, and the whole point of the command
        is storing a birthday FOR a specific server.
        """
        if message.author.bot or not message.guild:
            return
        content = (message.content or "").strip()
        if not content.startswith("!"):
            return
        parts = content[1:].split()
        if not parts:
            return
        triggers = parse_command_triggers(
            await get_guild_config(message.guild.id, "birthday_commands") or "",
            DEFAULT_BIRTHDAY_TRIGGERS,
        )
        word = parts[0].lower()
        if word not in triggers:
            return
        datum = parts[1] if len(parts) > 1 else ""
        delete_words = parse_command_triggers(
            await get_guild_config(message.guild.id, "birthday_delete_words") or "",
            DEFAULT_BIRTHDAY_DELETE_WORDS,
        )
        # Echoed back in every reply below instead of a hard-coded "!geburtstag": telling
        # someone on an English server that the format is "!geburtstag TT.MM" right after they
        # successfully typed "!birthday" would be worse than saying nothing.
        used = f"!{word}"

        async def answer(key: str, default: str, **extra) -> None:
            tpl = await get_guild_config(message.guild.id, key)
            text = (tpl if tpl and tpl.strip() else default)
            text = (text.replace("{command}", used)
                        .replace("{delete}", delete_words[0])
                        .replace("{user}", message.author.mention))
            for name, value in extra.items():
                text = text.replace("{" + name + "}", value)
            await self._reply(message, text)

        if datum.lower() in delete_words:
            await db_exec(
                "DELETE FROM birthdays WHERE user_id=? AND guild_id=?",
                (str(message.author.id), str(message.guild.id)),
            )
            await answer("birthday_reply_deleted", DEFAULT_BIRTHDAY_REPLY_DELETED)
            return

        try:
            date_parts = datum.strip().split(".")
            if len(date_parts) != 2:
                raise ValueError
            day, month = int(date_parts[0]), int(date_parts[1])
            datetime.date(2000, month, day)  # prüft ob Datum wirklich existiert (z.B. kein 30.02)
            bday = f"{month:02d}-{day:02d}"
        except (ValueError, IndexError):
            await answer("birthday_reply_error", DEFAULT_BIRTHDAY_REPLY_ERROR)
            return

        await db_exec(
            "INSERT OR REPLACE INTO birthdays (user_id, guild_id, birthday) VALUES (?,?,?)",
            (str(message.author.id), str(message.guild.id), bday),
        )
        # birthday_sent is only keyed by (user_id, guild_id, year), not the date itself -
        # if this user was already wished this year on their old (wrong) date, that row would
        # otherwise block them from getting wished again on the corrected date this same year.
        await db_exec(
            "DELETE FROM birthday_sent WHERE user_id=? AND guild_id=? AND year=?",
            (str(message.author.id), str(message.guild.id), datetime.datetime.now().year),
        )
        await answer("birthday_reply_saved", DEFAULT_BIRTHDAY_REPLY_SAVED,
                     date=f"{day:02d}.{month:02d}")

    @staticmethod
    async def _reply(message: discord.Message, text: str) -> None:
        # A reply to a message that has since been deleted, or a channel the bot may read but
        # not write in, would otherwise raise straight out of on_message.
        try:
            await message.reply(text, mention_author=False)
        except (discord.HTTPException, OSError) as e:
            print(f"[Birthday] reply in channel {message.channel.id} failed: {e}")


async def setup(bot):
    await bot.add_cog(Birthday(bot))
