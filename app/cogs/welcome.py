import asyncio
import io
import discord
from discord.ext import commands
from database import get_guild_config

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]
_FONT_PATHS_REG = [p.replace("Bold", "").replace("-Bold", "") for p in _FONT_PATHS]


def _hex_to_rgb(hex_color: str):
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return (255, 255, 255)
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _load_font(size: int, bold: bool = True):
    from PIL import ImageFont
    paths = _FONT_PATHS if bold else _FONT_PATHS_REG
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


async def _make_card(member: discord.Member, circle_color: str, text_color: str, username_color: str) -> io.BytesIO:
    import aiohttp
    from PIL import Image, ImageDraw

    avatar_url = str(member.display_avatar.replace(format="png", size=256))
    async with aiohttp.ClientSession() as session:
        async with session.get(avatar_url) as resp:
            avatar_bytes = await resp.read()

    W, H = 800, 280

    # Dark background with subtle blue-right gradient
    bg = Image.new("RGBA", (W, H), (20, 21, 30, 255))
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    for x in range(W):
        a = int(18 * x / W)
        ov_draw.line([(x, 0), (x, H)], fill=(80, 100, 255, a))
    bg = Image.alpha_composite(bg, overlay)

    draw = ImageDraw.Draw(bg)

    # Subtle divider line
    draw.rectangle([(238, 35), (240, H - 35)], fill=(60, 65, 90, 200))

    # --- Avatar ---
    avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((160, 160), Image.LANCZOS)
    mask = Image.new("L", (160, 160), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 159, 159), fill=255)
    avatar_img.putalpha(mask)

    # Border circle
    bw = 178
    border = Image.new("RGBA", (bw, bw), (0, 0, 0, 0))
    cr, cg, cb = _hex_to_rgb(circle_color)
    ImageDraw.Draw(border).ellipse((0, 0, bw - 1, bw - 1), fill=(cr, cg, cb, 255))

    bx, by = 31, 51
    bg.paste(border, (bx, by), border)
    bg.paste(avatar_img, (bx + 9, by + 9), avatar_img)

    # --- Text ---
    font_welcome = _load_font(52)
    font_name = _load_font(34)
    font_count = _load_font(22, bold=False)

    tx = 265

    tr, tg, tb = _hex_to_rgb(text_color)
    draw.text((tx, 72), "WELCOME", font=font_welcome, fill=(tr, tg, tb, 255))

    ur, ug, ub = _hex_to_rgb(username_color)
    name = member.display_name if len(member.display_name) <= 24 else member.display_name[:21] + "..."
    draw.text((tx, 146), name, font=font_name, fill=(ur, ug, ub, 255))

    draw.text((tx, 202), f"Mitglied #{member.guild.member_count}", font=font_count, fill=(140, 140, 160, 255))

    buf = io.BytesIO()
    bg.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


def fill(template: str, member: discord.Member) -> str:
    return (
        template
        .replace("{user}", member.mention)
        .replace("{username}", str(member))
        .replace("{server}", member.guild.name)
        .replace("{count}", str(member.guild.member_count))
    )


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # Used to `return` early whenever no welcome channel was configured (or it failed to
        # resolve) - which meant autorole below, a completely independent feature, silently
        # never ran either unless a welcome channel happened to ALSO be set up. A server that
        # only wants "give everyone a Member role on join" without a welcome message would have
        # had autorole permanently broken. Restructured so the welcome-message block is now
        # skippable on its own, and autorole always runs regardless of its outcome.
        channel_id = await get_guild_config(member.guild.id, "welcome_channel")
        message = await get_guild_config(member.guild.id, "welcome_message")
        channel = None
        if channel_id:
            try:
                channel = self.bot.get_channel(int(channel_id))
            except (ValueError, TypeError):
                channel = None

        if channel:
            card_enabled = await get_guild_config(member.guild.id, "welcome_card_enabled")
            if card_enabled == "1":
                circle_color  = await get_guild_config(member.guild.id, "welcome_card_circle_color")  or "#5865F2"
                text_color    = await get_guild_config(member.guild.id, "welcome_card_text_color")    or "#FFFFFF"
                username_color= await get_guild_config(member.guild.id, "welcome_card_username_color")or "#FFDA85"
                try:
                    buf  = await _make_card(member, circle_color, text_color, username_color)
                    file = discord.File(buf, filename="welcome.png")
                    if message:
                        embed = discord.Embed(description=fill(message, member), color=0x5865F2)
                        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
                        embed.set_image(url="attachment://welcome.png")
                        await channel.send(file=file, embed=embed)
                    else:
                        await channel.send(file=file)
                except Exception:
                    # Fallback: plain embed
                    if message:
                        embed = discord.Embed(description=fill(message, member), color=0x22c55e)
                        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
                        await channel.send(embed=embed)
            elif message:
                embed = discord.Embed(description=fill(message, member), color=0x22c55e)
                embed.set_author(name=str(member), icon_url=member.display_avatar.url)
                await channel.send(embed=embed)

        role_id = await get_guild_config(member.guild.id, "autorole")
        if role_id:
            try:
                role = member.guild.get_role(int(role_id))
            except (ValueError, TypeError):
                role = None
            if role:
                try:
                    await member.add_roles(role, reason="Autorole")
                except discord.HTTPException as e:
                    # Missing "Manage Roles", the role sitting above the bot's own top role,
                    # ... - previously unhandled, which would otherwise propagate out of this
                    # listener silently (discord.py's default per-event error handling logs it,
                    # but there's no other way for an admin to ever find out autorole stopped
                    # working for every new member).
                    print(f"[Welcome] autorole failed for {member} in guild {member.guild.id}: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        channel_id = await get_guild_config(member.guild.id, "leave_channel")
        message    = await get_guild_config(member.guild.id, "leave_message")
        if not channel_id or not message:
            return
        try:
            channel = self.bot.get_channel(int(channel_id))
        except (ValueError, TypeError):
            channel = None
        if channel:
            embed = discord.Embed(description=fill(message, member), color=0xef4444)
            embed.set_author(name=str(member), icon_url=member.display_avatar.url)
            await channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Welcome(bot))
