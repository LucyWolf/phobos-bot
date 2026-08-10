import discord
from discord import app_commands
from discord.ext import commands
from database import db_rows, db_exec


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
        trigger = content[1:].split()[0].lower()
        row = await db_rows(
            "SELECT response FROM custom_commands WHERE guild_id=? AND trigger=?",
            (message.guild.id, trigger),
        )
        if row:
            await message.channel.send(row[0]["response"])

    @app_commands.command(name="addcommand", description="Eigenen Command erstellen")
    @app_commands.default_permissions(manage_guild=True)
    async def addcommand(self, interaction: discord.Interaction, trigger: str, response: str):
        trigger = trigger.lower().strip("!")
        try:
            await db_exec(
                "INSERT INTO custom_commands (guild_id,trigger,response) VALUES (?,?,?)",
                (interaction.guild_id, trigger, response),
            )
            await interaction.response.send_message(f"Command `!{trigger}` erstellt.", ephemeral=True)
        except Exception:
            await db_exec(
                "UPDATE custom_commands SET response=? WHERE guild_id=? AND trigger=?",
                (response, interaction.guild_id, trigger),
            )
            await interaction.response.send_message(f"Command `!{trigger}` aktualisiert.", ephemeral=True)

    @app_commands.command(name="delcommand", description="Eigenen Command löschen")
    @app_commands.default_permissions(manage_guild=True)
    async def delcommand(self, interaction: discord.Interaction, trigger: str):
        trigger = trigger.lower().strip("!")
        await db_exec(
            "DELETE FROM custom_commands WHERE guild_id=? AND trigger=?",
            (interaction.guild_id, trigger),
        )
        await interaction.response.send_message(f"Command `!{trigger}` gelöscht.", ephemeral=True)

    @app_commands.command(name="commands", description="Alle eigenen Commands anzeigen")
    async def list_commands(self, interaction: discord.Interaction):
        rows = await db_rows(
            "SELECT trigger, response FROM custom_commands WHERE guild_id=? ORDER BY trigger",
            (interaction.guild_id,),
        )
        if not rows:
            await interaction.response.send_message("Keine eigenen Commands.", ephemeral=True)
            return
        lines = [f"`!{r['trigger']}` — {r['response'][:60]}" for r in rows]
        embed = discord.Embed(title="Eigene Commands", description="\n".join(lines), color=0x7c3aed)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(CustomCommands(bot))
