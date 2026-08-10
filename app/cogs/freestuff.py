import asyncio
import json
import urllib.request
import urllib.parse

import discord
from discord.ext import commands, tasks

from database import db_rows, db_exec, db_one


EPIC_URL = (
    "https://store-site-backend-static.ak.epicgames.com/"
    "freeGamesPromotions?locale=de&country=DE&allowCountries=DE"
)

PLATFORMS = {
    "epic":   {"name": "Epic Games",    "icon": "🎮", "color": 0x313131, "cs_id": None},
    "steam":  {"name": "Steam",         "icon": "🖥️", "color": 0x1B2838, "cs_id": "1"},
    "gog":    {"name": "GOG",           "icon": "🟣", "color": 0x86328A, "cs_id": "7"},
    "humble": {"name": "Humble Bundle", "icon": "🙏", "color": 0xCC2929, "cs_id": "11"},
}


def _epic_extract(elements: list) -> list:
    out = []
    for el in elements:
        try:
            price = el.get("price", {}).get("totalPrice", {})
            if price.get("discountPrice", -1) != 0:
                continue
            if price.get("originalPrice", 0) == 0:
                continue  # always free
            offers = (el.get("promotions") or {}).get("promotionalOffers") or []
            if not offers or not offers[0].get("promotionalOffers"):
                continue
            inner = offers[0]["promotionalOffers"][0]
            end = inner.get("endDate", "")[:10]
            img = next(
                (i["url"] for i in el.get("keyImages", [])
                 if i.get("type") in ("Thumbnail", "DieselStoreFrontWide", "OfferImageWide")),
                "",
            )
            mappings = (el.get("catalogNs") or {}).get("mappings") or []
            slug = mappings[0].get("pageSlug", "") if mappings else el.get("productSlug", "")
            store_url = (
                f"https://store.epicgames.com/de/p/{slug}"
                if slug else "https://store.epicgames.com/de/free-games"
            )
            out.append({
                "id": f"epic_{el.get('id', '')}",
                "title": el.get("title", ""),
                "description": (el.get("description") or "")[:180],
                "url": store_url,
                "image": img,
                "end_date": end,
                "platform": "epic",
            })
        except Exception:
            continue
    return out


class FreeStuff(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_loop.start()

    def cog_unload(self):
        self.check_loop.cancel()

    # ── Main loop ─────────────────────────────────────────────────────────────

    @tasks.loop(hours=2)
    async def check_loop(self):
        try:
            configs = await db_rows("SELECT * FROM freestuff_channels")
            if not configs:
                return

            # Collect which platforms any server needs
            needed = set()
            for cfg in configs:
                needed.update((cfg["platforms"] or "epic").split(","))

            all_games = await self._fetch_all(needed)
            if not all_games:
                return

            for cfg in configs:
                platforms = set((cfg["platforms"] or "epic").split(","))
                ch = self.bot.get_channel(int(cfg["channel_id"]))
                if not ch:
                    continue
                for game in all_games:
                    if game["platform"] not in platforms:
                        continue
                    already = await db_one(
                        "SELECT 1 FROM freestuff_posted WHERE guild_id=? AND game_id=? AND platform=?",
                        (cfg["guild_id"], game["id"], game["platform"]),
                    )
                    if already:
                        continue
                    try:
                        await self._send_embed(ch, game)
                    except Exception as e:
                        print(f"[FreeStuff] Send error: {e}")
                    await db_exec(
                        "INSERT OR IGNORE INTO freestuff_posted (guild_id, game_id, platform) VALUES (?,?,?)",
                        (cfg["guild_id"], game["id"], game["platform"]),
                    )
        except Exception as e:
            print(f"[FreeStuff] Loop error: {e}")

    @check_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    # ── Fetchers ──────────────────────────────────────────────────────────────

    async def _fetch_all(self, platforms: set) -> list:
        tasks = []
        if "epic" in platforms:
            tasks.append(self._fetch_epic())
        for key, info in PLATFORMS.items():
            if key != "epic" and key in platforms and info["cs_id"]:
                tasks.append(self._fetch_cheapshark(info["cs_id"], key))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        games = []
        for r in results:
            if isinstance(r, list):
                games.extend(r)
        return games

    async def _fetch_epic(self) -> list:
        try:
            def _get():
                req = urllib.request.Request(EPIC_URL, headers={"User-Agent": "PhobosBot/1.0"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.loads(r.read())

            data = await asyncio.to_thread(_get)
            elements = (data.get("data", {})
                           .get("Catalog", {})
                           .get("searchStore", {})
                           .get("elements", []))
            return _epic_extract(elements)
        except Exception as e:
            print(f"[FreeStuff] Epic error: {e}")
            return []

    async def _fetch_cheapshark(self, store_id: str, platform: str) -> list:
        try:
            url = (
                f"https://www.cheapshark.com/api/1.0/deals"
                f"?upperPrice=0&pageSize=60&storeID={store_id}&sortBy=Recent"
            )

            def _get():
                req = urllib.request.Request(url, headers={"User-Agent": "PhobosBot/1.0"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.loads(r.read())

            deals = await asyncio.to_thread(_get)
            out = []
            for d in deals:
                try:
                    normal = float(d.get("normalPrice", "0") or "0")
                    if normal <= 0:
                        continue  # always free, skip
                    deal_id = d.get("dealID", "")
                    game_id = f"{platform}_{d.get('gameID', deal_id)}"
                    title = d.get("title", "")
                    if not title:
                        continue
                    steam_id = d.get("steamAppID")
                    image = (
                        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{steam_id}/header.jpg"
                        if steam_id else d.get("thumb", "")
                    )
                    store_url = f"https://www.cheapshark.com/redirect?dealID={urllib.parse.quote(deal_id)}"
                    out.append({
                        "id": game_id,
                        "title": title,
                        "description": f"Normalpreis: {normal:.2f} €",
                        "url": store_url,
                        "image": image,
                        "end_date": "",
                        "platform": platform,
                    })
                except Exception:
                    continue
            return out
        except Exception as e:
            print(f"[FreeStuff] CheapShark ({platform}) error: {e}")
            return []

    # ── Embed ─────────────────────────────────────────────────────────────────

    async def _send_embed(self, channel: discord.TextChannel, game: dict):
        info = PLATFORMS.get(game["platform"], {"name": game["platform"], "icon": "🎁", "color": 0x5865F2})
        embed = discord.Embed(
            title=f"{info['icon']} {game['title']} — Kostenlos!",
            description=game["description"] or "Jetzt gratis holen!",
            url=game["url"],
            color=info["color"],
        )
        if game["image"]:
            embed.set_image(url=game["image"])
        if game["end_date"]:
            embed.add_field(name="Verfügbar bis", value=game["end_date"], inline=True)
        embed.add_field(name="Plattform", value=info["name"], inline=True)
        embed.set_footer(text=f"{info['name']} • Kostenlos-Benachrichtigung")
        await channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(FreeStuff(bot))
