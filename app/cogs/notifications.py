import asyncio
import datetime
import json
import urllib.parse
import urllib.request

import discord
from discord.ext import commands, tasks

from database import db_rows, db_exec, db_one


class Notifications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._token_cache: dict[int, tuple[str, datetime.datetime]] = {}
        self.twitch_loop.start()

    def cog_unload(self):
        self.twitch_loop.cancel()

    async def _twitch_auth(self, api_id: int, client_id: str, client_secret: str) -> tuple[str | None, str | None]:
        now = datetime.datetime.utcnow()
        cached = self._token_cache.get(api_id)
        if cached:
            token, expires = cached
            if now < expires:
                return token, client_id

        def _fetch():
            data = urllib.parse.urlencode({
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            }).encode()
            req = urllib.request.Request("https://id.twitch.tv/oauth2/token", data=data, method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())

        resp = await asyncio.to_thread(_fetch)
        token = resp["access_token"]
        expires = now + datetime.timedelta(seconds=resp.get("expires_in", 3600) - 60)
        self._token_cache[api_id] = (token, expires)
        return token, client_id

    @tasks.loop(minutes=3)
    async def twitch_loop(self):
        try:
            apis = await db_rows("SELECT * FROM twitch_apis")
            if not apis:
                return
            # Only auto-select when unambiguous — with multiple APIs registered by
            # different owners, a guild without an explicit choice must not silently
            # piggyback on someone else's Twitch credentials.
            default_api_id = apis[0]["id"] if len(apis) == 1 else None
            api_map = {a["id"]: a for a in apis}

            rows = await db_rows("SELECT * FROM notifications WHERE platform='twitch'")
            if not rows:
                return

            # resolve guild → api_id
            guild_api: dict[str, int | None] = {}
            for row in rows:
                gid = str(row["guild_id"])
                if gid not in guild_api:
                    cfg = await db_one(
                        "SELECT value FROM guild_configs WHERE guild_id=? AND key='twitch_api_id'",
                        (gid,),
                    )
                    guild_api[gid] = int(cfg["value"]) if cfg else default_api_id

            # group rows by api_id (skip guilds with no resolvable API)
            by_api: dict[int, list] = {}
            for row in rows:
                aid = guild_api.get(str(row["guild_id"]), default_api_id)
                if aid is None:
                    continue
                by_api.setdefault(aid, []).append(row)

            for api_id, api_rows in by_api.items():
                api = api_map.get(api_id)
                if not api:
                    continue
                try:
                    token, client_id = await self._twitch_auth(
                        api_id, api["client_id"], api["client_secret"]
                    )
                except Exception as e:
                    print(f"[Notifications] Auth error API#{api_id}: {e}")
                    continue
                if not token:
                    continue

                try:
                    usernames = [r["target"].lower() for r in api_rows]
                    for i in range(0, len(usernames), 100):
                        batch = usernames[i:i + 100]
                        qs = "&".join(f"user_login={u}" for u in batch)

                        def _fetch(q=qs, cid=client_id, tok=token):
                            req = urllib.request.Request(
                                f"https://api.twitch.tv/helix/streams?{q}",
                                headers={"Client-ID": cid, "Authorization": f"Bearer {tok}"},
                            )
                            with urllib.request.urlopen(req, timeout=10) as r:
                                return json.loads(r.read())

                        data = await asyncio.to_thread(_fetch)
                        live_map = {s["user_login"].lower(): s for s in data.get("data", [])}

                        for row in api_rows:
                            uname = row["target"].lower()
                            if uname not in batch:
                                continue
                            is_live = uname in live_map
                            was_live = bool(row["live"])

                            if is_live and not was_live:
                                ch = self.bot.get_channel(int(row["discord_channel_id"]))
                                if ch:
                                    try:
                                        await self._send_embed(ch, live_map[uname], row["custom_message"])
                                        await db_exec(
                                            "UPDATE notifications SET live=1, last_id=? WHERE id=?",
                                            (live_map[uname]["id"], row["id"]),
                                        )
                                    except Exception as e:
                                        print(f"[Notifications] send error for {uname}: {e}")
                            elif not is_live and was_live:
                                await db_exec("UPDATE notifications SET live=0 WHERE id=?", (row["id"],))
                except Exception as e:
                    print(f"[Notifications] Fetch error API#{api_id}: {e}")
                    continue

        except Exception as e:
            print(f"[Notifications] Twitch error: {e}")

    @twitch_loop.before_loop
    async def _before_loop(self):
        await self.bot.wait_until_ready()

    async def _send_embed(self, channel: discord.TextChannel, stream: dict, custom_msg: str):
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


async def setup(bot):
    await bot.add_cog(Notifications(bot))
