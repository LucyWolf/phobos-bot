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
their own average, everything else below is ordered by average rating.

User-requested follow-up ("die bewerungen möchte ich auch in dc posten können und andere sollen
die auch bewerten können und ich muss dafür ein text chanel anbinden können"): the list can now
be POSTED as a persistent, live-updating message in a dashboard-configured channel
(guild_configs' ratings_channel_id/ratings_message_id, set via main.py's /ratings/post route),
with an interactive Select menu right on that message so anyone can rate WITHOUT needing to know
the /bewerten command at all - picking an item opens an ephemeral row of 5 star buttons for that
one item. Both the Select and the star buttons feed through the exact same upsert as /bewerten
(never a second, diverging code path), and successfully rating from the posted message best-
effort refreshes that same message afterwards so its shown average/count never goes stale.

Second follow-up ("wäre cool wenn man da auch ein bild rein machen könnte genau wie bei
umfragen"): every item can now carry its own picture (dashboard-only, URL or upload - see
main.py's rating_item_add/edit). Discord only allows ONE image per embed, so - deliberately
mirroring cogs/polls.py's own _render_combined_poll_image solution to the exact same constraint
- every item's picture (when its raw bytes are available locally), label, star average/count
and a small fill bar (scaled to rating/5 rather than a vote share) are drawn together into ONE
combined canvas, which becomes this embed's single image. The handful of small helpers below
(_load_font/_hex_to_rgb/_fit_text/_cap_text_lines) are duplicated from cogs/polls.py rather than
imported - no cog in this project imports from another cog (see e.g. cogs/tickets.py's own
_parse_ticket_blocks docstring for the same, already-established convention), only main.py
imports shared pieces FROM cogs."""
import base64
import io

import discord
from discord import app_commands, ui
from discord.ext import commands
from database import db_exec, db_one, db_rows, get_guild_config

STAR_CHOICES = [
    app_commands.Choice(name="⭐ 1", value=1),
    app_commands.Choice(name="⭐⭐ 2", value=2),
    app_commands.Choice(name="⭐⭐⭐ 3", value=3),
    app_commands.Choice(name="⭐⭐⭐⭐ 4", value=4),
    app_commands.Choice(name="⭐⭐⭐⭐⭐ 5", value=5),
]

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]
_FONT_PATHS_REG = [p.replace("Bold", "").replace("-Bold", "") for p in _FONT_PATHS]


def _load_font(size: int, bold: bool = True):
    from PIL import ImageFont
    for p in (_FONT_PATHS if bold else _FONT_PATHS_REG):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _fit_text(draw, text: str, font, max_width: float) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return (text + "…") if text else "…"


def _cap_text_lines(lines: list, budget: int, joiner: str, more_label: str) -> str:
    """See cogs/polls.py's identical helper for the full rationale - duplicated rather than
    imported (no cog imports from another cog in this project)."""
    if not lines:
        return ""
    if budget <= 0:
        return more_label.format(n=len(lines))
    kept = []
    used = 0
    for i, line in enumerate(lines):
        added = len(line) + (len(joiner) if kept else 0)
        if used + added > budget:
            kept.append(more_label.format(n=len(lines) - i))
            break
        kept.append(line)
        used += added
    return joiner.join(kept)


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


def _render_combined_ratings_image(rows: list) -> bytes:
    """Same one-shared-canvas solution as cogs/polls.py's _render_combined_poll_image, applied
    to ratings instead of vote shares: Discord allows exactly one image per embed, so every
    item's own picture (drawn only when its raw bytes are already available locally - a bare
    external image_url with no local bytes falls back to a picture-less row, same reasoning as
    polls: this runs synchronously inside interaction/vote-handling code, a blocking network
    fetch here would stall the bot's event loop), label, star average/count, and a fill bar
    (scaled to avg/5 rather than a percentage of a shared vote total) are stacked into ONE PNG."""
    from PIL import Image, ImageDraw
    width = 440
    pad = 18
    bar_h = 16
    text_h = 24
    pic_gap = 8
    row_gap = 20
    label_font = _load_font(16, bold=True)
    meta_font = _load_font(13, bold=False)
    fill_rgb = (0xf5, 0xb4, 0x00)  # gold, matches the ⭐ theme (polls' bar is admin-colorable;
    # ratings has no such picker, a fixed gold keeps it unambiguously "this is a star rating")
    track_rgb = (0x40, 0x44, 0x4b)
    bg_rgba = (0x2b, 0x2d, 0x31, 255)

    prepared = []
    total_h = pad
    for i, row in enumerate(rows):
        pic = None
        if row.get("image_bytes"):
            try:
                pic = Image.open(io.BytesIO(row["image_bytes"]))
                pic.load()
                pic = pic.convert("RGBA")
                if pic.width > width:
                    pic = pic.resize((width, round(pic.height * width / pic.width)), Image.LANCZOS)
            except Exception:
                pic = None
        row_h = (pic.height + pic_gap if pic else 0) + text_h + bar_h
        prepared.append((pic, row_h))
        total_h += row_h + (row_gap if i < len(rows) - 1 else 0)
    total_h += pad

    canvas = Image.new("RGBA", (width, max(1, total_h)), bg_rgba)
    draw = ImageDraw.Draw(canvas)
    y = pad
    for row, (pic, _) in zip(rows, prepared):
        if pic is not None:
            x = (width - pic.width) // 2
            canvas.paste(pic, (x, y), pic)
            y += pic.height + pic_gap
        avg = row.get("avg_stars") or 0
        count = row.get("vote_count") or 0
        meta = f"⭐ {avg:.1f} ({count})" if count else "– keine Bewertungen –"
        meta_w = draw.textlength(meta, font=meta_font)
        prefix = "🌟 " if row.get("recommended") else ""
        label = _fit_text(draw, prefix + row["label"], label_font, width - pad * 2 - meta_w - 10)
        draw.text((pad, y), label, font=label_font, fill=(255, 255, 255))
        draw.text((width - pad - meta_w, y + 2), meta, font=meta_font, fill=(0xb5, 0xb8, 0xbe))
        bar_y = y + 24
        draw.rounded_rectangle([pad, bar_y, width - pad, bar_y + bar_h], radius=bar_h // 2, fill=track_rgb)
        pct = (avg / 5 * 100) if count else 0
        fill_w = max(0, min(width - pad * 2, round((width - pad * 2) * (pct / 100))))
        if fill_w > 0:
            fill_w = max(fill_w, bar_h)  # keeps a visible rounded blob even for a low average
            draw.rounded_rectangle([pad, bar_y, pad + fill_w, bar_y + bar_h], radius=bar_h // 2, fill=fill_rgb)
        y += text_h + bar_h + row_gap
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


async def build_ratings_embed(guild_id: int) -> tuple:
    """Shared by /bewertungen, the dashboard's post/update-message route, and every live refresh
    after a rating comes in via the posted message's own Select - one place for the layout so
    none of those call sites can ever drift apart from each other. Returns (embed, chart_files) -
    chart_files is a freshly generated discord.File list, same "always rebuild the attachment
    from scratch on every edit rather than trusting Discord kept an old one around" convention as
    cogs/polls.py's own chart_files (a rating's own picture/average/bar changes over time, unlike
    e.g. a ticket panel's static banner)."""
    items = await _ranked_items(guild_id)
    embed = discord.Embed(title="⭐ Bewertungsliste", color=0x7c3aed)
    if not items:
        embed.description = "Noch keine Einträge in der Bewertungsliste."
        return embed, []
    rows = []
    for it in items:
        image_bytes = None
        if it.get("image_data") and it.get("image_filename"):
            try:
                image_bytes = base64.b64decode(it["image_data"])
            except Exception:
                image_bytes = None
        rows.append({
            "label": it["label"], "recommended": it["recommended"],
            "avg_stars": it["avg_stars"], "vote_count": it["vote_count"],
            "image_bytes": image_bytes,
        })
    chart_bytes = _render_combined_ratings_image(rows)
    chart_files = [discord.File(io.BytesIO(chart_bytes), filename="ratings_bars.png")]
    embed.set_image(url="attachment://ratings_bars.png")

    # A picture is never clickable on Discord regardless of how it's rendered - same reasoning
    # as cogs/polls.py's own per-option link lines, listed separately here as real markdown
    # links right below the combined image instead of losing click-through entirely.
    link_lines = [f"🔗 [{it['label']}]({it['url']})" for it in items if it.get("url")]
    if link_lines:
        embed.description = _cap_text_lines(link_lines, 3900, "\n", "🔗 … und {n} weitere Links")
    embed.set_footer(text="🌟 = vom Team empfohlen  •  Zum Bewerten unten einen Eintrag wählen")
    return embed, chart_files


async def refresh_posted_list(bot, guild_id: int):
    """Best-effort - called after every successful rating AND every dashboard add/edit/delete of
    an item, so a persistently posted list message never shows a stale average/count/picture.
    Silently does nothing if this guild never posted one (no channel/message configured), the
    channel got deleted, or the message was removed outside the bot - exactly the same "don't
    let a cosmetic refresh crash the actual action that triggered it" principle as e.g.
    poll_edit_web's own best-effort live-message update in main.py. attachments= is always
    passed explicitly (even as an empty list, if the catalog was emptied out entirely) rather
    than omitted - unlike polls' rare legacy-banner exception, ratings has no "leave whatever's
    already attached alone" case to preserve, so every state transition controls its own
    attachment list outright."""
    channel_id = await get_guild_config(guild_id, "ratings_channel_id")
    message_id = await get_guild_config(guild_id, "ratings_message_id")
    if not channel_id or not message_id:
        return
    try:
        channel = bot.get_channel(int(channel_id))
        if not channel:
            return
        msg = await channel.fetch_message(int(message_id))
        items = await _ranked_items(guild_id)
        embed, chart_files = await build_ratings_embed(guild_id)
        await msg.edit(embed=embed, view=RatingsListView(items), attachments=chart_files)
    except Exception:
        pass


class RatingsStarButton(ui.Button):
    def __init__(self, item_id: int, stars: int):
        # Ephemeral, short-lived follow-up (tied to one Select interaction, times out with the
        # view below) - never posted as its own standalone channel message, so unlike
        # RatingsSelect's custom_id this one carries the item_id directly and doesn't need to
        # survive a bot restart via persistent re-registration.
        super().__init__(label="⭐" * stars, style=discord.ButtonStyle.secondary,
                          custom_id=f"rate_star_pick:{item_id}:{stars}")
        self.item_id = item_id
        self.stars = stars

    async def callback(self, interaction: discord.Interaction):
        row = await db_one(
            "SELECT * FROM rating_items WHERE id=? AND guild_id=?", (self.item_id, str(interaction.guild_id))
        )
        if not row:
            await interaction.response.edit_message(content="Dieser Eintrag existiert nicht (mehr).", view=None)
            return
        await db_exec(
            "INSERT INTO rating_votes (item_id,user_id,stars) VALUES (?,?,?) "
            "ON CONFLICT(item_id,user_id) DO UPDATE SET stars=excluded.stars",
            (self.item_id, interaction.user.id, self.stars),
        )
        agg = await db_one(
            "SELECT COUNT(*) AS c, AVG(stars) AS a FROM rating_votes WHERE item_id=?", (self.item_id,)
        )
        await interaction.response.edit_message(
            content=f"{'⭐' * self.stars} für **{row['label']}** gespeichert - jetzt {_stars_label(agg['a'], agg['c'])}.",
            view=None,
        )
        # interaction.client is always the actual Bot instance that received this interaction -
        # no need to store/pass one around separately just for this one best-effort refresh.
        await refresh_posted_list(interaction.client, interaction.guild_id)


class RatingsStarsView(ui.View):
    def __init__(self, item_id: int):
        super().__init__(timeout=300)
        for n in range(1, 6):
            self.add_item(RatingsStarButton(item_id, n))


class RatingsSelect(ui.Select):
    # Fixed regardless of which items are actually offered (varies per guild, per post) - same
    # reasoning as cogs/tickets.py's CloseTicketView: discord.py's persistent-view routing after
    # a restart matches purely by custom_id, never by a component's current options/label, so
    # ONE globally re-registered instance (cog_load, with a placeholder option - Discord itself
    # requires at least one) correctly routes clicks on every guild's own, differently-populated
    # already-posted message.
    def __init__(self, items: list):
        options = [
            discord.SelectOption(label=it["label"][:100], value=str(it["id"]))
            for it in items[:25]
        ] or [discord.SelectOption(label="Noch keine Einträge", value="_none")]
        super().__init__(
            placeholder="⭐ Zum Bewerten einen Eintrag wählen...", options=options,
            custom_id="ratings_pick_item", min_values=1, max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "_none":
            await interaction.response.send_message("Noch keine Einträge in der Bewertungsliste.", ephemeral=True)
            return
        try:
            item_id = int(self.values[0])
        except ValueError:
            return
        row = await db_one("SELECT * FROM rating_items WHERE id=? AND guild_id=?", (item_id, str(interaction.guild_id)))
        if not row:
            # Most likely cause: the item was deleted/the list was re-posted with different
            # entries between this message being shown and the user actually picking one.
            await interaction.response.send_message("Dieser Eintrag existiert nicht (mehr).", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Wie viele Sterne für **{row['label']}**?", view=RatingsStarsView(item_id), ephemeral=True
        )


class RatingsListView(ui.View):
    def __init__(self, items: list = None):
        super().__init__(timeout=None)
        self.add_item(RatingsSelect(items or []))


class Ratings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # Only needs registering ONCE globally (not per-guild, not per-message) - see
        # RatingsSelect's own docstring for why a single fixed custom_id suffices to route every
        # guild's differently-populated posted message correctly after a restart.
        self.bot.add_view(RatingsListView())

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
        await refresh_posted_list(self.bot, interaction.guild_id)

    @app_commands.command(name="bewertungen", description="Postet die aktuelle Bewertungsliste (mit Bewerten-Menü)")
    async def list_ratings(self, interaction: discord.Interaction):
        items = await _ranked_items(interaction.guild_id)
        embed, chart_files = await build_ratings_embed(interaction.guild_id)
        await interaction.response.send_message(embed=embed, view=RatingsListView(items), files=chart_files)


async def setup(bot):
    await bot.add_cog(Ratings(bot))
