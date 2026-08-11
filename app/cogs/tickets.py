import discord
from discord import app_commands, ui
from discord.ext import commands
from database import db_exec, db_one, db_rows


class CloseTicketView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Ticket schließen", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Ticket wird geschlossen...", ephemeral=True)
        await db_exec("UPDATE tickets SET status='closed' WHERE channel_id=?", (interaction.channel_id,))
        await interaction.channel.delete(reason=f"Ticket geschlossen von {interaction.user}")


class PanelButton(ui.Button):
    def __init__(self, panel_id: int, label: str = "Ticket öffnen", emoji: str = "🎫"):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary,
            emoji=emoji,
            custom_id=f"open_ticket:{panel_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        panel_id = int(self.custom_id.split(":")[1])
        panel = await db_one("SELECT * FROM ticket_panels WHERE id=?", (panel_id,))
        if not panel:
            await interaction.response.send_message("Panel nicht gefunden.", ephemeral=True)
            return

        guild = interaction.guild

        existing = await db_one(
            "SELECT channel_id FROM tickets WHERE guild_id=? AND user_id=? AND panel_id=? AND status='open'",
            (guild.id, interaction.user.id, panel_id),
        )
        if existing:
            ch = guild.get_channel(existing["channel_id"])
            if ch:
                await interaction.response.send_message(
                    f"Du hast bereits ein offenes Ticket: {ch.mention}", ephemeral=True
                )
                return

        category = None
        if panel.get("category_id"):
            try:
                category = guild.get_channel(int(panel["category_id"]))
            except (ValueError, TypeError):
                pass

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        if panel.get("support_role_id"):
            try:
                role = guild.get_role(int(panel["support_role_id"]))
                if role:
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            except (ValueError, TypeError):
                pass

        slug = panel["name"].lower().replace(" ", "-")[:18]
        channel = await guild.create_text_channel(
            f"ticket-{slug}-{interaction.user.name[:10]}",
            overwrites=overwrites,
            category=category,
            reason=f"Ticket von {interaction.user} – Panel: {panel['name']}",
        )
        await db_exec(
            "INSERT INTO tickets (guild_id, channel_id, user_id, panel_id) VALUES (?,?,?,?)",
            (guild.id, channel.id, interaction.user.id, panel_id),
        )

        embed = discord.Embed(
            title=f"{panel.get('emoji', '🎫')} {panel['name']}",
            description=(
                f"Hallo {interaction.user.mention}!\n"
                + (panel.get("description") or "Beschreibe dein Anliegen und wir helfen dir so schnell wie möglich.")
            ),
            color=0x7C3AED,
        )
        await channel.send(embed=embed, view=CloseTicketView())
        await interaction.response.send_message(f"Ticket erstellt: {channel.mention}", ephemeral=True)


class OpenTicketView(ui.View):
    def __init__(self, panel_id: int, label: str = "Ticket öffnen", emoji: str = "🎫"):
        super().__init__(timeout=None)
        self.add_item(PanelButton(panel_id, label, emoji))


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(CloseTicketView())
        panels = await db_rows(
            "SELECT id, button_label, emoji FROM ticket_panels WHERE status='published'"
        )
        for p in panels:
            self.bot.add_view(OpenTicketView(
                p["id"],
                p.get("button_label") or "Ticket öffnen",
                p.get("emoji") or "🎫",
            ))

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
