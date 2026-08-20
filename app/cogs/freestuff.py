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

GAMERPOWER_URL = "https://www.gamerpower.com/api/giveaways"

PLATFORMS = {
    "epic":      {"name": "Epic Games",      "icon": "🎮", "color": 0x313131, "cs_id": None,  "gp": None,     "gp_match": None},
    "steam":     {"name": "Steam",           "icon": "🖥️", "color": 0x1B2838, "cs_id": "1",   "gp": None,     "gp_match": None},
    "gog":       {"name": "GOG",             "icon": "🟣", "color": 0x86328A, "cs_id": "7",   "gp": None,     "gp_match": None},
    "humble":    {"name": "Humble Bundle",   "icon": "🙏", "color": 0xCC2929, "cs_id": "11",  "gp": None,     "gp_match": None},
    "fanatical": {"name": "Fanatical",       "icon": "🐰", "color": 0xFF4C00, "cs_id": "15",  "gp": None,     "gp_match": None},
    "gmg":       {"name": "GreenManGaming",  "icon": "🟢", "color": 0x00A650, "cs_id": "3",   "gp": None,     "gp_match": None},
    # GamerPower has no dedicated "platform" filter for these three - the API only
    # supports pc/steam/epic-games-store/gog/ps4/ps5/xbox-*/switch/android/ios/drm-free/itchio.
    # We fetch the general PC giveaway list once and match by the free-text "platforms" field instead.
    "ea":        {"name": "EA App",          "icon": "🟡", "color": 0xFF4747, "cs_id": None,  "gp": None,     "gp_match": ("origin", "ea app", "ea play")},
    "ubisoft":   {"name": "Ubisoft Connect", "icon": "🔷", "color": 0x0070D1, "cs_id": None,  "gp": None,     "gp_match": ("ubisoft",)},
    "battlenet": {"name": "Battle.net",      "icon": "⚔️", "color": 0x148EFF, "cs_id": None,  "gp": None,     "gp_match": ("battle.net", "battlenet", "blizzard")},
    "itchio":    {"name": "itch.io",         "icon": "🍓", "color": 0xFA5C5C, "cs_id": None,  "gp": "itchio", "gp_match": None},
}


def _epic_extract(elements: list) -> list:
    out = []
    for el in elements:
        try:
            price = el.get("price", {}).get("totalPrice", {})
            if price.get("discountPrice", -1) != 0:
                continue
            if price.get("originalPrice", 0) == 0:
                continue
            offers = (el.get("promotions") or {}).get("promotionalOffers") or []
            if not offers or not offers[0].get("promotionalOffers"):
                continue
            end = offers[0]["promotionalOffers"][0].get("endDate", "")[:10]
            img = next(
                (i["url"] for i in el.get("keyImages", [])
                 if i.get("type") in ("Thumbnail", "DieselStoreFrontWide", "OfferImageWide")),
                "",
            )
            mappings = (el.get("catalogNs") or {}).get("mappings") or []
            slug = mappings[0].get("pageSlug", "") if mappings else el.get("productSlug", "")
            out.append({
                "id": f"epic_{el.get('id', '')}",
                "title": el.get("title", ""),
                "description": (el.get("description") or "")[:180],
                "url": (f"https://store.epicgames.com/de/p/{slug}"
                        if slug else "https://store.epicgames.com/de/free-games"),
                "image": img,
                "end_date": end,
                "original_price": None,
                "sale_price": 0.0,
                "discount": 100,
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

    # ── Loop ──────────────────────────────────────────────────────────────────

    @tasks.loop(hours=1)
    async def check_loop(self):
        try:
            configs = await db_rows("SELECT * FROM freestuff_channels")
            if not configs:
                return

            needed_free = set()
            for cfg in configs:
                needed_free.update((cfg["platforms"] or "epic").split(","))

            free_games = await self._fetch_free(needed_free) if needed_free else []

            for cfg in configs:
                guild_id = cfg["guild_id"]
                try:
                    platforms = set((cfg["platforms"] or "epic").split(","))

                    # ── Free games ────────────────────────────────────────
                    ch_free = self.bot.get_channel(int(cfg["channel_id"]))
                    if ch_free:
                        for game in free_games:
                            if game["platform"] not in platforms:
                                continue
                            if await db_one(
                                "SELECT 1 FROM freestuff_posted WHERE guild_id=? AND game_id=? AND platform=?",
                                (guild_id, game["id"], game["platform"]),
                            ):
                                continue
                            try:
                                await self._send_embed(ch_free, game, is_deal=False)
                                await db_exec(
                                    "INSERT OR IGNORE INTO freestuff_posted (guild_id,game_id,platform) VALUES (?,?,?)",
                                    (guild_id, game["id"], game["platform"]),
                                )
                            except Exception as e:
                                print(f"[FreeStuff] send error: {e}")

                    # ── Deals ─────────────────────────────────────────────
                    max_price = cfg.get("deal_max_price")
                    stored_min_disc = cfg.get("deal_min_discount")
                    min_disc = int(stored_min_disc) if stored_min_disc is not None else 75
                    deal_ch_id = cfg.get("deal_channel_id") or cfg["channel_id"]
                    ch_deals = self.bot.get_channel(int(deal_ch_id))
                    deal_platforms = set((cfg.get("deal_platforms") or cfg["platforms"] or "").split(","))

                    if max_price and ch_deals:
                        deals = await self._fetch_deals(deal_platforms, float(max_price), min_disc)
                        for game in deals:
                            if game["platform"] not in deal_platforms:
                                continue
                            deal_key = f"deal_{game['id']}"
                            if await db_one(
                                "SELECT 1 FROM freestuff_posted WHERE guild_id=? AND game_id=? AND platform=?",
                                (guild_id, deal_key, game["platform"]),
                            ):
                                continue
                            try:
                                await self._send_embed(ch_deals, game, is_deal=True)
                                await db_exec(
                                    "INSERT OR IGNORE INTO freestuff_posted (guild_id,game_id,platform) VALUES (?,?,?)",
                                    (guild_id, deal_key, game["platform"]),
                                )
                            except Exception as e:
                                print(f"[FreeStuff] deal send error: {e}")
                except Exception as e:
                    print(f"[FreeStuff] Config error (guild {guild_id}): {e}")

        except Exception as e:
            print(f"[FreeStuff] Loop error: {e}")

    @check_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    # ── Fetchers ──────────────────────────────────────────────────────────────

    async def _fetch_free(self, platforms: set) -> list:
        fetch_tasks = []
        if "epic" in platforms:
            fetch_tasks.append(self._fetch_epic())

        needs_general = any(PLATFORMS[k].get("gp_match") for k in platforms if k in PLATFORMS)
        general_items = await self._fetch_gamerpower_general() if needs_general else []

        for key, info in PLATFORMS.items():
            if key not in platforms:
                continue
            if info["cs_id"]:
                fetch_tasks.append(self._fetch_cheapshark(info["cs_id"], key, upper=0, lower=0, min_disc=100))
            elif info.get("gp"):
                fetch_tasks.append(self._fetch_gamerpower(key, info["gp"]))
            elif info.get("gp_match"):
                fetch_tasks.append(self._match_gamerpower(key, info["gp_match"], general_items))
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        out = []
        for r in results:
            if isinstance(r, list):
                out.extend(r)
        return out

    async def _fetch_deals(self, platforms: set, max_price: float, min_disc: int) -> list:
        fetch_tasks = []
        for key, info in PLATFORMS.items():
            if key in platforms and info["cs_id"]:
                fetch_tasks.append(self._fetch_cheapshark(
                    info["cs_id"], key,
                    upper=max_price, lower=0.01,
                    min_disc=min_disc,
                ))
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        out = []
        for r in results:
            if isinstance(r, list):
                out.extend(r)
        return out

    async def _fetch_epic(self) -> list:
        try:
            def _get():
                req = urllib.request.Request(EPIC_URL, headers={"User-Agent": "PhobosBot/1.0"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.loads(r.read())
            data = await asyncio.to_thread(_get)
            elements = (data.get("data", {}).get("Catalog", {})
                            .get("searchStore", {}).get("elements", []))
            return _epic_extract(elements)
        except Exception as e:
            print(f"[FreeStuff] Epic error: {e}")
            return []

    def _gp_item_to_game(self, item: dict, platform_key: str) -> dict | None:
        try:
            if item.get("status", "").lower() != "active":
                return None
            worth = item.get("worth", "$0")
            # skip always-free items (worth = "N/A" or "$0.00")
            if worth in ("N/A", "$0.00", "$0"):
                return None
            url = item.get("open_giveaway_url") or item.get("gamerpower_url", "")
            if not url:
                # No usable link - skip rather than send an embed Discord will reject,
                # which would otherwise never get marked as posted and retry forever.
                return None
            end_raw = item.get("end_date", "")
            end = end_raw[:10] if end_raw and end_raw.lower() != "n/a" else ""
            return {
                "id": f"gp_{item['id']}",
                "title": item.get("title", ""),
                "description": (item.get("description") or "")[:180],
                "url": url,
                "image": item.get("image") or item.get("thumbnail", ""),
                "end_date": end,
                "original_price": None,
                "sale_price": 0.0,
                "discount": 100,
                "platform": platform_key,
            }
        except Exception:
            return None

    async def _gamerpower_get(self, params: dict) -> list:
        url = f"{GAMERPOWER_URL}?{urllib.parse.urlencode(params)}"

        def _get():
            req = urllib.request.Request(url, headers={"User-Agent": "PhobosBot/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
                return data if isinstance(data, list) else []

        return await asyncio.to_thread(_get)

    async def _fetch_gamerpower(self, platform_key: str, gp_platform: str) -> list:
        try:
            items = await self._gamerpower_get({"platform": gp_platform, "type": "game"})
            return [g for i in items if (g := self._gp_item_to_game(i, platform_key))]
        except Exception as e:
            print(f"[FreeStuff] GamerPower ({platform_key}) error: {e}")
            return []

    async def _fetch_gamerpower_general(self) -> list:
        """Unfiltered PC giveaway list, used as a base for platforms GamerPower has no
        dedicated "platform" filter for (EA/Origin, Ubisoft, Battle.net) - see PLATFORMS."""
        try:
            return await self._gamerpower_get({"platform": "pc", "type": "game"})
        except Exception as e:
            print(f"[FreeStuff] GamerPower (general) error: {e}")
            return []

    async def _match_gamerpower(self, platform_key: str, keywords: tuple, items: list) -> list:
        out = []
        for item in items:
            try:
                platforms_str = (item.get("platforms") or "").lower()
                if not any(kw in platforms_str for kw in keywords):
                    continue
                game = self._gp_item_to_game(item, platform_key)
                if game:
                    out.append(game)
            except Exception:
                continue
        return out

    async def _fetch_cheapshark(
        self, store_id: str, platform: str,
        upper: float, lower: float, min_disc: int,
    ) -> list:
        try:
            params = {
                "storeID": store_id,
                "pageSize": "60",
                "sortBy": "Recent",
                "upperPrice": str(upper),
            }
            if lower > 0:
                params["lowerPrice"] = str(lower)
            url = "https://www.cheapshark.com/api/1.0/deals?" + urllib.parse.urlencode(params)

            def _get():
                req = urllib.request.Request(url, headers={"User-Agent": "PhobosBot/1.0"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.loads(r.read())

            deals = await asyncio.to_thread(_get)
            out = []
            for d in deals:
                try:
                    normal = float(d.get("normalPrice") or 0)
                    sale = float(d.get("salePrice") or 0)
                    savings = float(d.get("savings") or 0)
                    if normal <= 0:
                        continue
                    if savings < min_disc:
                        continue
                    title = d.get("title", "")
                    if not title:
                        continue
                    steam_id = d.get("steamAppID")
                    image = (
                        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{steam_id}/header.jpg"
                        if steam_id else d.get("thumb", "")
                    )
                    deal_id = d.get("dealID", "")
                    out.append({
                        "id": f"{platform}_{d.get('gameID', deal_id)}",
                        "title": title,
                        "description": "",
                        "url": f"https://www.cheapshark.com/redirect?dealID={urllib.parse.quote(deal_id)}",
                        "image": image,
                        "end_date": "",
                        "original_price": normal,
                        "sale_price": sale,
                        "discount": int(savings),
                        "platform": platform,
                    })
                except Exception:
                    continue
            return out
        except Exception as e:
            print(f"[FreeStuff] CheapShark ({platform}) error: {e}")
            return []

    # ── Embed ─────────────────────────────────────────────────────────────────

    async def _send_embed(self, channel: discord.TextChannel, game: dict, is_deal: bool):
        info = PLATFORMS.get(game["platform"], {"name": game["platform"], "icon": "🎁", "color": 0x5865F2})
        disc = game.get("discount", 100)
        orig = game.get("original_price")
        sale = game.get("sale_price", 0.0)

        game_title = game.get("title") or "?"
        if len(game_title) > 200:
            game_title = game_title[:199] + "…"

        if is_deal:
            title_str = f"🔥 {game_title} — -{disc}%"
        else:
            title_str = f"{info['icon']} {game_title} — Kostenlos!"
        # Discord embed titles are capped at 256 chars - guard against any edge case
        # (e.g. a very high discount number) still pushing past the limit.
        if len(title_str) > 256:
            title_str = title_str[:255] + "…"

        embed = discord.Embed(
            title=title_str,
            description=game.get("description") or "",
            url=game["url"],
            color=info["color"],
        )
        if game.get("image"):
            embed.set_image(url=game["image"])
        if orig is not None and is_deal:
            embed.add_field(name="Normalpreis", value=f"{orig:.2f} €", inline=True)
            embed.add_field(name="Angebotspreis", value=f"{sale:.2f} €" if sale > 0 else "Gratis", inline=True)
            embed.add_field(name="Rabatt", value=f"-{disc}%", inline=True)
        elif game.get("end_date"):
            embed.add_field(name="Verfügbar bis", value=game["end_date"], inline=True)
        embed.add_field(name="Plattform", value=info["name"], inline=True)
        footer = "Angebot" if is_deal else "Kostenlos"
        embed.set_footer(text=f"{info['name']} • {footer}-Benachrichtigung")
        await channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(FreeStuff(bot))
