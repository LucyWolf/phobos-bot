import asyncio
import json
import urllib.request
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from database import db_rows, db_exec, db_one


EPIC_URL = (
    "https://store-site-backend-static.ak.epicgames.com/"
    "freeGamesPromotions?locale=de&country=DE&allowCountries=DE"
)
GOG_URL = "https://www.gog.com/games/ajax/filtered?mediaType=game&price=free&page=1"


def _epic_free(elements: list) -> list:
    free = []
    for el in elements:
        try:
            price = el.get("price", {}).get("totalPrice", {})
            if price.get("discountPrice", -1) != 0:
                continue
            if price.get("originalPrice", 0) == 0:
                continue  # always free, not a promo
            offers = (el.get("promotions") or {}).get("promotionalOffers") or []
            if not offers:
                continue
            inner = offers[0].get("promotionalOffers") or []
            if not inner:
                continue
            end = inner[0].get("endDate", "")
            img_url = ""
            for img in el.get("keyImages", []):
                if img.get("type") in ("Thumbnail", "DieselStoreFrontWide", "OfferImageWide"):
                    img_url = img.get("url", "")
                    break
            slug = (el.get("catalogNs") or {}).get("mappings") or []
            page_slug = slug[0].get("pageSlug", "") if slug else el.get("productSlug", "")
            free.append({
                "id": el.get("id", ""),
                "title": el.get("title", ""),
                "description": el.get("description", "")[:200],
                "url": f"https://store.epicgames.com/de/p/{page_slug}" if page_slug else "https://store.epicgames.com/de/free-games",
                "image": img_url,
                "end_date": end[:10] if end else "",
                "platform": "epic",
            })
        except Exception:
            continue
    return free


class FreeStuff(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_loop.start()

    def cog_unload(self):
        self.check_loop.cancel()

    @tasks.loop(hours=2)
    async def check_loop(self):
        try:
            games = await self._fetch_all()
            if not games:
                return
            configs = await db_rows("SELECT * FROM freestuff_channels")
            for cfg in configs:
                guild_id = cfg["guild_id"]
                platforms = (cfg["platforms"] or "epic").split(",")
                ch = self.bot.get_channel(int(cfg["channel_id"]))
                if not ch:
                    continue
                for game in games:
                    if game["platform"] not in platforms:
                        continue
                    already = await db_one(
                        "SELECT 1 FROM freestuff_posted WHERE guild_id=? AND game_id=? AND platform=?",
                        (guild_id, game["id"], game["platform"]),
                    )
                    if already:
                        continue
                    await self._send_embed(ch, game)
                    await db_exec(
                        "INSERT OR IGNORE INTO freestuff_posted (guild_id, game_id, platform) VALUES (?,?,?)",
                        (guild_id, game["id"], game["platform"]),
                    )
        except Exception as e:
            print(f"[FreeStuff] Error: {e}")

    @check_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    async def _fetch_all(self) -> list:
        games = []
        games += await self._fetch_epic()
        games += await self._fetch_gog()
        return games

    async def _fetch_epic(self) -> list:
        try:
            def _get():
                req = urllib.request.Request(EPIC_URL, headers={"User-Agent": "PhobosBot/1.0"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.loads(r.read())
            data = await asyncio.to_thread(_get)
            elements = (
                data.get("data", {})
                    .get("Catalog", {})
                    .get("searchStore", {})
                    .get("elements", [])
            )
            return _epic_free(elements)
        except Exception as e:
            print(f"[FreeStuff] Epic fetch error: {e}")
            return []

    async def _fetch_gog(self) -> list:
        try:
            def _get():
                req = urllib.request.Request(GOG_URL, headers={"User-Agent": "PhobosBot/1.0"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.loads(r.read())
            data = await asyncio.to_thread(_get)
            games = []
            for p in data.get("products", []):
                price = str(p.get("price", {}).get("finalAmount", "1"))
                if price not in ("0", "0.00", "0,00"):
                    continue
                gid = str(p.get("id", ""))
                if not gid:
                    continue
                games.append({
                    "id": f"gog_{gid}",
                    "title": p.get("title", ""),
                    "description": "",
                    "url": f"https://www.gog.com{p.get('url', '')}",
                    "image": "https:" + p.get("image", "") + ".jpg" if p.get("image") else "",
                    "end_date": "",
                    "platform": "gog",
                })
            return games
        except Exception as e:
            print(f"[FreeStuff] GOG fetch error: {e}")
            return []

    async def _send_embed(self, channel: discord.TextChannel, game: dict):
        colours = {"epic": 0x2D2D2D, "gog": 0x86328A}
        icons = {"epic": "🎮", "gog": "🟣"}
        names = {"epic": "Epic Games", "gog": "GOG"}
        colour = colours.get(game["platform"], 0x5865F2)

        embed = discord.Embed(
            title=f"{icons.get(game['platform'], '🎁')} {game['title']} — Kostenlos!",
            description=game["description"] or "Jetzt gratis holen!",
            url=game["url"],
            color=colour,
        )
        if game["image"]:
            embed.set_image(url=game["image"])
        if game["end_date"]:
            embed.add_field(name="Verfügbar bis", value=game["end_date"], inline=True)
        embed.add_field(name="Plattform", value=names.get(game["platform"], game["platform"]), inline=True)
        embed.set_footer(text=f"{names.get(game['platform'], '')} • Kostenlos-Benachrichtigung")
        await channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(FreeStuff(bot))
