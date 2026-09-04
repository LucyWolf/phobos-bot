"""Spam/link/word filter (Spam-Schutz tab). Deletes matching messages and applies an
admin-configured action (warn/timeout/kick/ban) - see _punish(). Word categories shown as
"+"-buttons in the dashboard come from automod_word_presets, not hardcoded here."""
import datetime
import re
import time
import discord
from discord.ext import commands
from database import get_guild_config, db_exec, log_mod_action

# discord.gg/... was the only invite format matched without a http(s):// prefix - Discord
# invites shared as plain text just as often use discord.com/invite/... or the legacy
# discordapp.com/invite/..., which slipped straight through the link filter (a message reading
# "join discord.com/invite/abc123" has no http(s):// and isn't discord.gg, so URL_RE never
# matched it at all). Deliberately NOT extended to a general bare-domain matcher (e.g. catching
# "example.com" with no protocol) - that needs a TLD allowlist to avoid false-positiving on
# ordinary prose (versions, abbreviations, filenames), which is a design decision beyond this
# specific, unambiguous gap.
URL_RE = re.compile(r"https?://\S+|discord\.gg/\S+|discord(?:app)?\.com/invite/\S+", re.IGNORECASE)


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
        # Chained .replace() calls corrupt already-substituted text if it happens to contain a
        # later placeholder's literal token - e.g. an admin-set guild name like "Cool {reason}
        # Server" would get its own "{reason}" replaced again by the second .replace() call.
        # Same bug class already fixed in welcome.py's fill(); noted but left here at the time
        # (v1.8.9) as out of scope for that tab's review round - fixed now that Spam-Schutz is
        # in scope. A single regex pass over the ORIGINAL template can't re-scan inserted text.
        dm_text = re.sub(
            r"\{server\}|\{reason\}",
            lambda m: message.guild.name if m.group(0) == "{server}" else reason,
            msg_template,
        )
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
