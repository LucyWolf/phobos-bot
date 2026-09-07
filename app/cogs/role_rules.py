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

self._debug_log keeps a rolling buffer of every step below (not just failures) - unlike a
docker-logs-only trace, main.py's dashboard reads this directly (via bot._bot_for_guild(...)
.get_cog("RoleRules")._debug_log) to show it right on the CrossVerification tab, since asking a
self-hoster to run docker exec commands for every troubleshooting round doesn't scale.
"""
import collections
import datetime
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

# Enough to cover several test attempts across multiple guilds without growing unbounded -
# this is purely an in-memory ring buffer for the dashboard debug view, not persisted anywhere.
DEBUG_LOG_MAXLEN = 200


class RoleRules(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # (guild_id, user_id) currently being evaluated - guards only against genuinely
        # concurrent EXTERNAL on_member_update dispatches for the same member, not against the
        # deliberate internal recursion inside _evaluate_member (which runs outside this guard,
        # see there).
        self._processing: set[tuple[int, int]] = set()
        self._last_run: dict[int, float] = {}
        self._debug_log: collections.deque = collections.deque(maxlen=DEBUG_LOG_MAXLEN)
        self._periodic.start()

    def cog_unload(self):
        self._periodic.cancel()

    def _log(self, msg: str) -> None:
        # Both a normal console/docker-logs line AND a dashboard-visible entry - see the module
        # docstring for why this isn't just a plain print() like the rest of the project's cogs.
        stamped = f"{datetime.datetime.now().strftime('%H:%M:%S')} {msg}"
        print(f"[RoleRules] {stamped}")
        self._debug_log.append(stamped)

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
            self._log(f"Auswertung abgebrochen: hop_budget={hop_budget}, member={member}")
            return
        rules = await self._get_rules(guild.id)
        self._log(f"Guild {guild.id} ({guild.name}): {len(rules)} aktive Regel(n) geladen für Mitglied {member.id}")
        if not rules:
            return
        current = {r.id for r in member.roles}
        to_add, to_remove = set(), set()
        cross_by_guild: dict = {}  # action_guild_id -> {"add": set(), "remove": set()}
        for rule in rules:
            # Rules are evaluated against the role set as it stood BEFORE this pass (not
            # incrementally re-checked against to_add/to_remove as they accumulate) - a single,
            # consistent snapshot per pass. A rule that depends on another rule's OWN result
            # (e.g. rule 2 reacting to a role rule 1 just granted) is deliberately caught by the
            # separate re-evaluation pass after applying changes (see below), not by chaining
            # rules within one pass - keeps the ordering easy to reason about.
            if not self._matches(rule, current):
                continue
            self._log(f"Regel #{rule['id']} ({rule['name'] or '—'}) trifft zu für Mitglied {member.id}: "
                      f"match_type={rule['match_type']} match_roles={rule['match_role_ids']} "
                      f"-> action={rule['action']} action_guild={rule['action_guild_id']} action_roles={rule['action_role_ids']}")
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
                # Grouped by target guild (not a flat list of per-rule actions) and merged with
                # the same "later rule in priority order overrides" semantics as the same-guild
                # case above - fixes a real bug: two rules targeting the SAME other guild used
                # to each run their own separate member.edit() call, computed from separately
                # fetched role snapshots. Discord's own gateway MEMBER_UPDATE confirming the
                # first edit isn't guaranteed to have reached this bot's cache before the second
                # edit reads it, so the second edit could easily read a stale role set and wipe
                # out the first edit's change. One merged edit per target guild avoids that
                # entirely, exactly like the same-guild to_add/to_remove sets already did.
                bucket = cross_by_guild.setdefault(str(rule["action_guild_id"]), {"add": set(), "remove": set()})
                if rule["action"] == "remove":
                    bucket["remove"] |= action_ids
                    bucket["add"] -= action_ids
                else:
                    bucket["add"] |= action_ids
                    bucket["remove"] -= action_ids
        changed = False
        updated_member = None
        if to_add or to_remove:
            new_roles = [r for r in member.roles if r.id not in to_remove]
            for rid in to_add:
                role = guild.get_role(rid)
                if role and role not in new_roles:
                    new_roles.append(role)
            if {r.id for r in new_roles} != current:
                try:
                    # discord.py's Member.edit(roles=...) returns a FRESH Member built straight
                    # from the REST response - it does NOT update guild._members, so a
                    # subsequent guild.get_member(member.id) would still return the stale
                    # pre-edit object. Capturing the return value here (used below for the
                    # same-guild chained-rules re-evaluation) is the only way to actually see
                    # the role we just granted, verified directly against discord.py 2.3.2's
                    # source rather than assumed.
                    updated_member = await member.edit(roles=new_roles, reason="CrossVerification")
                    changed = True
                except (discord.HTTPException, OSError) as e:
                    # OSError alongside HTTPException: discord.py's own http.py re-raises a bare
                    # OSError (not wrapped into HTTPException) for a genuine network-level
                    # failure - its request() retry loop only retries a caught OSError on
                    # macOS/Windows-specific errno codes (54/10054), re-raising unchanged
                    # otherwise, which on Linux (this project's actual runtime) is every
                    # realistic connection-reset/refused case. Left as discord.HTTPException-only
                    # this would propagate out of _evaluate_member entirely on a mere network
                    # hiccup, skipping the cross_by_guild loop below for OTHER, unrelated rules
                    # in the very same evaluation pass - not just this one failed edit.
                    self._log(f"FEHLER: Anwenden auf {member.id} in Guild {guild.id} fehlgeschlagen: {e}")
        if cross_by_guild:
            self._log(f"{len(cross_by_guild)} Ziel-Server-Aktion(en) zu verarbeiten für Mitglied {member.id}: "
                      f"{ {gid: (b['add'], b['remove']) for gid, b in cross_by_guild.items()} }")
        for action_guild_id, bucket in cross_by_guild.items():
            target_guild = self.bot.get_guild(int(action_guild_id))
            if not target_guild:
                # Not reachable via this same bot token - the dashboard only ever offers
                # same-token guilds as an action target, so this means the bot has since left
                # that server. Nothing sensible to do but skip.
                self._log(f"FEHLER: Zielserver {action_guild_id} über self.bot.get_guild() nicht erreichbar "
                          f"(dieser Bot-Token kennt {len(self.bot.guilds)} Server: {[g.id for g in self.bot.guilds]})")
                continue
            target_member = target_guild.get_member(member.id)
            if target_member is None:
                try:
                    target_member = await target_guild.fetch_member(member.id)
                except discord.NotFound:
                    self._log(f"Mitglied {member.id} ist nicht Teil von Guild {target_guild.id} ({target_guild.name})")
                    continue  # the user simply isn't a member of the target server
                except (discord.HTTPException, OSError) as e:
                    # OSError alongside HTTPException for the same reason noted above at the
                    # member.edit() call - a raw network failure here would otherwise propagate
                    # out of the whole `for action_guild_id, bucket in cross_by_guild.items():`
                    # loop, aborting processing for every OTHER, unrelated target guild still
                    # waiting in that same loop - not just this one unresolvable member.
                    self._log(f"FEHLER: Mitglied {member.id} auf Guild {target_guild.id} nicht auflösbar: {e}")
                    continue
            t_current = {r.id for r in target_member.roles}
            t_new_ids = (t_current | bucket["add"]) - bucket["remove"]
            self._log(f"Ziel-Mitglied {target_member.id} auf Guild {target_guild.id}: "
                      f"aktuelle Rollen={t_current}, gewünscht={t_new_ids}, ändert sich={t_new_ids != t_current}")
            if t_new_ids != t_current:
                t_new_roles = [r for r in (target_guild.get_role(rid) for rid in t_new_ids) if r]
                self._log(f"Aufgelöste Ziel-Rollenobjekte: {[(r.id, r.name) for r in t_new_roles]} "
                          f"(erwartet {len(t_new_ids)} IDs, {len(t_new_roles)} aufgelöst)")
                try:
                    # Same staleness issue as above - use the returned Member (reflects the
                    # edit we just made) for the recursion below, not the pre-edit target_member.
                    target_member = await target_member.edit(roles=t_new_roles, reason="CrossVerification (cross-server)") or target_member
                    self._log(f"member.edit() auf Guild {target_guild.id} erfolgreich gesendet")
                    # Recurse into the target guild so ITS OWN rules see the new role state too,
                    # bounded by hop_budget so two guilds whose rules reference each other can't
                    # loop forever - only when the edit above actually went through. Previously
                    # ran unconditionally (even when t_new_ids == t_current, i.e. the target
                    # already had the right roles) - the same-guild branch above already skips
                    # its own chained re-evaluation via `if changed:` for exactly this reason
                    # (a no-op teaches the target's rules nothing new), but this cross-guild
                    # branch didn't apply the same guard: every single trigger where the
                    # condition was already satisfied burned a _get_rules() DB call AND a
                    # hop_budget decrement on the target guild for zero effect - confirmed via
                    # a standalone test (already-satisfied target still logged a full "N aktive
                    # Regel(n) geladen" pass). In a long inert cross-guild chain that could even
                    # exhaust MAX_HOP_BUDGET before reaching a hop that actually needs to fire.
                    await self._evaluate_member(target_guild, target_member, hop_budget - 1)
                except (discord.HTTPException, OSError) as e:
                    self._log(f"FEHLER: Cross-Server-Anwenden auf {target_guild.id} fehlgeschlagen: {e}")
        if changed:
            # Same-guild chained rules (rule 1 grants role B, rule 2 reacts to role B) - use the
            # Member returned by our own edit() above (see the comment there for why a fresh
            # guild.get_member() lookup would still return the stale pre-edit object).
            fresh = updated_member or member
            await self._evaluate_member(guild, fresh, hop_budget - 1)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles == after.roles:
            return
        self._log(f"on_member_update: Rollenänderung erkannt für {after.id} in Guild "
                  f"{after.guild.id} ({after.guild.name}) - vorher={ {r.id for r in before.roles} }, "
                  f"nachher={ {r.id for r in after.roles} }")
        interval_raw = await get_guild_config(after.guild.id, "role_rules_interval_minutes")
        try:
            interval = int(interval_raw) if interval_raw else 0
        except ValueError:
            interval = 0
        if interval > 0:
            self._log(f"Guild {after.guild.id} läuft im periodischen Modus (Intervall={interval}min) - Live-Auswertung übersprungen")
            return  # this guild is in periodic mode - the loop below handles it instead
        key = (after.guild.id, after.id)
        if key in self._processing:
            self._log(f"Guild {after.guild.id}/Mitglied {after.id} wird bereits verarbeitet - übersprungen")
            return
        self._processing.add(key)
        try:
            await self._evaluate_member(after.guild, after)
        except Exception as e:
            self._log(f"FEHLER: Live-Auswertung für {after.id} in Guild {after.guild.id} fehlgeschlagen: {e}")
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
                self._log(f"Periodische Prüfung gestartet für Guild {guild.id} ({guild.name}): "
                          f"{len(guild.members)} Mitglied(er), Intervall={interval}min")
                for member in guild.members:
                    try:
                        await self._evaluate_member(guild, member)
                    except Exception as e:
                        self._log(f"FEHLER: Periodische Prüfung für {member.id} in Guild {guild.id} fehlgeschlagen: {e}")
            except Exception as e:
                self._log(f"FEHLER: Periodische Prüfung für Guild {guild.id} fehlgeschlagen: {e}")

    @_periodic.before_loop
    async def _before_periodic(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(RoleRules(bot))
