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


# v1.15.28 shipped a dropdown of 10 fixed emoji-color styles - rejected on sight ("so meinte ich
# das nicht ... ich meinte ein Slider ... optisch ähnlich wie das Original") in favor of a real
# color picker (any RGB value) with the bar rendered to LOOK like it (a genuinely smooth,
# continuously-filled bar, not a row of discrete emoji squares). Discord embeds are still plain
# text with no CSS, so an arbitrary custom color can only become a real generated image, not a
# character - see _render_combined_poll_image(). DEFAULT_BAR_COLOR matches the embed's own
# existing purple accent (0x7c3aed) so a poll that never touches this setting looks unchanged.
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


# Only used for the rare legacy-banner fallback in build_poll_embed (a pre-v1.15.20 poll whose
# per-poll banner image still occupies the header embed's one image slot) - every other case
# now goes through _render_combined_poll_image() instead, see that function's docstring for why
# the whole per-option-embed/bar-budget machinery this used to feed (v1.15.29-1.15.41) is gone.
def _pct_line(label: str, n: int, total: int) -> tuple:
    pct = (n / total * 100) if total else 0
    return f"**{label}**\n{pct:.0f}% ({n} Stimme(n))", pct


MAX_DESCRIPTION_CHARS = 3900  # Discord's real embed-description hard limit is 4096 - same
# safety margin already used elsewhere in this project for user-editable text blocks. Matters
# here because the header embed's description can carry a per-option link line (label up to 80
# chars + a link_url up to 500, see main.py's poll_create_web/poll_edit_web) for as many as 25
# options - unbounded, that's up to ~14,700 characters, several times over the real limit, which
# would make Discord reject the whole send/edit outright (exactly the VRChat-multi-map-with-
# links use case this feature exists for).


def _cap_text_lines(lines: list, budget: int, joiner: str, more_label: str) -> str:
    """Joins as many whole `lines` (in order) with `joiner` as fit within `budget` characters -
    stops the moment the NEXT full line wouldn't fit rather than cutting one in half (a half-
    emitted markdown link like "[label](https://exam" can't be parsed as a link at all by
    Discord, worse than just not showing it) and appends one final line (`more_label`, formatted
    with the count of everything left out) for whatever had to be dropped. Returns '' for an
    empty `lines`."""
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


def _fit_text(draw, text: str, font, max_width: float) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return (text + "…") if text else "…"


def _render_combined_poll_image(rows: list, bar_color: str) -> bytes:
    """Renders ONE composite PNG holding EVERY option - label, percentage/vote-count, a smooth
    progress bar, and (whenever available) the option's own picture right above its row -
    replacing v1.15.29-1.15.41's per-option-embed design entirely. That design gave any option
    with its own picture/link a whole separate embed (Discord's one-image-per-embed limit left
    no other way to show a picture there) - which visually looked like several disconnected
    cards stacked in one message, even though the percentages were already computed against the
    shared vote total the whole time, not each option's own: "das sind aber nicht getrennt, die
    sollte zusammen sein und gegenseitig in % rechnen" - the fix isn't the math (that was already
    correct), it's putting every option into ONE shared image so it visibly reads as one poll.

    A row's own picture is drawn directly onto this canvas when the raw bytes are already
    available LOCALLY (a dashboard upload, or a link's auto-fetched image that went through the
    px-width resize pass into a real attachment) - downscaled to this canvas's width if wider,
    otherwise centered as-is so a deliberately narrow custom width isn't stretched. A picture
    that's only a bare external image_url (no local bytes) can't be fetched here (this runs
    synchronously inside embed-building code called from vote/interaction handlers - a blocking
    network request there would stall the bot's event loop) and falls back to a bar-only row,
    same as an option with no picture at all. Becomes the header embed's own set_image() - the
    per-poll banner-image feature that used to live in that slot was removed entirely in
    v1.15.20, see build_poll_embed's docstring for the one remaining legacy exception.

    A row's own clickable link (if any) is deliberately NOT part of this image - an image can
    never be clickable on Discord regardless of how it's built, and an embed only supports one
    url (which makes its TITLE clickable, not something inside its picture) - build_poll_embed
    lists any option links separately as markdown links in the header embed's own description
    text instead, right below this image."""
    from PIL import Image, ImageDraw
    width = 440
    pad = 18
    bar_h = 16
    text_h = 24  # label baseline to the bar's top - keep in sync with the "y + 24" below
    pic_gap = 8
    row_gap = 20
    label_font = _load_font(16, bold=True)
    meta_font = _load_font(13, bold=False)
    fill_rgb = _hex_to_rgb(bar_color)
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
        # The pic's own height (if any) was already added to y right after pasting it above -
        # only the label/bar block's fixed height plus the gap before the next row remains.
        y += text_h + bar_h + row_gap
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def build_poll_embed(
    question: str, multiple_choice: bool, options: list, counts: dict, ended: bool = False,
    image_url: str = "", image_filename: str = "", ends_at: str = "", created_at: str = "",
    bar_color: str = DEFAULT_BAR_COLOR, show_started: bool = False, show_ranking: bool = False,
) -> tuple:
    """Shared by creation, every vote, and _end_poll - one place for the bar/percentage layout
    so it can never drift between the three call sites. Returns (embeds, chart_files) - embeds
    is a list purely for historical/signature-compatibility reasons (every caller already does
    `embeds=embeds`); in practice it's now ALWAYS exactly one embed. v1.15.29-1.15.41 gave any
    option with its own picture/link a separate embed of its own (Discord only allows one image
    per embed, so a picture-having option had nowhere else to put one) - which visually read as
    several disconnected message cards rather than one poll, even though the percentages were
    always computed against the shared vote total the whole time: "das sind aber nicht getrennt,
    die sollte zusammen sein und gegenseitig in % rechnen". Replaced entirely with ONE combined
    image (_render_combined_poll_image) holding every option - its own picture (when locally
    available), label, percentage, vote count, and bar - stacked in a single canvas, which
    becomes this one embed's own image. A picture that's only a bare external URL (no local
    bytes to draw synchronously here) simply shows as a bar-only row instead, same as an option
    with no picture at all - see that function's docstring for exactly why.

    A per-option link_url is no longer a clickable embed.url on that option's own (now
    nonexistent) embed - a picture is never clickable on Discord regardless of how it's
    rendered, and only ONE url per embed exists at all (the header's own). Every option that has
    a link instead gets a markdown `[label](url)` line, listed together in the header embed's
    own description, right below the combined image - genuinely clickable, just no longer
    attached to a specific picture inside the image itself.

    chart_files is a list of freshly generated discord.File objects - the ONE combined image
    (via _render_combined_poll_image), unless a legacy per-poll banner from before v1.15.20
    already occupies the header's one image slot (see has_legacy_image below), in which case
    chart_files stays empty and every option instead gets a plain percentage-only text line, no
    image at all - the only situation left where an option's picture can't be shown at all
    (rare: only affects a poll whose own per-poll banner predates this feature). Whenever
    chart_files isn't empty, the caller MUST pass it back in via `attachments=chart_files` (it
    has to be regenerated on every single vote/end, since a bar's fill % changes every time) -
    whenever it IS empty, `attachments=` must be omitted entirely (not `attachments=[]` or
    `None`), exactly mirroring the existing per-poll-image omission rule below.

    image_filename (set only when the per-POLL banner image came from a dashboard upload, not
    a pasted URL - a now-legacy field, see above) takes precedence over image_url and points at
    "attachment://<filename>" - the caller is responsible for actually attaching a matching
    discord.File with that same filename ONCE, at creation (see main.py's _embed_post_files,
    reused as-is for polls too). Deliberately NOT re-attached on every vote/end edit - a poll's
    per-poll image never changes after creation (no edit feature, same as giveaways), and
    discord.py's edit calls leave existing attachments alone when `attachments=`/`file=` is
    simply omitted (verified directly against discord.py 2.3.2's handle_message_parameters:
    attachments stays MISSING -> the 'attachments' key is left out of the request payload
    entirely -> Discord's own PATCH semantics keep whatever is already on the message).

    ends_at becomes a Discord-native `<t:...:R>` relative timestamp at the top of the header's
    description ("Endet: in 2 Stunden") while the poll is still running - Discord's OWN client
    renders and live-updates this (a countdown ticking down in real time) with zero further
    edits from the bot, exactly like cogs/giveaways.py's own `discord.utils.format_dt(ends_at,
    'R')` usage. Once `ended`, that line becomes a plain, timeless "**Beendet**" instead - user-
    requested explicitly ("bendet seit brauchen wir nicht es reicht wenn dort benddet steht"),
    since a relative "ended X ago" keeps counting up forever and isn't actually useful once it's
    already over. created_at's own "Gestartet: vor 5 Minuten" line is OFF by default
    (`show_started=False`, same reasoning: not something every poll needs) - only shown when a
    poll's own `show_started` column is turned on.

    show_ranking (also OFF by default) adds a text ranking list to the description, sorted by
    current vote count descending - built for game-night-style polls with 3+ options ("spiel 1
    das was die meisten stimungen haben spiel zwei was dann als zweites gespielt wirt"). Runs
    live, alongside the existing bar chart/percentage display (not a replacement for it) - ties
    keep the options' original `option_index` order since Python's sort is stable."""
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
    if show_started and created_at:
        try:
            # created_at/ends_at are always naive isoformat strings that REPRESENT UTC (built
            # from datetime.utcnow() throughout this module - see _start_poll/poll_create's own
            # comments on this exact convention), but carry no tzinfo of their own.
            # discord.utils.format_dt() calls dt.timestamp() internally, and Python's own
            # .timestamp() on a naive datetime assumes it's already expressed in the PROCESS'S
            # LOCAL system timezone, not UTC - this project's docker-compose.yml sets
            # TZ=Europe/Berlin, so without attaching UTC explicitly here every single "Gestartet"/
            # "Endet" timestamp would render 1-2 hours (the Berlin UTC offset) in the wrong
            # direction in the live Discord message, even though the underlying stored value was
            # always correct - a real, live-reported bug ("ich habe dauer 10 min eingestelt warum
            # sind dort 2 h", CEST's +2h offset matching exactly what was shown). Never caught by
            # this project's own test harness because that happens to run on a host already
            # sitting at UTC, where the (still wrong) naive-local assumption is a no-op by
            # coincidence.
            started_dt = datetime.datetime.fromisoformat(created_at).replace(tzinfo=datetime.timezone.utc)
            header_lines.append(f"**Gestartet:** {discord.utils.format_dt(started_dt, 'R')}")
        except Exception:
            pass
    if ended:
        # A relative "beendet vor X" would just keep counting up forever once a poll is over -
        # not useful, and confusing next to a "live countdown" feature that's about time still
        # REMAINING. A plain, timeless label is all that's needed once it's already done.
        header_lines.append("**Beendet**")
    elif ends_at:
        try:
            ends_dt = datetime.datetime.fromisoformat(ends_at).replace(tzinfo=datetime.timezone.utc)
            header_lines.append(f"**Endet:** {discord.utils.format_dt(ends_dt, 'R')}")
        except Exception:
            pass

    chart_files = []
    if options and not has_legacy_image:
        rows = []
        for opt in options:
            n = counts.get(opt["id"], 0)
            pct = (n / total * 100) if total else 0
            image_bytes = None
            if opt.get("image_data") and opt.get("image_filename"):
                try:
                    image_bytes = base64.b64decode(opt["image_data"])
                except Exception:
                    image_bytes = None
            rows.append({"label": opt["label"], "n": n, "pct": pct, "image_bytes": image_bytes})
        chart_bytes = _render_combined_poll_image(rows, bar_color)
        chart_files.append(discord.File(io.BytesIO(chart_bytes), filename="poll_bars.png"))
        header.set_image(url="attachment://poll_bars.png")
    elif options:
        # Legacy per-poll banner image already occupies the header's image slot (a poll created
        # before v1.15.20) - keep showing IT rather than silently swapping in the combined
        # options image, and fall back to a plain percentage line since there's no image slot
        # left for anything else. Budget-capped same as the link list below - up to 25 options'
        # worth of these lines could otherwise exceed Discord's real description limit on their
        # own, before the header's own timestamp lines are even counted.
        pct_lines = [_pct_line(opt["label"], counts.get(opt["id"], 0), total)[0] for opt in options]
        used = len("\n\n".join(header_lines)) + (4 if header_lines else 0)
        capped = _cap_text_lines(
            pct_lines, MAX_DESCRIPTION_CHARS - used, "\n\n", "… und {n} weitere Optionen ohne Platz"
        )
        if capped:
            header_lines.append(capped)

    if show_ranking and options:
        ranked = sorted(options, key=lambda o: counts.get(o["id"], 0), reverse=True)
        medals = ["🥇", "🥈", "🥉"]
        ranking_lines = []
        for i, opt in enumerate(ranked):
            n = counts.get(opt["id"], 0)
            prefix = medals[i] if i < 3 else f"`{i + 1}.`"
            ranking_lines.append(f"{prefix} {opt['label']} ({n} Stimme(n))")
        used = len("\n\n".join(header_lines)) + (4 if header_lines else 0)
        capped = _cap_text_lines(
            ranking_lines, MAX_DESCRIPTION_CHARS - used, "\n", "… und {n} weitere Plätze ohne Platz"
        )
        if capped:
            header_lines.append("**🏆 Rangliste:**\n" + capped)

    # A clickable link can never live inside the combined image itself (see this function's own
    # docstring) - listed as its own markdown line per option that has one, right after
    # everything else in the header's description. Budget-capped against the SAME real Discord
    # limit (see MAX_DESCRIPTION_CHARS) - a poll with many options each carrying their own long
    # link (e.g. several VRChat world links) could otherwise push the whole description past
    # what Discord accepts, making the entire send/edit fail outright rather than just this list
    # looking incomplete.
    link_lines = [f"🔗 [{opt['label']}]({opt['link_url']})" for opt in options if opt.get("link_url")]
    if link_lines:
        used = len("\n\n".join(header_lines)) + (4 if header_lines else 0)
        capped = _cap_text_lines(link_lines, MAX_DESCRIPTION_CHARS - used, "\n", "🔗 … und {n} weitere Links")
        if capped:
            header_lines.append(capped)

    if header_lines:
        header.description = "\n\n".join(header_lines)
    return [header], chart_files


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
        bar_color=poll.get("bar_color") or DEFAULT_BAR_COLOR, show_started=bool(poll.get("show_started")),
        show_ranking=bool(poll.get("show_ranking")),
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
    try:
        if chart_files:
            await interaction.response.edit_message(embeds=embeds, attachments=chart_files)
        else:
            await interaction.response.edit_message(embeds=embeds)
    except (discord.HTTPException, OSError) as e:
        # The vote is already written to the DB above by this point - a failure here (a genuine
        # network hiccup, or discord.py 2.3.2's http.py re-raising a real connection failure
        # unwrapped on Linux; also newly reachable since the combined chart image can grow large
        # enough with many picture options to exceed Discord's upload size limit) would
        # otherwise leave the vote counted but the visible message never updated, with zero
        # feedback for the voter - every other Discord-API call in this file already has this
        # same guard, this was the one gap. response.send_message can itself raise
        # InteractionResponded if edit_message got far enough to consume the response before
        # failing - followup is the only thing left that can still reach the user in that case.
        print(f"[Polls] failed to update poll {poll_id} after vote: {e}")
        try:
            await interaction.response.send_message(
                "Deine Stimme wurde gezählt, aber die Anzeige konnte nicht aktualisiert werden.",
                ephemeral=True,
            )
        except discord.InteractionResponded:
            try:
                await interaction.followup.send(
                    "Deine Stimme wurde gezählt, aber die Anzeige konnte nicht aktualisiert werden.",
                    ephemeral=True,
                )
            except Exception:
                pass


class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._tasks: dict = {}
        self._start_tasks: dict = {}

    async def cog_load(self):
        await asyncio.sleep(2)
        active = await db_rows("SELECT * FROM polls WHERE ended=0")
        for p in active:
            # A poll with a still-pending starts_at and no message_id yet was never actually
            # posted - it has no buttons to re-register and no end-timer to resume, only a
            # future start to reschedule. Guard this BEFORE the add_view() below, since that
            # call assumes options exist for an already-live message.
            if p.get("starts_at") and not p.get("message_id"):
                self._schedule_start(p)
                continue
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

    def _schedule_start(self, p: dict):
        pid = p["id"]
        if pid in self._start_tasks:
            return
        try:
            starts_at = datetime.datetime.fromisoformat(p["starts_at"])
        except Exception:
            return
        delay = (starts_at - datetime.datetime.utcnow()).total_seconds()
        if delay <= 0:
            self.bot.loop.create_task(self._start_poll(pid))
        else:
            self._start_tasks[pid] = self.bot.loop.call_later(
                delay, lambda: self.bot.loop.create_task(self._start_poll(pid))
            )

    async def _start_poll(self, poll_id: int):
        self._start_tasks.pop(poll_id, None)
        # Same atomic guard idea as _end_poll - a poll that was already posted (e.g. deleted
        # its scheduled starts_at and got posted some other way) or already ended should never
        # be posted a second time.
        poll = await db_one("SELECT * FROM polls WHERE id=? AND ended=0", (poll_id,))
        if not poll or poll.get("message_id"):
            return
        channel = self.bot.get_channel(int(poll["channel_id"])) if poll["channel_id"] else None
        if not channel:
            print(f"[Polls] failed to start poll {poll_id}: channel {poll['channel_id']} not found")
            return
        options = await db_rows("SELECT * FROM poll_options WHERE poll_id=? ORDER BY option_index", (poll_id,))
        if not options:
            return
        # A "duration" end mode couldn't precompute ends_at at creation time (the poll wasn't
        # running yet) - resolve it now, relative to the moment the poll actually starts, not
        # to when it was originally scheduled.
        ends_at = poll.get("ends_at") or ""
        duration_minutes = poll.get("duration_minutes") or 0
        created_at = datetime.datetime.utcnow().isoformat()
        if not ends_at and duration_minutes > 0:
            ends_at = (datetime.datetime.utcnow() + datetime.timedelta(minutes=duration_minutes)).isoformat()
        embeds, chart_files = build_poll_embed(
            poll["question"], bool(poll["multiple_choice"]), options, {},
            image_url=poll.get("image_url") or "", image_filename=poll.get("image_filename") or "",
            ends_at=ends_at, created_at=created_at,
            bar_color=poll.get("bar_color") or DEFAULT_BAR_COLOR, show_started=bool(poll.get("show_started")),
        show_ranking=bool(poll.get("show_ranking")),
        )
        view = PollView(poll_id, options)
        try:
            msg = await channel.send(embeds=embeds, view=view, files=chart_files)
        except (discord.HTTPException, OSError) as e:
            print(f"[Polls] failed to start poll {poll_id}: {e}")
            return
        await db_exec(
            "UPDATE polls SET message_id=?, ends_at=?, created_at=? WHERE id=?",
            (str(msg.id), ends_at, created_at, poll_id),
        )
        if ends_at:
            poll_row = await db_one("SELECT * FROM polls WHERE id=?", (poll_id,))
            self._schedule(poll_row)

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
            bar_color=poll.get("bar_color") or DEFAULT_BAR_COLOR, show_started=bool(poll.get("show_started")),
        show_ranking=bool(poll.get("show_ranking")),
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
