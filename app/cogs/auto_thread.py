"""Creates a thread on every message posted in admin-configured channels
(auto_thread_channels, configured via main.py's "Auto-Thread" section).

User-requested as its own feature, explicitly NOT as part of Embed-Nachrichten ("ne ist
theoretisch eigen .... dass er in dem zugewiesenen channel automatisch threads to allen
nachrichten erstellt"): Embed-Nachrichten creates a forum post on demand from the dashboard,
this one reacts to what members post.

Config is cached in memory and refreshed through reload() whenever the dashboard writes to the
table - same pattern as cogs/auto_delete.py, which this feature is closest to in shape.
"""
import datetime

import discord
from discord.ext import commands

from database import db_rows

# Discord only accepts these four values for a thread's auto-archive duration - anything else
# is rejected by the API. Also used by main.py to validate the dashboard form, but duplicated
# there as a literal rather than imported: main.py never imports from a cog at module level.
ALLOWED_ARCHIVE_MINUTES = (60, 1440, 4320, 10080)

# Discord's hard limit for a thread name. A template that renders longer is truncated rather
# than letting the API reject the whole thread.
MAX_THREAD_NAME = 100

# How much of the message itself {text} may contribute. Well under MAX_THREAD_NAME so the rest
# of the template (a user name, a date) still fits alongside it.
TEXT_SNIPPET_LEN = 40

# Repeated failures for the same channel (missing "Create Public Threads", a channel type that
# can't hold threads, ...) are logged once per this many seconds instead of once per message -
# a busy channel would otherwise flood the log with the same line hundreds of times.
ERROR_LOG_INTERVAL = 300


class AutoThread(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._configs: dict = {}  # {guild_id: {channel_id: row-dict}}
        self._last_error: dict = {}  # channel_id -> monotonic-ish timestamp of last logged error

    async def _load_configs(self):
        rows = await db_rows("SELECT * FROM auto_thread_channels")
        configs: dict = {}
        for r in rows:
            configs.setdefault(r["guild_id"], {})[r["channel_id"]] = r
        self._configs = configs

    async def reload(self):
        await self._load_configs()

    @commands.Cog.listener()
    async def on_ready(self):
        await self._load_configs()

    def _log_error(self, channel_id: str, msg: str) -> None:
        now = datetime.datetime.utcnow().timestamp()
        last = self._last_error.get(channel_id)
        if last is not None and now - last < ERROR_LOG_INTERVAL:
            return
        self._last_error[channel_id] = now
        print(f"[AutoThread] {msg}")

    @staticmethod
    def _build_name(template: str, message: discord.Message) -> str:
        snippet = " ".join((message.content or "").split())[:TEXT_SNIPPET_LEN].strip()
        name = (template or "{user}").replace("{user}", message.author.display_name)
        name = name.replace("{text}", snippet)
        name = name.replace("{date}", message.created_at.strftime("%d.%m.%Y"))
        # Collapse whatever the substitutions left behind: an image-only post renders {text} as
        # nothing, so a template like "{user} - {text}" would otherwise end in a dangling dash.
        name = " ".join(name.split()).strip(" -–—:|,")
        if not name:
            # Every placeholder rendered empty (e.g. template is just "{text}" on an
            # attachment-only post). A thread MUST have a name, so fall back to the author
            # rather than letting the API reject it.
            name = message.author.display_name or "Thread"
        return name[:MAX_THREAD_NAME]

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild:
            return
        # A message inside a thread would create a thread on a thread, which Discord rejects.
        # Forum channels are covered by the same check: their posts ARE threads, so every
        # message in one arrives here with channel being a Thread.
        if isinstance(message.channel, discord.Thread):
            return
        # Joins, pins, boosts and friends: threading those is never what an admin configured
        # this for, and they carry no content to name a thread after.
        if message.type not in (discord.MessageType.default, discord.MessageType.reply):
            return
        cfg = (self._configs.get(str(message.guild.id)) or {}).get(str(message.channel.id))
        if not cfg:
            return
        if message.author.bot and cfg["skip_bots"]:
            return
        if cfg["require_attachment"] and not message.attachments:
            return
        # Discord attaches at most one thread to a message - if something else already made
        # one (another bot, or this cog before a reconnect replayed the message), leave it be
        # instead of failing on every retry.
        #
        # Looked up through the CHANNEL, not as message.thread: discord.py 2.3.2 (the pinned
        # version in requirements.txt) has no Message.thread attribute at all, so reading it
        # would raise AttributeError for every single message in a configured channel - the
        # feature would never create one thread. A thread started from a message carries that
        # message's own id, which is what makes this lookup equivalent.
        get_thread = getattr(message.channel, "get_thread", None)
        if get_thread is not None and get_thread(message.id) is not None:
            return
        archive = cfg["archive_minutes"]
        if archive not in ALLOWED_ARCHIVE_MINUTES:
            # Only reachable through a hand-edited or restored-from-corrupt-backup row; the
            # dashboard validates against the same tuple. Falling back beats having the API
            # reject every single message in the channel.
            archive = 1440
        try:
            thread = await message.create_thread(
                name=self._build_name(cfg["name_template"], message),
                auto_archive_duration=archive,
                reason="Auto-Thread",
            )
        except discord.Forbidden:
            self._log_error(
                str(message.channel.id),
                f"missing permission to create a thread in channel {message.channel.id} "
                f"(guild {message.guild.id}) - the bot needs 'Create Public Threads' there",
            )
            return
        except (discord.HTTPException, OSError) as e:
            self._log_error(
                str(message.channel.id),
                f"creating a thread in channel {message.channel.id} (guild {message.guild.id}) failed: {e}",
            )
            return
        starter = (cfg["starter_message"] or "").strip()
        if not starter:
            return
        try:
            await thread.send(starter.replace("{user}", message.author.mention)[:2000])
        except (discord.HTTPException, OSError) as e:
            # The thread itself already exists and is the point of the feature - a failed
            # opening post is worth a line in the log but must not look like the whole thing
            # failed, and must not be retried by raising.
            self._log_error(
                f"{message.channel.id}:starter",
                f"thread {thread.id} was created but its starter message could not be sent: {e}",
            )


async def setup(bot):
    await bot.add_cog(AutoThread(bot))
