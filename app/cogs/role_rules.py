"""Admin-defined "IF a member has/lacks certain roles, THEN add/remove roles" rules
(role_rules table, configured via main.py's "CrossVerification" tab). Evaluated live whenever a
member's roles change, or on a fixed periodic interval instead if the guild is configured for
that (guild_configs key role_rules_interval_minutes, 0 = live). An action can target a
DIFFERENT guild than the one the condition was checked against, for cross-server role sync -
but only between guilds served by the SAME bot token, since this cog only ever has access to
its own commands.Bot instance (self.bot), never the module-level BotManager that aggregates
across tokens (main.py imports from cogs, never the reverse - a cog reaching back into main.py
would be circular). main.py's dashboard only ever lets an admin pick a same-token guild as the
action target in the first place, so that constraint never actually bites at evaluation time.
"""
import time

import discord
from discord.ext import commands, tasks

from database import db_rows, get_guild_config

# How many hops (same-guild re-evaluation passes AND cross-guild jumps both count as one hop
# each) a single triggering role change may cascade through before _evaluate_member gives up.
# Purely a safety net against a pathological rule configuration that would otherwise loop
# forever (e.g. two guilds whose rules keep re-triggering each other) - a real, intentional
# rule chain is expected to converge in a handful of hops at most.
MAX_HOP_BUDGET = 8


class RoleRules(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # (guild_id, user_id) currently being evaluated - guards only against genuinely
        # concurrent EXTERNAL on_member_update dispatches for the same member, not against the
        # deliberate internal recursion inside _evaluate_member (which runs outside this guard,
        # see there).
        self._processing: set[tuple[int, int]] = set()
        self._last_run: dict[int, float] = {}
        self._periodic.start()

    def cog_unload(self):
        self._periodic.cancel()

    async def _get_rules(self, guild_id: int) -> list:
        return await db_rows(
            "SELECT * FROM role_rules WHERE guild_id=? AND enabled=1 ORDER BY priority ASC, id ASC",
            (str(guild_id),),
        )

    @staticmethod
    def _matches(rule: dict, current_role_ids: set) -> bool:
        match_ids = {int(x) for x in (rule["match_role_ids"] or "").split(",") if x}
        if not match_ids:
            return False
        if rule["match_type"] == "all":
            return match_ids.issubset(current_role_ids)
        if rule["match_type"] == "none":
            return not (match_ids & current_role_ids)
        # "any" is both the explicit default and the fallback for an unrecognized value - never
        # silently matches everything or nothing due to a typo/future value.
        return bool(match_ids & current_role_ids)

    async def _evaluate_member(self, guild: discord.Guild, member, hop_budget: int = MAX_HOP_BUDGET):
        if hop_budget <= 0 or member is None:
            return
        rules = await self._get_rules(guild.id)
        if not rules:
            return
        current = {r.id for r in member.roles}
        to_add, to_remove = set(), set()
        cross_actions = []  # list of (action_guild_id, action, role_ids)
        for rule in rules:
            # Rules are evaluated against the role set as it stood BEFORE this pass (not
            # incrementally re-checked against to_add/to_remove as they accumulate) - a single,
            # consistent snapshot per pass. A rule that depends on another rule's OWN result
            # (e.g. rule 2 reacting to a role rule 1 just granted) is deliberately caught by the
            # separate re-evaluation pass after applying changes (see below), not by chaining
            # rules within one pass - keeps the ordering easy to reason about.
            if not self._matches(rule, current):
                continue
            action_ids = {int(x) for x in (rule["action_role_ids"] or "").split(",") if x}
            if not action_ids:
                continue
            # Rules are applied in priority order (lowest number first) - a LATER rule that
            # targets the same role on the same guild overrides an earlier one's effect on it
            # (e.g. rule 1 removes role X, rule 2 re-adds it - rule 2 wins since it's applied
            # after). Deliberate "later rule can override" semantics, not "first match wins".
            if str(rule["action_guild_id"]) == str(guild.id):
                if rule["action"] == "remove":
                    to_remove |= action_ids
                    to_add -= action_ids
                else:
                    to_add |= action_ids
                    to_remove -= action_ids
            else:
                cross_actions.append((rule["action_guild_id"], rule["action"], action_ids))
        changed = False
        if to_add or to_remove:
            new_roles = [r for r in member.roles if r.id not in to_remove]
            for rid in to_add:
                role = guild.get_role(rid)
                if role and role not in new_roles:
                    new_roles.append(role)
            if {r.id for r in new_roles} != current:
                try:
                    await member.edit(roles=new_roles, reason="CrossVerification")
                    changed = True
                except discord.HTTPException as e:
                    print(f"[RoleRules] Anwenden auf {member.id} in Guild {guild.id} fehlgeschlagen: {e}")
        for action_guild_id, action, role_ids in cross_actions:
            target_guild = self.bot.get_guild(int(action_guild_id))
            if not target_guild:
                # Not reachable via this same bot token - the dashboard only ever offers
                # same-token guilds as an action target, so this means the bot has since left
                # that server. Nothing sensible to do but skip.
                continue
            target_member = target_guild.get_member(member.id)
            if target_member is None:
                try:
                    target_member = await target_guild.fetch_member(member.id)
                except discord.NotFound:
                    continue  # the user simply isn't a member of the target server
                except discord.HTTPException as e:
                    print(f"[RoleRules] Mitglied {member.id} auf Guild {target_guild.id} nicht auflösbar: {e}")
                    continue
            t_current = {r.id for r in target_member.roles}
            t_new_ids = (t_current | role_ids) if action == "add" else (t_current - role_ids)
            if t_new_ids != t_current:
                t_new_roles = [r for r in (target_guild.get_role(rid) for rid in t_new_ids) if r]
                try:
                    await target_member.edit(roles=t_new_roles, reason="CrossVerification (cross-server)")
                except discord.HTTPException as e:
                    print(f"[RoleRules] Cross-Server-Anwenden auf {target_guild.id} fehlgeschlagen: {e}")
            # Recurse into the target guild so ITS OWN rules see the new role state too, bounded
            # by hop_budget so two guilds whose rules reference each other can't loop forever.
            await self._evaluate_member(target_guild, target_member, hop_budget - 1)
        if changed:
            # Same-guild chained rules (rule 1 grants role B, rule 2 reacts to role B) - re-fetch
            # rather than trust member.roles to already reflect our own edit locally.
            fresh = guild.get_member(member.id) or member
            await self._evaluate_member(guild, fresh, hop_budget - 1)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles == after.roles:
            return
        interval_raw = await get_guild_config(after.guild.id, "role_rules_interval_minutes")
        try:
            interval = int(interval_raw) if interval_raw else 0
        except ValueError:
            interval = 0
        if interval > 0:
            return  # this guild is in periodic mode - the loop below handles it instead
        key = (after.guild.id, after.id)
        if key in self._processing:
            return
        self._processing.add(key)
        try:
            await self._evaluate_member(after.guild, after)
        except Exception as e:
            print(f"[RoleRules] Live-Auswertung für {after.id} in Guild {after.guild.id} fehlgeschlagen: {e}")
        finally:
            self._processing.discard(key)

    @tasks.loop(minutes=1)
    async def _periodic(self):
        now = time.monotonic()
        for guild in self.bot.guilds:
            try:
                interval_raw = await get_guild_config(guild.id, "role_rules_interval_minutes")
                interval = int(interval_raw) if interval_raw else 0
                if interval <= 0:
                    continue
                last = self._last_run.get(guild.id, 0)
                if now - last < interval * 60:
                    continue
                self._last_run[guild.id] = now
                for member in guild.members:
                    try:
                        await self._evaluate_member(guild, member)
                    except Exception as e:
                        print(f"[RoleRules] Periodische Prüfung für {member.id} in Guild {guild.id} fehlgeschlagen: {e}")
            except Exception as e:
                print(f"[RoleRules] Periodische Prüfung für Guild {guild.id} fehlgeschlagen: {e}")

    @_periodic.before_loop
    async def _before_periodic(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(RoleRules(bot))
