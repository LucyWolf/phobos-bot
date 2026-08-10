import discord
from discord import app_commands, ui
from discord.ext import commands
from database import db_exec, db_one, get_guild_config


class CloseTicketView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Ticket schließen", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Ticket wird geschlossen...", ephemeral=True)
        await db_exec(
            "UPDATE tickets SET status='closed' WHERE channel_id=?",
            (interaction.channel_id,),
        )
        await interaction.channel.delete(reason=f"Ticket geschlossen von {interaction.user}")


class OpenTicketView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Ticket öffnen", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: ui.Button):
        guild = interaction.guild
        existing = await db_one(
            "SELECT channel_id FROM tickets WHERE guild_id=? AND user_id=? AND status='open'",
            (guild.id, interaction.user.id),
        )
        if existing:
            ch = guild.get_channel(existing["channel_id"])
            if ch:
                await interaction.response.send_message(f"Du hast bereits ein offenes Ticket: {ch.mention}", ephemeral=True)
                return

        support_role_id = await get_guild_config(guild.id, "ticket_support_role")
        category_id = await get_guild_config(guild.id, "ticket_category")
        category = guild.get_channel(int(category_id)) if category_id else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        if support_role_id:
            role = guild.get_role(int(support_role_id))
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel = await guild.create_text_channel(
            f"ticket-{interaction.user.name}",
            overwrites=overwrites,
            category=category,
            reason=f"Ticket von {interaction.user}",
        )
        await db_exec(
            "INSERT INTO tickets (guild_id,channel_id,user_id) VALUES (?,?,?)",
            (guild.id, channel.id, interaction.user.id),
        )

        embed = discord.Embed(
            title="🎫 Support Ticket",
            description=f"Hallo {interaction.user.mention}!\nBeschreibe dein Anliegen und wir helfen dir so schnell wie möglich.",
            color=0x7c3aed,
        )
        await channel.send(embed=embed, view=CloseTicketView())
        await interaction.response.send_message(f"Ticket erstellt: {channel.mention}", ephemeral=True)


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(OpenTicketView())
        self.bot.add_view(CloseTicketView())

    @app_commands.command(name="ticket-panel", description="Ticket-Panel in diesem Kanal posten")
    @app_commands.default_permissions(manage_guild=True)
    async def ticket_panel(self, interaction: discord.Interaction, title: str = "Support", description: str = "Klicke unten um ein Ticket zu öffnen."):
        embed = discord.Embed(title=f"🎫 {title}", description=description, color=0x7c3aed)
        await interaction.channel.send(embed=embed, view=OpenTicketView())
        await interaction.response.send_message("Panel gepostet.", ephemeral=True)

    @app_commands.command(name="ticket-close", description="Dieses Ticket schließen")
    async def ticket_close(self, interaction: discord.Interaction):
        ticket = await db_one(
            "SELECT id FROM tickets WHERE channel_id=? AND status='open'",
            (interaction.channel_id,),
        )
        if not ticket:
            await interaction.response.send_message("Dieser Kanal ist kein offenes Ticket.", ephemeral=True)
            return
        await interaction.response.send_message("Ticket wird geschlossen...")
        await db_exec("UPDATE tickets SET status='closed' WHERE channel_id=?", (interaction.channel_id,))
        await interaction.channel.delete(reason=f"Ticket geschlossen von {interaction.user}")


async def setup(bot):
    await bot.add_cog(Tickets(bot))
