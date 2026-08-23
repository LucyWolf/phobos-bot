import datetime
import re
import time
import discord
from discord.ext import commands
from database import get_guild_config, db_exec, log_mod_action

URL_RE = re.compile(r"https?://\S+|discord\.gg/\S+", re.IGNORECASE)


class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._spam: dict = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.author.guild_permissions.manage_messages:
            return

        enabled = await get_guild_config(message.guild.id, "automod_enabled")
        if enabled != "1":
            return

        if await self._check_spam(message):
            return
        if await self._check_links(message):
            return
        await self._check_words(message)

    async def _check_spam(self, message: discord.Message) -> bool:
        threshold = await get_guild_config(message.guild.id, "automod_spam_threshold")
        if not threshold:
            return False
        try:
            threshold = int(threshold)
        except ValueError:
            return False
        window_raw = await get_guild_config(message.guild.id, "automod_spam_window")
        try:
            window = int(window_raw) if window_raw else 5
        except ValueError:
            window = 5
        key = (message.guild.id, message.author.id)
        now = time.time()
        history = self._spam.get(key, [])
        history = [t for t in history if now - t < window]
        history.append(now)
        self._spam[key] = history
        if len(history) >= threshold:
            try:
                await message.delete()
            except Exception:
                pass
            await self._punish(message, "Anti-Spam: zu viele Nachrichten")
            self._spam[key] = []
            return True
        return False

    async def _check_links(self, message: discord.Message) -> bool:
        enabled = await get_guild_config(message.guild.id, "automod_links")
        if enabled != "1":
            return False
        if URL_RE.search(message.content):
            try:
                await message.delete()
            except Exception:
                pass
            await self._punish(message, "Auto-Mod: Links nicht erlaubt")
            return True
        return False

    async def _check_words(self, message: discord.Message):
        words_raw = await get_guild_config(message.guild.id, "automod_banned_words")
        if not words_raw:
            return
        banned = [w.strip().lower() for w in words_raw.split(",") if w.strip()]
        content = message.content.lower()
        for word in banned:
            if re.search(rf"\b{re.escape(word)}\b", content):
                try:
                    await message.delete()
                except Exception:
                    pass
                await self._punish(message, f"Auto-Mod: verbotenes Wort")
                return

    async def _punish(self, message: discord.Message, reason: str):
        action = await get_guild_config(message.guild.id, "automod_action") or "warn"
        member = message.author
        bot_member = message.guild.me
        msg_template = await get_guild_config(message.guild.id, "automod_warn_message") \
            or "⚠️ **{server}**: {reason}"
        dm_text = msg_template.replace("{server}", message.guild.name).replace("{reason}", reason)
        try:
            await member.send(dm_text)
        except Exception:
            pass
        try:
            if action == "warn":
                await db_exec(
                    "INSERT INTO warnings (user_id,guild_id,moderator_id,reason) VALUES (?,?,?,?)",
                    (member.id, message.guild.id, bot_member.id, reason),
                )
            elif action == "timeout":
                timeout_raw = await get_guild_config(message.guild.id, "automod_timeout_minutes")
                try:
                    timeout_minutes = int(timeout_raw) if timeout_raw else 5
                except ValueError:
                    timeout_minutes = 5
                until = discord.utils.utcnow() + datetime.timedelta(minutes=timeout_minutes)
                await member.timeout(until, reason=reason)
            elif action == "kick":
                await member.kick(reason=reason)
            elif action == "ban":
                await member.ban(reason=reason)
        except Exception as e:
            print(f"[AutoMod] Konnte {action} nicht ausführen auf {member}: {e}")
            return
        await log_mod_action(f"automod:{action}", member, bot_member, message.guild.id, reason)


async def setup(bot):
    await bot.add_cog(AutoMod(bot))
