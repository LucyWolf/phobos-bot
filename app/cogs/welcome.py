"""Welcome/leave messages (with an optional generated welcome-card image, see _make_card()) and
autorole on join. Both the welcome message and the autorole assignment run independently of
each other - a server with no welcome channel configured still gets autorole."""
import base64
import io
import re
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


def _cover_crop(img, target_w: int, target_h: int):
    """Scales img up just enough that it fully covers a target_w x target_h box (like CSS
    background-size:cover), then center-crops the overflow - so an admin-uploaded image of any
    aspect ratio always fills the card canvas with no letterboxing, at the cost of cropping
    whatever doesn't fit rather than squishing it."""
    from PIL import Image
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w, new_h = max(1, round(src_w * scale)), max(1, round(src_h * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


async def _make_card(member: discord.Member, circle_color: str, text_color: str, username_color: str,
                      bg_image_b64: str | None = None, heading_text: str = "WELCOME",
                      subtitle_text: str | None = None) -> io.BytesIO:
    import aiohttp
    from PIL import Image, ImageDraw

    avatar_url = str(member.display_avatar.replace(format="png", size=256))
    # Every other external HTTP call in this project (notifications.py, freestuff.py) sets an
    # explicit timeout=10 - this one didn't, so a slow/unresponsive Discord CDN response could
    # hang this specific join's card generation for aiohttp's much longer default before the
    # caller's try/except finally falls back to a plain embed.
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        async with session.get(avatar_url) as resp:
            avatar_bytes = await resp.read()

    W, H = 800, 280

    bg = None
    if bg_image_b64:
        # An admin-uploaded custom background - stored already re-encoded/downscaled at upload
        # time (see main.py's _read_welcome_bg_upload), so this is just decode+cover-crop, no
        # further validation needed. A corrupted/undecodable value (shouldn't happen via the
        # dashboard's own upload path, but guards against a hand-edited DB row) falls back to
        # the default background below rather than aborting the whole card - a member still
        # joining without their custom look is much better than the join message vanishing
        # entirely into the outer try/except's plain-embed fallback.
        try:
            custom = Image.open(io.BytesIO(base64.b64decode(bg_image_b64))).convert("RGB")
            bg = _cover_crop(custom, W, H).convert("RGBA")
            # Fixed dark scrim on top, independent of the uploaded image's own brightness/
            # colors - guarantees the text (drawn in whatever color the admin picked for
            # circle/text/username, none of which are guaranteed to contrast with an arbitrary
            # photo) stays legible regardless of what was uploaded.
            scrim = Image.new("RGBA", (W, H), (0, 0, 0, 100))
            bg = Image.alpha_composite(bg, scrim)
        except Exception:
            bg = None

    if bg is None:
        # Default look, unchanged from before this feature existed - dark background with a
        # subtle blue-right gradient.
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

    # Falls back to the original hardcoded text if the caller passes an empty string (e.g. a
    # guild_config value that's set but blank) rather than None - keeps this function safe to
    # call regardless of exactly how the caller distinguishes "not configured" from "empty".
    heading_text = (heading_text or "").strip() or "WELCOME"
    subtitle_text = (subtitle_text or "").strip() or f"Mitglied #{member.guild.member_count}"

    tr, tg, tb = _hex_to_rgb(text_color)
    draw.text((tx, 72), heading_text, font=font_welcome, fill=(tr, tg, tb, 255))

    ur, ug, ub = _hex_to_rgb(username_color)
    name = member.display_name if len(member.display_name) <= 24 else member.display_name[:21] + "..."
    draw.text((tx, 146), name, font=font_name, fill=(ur, ug, ub, 255))

    draw.text((tx, 202), subtitle_text, font=font_count, fill=(140, 140, 160, 255))

    buf = io.BytesIO()
    bg.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


_PLACEHOLDER_RE = re.compile(r"\{user\}|\{username\}|\{server\}|\{count\}")


def fill(template: str, member: discord.Member) -> str:
    # Chained .replace() calls used to substitute one placeholder at a time - if an
    # already-substituted value (most plausibly the guild's own name, which admins can set to
    # anything, e.g. "Cool {count} Server") happened to literally contain another placeholder's
    # token, a LATER .replace() in the chain would go on to corrupt that already-inserted text
    # too. A single regex pass over the ORIGINAL template can't do that, since it never
    # re-scans text it has already substituted in.
    values = {
        "{user}": member.mention,
        "{username}": str(member),
        "{server}": member.guild.name,
        "{count}": str(member.guild.member_count),
    }
    return _PLACEHOLDER_RE.sub(lambda m: values[m.group(0)], template)


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
                bg_image_b64  = await get_guild_config(member.guild.id, "welcome_card_bg_image")
                heading_raw   = await get_guild_config(member.guild.id, "welcome_card_heading_text")
                subtitle_raw  = await get_guild_config(member.guild.id, "welcome_card_subtitle_text")
                heading_text  = fill(heading_raw, member) if heading_raw else None
                subtitle_text = fill(subtitle_raw, member) if subtitle_raw else None
                try:
                    buf  = await _make_card(member, circle_color, text_color, username_color,
                                             bg_image_b64=bg_image_b64, heading_text=heading_text,
                                             subtitle_text=subtitle_text)
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
