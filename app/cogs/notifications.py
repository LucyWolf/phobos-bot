import asyncio
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import datetime

import discord
from discord.ext import commands, tasks

from database import db_rows, db_exec, get_config


class Notifications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._twitch_token: str | None = None
        self._twitch_expires: datetime.datetime | None = None
        self.twitch_loop.start()
        self.youtube_loop.start()

    def cog_unload(self):
        self.twitch_loop.cancel()
        self.youtube_loop.cancel()

    # ── Twitch ────────────────────────────────────────────────────────────────

    async def _twitch_auth(self) -> tuple[str | None, str | None]:
        client_id = await get_config("twitch_client_id")
        client_secret = await get_config("twitch_client_secret")
        if not client_id or not client_secret:
            return None, None
        now = datetime.datetime.utcnow()
        if self._twitch_token and self._twitch_expires and now < self._twitch_expires:
            return self._twitch_token, client_id

        def _fetch_token():
            data = urllib.parse.urlencode({
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            }).encode()
            req = urllib.request.Request("https://id.twitch.tv/oauth2/token", data=data, method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())

        resp = await asyncio.to_thread(_fetch_token)
        self._twitch_token = resp["access_token"]
        self._twitch_expires = now + datetime.timedelta(seconds=resp.get("expires_in", 3600) - 60)
        return self._twitch_token, client_id

    @tasks.loop(minutes=3)
    async def twitch_loop(self):
        try:
            rows = await db_rows("SELECT * FROM notifications WHERE platform='twitch'")
            if not rows:
                return
            token, client_id = await self._twitch_auth()
            if not token:
                return

            usernames = [r["target"].lower() for r in rows]
            for i in range(0, len(usernames), 100):
                batch = usernames[i:i + 100]
                qs = "&".join(f"user_login={u}" for u in batch)

                def _fetch(q=qs):
                    req = urllib.request.Request(
                        f"https://api.twitch.tv/helix/streams?{q}",
                        headers={"Client-ID": client_id, "Authorization": f"Bearer {token}"},
                    )
                    with urllib.request.urlopen(req, timeout=10) as r:
                        return json.loads(r.read())

                data = await asyncio.to_thread(_fetch)
                live_map = {s["user_login"].lower(): s for s in data.get("data", [])}

                for row in rows:
                    uname = row["target"].lower()
                    if uname not in [b.lower() for b in batch]:
                        continue
                    is_live = uname in live_map
                    was_live = bool(row["live"])

                    if is_live and not was_live:
                        ch = self.bot.get_channel(int(row["discord_channel_id"]))
                        if ch:
                            await self._send_twitch(ch, live_map[uname], row["custom_message"])
                        await db_exec(
                            "UPDATE notifications SET live=1, last_id=? WHERE id=?",
                            (live_map[uname]["id"], row["id"]),
                        )
                    elif not is_live and was_live:
                        await db_exec("UPDATE notifications SET live=0 WHERE id=?", (row["id"],))
        except Exception as e:
            print(f"[Notifications] Twitch error: {e}")

    @twitch_loop.before_loop
    async def _before_twitch(self):
        await self.bot.wait_until_ready()

    async def _send_twitch(self, channel: discord.TextChannel, stream: dict, custom_msg: str):
        name = stream.get("user_name", stream.get("user_login", ""))
        embed = discord.Embed(
            title=f"🔴 {name} ist jetzt live!",
            description=stream.get("title", ""),
            url=f"https://twitch.tv/{stream.get('user_login', '')}",
            color=0x9146FF,
        )
        embed.add_field(name="Spiel", value=stream.get("game_name", "—"), inline=True)
        embed.add_field(name="Zuschauer", value=str(stream.get("viewer_count", 0)), inline=True)
        thumb = stream.get("thumbnail_url", "").replace("{width}", "1280").replace("{height}", "720")
        if thumb:
            embed.set_image(url=thumb)
        embed.set_footer(text="Twitch • Live-Benachrichtigung")
        await channel.send(content=custom_msg or None, embed=embed)

    # ── YouTube ───────────────────────────────────────────────────────────────

    @tasks.loop(minutes=15)
    async def youtube_loop(self):
        try:
            rows = await db_rows("SELECT * FROM notifications WHERE platform='youtube'")
            for row in rows:
                try:
                    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={row['target']}"

                    def _fetch(u=feed_url):
                        req = urllib.request.Request(u, headers={"User-Agent": "PhobosBot/1.0"})
                        with urllib.request.urlopen(req, timeout=10) as r:
                            return r.read()

                    xml_bytes = await asyncio.to_thread(_fetch)
                    root = ET.fromstring(xml_bytes)
                    ns = {
                        "atom": "http://www.w3.org/2005/Atom",
                        "yt": "http://www.youtube.com/xml/schemas/2015",
                    }
                    entries = root.findall("atom:entry", ns)
                    if not entries:
                        continue

                    latest = entries[0]
                    vid_el = latest.find("yt:videoId", ns)
                    if vid_el is None:
                        continue
                    video_id = vid_el.text
                    if video_id == row["last_id"]:
                        continue

                    title = (latest.find("atom:title", ns) or type("", (), {"text": "Neues Video"})()).text
                    link = (latest.find("atom:link", ns) or type("", (), {})())
                    url = getattr(link, "attrib", {}).get("href", f"https://youtu.be/{video_id}")
                    author_el = root.find("atom:author/atom:name", ns)
                    author = author_el.text if author_el is not None else (row["target_name"] or row["target"])

                    ch = self.bot.get_channel(int(row["discord_channel_id"]))
                    if ch:
                        await self._send_youtube(ch, author, title, url, video_id, row["custom_message"])
                    await db_exec("UPDATE notifications SET last_id=? WHERE id=?", (video_id, row["id"]))
                except Exception as e:
                    print(f"[Notifications] YouTube error for {row['target']}: {e}")
        except Exception as e:
            print(f"[Notifications] YouTube loop error: {e}")

    @youtube_loop.before_loop
    async def _before_youtube(self):
        await self.bot.wait_until_ready()

    async def _send_youtube(self, channel, author, title, url, video_id, custom_msg):
        embed = discord.Embed(
            title=f"📹 {author} – Neues Video!",
            description=title,
            url=url,
            color=0xFF0000,
        )
        embed.set_image(url=f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg")
        embed.set_footer(text="YouTube • Video-Benachrichtigung")
        await channel.send(content=custom_msg or None, embed=embed)


async def setup(bot):
    await bot.add_cog(Notifications(bot))
