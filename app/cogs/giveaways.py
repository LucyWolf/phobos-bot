import asyncio
import datetime
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import db_exec, db_exec_rowcount, db_insert, db_one, db_rows


GIVEAWAY_EMOJI = "🎉"


class Giveaways(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._tasks: dict = {}

    async def cog_load(self):
        await asyncio.sleep(2)
        active = await db_rows("SELECT * FROM giveaways WHERE ended=0")
        for g in active:
            self._schedule(g)

    def _schedule(self, g: dict):
        gid = g["id"]
        if gid in self._tasks:
            return
        try:
            ends_at = datetime.datetime.fromisoformat(g["ends_at"])
        except Exception:
            return
        delay = (ends_at - datetime.datetime.utcnow()).total_seconds()
        if delay <= 0:
            self.bot.loop.create_task(self._end_giveaway(gid))
        else:
            task = self.bot.loop.call_later(delay, lambda: self.bot.loop.create_task(self._end_giveaway(gid)))
            self._tasks[gid] = task

    async def _end_giveaway(self, giveaway_id: int):
        self._tasks.pop(giveaway_id, None)
        # Atomisch auf ended=1 setzen — liefert 0 zurück wenn schon beendet
        rows_updated = await db_exec_rowcount(
            "UPDATE giveaways SET ended=1 WHERE id=? AND ended=0", (giveaway_id,)
        )
        if rows_updated == 0:
            return
        g = await db_one("SELECT * FROM giveaways WHERE id=?", (giveaway_id,))
        if not g:
            return
        channel = self.bot.get_channel(g["channel_id"])
        if not channel:
            return
        try:
            msg = await channel.fetch_message(g["message_id"])
        except Exception:
            return

        users = []
        for reaction in msg.reactions:
            if str(reaction.emoji) == GIVEAWAY_EMOJI:
                async for user in reaction.users():
                    if not user.bot:
                        users.append(user)
                break

        embed = msg.embeds[0] if msg.embeds else discord.Embed()
        if not users:
            embed.color = 0x64748b
            embed.set_footer(text="Niemand hat teilgenommen.")
            await msg.edit(embed=embed)
            await channel.send("Niemand hat am Giveaway teilgenommen.")
            return

        # A reroll (giveaway_reroll resets ended=0 and calls this again) would otherwise be
        # able to pick the exact same winner(s) again, since this only ever looked at who's
        # currently reacted with no memory of who already won - defeating the actual point of
        # rerolling (usually: the previous winner didn't respond, give someone else a chance).
        # Exclude everyone recorded as a past winner of this giveaway, falling back to the full
        # pool only if that would leave nobody left to pick from.
        prev_winner_ids = {int(x) for x in (g.get("winner_ids") or "").split(",") if x.strip()}
        pool = [u for u in users if u.id not in prev_winner_ids] or users

        winners_count = min(g["winners"], len(pool))
        winners = random.sample(pool, winners_count)
        mentions = " ".join(w.mention for w in winners)

        await db_exec(
            "UPDATE giveaways SET winner_ids=? WHERE id=?",
            (",".join(str(i) for i in prev_winner_ids | {w.id for w in winners}), giveaway_id),
        )

        embed.color = 0x64748b
        embed.set_footer(text=f"Gewinner: {', '.join(str(w) for w in winners)}")
        await msg.edit(embed=embed)
        await channel.send(f"🎉 Glückwunsch {mentions}! Du/Ihr habt **{g['prize']}** gewonnen!")

    @app_commands.command(name="giveaway-start", description="Giveaway starten")
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_start(self, interaction: discord.Interaction, prize: str, duration_minutes: int, winners: int = 1):
        if winners < 1:
            # random.sample() raises ValueError for a negative/zero sample size - without this
            # check that would only surface much later when the giveaway actually ends (in the
            # scheduled task, unhandled), leaving it stuck "ended" with no winner announcement
            # ever sent instead of rejecting the obviously-wrong input up front.
            await interaction.response.send_message("Anzahl Gewinner muss mindestens 1 sein.", ephemeral=True)
            return
        if duration_minutes < 1:
            await interaction.response.send_message("Dauer muss mindestens 1 Minute sein.", ephemeral=True)
            return
        ends_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=duration_minutes)
        embed = discord.Embed(
            title=f"🎉 GIVEAWAY: {prize}",
            description=f"Reagiere mit {GIVEAWAY_EMOJI} um teilzunehmen!\n\n**Gewinner:** {winners}\n**Endet:** {discord.utils.format_dt(ends_at, 'R')}",
            color=0x7c3aed,
        )
        embed.set_footer(text=f"Endet am {ends_at.strftime('%d.%m.%Y %H:%M')} UTC")
        await interaction.response.defer(ephemeral=True)
        msg = await interaction.channel.send(embed=embed)
        await msg.add_reaction(GIVEAWAY_EMOJI)

        gid = await db_insert(
            "INSERT INTO giveaways (guild_id,channel_id,message_id,prize,winners,ends_at,created_by) VALUES (?,?,?,?,?,?,?)",
            (interaction.guild_id, interaction.channel_id, msg.id, prize, winners, ends_at.isoformat(), interaction.user.id),
        )

        g = await db_one("SELECT * FROM giveaways WHERE id=?", (gid,))
        self._schedule(g)
        await interaction.followup.send(f"Giveaway gestartet! Endet in {duration_minutes} Minuten.", ephemeral=True)

    @app_commands.command(name="giveaway-end", description="Giveaway sofort beenden")
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_end(self, interaction: discord.Interaction, giveaway_id: int):
        g = await db_one("SELECT id FROM giveaways WHERE id=? AND guild_id=?", (giveaway_id, interaction.guild_id))
        if not g:
            await interaction.response.send_message("Giveaway nicht gefunden.", ephemeral=True)
            return
        await self._end_giveaway(giveaway_id)
        await interaction.response.send_message("Giveaway beendet.", ephemeral=True)

    @app_commands.command(name="giveaway-reroll", description="Giveaway neu auslosen")
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_reroll(self, interaction: discord.Interaction, message_id: str):
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("Ungültige Nachrichten-ID.", ephemeral=True)
            return
        g = await db_one("SELECT * FROM giveaways WHERE message_id=? AND guild_id=?", (mid, interaction.guild_id))
        if not g:
            await interaction.response.send_message("Giveaway nicht gefunden.", ephemeral=True)
            return
        await db_exec("UPDATE giveaways SET ended=0 WHERE id=?", (g["id"],))
        await self._end_giveaway(g["id"])
        await interaction.response.send_message("Neu ausgelost!", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Giveaways(bot))
