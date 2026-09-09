"""Ratings: an admin-curated catalog of maps/sites/games/whatever ("die maps oder seiten in
eine liste eintragen"), entered/edited on the dashboard - members star-rate any entry at any
time via /bewerten, and /bewertungen shows the current ranked list in Discord. Deliberately
separate from cogs/polls.py: a poll is a one-shot, time-boxed vote between fixed options, while
a rating list is a persistent, ever-growing catalog anyone can add an opinion to whenever they
like - the two share no state and don't need to.

A re-rating REPLACES a user's previous star value for that item (confirmed: "pro map/link/spiel
... hat einer nur 1 stern") via a plain UNIQUE(item_id,user_id) + ON CONFLICT upsert, not a
second accumulating row - the average always reflects everyone's CURRENT opinion, not a history
of every past one. "Empfohlen" is a manual per-item admin toggle (dashboard-only, no slash
command for it) that coexists with the automatic best-rated-first sort rather than replacing it
(confirmed: "beides einstellbar") - recommended items are always sorted to the top regardless of
their own average, everything else below is ordered by average rating."""
import discord
from discord import app_commands
from discord.ext import commands
from database import db_exec, db_one, db_rows

STAR_CHOICES = [
    app_commands.Choice(name="⭐ 1", value=1),
    app_commands.Choice(name="⭐⭐ 2", value=2),
    app_commands.Choice(name="⭐⭐⭐ 3", value=3),
    app_commands.Choice(name="⭐⭐⭐⭐ 4", value=4),
    app_commands.Choice(name="⭐⭐⭐⭐⭐ 5", value=5),
]


def _stars_label(avg, count: int) -> str:
    if not count:
        return "– noch keine Bewertungen –"
    return f"⭐ {avg:.1f} ({count} Bewertung{'en' if count != 1 else ''})"


async def _ranked_items(guild_id: int) -> list:
    """Recommended items first (manual flag, independent of rating), then everything else
    sorted by average rating descending - a never-rated item's NULL average sorts last in
    SQLite's own DESC ordering, exactly the "not enough data yet" spot it belongs in."""
    return await db_rows(
        "SELECT i.*, "
        "(SELECT COUNT(*) FROM rating_votes v WHERE v.item_id=i.id) AS vote_count, "
        "(SELECT AVG(stars) FROM rating_votes v WHERE v.item_id=i.id) AS avg_stars "
        "FROM rating_items i WHERE i.guild_id=? "
        "ORDER BY i.recommended DESC, avg_stars DESC, i.label COLLATE NOCASE",
        (str(guild_id),),
    )


class Ratings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _item_autocomplete(self, interaction: discord.Interaction, current: str):
        rows = await db_rows(
            "SELECT id, label FROM rating_items WHERE guild_id=? AND label LIKE ? "
            "ORDER BY label COLLATE NOCASE LIMIT 25",
            (str(interaction.guild_id), f"%{current}%"),
        )
        return [app_commands.Choice(name=r["label"][:100], value=r["id"]) for r in rows]

    @app_commands.command(name="bewerten", description="Einen Eintrag aus der Bewertungsliste mit Sternen bewerten")
    @app_commands.describe(item="Map/Seite/Spiel/...", sterne="1 (schlecht) bis 5 (super)")
    @app_commands.choices(sterne=STAR_CHOICES)
    @app_commands.autocomplete(item=_item_autocomplete)
    async def rate(self, interaction: discord.Interaction, item: int, sterne: app_commands.Choice[int]):
        row = await db_one("SELECT * FROM rating_items WHERE id=? AND guild_id=?", (item, str(interaction.guild_id)))
        if not row:
            # Most likely cause: the item was deleted on the dashboard between the user opening
            # autocomplete and actually submitting - not a real error to log, just stale UI.
            await interaction.response.send_message("Dieser Eintrag existiert nicht (mehr).", ephemeral=True)
            return
        await db_exec(
            "INSERT INTO rating_votes (item_id,user_id,stars) VALUES (?,?,?) "
            "ON CONFLICT(item_id,user_id) DO UPDATE SET stars=excluded.stars",
            (item, interaction.user.id, sterne.value),
        )
        agg = await db_one(
            "SELECT COUNT(*) AS c, AVG(stars) AS a FROM rating_votes WHERE item_id=?", (item,)
        )
        await interaction.response.send_message(
            f"{sterne.name} für **{row['label']}** gespeichert - jetzt {_stars_label(agg['a'], agg['c'])}.",
            ephemeral=True,
        )

    @app_commands.command(name="bewertungen", description="Zeigt die aktuelle Bewertungsliste")
    async def list_ratings(self, interaction: discord.Interaction):
        items = await _ranked_items(interaction.guild_id)
        if not items:
            await interaction.response.send_message("Noch keine Einträge in der Bewertungsliste.", ephemeral=True)
            return
        embed = discord.Embed(title="⭐ Bewertungsliste", color=0x7c3aed)
        lines = []
        for it in items:
            prefix = "🌟 " if it["recommended"] else ""
            line = f"{prefix}**{it['label']}**"
            if it.get("url"):
                line = f"{prefix}**[{it['label']}]({it['url']})**"
            line += f"\n{_stars_label(it['avg_stars'], it['vote_count'])}"
            lines.append(line)
        # Same real Discord embed-description limit / cut-without-breaking-a-line safety margin
        # already established in cogs/polls.py for its own option lists - a catalog can grow
        # past what fits in one message just as easily as a poll's options can.
        budget = 3900
        kept = []
        used = 0
        for i, line in enumerate(lines):
            added = len(line) + (2 if kept else 0)
            if used + added > budget:
                kept.append(f"… und {len(lines) - i} weitere")
                break
            kept.append(line)
            used += added
        embed.description = "\n\n".join(kept)
        embed.set_footer(text="🌟 = vom Team empfohlen")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Ratings(bot))
