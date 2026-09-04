"""Server event log (joins/leaves, bans, role changes, message edits/deletes, voice/channel
events, boosts, ...). Every event writes to server_logs (shown on the dashboard's Log page,
pruned to the last 200 rows per guild) and optionally posts live to a configured Discord
channel too."""
import asyncio
import datetime
import discord
from discord.ext import commands
from database import get_guild_config, db_exec


class Logging(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _is_excluded(self, guild_id: int, channel_id: int) -> bool:
        raw = await get_guild_config(guild_id, "log_exclude_channels") or ""
        if not raw:
            return False
        excluded = [c.strip() for c in raw.split(",") if c.strip()]
        if str(channel_id) in excluded:
            return True
        # A message inside a thread has the thread's own channel_id, distinct from the
        # parent text channel that's actually selectable in the exclude-list dropdown -
        # also check the parent so excluding a channel covers its threads too.
        channel = self.bot.get_channel(channel_id)
        if isinstance(channel, discord.Thread) and channel.parent_id:
            return str(channel.parent_id) in excluded
        return False

    async def _log(self, guild_id: int, embed: discord.Embed, plain: str = ""):
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        title = embed.title or ""
        icon = title.split()[0] if title else "📋"
        label = (title[len(icon):] if title.startswith(icon) else title).strip()

        try:
            await db_exec(
                "INSERT INTO server_logs (guild_id, icon, title, description) VALUES (?,?,?,?)",
                (str(guild_id), icon, label, plain[:300]),
            )
            await db_exec(
                """DELETE FROM server_logs WHERE guild_id=? AND id NOT IN (
                    SELECT id FROM server_logs WHERE guild_id=? ORDER BY id DESC LIMIT 200
                )""",
                (str(guild_id), str(guild_id)),
            )
        except Exception as e:
            print(f"[logging_cog] server_logs insert failed for guild {guild_id} ({title!r}): {e!r}")

        channel_id = await get_guild_config(guild_id, "log_channel")
        if not channel_id:
            return
        try:
            channel = self.bot.get_channel(int(channel_id))
        except (ValueError, TypeError):
            channel = None
        if channel:
            try:
                await channel.send(embed=embed)
            except Exception as e:
                print(f"[logging_cog] failed to send log embed to channel {channel_id}: {e!r}")

    async def _find_deleter(self, guild: discord.Guild, channel_id: int, author_id: int):
        """Checks audit log to find who deleted the message (None if self-deleted)."""
        try:
            await asyncio.sleep(1)
            async for entry in guild.audit_logs(limit=10, action=discord.AuditLogAction.message_delete):
                age = (datetime.datetime.now(datetime.timezone.utc) - entry.created_at).total_seconds()
                if age < 15 and entry.extra.channel.id == channel_id and entry.target and entry.target.id == author_id:
                    return entry.user
        except Exception:
            pass
        return None

    async def _audit_delete_info(self, guild: discord.Guild, channel_id: int):
        """Best-effort audit log lookup for an uncached deletion, where there's no known
        author to match against - just takes the most recent message_delete entry for this
        channel. Returns (author, deleter), either of which can be None."""
        try:
            await asyncio.sleep(1)
            async for entry in guild.audit_logs(limit=10, action=discord.AuditLogAction.message_delete):
                age = (datetime.datetime.now(datetime.timezone.utc) - entry.created_at).total_seconds()
                if age < 15 and entry.extra.channel.id == channel_id:
                    return entry.target, entry.user
        except Exception:
            pass
        return None, None

    # ── Mitglieder ────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        embed = discord.Embed(title="📥 Member beigetreten", color=0x22c55e)
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.add_field(name="Nutzer", value=member.mention)
        embed.add_field(name="Account-Alter", value=discord.utils.format_dt(member.created_at, "R"))
        embed.add_field(name="ID", value=str(member.id))
        embed.set_thumbnail(url=member.display_avatar.url)
        await self._log(member.guild.id, embed, plain=f"{member.display_name} ({member.name})")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        embed = discord.Embed(title="📤 Member verlassen", color=0xef4444)
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.add_field(name="Nutzer", value=str(member))
        embed.add_field(name="ID", value=str(member.id))
        roles = [r.name for r in member.roles if r.name != "@everyone"]
        if roles:
            embed.add_field(name="Hatte Rollen", value=", ".join(roles)[:1000], inline=False)
        plain = member.display_name
        if roles:
            plain += f" · Rollen: {', '.join(roles[:3])}"
        await self._log(member.guild.id, embed, plain=plain)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles != after.roles:
            added   = [r for r in after.roles if r not in before.roles]
            removed = [r for r in before.roles if r not in after.roles]
            if added or removed:
                embed = discord.Embed(title="🏷️ Rollen aktualisiert", color=0x3b82f6)
                embed.set_author(name=str(after), icon_url=after.display_avatar.url)
                embed.add_field(name="Nutzer", value=after.mention)
                # Discord embed field values are capped at 1024 chars - a bulk role change
                # (e.g. via an external tool) could otherwise push this past the limit and
                # make the whole channel.send() fail, same guard as on_member_remove below.
                if added:
                    embed.add_field(name="➕ Hinzugefügt", value=" ".join(r.mention for r in added)[:1000])
                if removed:
                    embed.add_field(name="➖ Entfernt", value=" ".join(r.mention for r in removed)[:1000])
                parts = [after.display_name]
                if added:
                    parts.append("+" + ", ".join(r.name for r in added))
                if removed:
                    parts.append("-" + ", ".join(r.name for r in removed))
                await self._log(after.guild.id, embed, plain=" · ".join(parts))

        if before.nick != after.nick:
            embed = discord.Embed(title="✏️ Nickname geändert", color=0xa78bfa)
            embed.set_author(name=str(after), icon_url=after.display_avatar.url)
            embed.add_field(name="Nutzer", value=after.mention)
            embed.add_field(name="Vorher", value=before.nick or before.name, inline=False)
            embed.add_field(name="Nachher", value=after.nick or after.name, inline=False)
            await self._log(after.guild.id, embed,
                plain=f"{after.name} · {before.nick or before.name} → {after.nick or after.name}")

        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until:
                embed = discord.Embed(title="⏱️ Timeout verhängt", color=0xf59e0b)
                embed.set_author(name=str(after), icon_url=after.display_avatar.url)
                embed.add_field(name="Nutzer", value=after.mention)
                embed.add_field(name="Bis", value=discord.utils.format_dt(after.timed_out_until, "f"))
                plain = f"{after.display_name} · bis {after.timed_out_until.strftime('%d.%m.%Y %H:%M')}"
            else:
                # Different icon than "Timeout verhängt" on purpose - same pairing pattern as
                # 🔨/✅ (ban/unban) and 💎/💔 (boost/unboost), so the dashboard's bar-color
                # lookup (_log_bar_class in main.py, keyed purely on the icon since the embed's
                # actual color isn't persisted to the DB) can tell the two apart too.
                embed = discord.Embed(title="✅ Timeout aufgehoben", color=0x22c55e)
                embed.set_author(name=str(after), icon_url=after.display_avatar.url)
                embed.add_field(name="Nutzer", value=after.mention)
                plain = after.display_name
            await self._log(after.guild.id, embed, plain=plain)

    # ── Bans ──────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        embed = discord.Embed(title="🔨 Member gebannt", color=0xef4444)
        embed.set_author(name=str(user), icon_url=user.display_avatar.url)
        embed.add_field(name="Nutzer", value=str(user))
        embed.add_field(name="ID", value=str(user.id))
        await self._log(guild.id, embed, plain=f"{user.display_name} ({user.name})")

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        embed = discord.Embed(title="✅ Member entbannt", color=0x22c55e)
        embed.set_author(name=str(user), icon_url=user.display_avatar.url)
        embed.add_field(name="Nutzer", value=str(user))
        await self._log(guild.id, embed, plain=f"{user.display_name} ({user.name})")

    # ── Voice-Kanäle ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if before.channel == after.channel:
            return
        if before.channel is None and after.channel is not None:
            embed = discord.Embed(title="🔊 Voice beigetreten", color=0x22c55e)
            embed.set_author(name=str(member), icon_url=member.display_avatar.url)
            embed.add_field(name="Nutzer", value=member.mention)
            embed.add_field(name="Kanal", value=after.channel.mention)
            plain = f"{member.display_name} · #{after.channel.name}"
        elif before.channel is not None and after.channel is None:
            embed = discord.Embed(title="🔇 Voice verlassen", color=0xef4444)
            embed.set_author(name=str(member), icon_url=member.display_avatar.url)
            embed.add_field(name="Nutzer", value=member.mention)
            embed.add_field(name="Kanal", value=before.channel.mention)
            plain = f"{member.display_name} · #{before.channel.name}"
        else:
            embed = discord.Embed(title="🔀 Voice gewechselt", color=0xf59e0b)
            embed.set_author(name=str(member), icon_url=member.display_avatar.url)
            embed.add_field(name="Nutzer", value=member.mention)
            embed.add_field(name="Von", value=before.channel.mention)
            embed.add_field(name="Nach", value=after.channel.mention)
            plain = f"{member.display_name} · #{before.channel.name} → #{after.channel.name}"
        await self._log(member.guild.id, embed, plain=plain)

    # ── Nachrichten ───────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        # Raw event - fires for every deletion, unlike on_message_delete which discord.py
        # only dispatches for messages still in the (size-limited, cross-guild-shared) cache.
        if not payload.guild_id:
            return
        if await self._is_excluded(payload.guild_id, payload.channel_id):
            return

        message = payload.cached_message
        if message is not None:
            if message.author.bot:
                return

            embed = discord.Embed(title="🗑️ Nachricht gelöscht", color=0xf97316)
            embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
            embed.add_field(name="Autor", value=message.author.mention)
            embed.add_field(name="Kanal", value=message.channel.mention)
            if message.content:
                embed.add_field(name="Inhalt", value=message.content[:1000], inline=False)

            deleter = await self._find_deleter(message.guild, payload.channel_id, message.author.id)
            if deleter and deleter.id != message.author.id:
                embed.add_field(name="Gelöscht von", value=deleter.mention)

            plain = f"{message.author.display_name} · #{message.channel.name}"
            if deleter and deleter.id != message.author.id:
                plain += f" · gelöscht von {deleter.display_name}"
            if message.content:
                plain += f" · {message.content[:80]}"
        else:
            # Not in cache - Discord doesn't send author/content for uncached deletions,
            # so fall back to a best-effort audit log lookup (author + deleter only).
            guild = self.bot.get_guild(payload.guild_id)
            if not guild:
                return
            channel = guild.get_channel(payload.channel_id)
            author, deleter = await self._audit_delete_info(guild, payload.channel_id)
            if author and author.bot:
                return

            embed = discord.Embed(title="🗑️ Nachricht gelöscht", color=0xf97316)
            if author:
                embed.set_author(name=str(author), icon_url=author.display_avatar.url)
                embed.add_field(name="Autor", value=author.mention)
            embed.add_field(name="Kanal", value=channel.mention if channel else f"<#{payload.channel_id}>")
            embed.add_field(name="Hinweis", value="Nachricht war nicht im Cache – Inhalt unbekannt", inline=False)
            if deleter and (not author or deleter.id != author.id):
                embed.add_field(name="Gelöscht von", value=deleter.mention)

            chan_name = channel.name if channel else str(payload.channel_id)
            plain = f"{author.display_name if author else '?'} · #{chan_name} · Inhalt unbekannt (nicht im Cache)"
            if deleter and (not author or deleter.id != author.id):
                plain += f" · gelöscht von {deleter.display_name}"

        await self._log(payload.guild_id, embed, plain=plain)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        # Raw event - on_bulk_message_delete only sees the cached subset, which would
        # both under-report the count and miss the event entirely if nothing was cached.
        if not payload.guild_id or not payload.message_ids:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        if await self._is_excluded(payload.guild_id, payload.channel_id):
            return
        channel = guild.get_channel(payload.channel_id)

        embed = discord.Embed(title="🗑️ Massenlöschung", color=0xef4444)
        embed.add_field(name="Kanal", value=channel.mention if channel else f"<#{payload.channel_id}>")
        embed.add_field(name="Nachrichten", value=str(len(payload.message_ids)))

        mod = None
        try:
            await asyncio.sleep(1)
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.message_bulk_delete):
                age = (datetime.datetime.now(datetime.timezone.utc) - entry.created_at).total_seconds()
                if age < 15 and entry.user:
                    mod = entry.user
                    embed.add_field(name="Gelöscht von", value=mod.mention)
                    break
        except Exception:
            pass

        chan_name = channel.name if channel else str(payload.channel_id)
        plain = f"#{chan_name} · {len(payload.message_ids)} Nachrichten"
        if mod:
            plain += f" · von {mod.display_name}"
        await self._log(payload.guild_id, embed, plain=plain)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild or before.content == after.content:
            return
        if await self._is_excluded(before.guild.id, before.channel.id):
            return

        embed = discord.Embed(title="✏️ Nachricht bearbeitet", color=0xeab308)
        embed.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)
        embed.add_field(name="Nutzer", value=before.author.mention)
        embed.add_field(name="Kanal", value=before.channel.mention)
        embed.add_field(name="Vorher", value=before.content[:500] or "—", inline=False)
        embed.add_field(name="Nachher", value=after.content[:500] or "—", inline=False)
        embed.add_field(name="Link", value=f"[Zur Nachricht]({after.jump_url})")
        plain = (f"{before.author.display_name} · #{before.channel.name}"
                 f" · {before.content[:60] or '—'} → {after.content[:60] or '—'}")
        await self._log(before.guild.id, embed, plain=plain)

    # ── Kanäle ────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        embed = discord.Embed(title="📁 Kanal erstellt", color=0x22c55e)
        embed.add_field(name="Name", value=channel.mention if hasattr(channel, "mention") else channel.name)
        embed.add_field(name="Typ", value=str(channel.type).replace("_", " ").title())
        await self._log(channel.guild.id, embed, plain=f"#{channel.name}")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        embed = discord.Embed(title="🗑️ Kanal gelöscht", color=0xef4444)
        embed.add_field(name="Name", value=f"#{channel.name}")
        embed.add_field(name="Typ", value=str(channel.type).replace("_", " ").title())
        await self._log(channel.guild.id, embed, plain=f"#{channel.name}")

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        try:
            if before.name != after.name:
                embed = discord.Embed(title="✏️ Kanal umbenannt", color=0xa78bfa)
                embed.add_field(name="Vorher", value=f"#{before.name}")
                embed.add_field(name="Nachher", value=after.mention if hasattr(after, "mention") else f"#{after.name}")
                await self._log(after.guild.id, embed, plain=f"#{before.name} → #{after.name}")
        except Exception as e:
            print(f"[logging_cog] on_guild_channel_update failed for channel {getattr(after, 'id', '?')}: {e!r}")

    # ── Server-Boost ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        if before.premium_subscription_count != after.premium_subscription_count:
            diff = after.premium_subscription_count - before.premium_subscription_count
            embed = discord.Embed(
                title="💎 Server-Boost" if diff > 0 else "💔 Boost entfernt",
                color=0xff73fa if diff > 0 else 0x94a3b8,
            )
            embed.add_field(name="Boosts gesamt", value=str(after.premium_subscription_count))
            embed.add_field(name="Level", value=str(after.premium_tier))
            await self._log(after.id, embed,
                plain=f"Boosts: {after.premium_subscription_count} · Level {after.premium_tier}")


async def setup(bot):
    await bot.add_cog(Logging(bot))
