"""Polls via Discord buttons (one button per option) - /poll-create, /poll-end, or the
dashboard. Survives a bot restart like tickets/giveaways: persistent views (custom_id-routed)
get re-registered in cog_load(), and any poll with an auto-end time gets rescheduled with its
remaining delay, mirroring cogs/giveaways.py's _schedule()/_end_giveaway()."""
import asyncio
import datetime
import discord
from discord import app_commands
from discord.ext import commands
from database import db_exec, db_exec_rowcount, db_insert, db_one, db_rows

MAX_OPTIONS = 25  # Discord's own hard ceiling for buttons on one message (5 rows x 5) - there
# is no way to have "unlimited" options with a button-per-option design, this is the real max.
MAX_DURATION_MINUTES = 10080  # 7 days - same kind of sane upper bound as other duration fields


def build_poll_embed(
    question: str, multiple_choice: bool, options: list, counts: dict, ended: bool = False,
    image_url: str = "", image_filename: str = "",
) -> discord.Embed:
    """Shared by creation, every vote, and _end_poll - one place for the bar/percentage layout
    so it can never drift between the three call sites. image_filename (set only when the
    image came from a dashboard upload, not a pasted URL) takes precedence and points at
    "attachment://<filename>" - the caller is responsible for actually attaching a matching
    discord.File with that same filename ONCE, at creation (see main.py's _embed_post_files,
    reused as-is for polls too). Deliberately NOT re-attached on every vote/end edit - a poll's
    image never changes after creation (no edit feature, same as giveaways), and discord.py's
    edit calls leave existing attachments alone when `attachments=`/`file=` is simply omitted
    (verified directly against discord.py 2.3.2's handle_message_parameters: attachments stays
    MISSING -> the 'attachments' key is left out of the request payload entirely -> Discord's
    own PATCH semantics keep whatever is already on the message)."""
    total = sum(counts.values())
    lines = []
    for opt in options:
        n = counts.get(opt["id"], 0)
        pct = (n / total * 100) if total else 0
        filled = round(pct / 10)
        bar = "█" * filled + "░" * (10 - filled)
        lines.append(f"**{opt['label']}**\n{bar} {pct:.0f}% ({n})")
    embed = discord.Embed(
        title=("🔒 " if ended else "🗳️ ") + question,
        description="\n\n".join(lines),
        color=0x64748b if ended else 0x7c3aed,
    )
    if image_filename:
        embed.set_image(url=f"attachment://{image_filename}")
    elif image_url:
        embed.set_image(url=image_url)
    kind = "Mehrfachauswahl" if multiple_choice else "Einzelauswahl"
    footer = f"{kind} · {total} Stimme(n)"
    if ended:
        footer += " · Beendet"
    embed.set_footer(text=footer)
    return embed


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
    embed = build_poll_embed(
        poll["question"], bool(poll["multiple_choice"]), options, counts,
        image_url=poll.get("image_url") or "", image_filename=poll.get("image_filename") or "",
    )
    # No view= (and no attachments=/file=) here on purpose - discord.py's edit_message() default for view is MISSING (not
    # None), so omitting it leaves the existing buttons untouched instead of needing to
    # rebuild+reattach an identical PollView on every single vote (verified directly against
    # discord.py 2.3.2's own source: InteractionResponse.edit_message only calls
    # state.prevent_view_updates_for()/replaces components when view is explicitly passed).
    await interaction.response.edit_message(embed=embed)


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
        embed = build_poll_embed(
            poll["question"], bool(poll["multiple_choice"]), options, counts, ended=True,
            image_url=poll.get("image_url") or "", image_filename=poll.get("image_filename") or "",
        )
        try:
            await msg.edit(embed=embed, view=None)
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
        embed = build_poll_embed(question, multiple, opt_rows, {})
        view = PollView(pid, opt_rows)
        try:
            msg = await interaction.channel.send(embed=embed, view=view)
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
