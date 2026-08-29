import discord
from discord import app_commands
from discord.ext import commands
from database import db_rows, db_exec, db_exec_rowcount, db_one


class CustomCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        content = message.content.strip()
        if not content.startswith("!"):
            return
        parts = content[1:].split()
        if not parts:
            return
        trigger = parts[0].lower()
        row = await db_rows(
            "SELECT response FROM custom_commands WHERE guild_id=? AND trigger=?",
            (message.guild.id, trigger),
        )
        if row:
            try:
                await message.channel.send(row[0]["response"])
            except Exception as e:
                # Defense in depth: /addcommand and the dashboard now both reject a response
                # over Discord's 2000-char plain-message limit at save time, but a row saved
                # before that validation existed could still be sitting in the DB - without
                # this, on_message would raise unhandled here every single time someone
                # triggers that one command.
                print(f"[CustomCommands] send failed for trigger '{trigger}' in guild {message.guild.id}: {e}")

    @app_commands.command(name="addcommand", description="Eigenen Command erstellen")
    @app_commands.default_permissions(manage_guild=True)
    async def addcommand(self, interaction: discord.Interaction, trigger: str, response: str):
        trigger = trigger.lower().strip("!").strip()
        if not trigger:
            await interaction.response.send_message("Trigger darf nicht leer sein.", ephemeral=True)
            return
        if trigger in {c.name for c in self.bot.commands}:
            # Both this cog's on_message AND discord.py's own classic-command dispatcher (the
            # bot was built with command_prefix="!", see birthday.py's `!geburtstag`) run
            # independently for every message - a custom trigger that happens to match a real
            # registered command's name would fire BOTH on every use, sending two unrelated
            # responses for one message. Checked dynamically against self.bot.commands rather
            # than hardcoding "geburtstag" so this stays correct if more prefix commands are
            # ever added.
            await interaction.response.send_message(
                f"`!{trigger}` ist ein reservierter Befehlsname und kann nicht überschrieben werden.",
                ephemeral=True,
            )
            return
        if len(response) > 2000:
            # Discord's own hard limit for a plain (non-embed) message - on_message sends this
            # response as-is, so a longer value would silently never work once someone actually
            # triggers the command (now also caught defensively there, but better to reject it
            # here where the admin can see it and fix it right away).
            await interaction.response.send_message(
                "Antwort zu lang (max. 2000 Zeichen).", ephemeral=True
            )
            return
        existing = await db_one(
            "SELECT 1 FROM custom_commands WHERE guild_id=? AND trigger=?",
            (interaction.guild_id, trigger),
        )
        # A bare `except Exception` around the INSERT used to stand in for "this trigger
        # already exists" - too broad, since it would just as happily swallow an unrelated DB
        # error and report a false "aktualisiert" success. Atomic upsert instead, with the
        # existence check above only used to pick the right wording for the reply.
        await db_exec(
            "INSERT INTO custom_commands (guild_id,trigger,response) VALUES (?,?,?) "
            "ON CONFLICT(guild_id,trigger) DO UPDATE SET response=excluded.response",
            (interaction.guild_id, trigger, response),
        )
        verb = "aktualisiert" if existing else "erstellt"
        await interaction.response.send_message(f"Command `!{trigger}` {verb}.", ephemeral=True)

    @app_commands.command(name="delcommand", description="Eigenen Command löschen")
    @app_commands.default_permissions(manage_guild=True)
    async def delcommand(self, interaction: discord.Interaction, trigger: str):
        trigger = trigger.lower().strip("!").strip()
        deleted = await db_exec_rowcount(
            "DELETE FROM custom_commands WHERE guild_id=? AND trigger=?",
            (interaction.guild_id, trigger),
        )
        if deleted:
            await interaction.response.send_message(f"Command `!{trigger}` gelöscht.", ephemeral=True)
        else:
            # Previously said "gelöscht" unconditionally, even when no such trigger existed at
            # all (0 rows affected) - misleading confirmation for what was actually a no-op.
            await interaction.response.send_message(f"Command `!{trigger}` existiert nicht.", ephemeral=True)

    @app_commands.command(name="commands", description="Alle eigenen Commands anzeigen")
    async def list_commands(self, interaction: discord.Interaction):
        rows = await db_rows(
            "SELECT trigger, response FROM custom_commands WHERE guild_id=? ORDER BY trigger",
            (interaction.guild_id,),
        )
        if not rows:
            await interaction.response.send_message("Keine eigenen Commands.", ephemeral=True)
            return
        # Each line is already capped at 60 chars for the response, but with enough commands
        # the JOINED description could still exceed Discord's 4096-char embed description
        # limit (unguarded before this fix) - stop adding lines once close to that limit and
        # note how many were left out, instead of letting send_message raise.
        lines: list[str] = []
        total_len = 0
        for r in rows:
            line = f"`!{r['trigger']}` — {r['response'][:60]}"
            if total_len + len(line) + 1 > 3900:
                break
            lines.append(line)
            total_len += len(line) + 1
        remaining = len(rows) - len(lines)
        description = "\n".join(lines)
        if remaining > 0:
            description += f"\n… und {remaining} weitere"
        embed = discord.Embed(title="Eigene Commands", description=description, color=0x7c3aed)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(CustomCommands(bot))
