"""Polls via Discord buttons (one button per option) - /poll-create, /poll-end, or the
dashboard. Survives a bot restart like tickets/giveaways: persistent views (custom_id-routed)
get re-registered in cog_load(), and any poll with an auto-end time gets rescheduled with its
remaining delay, mirroring cogs/giveaways.py's _schedule()/_end_giveaway()."""
import asyncio
import base64
import datetime
import io
import discord
from discord import app_commands
from discord.ext import commands
from database import db_exec, db_exec_rowcount, db_insert, db_one, db_rows

MAX_OPTIONS = 25  # Discord's own hard ceiling for buttons on one message (5 rows x 5) - there
# is no way to have "unlimited" options with a button-per-option design, this is the real max.
MAX_DURATION_MINUTES = 10080  # 7 days - same kind of sane upper bound as other duration fields


MAX_RICH_OPTION_EMBEDS = 9  # Discord caps a message at 10 embeds total - one of those is the
# header embed (question/overall image/tally footer), leaving at most 9 for individual
# per-option image/link embeds. Any option beyond that still gets a bar-chart line in the
# header's description instead of its own rich embed - a poll with more than 9 image/link
# options simply can't show all of them richly in one Discord message, this is the real ceiling.


# v1.15.28 shipped a dropdown of 10 fixed emoji-color styles - rejected on sight ("so meinte ich
# das nicht ... ich meinte ein Slider ... optisch ähnlich wie das Original") in favor of a real
# color picker (any RGB value) with the bar rendered to LOOK like it (a genuinely smooth,
# continuously-filled bar, not a row of discrete emoji squares). Discord embeds are still plain
# text with no CSS, so an arbitrary custom color can only become a real generated image, not a
# character - see _render_bar_chart_image(). DEFAULT_BAR_COLOR matches the embed's own existing
# purple accent (0x7c3aed) so a poll that never touches this setting looks unchanged.
DEFAULT_BAR_COLOR = "#7c3aed"

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


def _hex_to_rgb(hex_color: str) -> tuple:
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        return (124, 58, 237)  # DEFAULT_BAR_COLOR's own RGB, as a safe fallback
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (124, 58, 237)


# v1.15.32's "an option with its own picture keeps a text bar in its footer" turned out to
# still look wrong to the user ("entferne alles ... was diese 4 ecke erzeugt") - even a single
# option with its own image made that one option's footer still show the old discrete-square
# look, and simply picking the nearest-matching emoji color didn't read as "fixed" to them.
# Removed entirely rather than reworked again: nothing in this file builds a square/emoji bar
# character anymore, anywhere. The one spot that still can't show the real generated bar-chart
# image (a per-option RICH embed - Discord allows only one image per embed, already used by the
# option's own picture there) now shows a plain percentage/vote-count line instead - still
# readable, just no bar visual at all, rather than a bar that looks inconsistent with the real
# generated one everywhere else.
def _pct_line(label: str, n: int, total: int) -> tuple:
    pct = (n / total * 100) if total else 0
    return f"**{label}**\n{pct:.0f}% ({n} Stimme(n))", pct


def _fit_text(draw, text: str, font, max_width: float) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return (text + "…") if text else "…"


def _render_bar_chart_image(rows: list, bar_color: str) -> bytes:
    """Renders one composite PNG with every option's label/percentage/vote-count and an actual
    smooth, continuously-filled progress bar in the admin's chosen RGB color - the reason this
    function exists at all: a Discord embed can only ever be plain text, no CSS, so a genuinely
    smooth bar in an arbitrary color has to be a real generated image (same "Pillow, like the
    welcome card" approach used elsewhere in this project), not a character. Becomes the header
    embed's own set_image() - safe to reuse that slot because the per-poll banner-image feature
    that used to live there was removed entirely in v1.15.20; build_poll_embed() only calls this
    when that now-legacy field is empty (an old poll that still has one keeps showing IT, see
    build_poll_embed's docstring, and falls back to the text bar instead)."""
    from PIL import Image, ImageDraw
    width = 440
    pad = 18
    bar_h = 14
    row_content_h = 24 + bar_h  # label baseline to the bottom of its bar
    gap = 16
    n_rows = max(1, len(rows))
    height = pad * 2 + n_rows * row_content_h + (n_rows - 1) * gap
    img = Image.new("RGB", (width, height), (0x2b, 0x2d, 0x31))  # matches the dashboard preview's
    draw = ImageDraw.Draw(img)                                    # own .poll-preview-embed bg
    label_font = _load_font(16, bold=True)
    meta_font = _load_font(13, bold=False)
    fill_rgb = _hex_to_rgb(bar_color)
    track_rgb = (0x40, 0x44, 0x4b)
    for i, row in enumerate(rows):
        y = pad + i * (row_content_h + gap)
        meta = f"{row['pct']:.0f}% ({row['n']})"
        meta_w = draw.textlength(meta, font=meta_font)
        label = _fit_text(draw, row["label"], label_font, width - pad * 2 - meta_w - 10)
        draw.text((pad, y), label, font=label_font, fill=(255, 255, 255))
        draw.text((width - pad - meta_w, y + 2), meta, font=meta_font, fill=(0xb5, 0xb8, 0xbe))
        bar_y = y + 24
        draw.rounded_rectangle([pad, bar_y, width - pad, bar_y + bar_h], radius=bar_h // 2, fill=track_rgb)
        fill_w = max(0, min(width - pad * 2, round((width - pad * 2) * (row["pct"] / 100))))
        if fill_w > 0:
            fill_w = max(fill_w, bar_h)  # keeps a visible rounded blob even for a tiny share
            draw.rounded_rectangle([pad, bar_y, pad + fill_w, bar_y + bar_h], radius=bar_h // 2, fill=fill_rgb)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _option_upload_file(opt: dict):
    """Rebuilds a discord.File for a per-option DASHBOARD UPLOAD (not a URL) from its stored
    base64 image_data - own copy of main.py's _embed_post_files() logic (cogs don't import from
    main.py, see cogs/tickets.py's _parse_ticket_blocks for the same established reason). Only
    needed now that a per-option rich embed always attaches a fresh generated bar image too
    (see build_poll_embed) - passing attachments= explicitly on every vote/end for THAT reason
    would otherwise silently drop an uploaded (non-URL) option picture, since Discord replaces
    the whole attachment set whenever attachments= is given, not just the file(s) being added.
    Returns None for a plain image_url (no attachment needed for that) or no image at all."""
    data_b64, filename = opt.get("image_data") or "", opt.get("image_filename") or ""
    if not data_b64 or not filename:
        return None
    try:
        return discord.File(io.BytesIO(base64.b64decode(data_b64)), filename=filename)
    except Exception:
        return None


def _render_option_bar_image(n: int, pct: float, bar_color: str) -> bytes:
    """Single-bar sibling of _render_bar_chart_image, for a per-option RICH embed (one that has
    its own picture and/or link). No label drawn - the option's name already shows as that
    embed's own title, so a second copy inside the image would be redundant. Exists because
    Discord gives one embed only ONE large image slot: as long as the option's own picture also
    wanted that slot, there was no room left for a real bar there at all (v1.15.29-1.15.33 all
    fell back to text-only for this one case in turn). build_poll_embed() now moves the option's
    own picture to the embed's SEPARATE, smaller thumbnail slot instead, freeing the large slot
    for this - both are visible at once, not a choice between them."""
    from PIL import Image, ImageDraw
    width = 440
    pad = 18
    bar_h = 16
    text_h = 22
    height = pad * 2 + text_h + bar_h
    img = Image.new("RGB", (width, height), (0x2b, 0x2d, 0x31))
    draw = ImageDraw.Draw(img)
    meta_font = _load_font(15, bold=True)
    fill_rgb = _hex_to_rgb(bar_color)
    track_rgb = (0x40, 0x44, 0x4b)
    meta = f"{pct:.0f}% ({n} Stimme(n))"
    draw.text((pad, pad), meta, font=meta_font, fill=(255, 255, 255))
    bar_y = pad + text_h
    draw.rounded_rectangle([pad, bar_y, width - pad, bar_y + bar_h], radius=bar_h // 2, fill=track_rgb)
    fill_w = max(0, min(width - pad * 2, round((width - pad * 2) * (pct / 100))))
    if fill_w > 0:
        fill_w = max(fill_w, bar_h)
        draw.rounded_rectangle([pad, bar_y, pad + fill_w, bar_y + bar_h], radius=bar_h // 2, fill=fill_rgb)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_poll_embed(
    question: str, multiple_choice: bool, options: list, counts: dict, ended: bool = False,
    image_url: str = "", image_filename: str = "", ends_at: str = "", created_at: str = "",
    bar_color: str = DEFAULT_BAR_COLOR,
) -> tuple:
    """Shared by creation, every vote, and _end_poll - one place for the bar/percentage layout
    so it can never drift between the three call sites. Returns (embeds, chart_files): embeds is
    a LIST, not a single one - if any option has its own image_url/link_url set (e.g. a VRChat
    world's cover image + world page link, one per map/option in the same poll), each such
    option gets its OWN embed (title = option label, clickable via embed.url when link_url is
    set) instead of being squeezed into one shared text description - up to MAX_RICH_OPTION_EMBEDS
    of them, Discord's 10-embeds-per-message limit otherwise. Options without their own
    image/link (or the overflow beyond that cap) still get a percentage line in the header
    embed's description, so no option's tally is ever dropped.

    chart_files is a list of freshly generated discord.File objects (see
    _render_bar_chart_image/_render_option_bar_image) - empty only when the poll has a legacy
    per-poll banner image occupying every image slot that would otherwise hold a generated bar
    (an old pre-v1.15.20 poll still has its original banner, the one remaining case with no bar
    at all). Otherwise: one shared bar-chart image for every option WITHOUT its own picture/link
    (the header embed's own image slot), PLUS one per-option bar image for every option WITH its
    own picture/link (that embed's image slot - its own picture moves to the smaller thumbnail
    slot instead, see build_poll_embed's per-option loop below, so both are visible together
    instead of one replacing the other). Unlike a per-poll/per-option image (attached ONCE at
    creation, never re-touched - see below), every file in chart_files has to be regenerated and
    RE-ATTACHED on every single vote/end, since its whole content (the bar fill %) changes every
    time - every caller MUST pass chart_files back in via `attachments=chart_files` whenever the
    list isn't empty, `omitted entirely` (not `attachments=[]` or `None`) whenever it IS, exactly
    mirroring the existing per-poll-image omission rule below.

    image_filename (set only when the per-POLL banner image came from a dashboard upload, not
    a pasted URL - a now-legacy field, see above) takes precedence over image_url and points at
    "attachment://<filename>" - the caller is responsible for actually attaching a matching
    discord.File with that same filename ONCE, at creation (see main.py's _embed_post_files,
    reused as-is for polls too). Deliberately NOT re-attached on every vote/end edit - a poll's
    per-poll image never changes after creation (no edit feature, same as giveaways), and
    discord.py's edit calls leave existing attachments alone when `attachments=`/`file=` is
    simply omitted (verified directly against discord.py 2.3.2's handle_message_parameters:
    attachments stays MISSING -> the 'attachments' key is left out of the request payload
    entirely -> Discord's own PATCH semantics keep whatever is already on the message). A
    per-OPTION image follows the exact same image_filename-takes-precedence-over-image_url rule
    and the exact same "attached once at creation, never re-touched" logic - each uploaded
    option image just needs its own unique attachment filename (handled by the caller, see
    main.py's poll_create_web) since Discord requires distinct filenames when a message carries
    more than one attachment.

    created_at/ends_at each become a Discord-native `<t:...:R>` relative timestamp at the top of
    the header's description ("Gestartet: vor 5 Minuten" / "Endet: in 2 Stunden") - Discord's
    OWN client renders and live-updates these (a countdown ticking down in real time for
    ends_at) with zero further edits from the bot, exactly like cogs/giveaways.py's own
    `discord.utils.format_dt(ends_at, 'R')` usage. created_at is shown whenever known (a poll
    always has one); ends_at only for a poll with an auto-end configured (nothing to show for a
    manual-only poll)."""
    total = sum(counts.values())
    header = discord.Embed(
        title=("🔒 " if ended else "🗳️ ") + question,
        color=0x64748b if ended else 0x7c3aed,
    )
    has_legacy_image = bool(image_filename or image_url)
    if image_filename:
        header.set_image(url=f"attachment://{image_filename}")
    elif image_url:
        header.set_image(url=image_url)
    kind = "Mehrfachauswahl" if multiple_choice else "Einzelauswahl"
    footer = f"{kind} · {total} Stimme(n)"
    if ended:
        footer += " · Beendet"
    header.set_footer(text=footer)

    header_lines = []
    if created_at:
        try:
            started_dt = datetime.datetime.fromisoformat(created_at)
            header_lines.append(f"**Gestartet:** {discord.utils.format_dt(started_dt, 'R')}")
        except Exception:
            pass
    if ends_at:
        try:
            ends_dt = datetime.datetime.fromisoformat(ends_at)
            label = "Beendet" if ended else "Endet"
            header_lines.append(f"**{label}:** {discord.utils.format_dt(ends_dt, 'R')}")
        except Exception:
            pass

    # Split options into two groups instead of one all-or-nothing "has_rich" switch (the pre-
    # v1.15.32 behavior): the moment ANY option had its own image/link, EVERY option - including
    # ones with nothing of their own - fell back to the old discrete-square text bar, because
    # the code only knew "rich poll" vs "plain poll", not "this specific option is rich". Live-
    # confirmed as the actual cause of a "the bar chart image never shows up" report: adding a
    # link to just ONE option (which auto-fetches a real picture, e.g. a game's cover art) was
    # enough to silently downgrade ALL other options' bars too, not just that one's - surprising
    # for a poll where several options have nothing to do with images/links at all.
    image_options, plain_options = [], []
    for opt in options:
        (image_options if (opt.get("image_url") or opt.get("image_filename") or opt.get("link_url")) else plain_options).append(opt)

    if not image_options:
        # No option anywhere has its own image/link - fully unchanged from before this split,
        # byte-for-byte the same behavior as when this was still a single "not has_rich" branch.
        if not has_legacy_image and options:
            rows = [
                {"label": opt["label"], "n": counts.get(opt["id"], 0),
                 "pct": (counts.get(opt["id"], 0) / total * 100) if total else 0}
                for opt in options
            ]
            chart_bytes = _render_bar_chart_image(rows, bar_color)
            chart_file = discord.File(io.BytesIO(chart_bytes), filename="poll_bars.png")
            header.set_image(url="attachment://poll_bars.png")
            if header_lines:
                header.description = "\n\n".join(header_lines)
            return [header], [chart_file]
        # Legacy per-poll banner image already occupies the header's image slot (a poll created
        # before v1.15.20) - keep showing IT rather than silently swapping in the new bar-chart
        # image, and fall back to a plain percentage line since there's no image slot left.
        pct_lines = [_pct_line(opt["label"], counts.get(opt["id"], 0), total)[0] for opt in options]
        combined = header_lines + pct_lines
        if combined:
            header.description = "\n\n".join(combined)
        return [header], []

    # At least one option has its own image/link. Those still get their own individual embed
    # (own image, own text/emoji footer bar - Discord allows only one image per embed, so a
    # generated bar-chart PNG genuinely has no room there). But any OTHER option in the SAME
    # poll that has nothing of its own is no longer forced into the same text-bar fallback just
    # because a sibling option happens to have a picture - it joins a shared bar-chart image
    # instead, using the header embed's own (otherwise unused, see has_legacy_image above) image
    # slot. Doesn't cost an extra embed slot (still header + up to MAX_RICH_OPTION_EMBEDS image
    # options, exactly Discord's 10-embeds-per-message ceiling as before this split) since it's
    # the header's EXISTING image, not a new embed.
    chart_files = []
    if plain_options:
        if not has_legacy_image:
            rows = [
                {"label": opt["label"], "n": counts.get(opt["id"], 0),
                 "pct": (counts.get(opt["id"], 0) / total * 100) if total else 0}
                for opt in plain_options
            ]
            chart_bytes = _render_bar_chart_image(rows, bar_color)
            chart_files.append(discord.File(io.BytesIO(chart_bytes), filename="poll_bars.png"))
            header.set_image(url="attachment://poll_bars.png")
        else:
            # Rare edge case: an old poll's legacy banner already occupies the header's one
            # image slot, so the plain options fall back to the old text bars too, same as the
            # no-image-options branch above already does for its own legacy-image case.
            header_lines += [
                _pct_line(opt["label"], counts.get(opt["id"], 0), total)[0] for opt in plain_options
            ]

    rich_options, overflow_options = image_options[:MAX_RICH_OPTION_EMBEDS], image_options[MAX_RICH_OPTION_EMBEDS:]

    # v1.15.34's first attempt moved EVERY option's own picture to the small thumbnail slot,
    # regardless of its admin-chosen size ("groß"/"klein"/benutzerdefinierte px) - rejected on
    # sight ("jetzt wieder zur bild größe ... das px 300 war perfekt lass es nur in px
    # skalieren"): a deliberately large/custom-width picture shrunk down to a ~80px thumbnail
    # defeats the whole point of that size choice. The size setting is respected again below -
    # 'large'/'custom' keep the picture in the big slot at its own configured size (no room left
    # there for a bar, same trade-off v1.15.29-33 settled on, just scoped to this one size now
    # instead of every option); only 'small' (which already shrinks the picture on purpose) frees
    # the big slot for a real bar. An option with a link but no picture of its own never competes
    # for either slot, so it gets the bar too.
    rich_info = []
    for opt in rich_options:
        if opt.get("image_filename"):
            img_src = f"attachment://{opt['image_filename']}"
        elif opt.get("image_url"):
            img_src = opt["image_url"]
        else:
            img_src = None
        needs_bar = (img_src is None) or (opt.get("image_size") == "small")
        rich_info.append((opt, img_src, needs_bar))

    # Whenever ANY attachment here needs a fresh (re-)upload this time - this option's own bar,
    # or the shared header bar built above for plain_options - every caller ends up passing
    # attachments= explicitly, which REPLACES the whole attachment set rather than adding to it.
    # So every rich option's own UPLOADED picture (a plain image_url needs no file at all) has to
    # ride along too, even one that itself shows no bar ('large'/'custom'), or it would vanish on
    # the very next vote/edit even though nothing about THAT option changed. When nothing
    # anywhere needs a bar (e.g. every option is 'large'/'custom' with no plain_options),
    # chart_files stays empty and every caller correctly omits attachments= entirely instead -
    # the original "attach once, never touch again" behavior, still intact for that case.
    if chart_files or any(needs_bar for _, _, needs_bar in rich_info):
        for opt, img_src, _ in rich_info:
            if opt.get("image_filename"):
                upload_file = _option_upload_file(opt)
                if upload_file:
                    chart_files.append(upload_file)

    embeds = [header]
    for opt, img_src, needs_bar in rich_info:
        n = counts.get(opt["id"], 0)
        pct = (n / total * 100) if total else 0
        option_embed = discord.Embed(title=opt["label"], color=0x64748b if ended else 0x7c3aed)
        if opt.get("link_url"):
            option_embed.url = opt["link_url"]
        if needs_bar:
            if img_src:
                option_embed.set_thumbnail(url=img_src)
            bar_filename = f"poll_opt_bar_{opt['id']}.png"
            bar_bytes = _render_option_bar_image(n, pct, bar_color)
            chart_files.append(discord.File(io.BytesIO(bar_bytes), filename=bar_filename))
            option_embed.set_image(url=f"attachment://{bar_filename}")
        elif img_src:
            option_embed.set_image(url=img_src)
        option_embed.set_footer(text=f"{pct:.0f}% ({n} Stimme(n))")
        embeds.append(option_embed)
    if overflow_options:
        header_lines += [
            _pct_line(opt["label"], counts.get(opt["id"], 0), total)[0] for opt in overflow_options
        ]
    if header_lines:
        header.description = "\n\n".join(header_lines)
    return embeds, chart_files


class PollButton(discord.ui.Button):
    def __init__(self, poll_id: int, option_id: int, label: str):
        super().__init__(
            label=label[:80], style=discord.ButtonStyle.secondary,
            custom_id=f"poll_vote:{poll_id}:{option_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        await _handle_vote(interaction, self.custom_id)


class PollView(discord.ui.View):
    def __init__(self, poll_id: int, options: list):
        super().__init__(timeout=None)
        for opt in options[:MAX_OPTIONS]:
            self.add_item(PollButton(poll_id, opt["id"], opt["label"]))


async def _handle_vote(interaction: discord.Interaction, custom_id: str):
    try:
        _, poll_id_s, option_id_s = custom_id.split(":")
        poll_id, option_id = int(poll_id_s), int(option_id_s)
    except (ValueError, IndexError):
        await interaction.response.send_message("Ungültige Umfrage.", ephemeral=True)
        return
    poll = await db_one("SELECT * FROM polls WHERE id=?", (poll_id,))
    if not poll or poll["ended"]:
        await interaction.response.send_message("Diese Umfrage ist bereits beendet.", ephemeral=True)
        return
    user_id = interaction.user.id
    if poll["multiple_choice"]:
        existing = await db_one(
            "SELECT id FROM poll_votes WHERE poll_id=? AND user_id=? AND option_id=?",
            (poll_id, user_id, option_id),
        )
        if existing:
            await db_exec("DELETE FROM poll_votes WHERE id=?", (existing["id"],))
        else:
            await db_exec(
                "INSERT INTO poll_votes (poll_id,user_id,option_id) VALUES (?,?,?)",
                (poll_id, user_id, option_id),
            )
    else:
        # Single choice: replace this user's ENTIRE vote for this poll (not just this one
        # option), so switching between options never leaves two rows for the same user.
        await db_exec("DELETE FROM poll_votes WHERE poll_id=? AND user_id=?", (poll_id, user_id))
        await db_exec(
            "INSERT INTO poll_votes (poll_id,user_id,option_id) VALUES (?,?,?)",
            (poll_id, user_id, option_id),
        )
    options = await db_rows("SELECT * FROM poll_options WHERE poll_id=? ORDER BY option_index", (poll_id,))
    rows = await db_rows("SELECT option_id, COUNT(*) c FROM poll_votes WHERE poll_id=? GROUP BY option_id", (poll_id,))
    counts = {r["option_id"]: r["c"] for r in rows}
    embeds, chart_files = build_poll_embed(
        poll["question"], bool(poll["multiple_choice"]), options, counts,
        image_url=poll.get("image_url") or "", image_filename=poll.get("image_filename") or "",
        ends_at=poll.get("ends_at") or "", created_at=poll.get("created_at") or "",
        bar_color=poll.get("bar_color") or DEFAULT_BAR_COLOR,
    )
    # No view= here on purpose - discord.py's edit_message() default for view is MISSING (not
    # None), so omitting it leaves the existing buttons untouched instead of needing to rebuild+
    # reattach an identical PollView on every single vote (verified directly against discord.py
    # 2.3.2's own source: InteractionResponse.edit_message only calls state.
    # prevent_view_updates_for()/replaces components when view is explicitly passed).
    # attachments=, unlike view=, MUST be passed whenever chart_files is non-empty - unlike a
    # per-poll/per-option image (attached once, never touched again), a generated bar image's
    # whole content (the fill %) changes with every vote, so fresh ones have to ride along on
    # every edit; the omit-to-preserve trick only applies to the OTHER, unrelated attachments (an
    # option's own picture, now always in its embed's thumbnail slot - see build_poll_embed).
    if chart_files:
        await interaction.response.edit_message(embeds=embeds, attachments=chart_files)
    else:
        await interaction.response.edit_message(embeds=embeds)


class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._tasks: dict = {}

    async def cog_load(self):
        await asyncio.sleep(2)
        active = await db_rows("SELECT * FROM polls WHERE ended=0")
        for p in active:
            options = await db_rows("SELECT * FROM poll_options WHERE poll_id=? ORDER BY option_index", (p["id"],))
            if options:
                # add_view() without a message_id registers the view under discord.py's global
                # custom_id fallback (ViewStore._views[None]) - the only way a poll's buttons
                # from a PREVIOUS process run become clickable again after a restart, since the
                # original in-memory View instance from back then is gone.
                self.bot.add_view(PollView(p["id"], options))
            if p.get("ends_at"):
                self._schedule(p)

    def _schedule(self, p: dict):
        pid = p["id"]
        if pid in self._tasks:
            return
        try:
            ends_at = datetime.datetime.fromisoformat(p["ends_at"])
        except Exception:
            return
        delay = (ends_at - datetime.datetime.utcnow()).total_seconds()
        if delay <= 0:
            self.bot.loop.create_task(self._end_poll(pid))
        else:
            self._tasks[pid] = self.bot.loop.call_later(
                delay, lambda: self.bot.loop.create_task(self._end_poll(pid))
            )

    async def _end_poll(self, poll_id: int):
        self._tasks.pop(poll_id, None)
        # Atomic ended=0->1 guard - returns 0 rows if a timer, /poll-end, and the dashboard's
        # "Beenden" button somehow race each other, so only the first one to land actually
        # finalizes the message.
        rows_updated = await db_exec_rowcount("UPDATE polls SET ended=1 WHERE id=? AND ended=0", (poll_id,))
        if rows_updated == 0:
            return
        poll = await db_one("SELECT * FROM polls WHERE id=?", (poll_id,))
        if not poll:
            return
        channel = self.bot.get_channel(int(poll["channel_id"])) if poll["channel_id"] else None
        if not channel:
            return
        try:
            msg = await channel.fetch_message(int(poll["message_id"]))
        except Exception:
            return
        options = await db_rows("SELECT * FROM poll_options WHERE poll_id=? ORDER BY option_index", (poll_id,))
        rows = await db_rows("SELECT option_id, COUNT(*) c FROM poll_votes WHERE poll_id=? GROUP BY option_id", (poll_id,))
        counts = {r["option_id"]: r["c"] for r in rows}
        embeds, chart_files = build_poll_embed(
            poll["question"], bool(poll["multiple_choice"]), options, counts, ended=True,
            image_url=poll.get("image_url") or "", image_filename=poll.get("image_filename") or "",
            ends_at=poll.get("ends_at") or "", created_at=poll.get("created_at") or "",
            bar_color=poll.get("bar_color") or DEFAULT_BAR_COLOR,
        )
        try:
            if chart_files:
                await msg.edit(embeds=embeds, view=None, attachments=chart_files)
            else:
                await msg.edit(embeds=embeds, view=None)
        except Exception as e:
            print(f"[Polls] failed to finalize poll {poll_id}: {e}")

    @app_commands.command(name="poll-create", description="Umfrage erstellen")
    @app_commands.default_permissions(manage_guild=True)
    async def poll_create(
        self, interaction: discord.Interaction, question: str,
        option1: str, option2: str,
        option3: str = None, option4: str = None, option5: str = None,
        option6: str = None, option7: str = None, option8: str = None,
        option9: str = None, option10: str = None,
        multiple: bool = False, duration_minutes: int = 0,
    ):
        # Capped at 10 explicit params (not the full 25-button ceiling _dashboard_ polls allow)
        # - a slash command renders one fillable field per parameter in Discord's own command
        # UI, so this is already a fairly long form; anything needing more options belongs on
        # the dashboard instead, per explicit user choice when this was raised.
        options = [o for o in [
            option1, option2, option3, option4, option5,
            option6, option7, option8, option9, option10,
        ] if o]
        if len(question) > 200:
            await interaction.response.send_message("Frage darf max. 200 Zeichen lang sein.", ephemeral=True)
            return
        if duration_minutes < 0 or duration_minutes > MAX_DURATION_MINUTES:
            await interaction.response.send_message(
                f"Dauer muss zwischen 0 (kein Auto-Ende) und {MAX_DURATION_MINUTES} Minuten liegen.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        created_at = datetime.datetime.utcnow().isoformat()
        ends_at = ""
        if duration_minutes > 0:
            ends_at = (datetime.datetime.utcnow() + datetime.timedelta(minutes=duration_minutes)).isoformat()
        pid = await db_insert(
            "INSERT INTO polls (guild_id,channel_id,question,multiple_choice,ends_at,created_by) VALUES (?,?,?,?,?,?)",
            (str(interaction.guild_id), str(interaction.channel_id), question, int(multiple), ends_at, interaction.user.id),
        )
        for i, label in enumerate(options):
            await db_exec(
                "INSERT INTO poll_options (poll_id,option_index,label) VALUES (?,?,?)",
                (pid, i, label[:80]),
            )
        opt_rows = await db_rows("SELECT * FROM poll_options WHERE poll_id=? ORDER BY option_index", (pid,))
        embeds, chart_files = build_poll_embed(question, multiple, opt_rows, {}, ends_at=ends_at, created_at=created_at)
        view = PollView(pid, opt_rows)
        try:
            msg = await interaction.channel.send(embeds=embeds, view=view, files=chart_files)
        except (discord.HTTPException, OSError) as e:
            # defer() already ran above - an unhandled exception here (missing "Send
            # Messages", or a genuine network-level OSError; discord.py 2.3.2's http.py
            # re-raises a real connection failure unwrapped on Linux, this project's actual
            # runtime) would otherwise leave the interaction stuck "thinking..." forever
            # instead of ever getting a followup, with no poll ever actually created.
            await db_exec("DELETE FROM polls WHERE id=?", (pid,))
            await interaction.followup.send(f"Umfrage konnte nicht gestartet werden: {e}", ephemeral=True)
            return
        await db_exec("UPDATE polls SET message_id=? WHERE id=?", (str(msg.id), pid))
        if ends_at:
            poll_row = await db_one("SELECT * FROM polls WHERE id=?", (pid,))
            self._schedule(poll_row)
        await interaction.followup.send("Umfrage gestartet!", ephemeral=True)

    @app_commands.command(name="poll-end", description="Umfrage vorzeitig beenden")
    @app_commands.default_permissions(manage_guild=True)
    async def poll_end(self, interaction: discord.Interaction, poll_id: int):
        poll = await db_one("SELECT id FROM polls WHERE id=? AND guild_id=?", (poll_id, str(interaction.guild_id)))
        if not poll:
            await interaction.response.send_message("Umfrage nicht gefunden.", ephemeral=True)
            return
        await self._end_poll(poll_id)
        await interaction.response.send_message("Umfrage beendet.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Polls(bot))
