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
# header embed (question/overall image/tally footer), leaving a budget of 9 for individual
# per-option image/link embeds. This is spent per-option, not counted 1:1 anymore: an option
# with its own picture needs TWO embeds (the picture, then its bar as a genuinely separate card
# directly below - see build_poll_embed's per-option loop for why), an option with only a link
# needs just one (the bar has nowhere else to compete for the image slot there). Whatever
# doesn't fit in the remaining budget still gets a bar-chart line in the header's description
# instead of its own rich embed(s) - a poll with enough image/link options simply can't show all
# of them richly in one Discord message, this is the real ceiling.


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
    main.py, see cogs/tickets.py's _parse_ticket_blocks for the same established reason). Used by
    build_poll_embed() exclusively for its two-card fallback (an uploaded picture that couldn't
    be composited with its bar, or that has no bar to begin with) - that embed references the
    upload directly via attachment://, so the file has to physically ride along in chart_files
    every time, unlike a composited picture (which folds the upload INTO a fresh combo PNG
    instead, see _render_option_image_with_bar) or a plain image_url (no file needed at all,
    Discord fetches the URL itself). Returns None for a plain image_url or no image at all."""
    data_b64, filename = opt.get("image_data") or "", opt.get("image_filename") or ""
    if not data_b64 or not filename:
        return None
    try:
        return discord.File(io.BytesIO(base64.b64decode(data_b64)), filename=filename)
    except Exception:
        return None


def _render_option_image_with_bar(image_bytes: bytes, n: int, pct: float, bar_color: str):
    """v1.15.39's separate-card layout ("unter dem bild ... nicht im bild") got put side by
    side against baking the bar right into the picture instead ("baue den balken mal in das
    bild mit ein um zu schauen wie das jetzt ausieht") - this is that alternative: composites
    the option's own picture with a bar strip appended directly below it, INTO one single PNG,
    so the whole thing is one embed's one image again instead of two stacked cards. Only usable
    when the picture's raw bytes are already available locally (a dashboard upload, or a link's
    auto-fetched image after it went through the px-width resize pass) - a plain external
    image_url's bytes aren't fetched here (this function runs synchronously inside embed-
    building code called from vote/interaction handlers; a blocking network request there would
    stall the bot's event loop) - build_poll_embed's caller falls back to the two-card layout
    for that case instead. Returns None on any failure (corrupt/unreadable bytes) rather than
    raising - the caller then falls back to the two-card layout exactly as if there were no
    local bytes to begin with, never breaking the whole embed over one bad image."""
    from PIL import Image, ImageDraw
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
    except Exception:
        return None
    img = img.convert("RGBA")
    max_w = 440
    if img.width > max_w:
        img = img.resize((max_w, round(img.height * max_w / img.width)), Image.LANCZOS)
    pad = 18
    bar_h = 16
    text_h = 22
    strip_h = pad + text_h + bar_h + pad
    canvas = Image.new("RGBA", (img.width, img.height + strip_h), (0x2b, 0x2d, 0x31, 255))
    canvas.paste(img, (0, 0), img)
    draw = ImageDraw.Draw(canvas)
    meta_font = _load_font(15, bold=True)
    fill_rgb = _hex_to_rgb(bar_color)
    track_rgb = (0x40, 0x44, 0x4b)
    meta = f"{pct:.0f}% ({n} Stimme(n))"
    text_y = img.height + pad
    draw.text((pad, text_y), meta, font=meta_font, fill=(255, 255, 255))
    bar_y = text_y + text_h
    bar_x2 = img.width - pad
    draw.rounded_rectangle([pad, bar_y, bar_x2, bar_y + bar_h], radius=bar_h // 2, fill=track_rgb)
    fill_w = max(0, min(bar_x2 - pad, round((bar_x2 - pad) * (pct / 100))))
    if fill_w > 0:
        fill_w = max(fill_w, bar_h)
        draw.rounded_rectangle([pad, bar_y, pad + fill_w, bar_y + bar_h], radius=bar_h // 2, fill=fill_rgb)
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def _render_option_bar_image(n: int, pct: float, bar_color: str) -> bytes:
    """Single-bar sibling of _render_bar_chart_image, used ONLY for a per-option RICH embed that
    has NO picture of its own (a bare link_url, or truly nothing) - an option WITH its own
    picture keeps it in the embed's one large image slot at its own configured pixel width
    instead (see build_poll_embed's per-option loop), no bar for that case, there's no room left
    for one. No label drawn here - the option's name already shows as that embed's own title, so
    a second copy inside the image would be redundant."""
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
    option gets its OWN embed(s) (title = option label, clickable via embed.url when link_url is
    set) instead of being squeezed into one shared text description - a picture-having option
    gets a SECOND embed right after it too, holding just its progress bar (Discord's embed
    layout has no second image slot after the first within one embed, so a bar that must stay
    visually separate from the picture - never drawn into it - needs its own card instead), an
    option with only a link needs just the one. Costed against a shared MAX_RICH_OPTION_EMBEDS
    budget (Discord's 10-embeds-per-message limit, minus 1 for the header), 1 or 2 per option
    depending on whether it has its own picture - see the per-option loop below for the exact
    accounting. Whatever doesn't fit (or has no image/link at all) still gets a percentage line
    in the header embed's description, so no option's tally is ever dropped.

    chart_files is a list of freshly generated discord.File objects (see
    _render_bar_chart_image/_render_option_bar_image): one shared bar-chart image for every
    option WITHOUT its own picture/link (the header embed's own image slot, unless a legacy
    per-poll banner from before v1.15.20 already occupies it - then those options fall back to a
    plain percentage line with no bar instead), PLUS - for EVERY rich option - either a
    composite picture+bar PNG (an uploaded picture, bar baked directly in, see
    _render_option_image_with_bar) or a plain bar-only image (nothing of its own, or a bare
    external URL that couldn't be composited - the latter also re-attaches the picture's own
    upload alongside its bar, see the per-option loop). chart_files is the COMPLETE, authoritative
    attachment list needed to render everything build_poll_embed just returned - a caller never
    needs to separately collect anything for an option's own picture, only the per-POLL banner
    image stays the caller's own responsibility (attached once at creation, never re-touched -
    see below). Every file in chart_files has to be regenerated and RE-ATTACHED on every single
    vote/end regardless of which of these cases produced it (a bar's fill % or a composite's
    whole content changes every time) - every caller MUST pass chart_files back in via
    `attachments=chart_files` whenever the list isn't empty, `omitted entirely` (not
    `attachments=[]` or `None`) whenever it IS empty, exactly mirroring the existing per-poll-
    image omission rule below.

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

    # At least one option has its own image/link. Those still get their own individual embed(s)
    # (see the per-option loop further below for exactly how the picture and its bar split
    # across one or two cards). But any OTHER option in the SAME poll that has nothing of its
    # own is no longer forced into the same fallback just because a sibling option happens to
    # have a picture - it joins a shared bar-chart image instead, using the header embed's own
    # (otherwise unused, see has_legacy_image above) image slot. Doesn't cost an extra embed slot
    # since it's the header's EXISTING image, not a new embed.
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

    # v1.15.34-39 went back and forth on where an option's own picture and its bar can coexist:
    # thumbnail+bar, picture-only-no-bar, then a genuinely separate second card below the
    # picture (v1.15.39, "nicht im bild"). Immediately compared side by side against the
    # opposite ("baue den balken mal in das bild mit ein um zu schauen wie das jetzt ausieht") -
    # baking it directly into the picture as ONE composite PNG (_render_option_image_with_bar)
    # instead. That's only possible when the picture's raw bytes are available LOCALLY (a
    # dashboard upload, or a link's auto-fetched image after the px-width resize pass turned it
    # into one - see that function's docstring for why a plain external image_url can't be
    # composited here) - a picture with no local bytes still falls back to the v1.15.39 two-card
    # layout, the only way left to keep bar and picture visually distinct without them.
    # Budgeted per-option against Discord's 10-embeds-per-message cap (minus 1 for the header):
    # 1 for no picture (bar in its own slot) or a picture WITH local bytes (composited into one
    # embed), 2 only for a picture that's a bare external URL (needs the two-card fallback).
    BAR_EMBED_BUDGET = MAX_RICH_OPTION_EMBEDS
    rich_options, overflow_options = [], []
    used_budget = 0
    for opt in image_options:
        has_pic = bool(opt.get("image_filename") or opt.get("image_url"))
        has_local_bytes = bool(opt.get("image_data")) and bool(opt.get("image_filename"))
        cost = 1 if (not has_pic or has_local_bytes) else 2
        if used_budget + cost <= BAR_EMBED_BUDGET:
            rich_options.append(opt)
            used_budget += cost
        else:
            overflow_options.append(opt)

    embeds = [header]
    for opt in rich_options:
        n = counts.get(opt["id"], 0)
        pct = (n / total * 100) if total else 0
        if opt.get("image_filename"):
            img_src = f"attachment://{opt['image_filename']}"
        elif opt.get("image_url"):
            img_src = opt["image_url"]
        else:
            img_src = None

        option_embed = discord.Embed(title=opt["label"], color=0x64748b if ended else 0x7c3aed)
        if opt.get("link_url"):
            option_embed.url = opt["link_url"]

        if img_src is None:
            # Nothing of its own - the bar goes directly into this embed's own image slot.
            bar_filename = f"poll_opt_bar_{opt['id']}.png"
            bar_bytes = _render_option_bar_image(n, pct, bar_color)
            chart_files.append(discord.File(io.BytesIO(bar_bytes), filename=bar_filename))
            option_embed.set_image(url=f"attachment://{bar_filename}")
            embeds.append(option_embed)
            continue

        combo_bytes = None
        if opt.get("image_data") and opt.get("image_filename"):
            try:
                combo_bytes = _render_option_image_with_bar(
                    base64.b64decode(opt["image_data"]), n, pct, bar_color,
                )
            except Exception:
                combo_bytes = None

        if combo_bytes:
            # Picture + bar baked into one PNG - a single embed, single image slot.
            combo_filename = f"poll_opt_combo_{opt['id']}.png"
            chart_files.append(discord.File(io.BytesIO(combo_bytes), filename=combo_filename))
            option_embed.set_image(url=f"attachment://{combo_filename}")
            embeds.append(option_embed)
        else:
            # No local bytes to composite (a plain external URL), or compositing failed on a
            # corrupt upload - two-card fallback: the picture keeps this embed (re-attaching the
            # raw upload itself if it IS an upload, since this embed references it directly -
            # a plain URL needs no file at all), the bar rides as its own separate card after.
            if opt.get("image_filename"):
                upload_file = _option_upload_file(opt)
                if upload_file:
                    chart_files.append(upload_file)
                else:
                    # Same corrupt/unreadable bytes that already failed to composite also failed
                    # to decode here - nothing valid to reference, so don't set an image at all
                    # rather than pointing at attachment://a-file-that-was-never-attached (a
                    # broken image in Discord, same failure mode this whole file exists to
                    # avoid). The option still gets its title + bar card below.
                    img_src = None
            if img_src:
                option_embed.set_image(url=img_src)
            embeds.append(option_embed)
            bar_filename = f"poll_opt_bar_{opt['id']}.png"
            bar_bytes = _render_option_bar_image(n, pct, bar_color)
            chart_files.append(discord.File(io.BytesIO(bar_bytes), filename=bar_filename))
            bar_embed = discord.Embed(color=0x64748b if ended else 0x7c3aed)
            bar_embed.set_image(url=f"attachment://{bar_filename}")
            embeds.append(bar_embed)
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
    # every edit; the omit-to-preserve trick only applies when NOTHING in the poll needs a bar at
    # all, so nothing here needed re-attaching in the first place (see build_poll_embed).
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
