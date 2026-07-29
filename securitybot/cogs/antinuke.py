from __future__ import annotations

import asyncio
import copy
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands

from securitybot.utils import base_embed, log_embed, dangerous_permissions_removed, strip_admin_roles

# Add user IDs here to receive DM alerts when antinuke triggers
ALERT_IDS = [
    903327749534523452,
]


CATEGORIES = {
    "webhook": {
        "label": "Webhook Protection",
        "events": ["webhook_create"],
        "desc": "Auto-deletes webhooks when mass-creation is detected.",
    },
    "ping": {
        "label": "Ping Protection",
        "events": ["mass_ping"],
        "desc": "Clones and replaces channel when @everyone/@here is abused.",
    },
    "channels": {
        "label": "Channel Protection",
        "events": ["channel_delete", "channel_create", "channel_update"],
        "desc": "Detects mass channel deletion, creation, or settings changes.",
    },
    "roles": {
        "label": "Role Protection",
        "events": ["role_delete", "role_create", "role_give"],
        "desc": "Detects mass role deletion, creation, or admin role giving.",
    },
    "bans": {
        "label": "Ban Protection",
        "events": ["ban"],
        "desc": "Detects mass banning of members. Threshold-based trigger.",
    },
    "kicks": {
        "label": "Kick Protection",
        "events": ["kick"],
        "desc": "Detects mass kicking of members.",
    },
    "audit": {
        "label": "Audit Protection",
        "events": ["audit_change", "guild_update", "role_update", "channel_update"],
        "desc": "Detects suspicious server/role/channel setting changes.",
    },
}

CATEGORY_ORDER = ["webhook", "ping", "channels", "roles", "bans", "kicks", "audit"]

EVENT_NAMES = {
    "webhook_create": "Webhook Creates",
    "mass_ping": "Mass Pings",
    "channel_delete": "Channel Deletes",
    "channel_create": "Channel Creates",
    "channel_update": "Channel Updates",
    "role_delete": "Role Deletes",
    "role_create": "Role Creates",
    "role_give": "Admin Role Gives",
    "role_update": "Role Updates",
    "ban": "Bans",
    "kick": "Kicks",
    "audit_change": "Audit Changes",
    "guild_update": "Server Updates",
}

DEFAULT_EVENT = {"enabled": True, "threshold": 1, "punishment": "strip"}

LEFT_ARROW = discord.PartialEmoji(name="leftarrow", id=1529588948127453255)
RIGHT_ARROW = discord.PartialEmoji(name="rightarrow", id=1529588910894743562)
NUM_LIST = discord.PartialEmoji(name="number_list", id=1529619008423198811)
CHECK = discord.PartialEmoji(name="Check", id=1529617202141987027)
CROSS = discord.PartialEmoji(name="Cross", id=1529617223755370538)
SEC_ICON = discord.PartialEmoji(name="Security_Icon", id=1529617120210714624)

BABY_BLUE = 0xA8D8EA
TOTAL_PAGES = 10  # was 9, added mass-ban page before whitelist


def get_event_cfg(config, event):
    events = config.get("events", {})
    val = events.get(event)
    if isinstance(val, dict):
        return {**DEFAULT_EVENT, **val}
    return {**DEFAULT_EVENT, "enabled": bool(val) if val is not None else True}


def set_event_cfg(config, event, key, value):
    events = config.setdefault("events", {})
    if not isinstance(events.get(event), dict):
        events[event] = {**DEFAULT_EVENT, "enabled": bool(events.get(event, True))}
    events[event][key] = value


def get_cat_cfg(config, cat_key):
    return get_event_cfg(config, CATEGORIES[cat_key]["events"][0])


def set_cat_cfg(config, cat_key, key, value):
    for ev in CATEGORIES[cat_key]["events"]:
        set_event_cfg(config, ev, key, value)


def status_emoji(enabled):
    return str(CHECK) if enabled else str(CROSS)


class JumpToPageModal(discord.ui.Modal, title="Jump to Page"):
    page = discord.ui.TextInput(label=f"Page number (1-{TOTAL_PAGES})", placeholder="1", max_length=2)

    async def on_submit(self, interaction):
        v = self.view
        try:
            p = max(0, min(TOTAL_PAGES - 1, int(self.page.value) - 1))
        except ValueError:
            p = 0
        v.page = p
        v.rebuild()
        await interaction.response.edit_message(embed=v.cog.render_page(v.config, v.page, v.guild), view=v)


class CategoryModal(discord.ui.Modal, title="Edit Category"):
    enabled = discord.ui.TextInput(label="Enabled (on / off)", placeholder="on", max_length=3)
    threshold = discord.ui.TextInput(label="Threshold (1-50)", placeholder="1", max_length=3)
    punishment = discord.ui.TextInput(label="Action (strip / kick / ban)", placeholder="strip", max_length=10)

    async def on_submit(self, interaction):
        v = self.view
        cat = v.editing_category
        en = self.enabled.value.strip().lower() == "on"
        try:
            th = max(1, min(50, int(self.threshold.value)))
        except ValueError:
            th = 1
        p = self.punishment.value.strip().lower()
        if p not in ("strip", "kick", "ban"):
            p = "strip"
        old_config = copy.deepcopy(v.config)
        for ev in CATEGORIES[cat]["events"]:
            old_config.setdefault(ev, {})
        set_cat_cfg(v.config, cat, "enabled", en)
        set_cat_cfg(v.config, cat, "threshold", th)
        set_cat_cfg(v.config, cat, "punishment", p)
        await v.save(interaction, old_config)


class PingSettingsModal(discord.ui.Modal, title="Ping Protection Settings"):
    enabled = discord.ui.TextInput(label="Enabled (on / off)", placeholder="on", max_length=3)
    threshold = discord.ui.TextInput(label="Threshold (1-50)", placeholder="1", max_length=3)
    punishment = discord.ui.TextInput(label="Action (strip / kick / ban)", placeholder="strip", max_length=10)
    channels = discord.ui.TextInput(label="Whitelisted channel IDs (comma separated)", placeholder="123, 456", max_length=500, required=False)

    async def on_submit(self, interaction):
        v = self.view
        en = self.enabled.value.strip().lower() == "on"
        try:
            th = max(1, min(50, int(self.threshold.value)))
        except ValueError:
            th = 1
        p = self.punishment.value.strip().lower()
        if p not in ("strip", "kick", "ban"):
            p = "strip"
        old_config = copy.deepcopy(v.config)
        for ev in CATEGORIES["ping"]["events"]:
            old_config.setdefault(ev, {})
        set_cat_cfg(v.config, "ping", "enabled", en)
        set_cat_cfg(v.config, "ping", "threshold", th)
        set_cat_cfg(v.config, "ping", "punishment", p)
        raw = self.channels.value.strip()
        if raw:
            chans = []
            for part in raw.split(","):
                part = part.strip()
                if part.isdigit():
                    chans.append(int(part))
            v.config["ping_channel_whitelist"] = chans
        else:
            v.config["ping_channel_whitelist"] = []
        await v.save(interaction, old_config)


class WhitelistModal(discord.ui.Modal, title="Global Whitelist"):
    add = discord.ui.TextInput(label="Add user ID", placeholder="123456789", max_length=20, required=False)
    remove = discord.ui.TextInput(label="Remove user ID", placeholder="123456789", max_length=20, required=False)

    async def on_submit(self, interaction):
        v = self.view
        old_config = copy.deepcopy(v.config)
        wl = v.config.setdefault("whitelist", [])
        if self.add.value.strip():
            try:
                uid = int(self.add.value.strip())
                if uid not in wl:
                    wl.append(uid)
            except ValueError:
                pass
        if self.remove.value.strip():
            try:
                uid = int(self.remove.value.strip())
                if uid in wl:
                    wl.remove(uid)
            except ValueError:
                pass
        await v.save(interaction, old_config)


class GlobalModal(discord.ui.Modal, title="Edit Global Settings"):
    enabled = discord.ui.TextInput(label="Master switch (on / off)", placeholder="on", max_length=3)
    window = discord.ui.TextInput(label="Detection window (seconds)", placeholder="30", max_length=4)

    async def on_submit(self, interaction):
        v = self.view
        old_config = copy.deepcopy(v.config)
        v.config["enabled"] = self.enabled.value.strip().lower() == "on"
        try:
            v.config["window_seconds"] = max(5, min(600, int(self.window.value)))
        except ValueError:
            pass
        await v.save(interaction, old_config)


class MassBanModal(discord.ui.Modal, title="Anti Mass-Ban"):
    enabled = discord.ui.TextInput(label="Enabled (on / off)", placeholder="on", max_length=3)
    threshold = discord.ui.TextInput(label="Ban threshold (1-20)", placeholder="3", max_length=3)
    role_id = discord.ui.TextInput(label="Access role ID", placeholder="123456789012345678", max_length=20, required=False)

    async def on_submit(self, interaction):
        v = self.view
        old_config = copy.deepcopy(v.config)
        mb = v.config.setdefault("massban_lockdown", {})
        mb["enabled"] = self.enabled.value.strip().lower() == "on"
        try:
            mb["threshold"] = max(1, min(20, int(self.threshold.value)))
        except ValueError:
            pass
        raw = self.role_id.value.strip()
        if raw.isdigit():
            mb["access_role_id"] = int(raw)
        elif not raw:
            mb["access_role_id"] = None
        await v.save(interaction, old_config)


class AntinukeView(discord.ui.View):
    def __init__(self, cog, guild_id, author_id, config):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.author_id = author_id
        self.config = config
        self.page = 0
        self.editing_category = "webhook"

    @property
    def guild(self):
        return self.cog.bot.get_guild(self.guild_id)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the panel opener can edit this.", ephemeral=True)
            return False
        return True

    async def save(self, interaction, old_config=None):
        changes = []
        if old_config:
            for key in self.config:
                if key in ("whitelist", "window_seconds"):
                    continue
                if isinstance(self.config[key], dict) and isinstance(old_config.get(key), dict):
                    for sub_key in self.config[key]:
                        old_val = old_config.get(key, {}).get(sub_key)
                        new_val = self.config[key].get(sub_key)
                        if old_val != new_val:
                            changes.extend([
                                f"> **Setting**: {key} → {sub_key}",
                                f"> **Before**: `{old_val}`",
                                f"> **After**: `{new_val}`",
                            ])
                elif self.config.get(key) != old_config.get(key):
                    changes.extend([
                        f"> **Setting**: {key}",
                        f"> **Before**: `{old_config.get(key)}`",
                        f"> **After**: `{self.config.get(key)}`",
                    ])
        await self.cog.bot.db.update_settings(self.guild_id, antinuke=self.config)
        self.rebuild()
        await interaction.response.edit_message(embed=self.cog.render_page(self.config, self.page, self.guild), view=self)
        guild = self.cog.bot.get_guild(self.guild_id)
        if guild and changes:
            changes.insert(0, f"> **User**: {interaction.user.mention}")
            await self.cog.log(guild, log_embed("Settings Updated", changes, user=interaction.user))

    def rebuild(self):
        self.clear_items()
        cfg = self.config

        prev = discord.ui.Button(emoji=LEFT_ARROW, style=discord.ButtonStyle.primary, row=0)
        jump = discord.ui.Button(emoji=NUM_LIST, style=discord.ButtonStyle.secondary, row=0)
        lbl = discord.ui.Button(label=f"{self.page + 1}/{TOTAL_PAGES}", style=discord.ButtonStyle.secondary, disabled=True, row=0)
        nxt = discord.ui.Button(emoji=RIGHT_ARROW, style=discord.ButtonStyle.primary, row=0)

        async def on_prev(i):
            self.page = (self.page - 1) % TOTAL_PAGES
            self.rebuild()
            await i.response.edit_message(embed=self.cog.render_page(self.config, self.page, self.guild), view=self)
        async def on_next(i):
            self.page = (self.page + 1) % TOTAL_PAGES
            self.rebuild()
            await i.response.edit_message(embed=self.cog.render_page(self.config, self.page, self.guild), view=self)
        async def on_jump(i):
            m = JumpToPageModal()
            m.view = self
            m.page.default = str(self.page + 1)
            await i.response.send_modal(m)
        prev.callback = on_prev
        jump.callback = on_jump
        nxt.callback = on_next
        self.add_item(prev)
        self.add_item(jump)
        self.add_item(lbl)
        self.add_item(nxt)

        if self.page == 0:
            enabled = cfg.get("enabled", False)
            toggle = discord.ui.Button(
                label="Enabled" if enabled else "Disabled",
                style=discord.ButtonStyle.primary if enabled else discord.ButtonStyle.secondary,
                row=1,
            )
            async def on_toggle(i):
                old_config = copy.deepcopy(self.config)
                self.config["enabled"] = not self.config.get("enabled", False)
                await self.save(i, old_config)
            toggle.callback = on_toggle
            self.add_item(toggle)

            edit = discord.ui.Button(label="Edit Settings", style=discord.ButtonStyle.primary, row=1)
            async def on_edit(i):
                m = GlobalModal()
                m.view = self
                m.enabled.default = "on" if cfg.get("enabled", True) else "off"
                m.window.default = str(cfg.get("window_seconds", 5))
                await i.response.send_modal(m)
            edit.callback = on_edit
            self.add_item(edit)

        elif self.page == 2:
            ecfg = get_cat_cfg(cfg, "ping")
            toggle = discord.ui.Button(
                label="Enabled" if ecfg["enabled"] else "Disabled",
                style=discord.ButtonStyle.primary if ecfg["enabled"] else discord.ButtonStyle.secondary,
                row=1,
            )
            async def on_toggle(i):
                old_config = copy.deepcopy(self.config)
                cur = get_cat_cfg(self.config, "ping")
                set_cat_cfg(self.config, "ping", "enabled", not cur["enabled"])
                await self.save(i, old_config)
            toggle.callback = on_toggle
            self.add_item(toggle)

            edit = discord.ui.Button(label="Edit Settings", style=discord.ButtonStyle.primary, row=1)
            async def on_edit(i):
                self.editing_category = "ping"
                m = PingSettingsModal()
                m.view = self
                ec = get_cat_cfg(self.config, "ping")
                m.enabled.default = "on" if ec["enabled"] else "off"
                m.threshold.default = str(ec["threshold"])
                m.punishment.default = ec["punishment"]
                chans = self.config.get("ping_channel_whitelist", [])
                m.channels.default = ", ".join(str(c) for c in chans) if chans else ""
                await i.response.send_modal(m)
            edit.callback = on_edit
            self.add_item(edit)

        elif self.page == 8:
            mb = cfg.get("massban_lockdown", {})
            mb_enabled = mb.get("enabled", False)
            toggle = discord.ui.Button(
                label="Enabled" if mb_enabled else "Disabled",
                style=discord.ButtonStyle.primary if mb_enabled else discord.ButtonStyle.secondary,
                row=1,
            )
            async def on_mb_toggle(i):
                old_config = copy.deepcopy(self.config)
                mb_cfg = self.config.setdefault("massban_lockdown", {})
                mb_cfg["enabled"] = not mb_cfg.get("enabled", False)
                await self.save(i, old_config)
            toggle.callback = on_mb_toggle
            self.add_item(toggle)

            edit = discord.ui.Button(label="Edit Settings", style=discord.ButtonStyle.primary, row=1)
            async def on_mb_edit(i):
                m = MassBanModal()
                m.view = self
                mb_cfg = self.config.get("massban_lockdown", {})
                m.enabled.default = "on" if mb_cfg.get("enabled", False) else "off"
                m.threshold.default = str(mb_cfg.get("threshold", 3))
                m.role_id.default = str(mb_cfg.get("access_role_id", "")) if mb_cfg.get("access_role_id") else ""
                await i.response.send_modal(m)
            edit.callback = on_mb_edit
            self.add_item(edit)

        elif self.page == 9:
            add_btn = discord.ui.Button(label="Add User", style=discord.ButtonStyle.primary, row=1)
            async def on_add(i):
                m = WhitelistModal()
                m.view = self
                await i.response.send_modal(m)
            add_btn.callback = on_add
            self.add_item(add_btn)

        else:
            cat_key = CATEGORY_ORDER[self.page - 1]
            ecfg = get_cat_cfg(cfg, cat_key)

            toggle = discord.ui.Button(
                label="Enabled" if ecfg["enabled"] else "Disabled",
                style=discord.ButtonStyle.primary if ecfg["enabled"] else discord.ButtonStyle.secondary,
                row=1,
            )
            async def on_toggle(i, c=cat_key):
                old_config = copy.deepcopy(self.config)
                cur = get_cat_cfg(self.config, c)
                set_cat_cfg(self.config, c, "enabled", not cur["enabled"])
                await self.save(i, old_config)
            toggle.callback = on_toggle
            self.add_item(toggle)

            edit = discord.ui.Button(label="Edit Settings", style=discord.ButtonStyle.primary, row=1)
            async def on_edit(i, c=cat_key):
                self.editing_category = c
                m = CategoryModal()
                m.view = self
                ec = get_cat_cfg(self.config, c)
                m.enabled.default = "on" if ec["enabled"] else "off"
                m.threshold.default = str(ec["threshold"])
                m.punishment.default = ec["punishment"]
                await i.response.send_modal(m)
            edit.callback = on_edit
            self.add_item(edit)


class AntiNukeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.events = defaultdict(deque)
        self.cooldowns = {}  # (guild_id, user_id, event) -> datetime of last trigger

    @commands.command(name="antinuke")
    async def antinuke_panel(self, ctx):
        settings = await self.bot.db.get_settings(ctx.guild.id)
        config = settings["antinuke"]
        view = AntinukeView(self, ctx.guild.id, ctx.author.id, config)
        view.rebuild()
        await ctx.send(embed=self.render_page(config, 0, ctx.guild), view=view)

    def render_page(self, config, page, guild=None):
        if page == 0:
            return self.render_overview(config)
        if page == 8:
            return self.render_massban(config)
        if page == 9:
            return self.render_whitelist(config, guild)
        cat_key = CATEGORY_ORDER[page - 1]
        return self.render_category(config, cat_key, page)

    def render_overview(self, config):
        enabled = config.get("enabled", False)
        window = config.get("window_seconds", 5)
        embed = discord.Embed(title=f"{SEC_ICON} Security Panel", color=BABY_BLUE)
        embed.add_field(
            name="[1] Global Settings",
            value=f"\u25b6 (A) Master: {status_emoji(enabled)}\n\u25b6 (B) Window: `{window}s`",
            inline=True,
        )
        summaries = []
        for i, cat_key in enumerate(CATEGORY_ORDER, start=2):
            cat = CATEGORIES[cat_key]
            ecfg = get_cat_cfg(config, cat_key)
            summaries.append(f"**[{i}]** {status_emoji(ecfg['enabled'])} {cat['label']}")
        mb = config.get("massban_lockdown", {})
        mb_enabled = mb.get("enabled", False)
        summaries.append(f"**[9]** {status_emoji(mb_enabled)} Mass-Ban Lockdown")
        summaries.append(f"**[10]** Whitelist")
        embed.add_field(name="Categories", value="\n".join(summaries), inline=True)
        embed.set_footer(text=f"Page 1/{TOTAL_PAGES} \u2022 Overview")
        return embed

    def render_category(self, config, cat_key, page):
        cat = CATEGORIES[cat_key]
        ecfg = get_cat_cfg(config, cat_key)
        embed = discord.Embed(title=f"{SEC_ICON} {cat['label']}", description=cat["desc"], color=BABY_BLUE)
        for idx, ev in enumerate(cat["events"]):
            name = EVENT_NAMES.get(ev, ev)
            embed.add_field(
                name=f"[{page}] {name}",
                value=f"\u25b6 (A) Status: {status_emoji(ecfg['enabled'])}\n\u25b6 (B) Threshold: `{ecfg['threshold']}` actions\n\u25b6 (C) Action: `{ecfg['punishment']}`",
                inline=True,
            )
        if cat_key == "ping":
            chans = config.get("ping_channel_whitelist", [])
            wl_text = ", ".join(f"`{c}`" for c in chans) if chans else "none"
            embed.add_field(name="Channel Whitelist (9D-)", value=f"\u25b6 {wl_text}", inline=False)
        embed.set_footer(text=f"Page {page}/{TOTAL_PAGES} \u2022 {cat['label']}")
        return embed

    def render_massban(self, config):
        mb = config.get("massban_lockdown", {})
        enabled = mb.get("enabled", False)
        threshold = mb.get("threshold", 3)
        role_id = mb.get("access_role_id")
        role_str = f"<@&{role_id}>" if role_id else "`not set`"
        embed = discord.Embed(
            title=f"{SEC_ICON} Mass-Ban Lockdown",
            description="When the ban threshold is hit within the detection window, the configured access role is moved to the highest position (just below the bot) so only trusted users can ban.",
            color=BABY_BLUE,
        )
        embed.add_field(
            name="[9] Settings",
            value=(
                f"\u25b6 (A) Status: {status_emoji(enabled)}\n"
                f"\u25b6 (B) Threshold: `{threshold}` bans\n"
                f"\u25b6 (C) Access Role: {role_str}"
            ),
            inline=False,
        )
        embed.set_footer(text=f"Page 9/{TOTAL_PAGES} \u2022 Mass-Ban Lockdown")
        return embed

    def render_whitelist(self, config, guild):
        wl = config.get("whitelist", [])
        embed = discord.Embed(title=f"{SEC_ICON} Whitelist", description="Users here bypass ALL antinuke checks.", color=BABY_BLUE)
        if wl:
            lines = []
            for uid in wl:
                member = guild.get_member(uid)
                name = member.name if member else "Unknown"
                lines.append(f"\u25b6 `{uid}` **{name}**")
            embed.add_field(name=f"{len(wl)} Whitelisted Users", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="0 Whitelisted Users", value="\u25b6 No users whitelisted yet", inline=False)
        embed.set_footer(text=f"Page {TOTAL_PAGES}/{TOTAL_PAGES} \u2022 Whitelist")
        return embed

    # ── Mass-ban lockdown ──────────────────────────────────────────────────────

    async def check_massban_lockdown(self, guild: discord.Guild, actor) -> None:
        """Called on every ban event. If threshold is hit, hoist the access role."""
        settings = await self.bot.db.get_settings(guild.id)
        config = settings["antinuke"]
        mb = config.get("massban_lockdown", {})
        if not mb.get("enabled"):
            return
        if actor is None or actor.bot:
            return
        # Whitelisted users are exempt
        if actor.id in config.get("whitelist", []):
            return
        if await self.bot.is_whitelisted(guild, actor.id):
            return

        threshold = mb.get("threshold", 3)
        now = datetime.now(timezone.utc)
        window = timedelta(seconds=int(config.get("window_seconds", 5)))
        key = (guild.id, actor.id, "massban_lockdown")
        bucket = self.events[key]
        bucket.append(now)
        while bucket and now - bucket[0] > window:
            bucket.popleft()

        if len(bucket) >= threshold:
            bucket.clear()
            role_id = mb.get("access_role_id")
            if not role_id:
                return
            role = guild.get_role(role_id)
            if not role:
                return
            # Move access role just below the bot's top role
            bot_top = guild.me.top_role
            target_position = max(1, bot_top.position - 1)
            try:
                await role.edit(position=target_position, reason="Anti-nuke: mass-ban lockdown triggered")
            except discord.HTTPException:
                pass
            await self.log(guild, log_embed("Mass-Ban Lockdown Triggered", [
                f"> **Actor**: {actor.mention} (`{actor.id}`)",
                f"> **Role hoisted**: {role.mention}",
                f"> **New position**: `{target_position}`",
            ], user=actor))
            await self.send_alert(guild, actor, "mass_ban_lockdown", "role_hoist")

    async def handle_mass_ping(self, message):
        settings = await self.bot.db.get_settings(message.guild.id)
        config = settings["antinuke"]
        if not config.get("enabled"):
            return
        ecfg = get_event_cfg(config, "mass_ping")
        if not ecfg["enabled"]:
            return
        if message.author.id in config.get("whitelist", []):
            return
        if message.channel.id in config.get("ping_channel_whitelist", []):
            return
        if await self.bot.is_whitelisted(message.guild, message.author.id):
            return
        if await self.bot.db.use_ping_protection(message.guild.id, message.author.id):
            return

        actor = message.author
        punishment = ecfg["punishment"]
        now = datetime.now(timezone.utc)
        window = timedelta(seconds=int(config.get("window_seconds", 5)))

        # Cooldown: skip if triggered recently in THIS channel
        cd_key = (message.guild.id, message.channel.id, actor.id, "mass_ping")
        last_trigger = self.cooldowns.get(cd_key)
        if last_trigger and (now - last_trigger) < window:
            return

        threshold = ecfg.get("threshold", 1)
        key = (message.guild.id, actor.id, "mass_ping")
        bucket = self.events[key]
        bucket.append(now)
        while bucket and now - bucket[0] > window:
            bucket.popleft()

        if len(bucket) < threshold:
            return

        bucket.clear()
        self.cooldowns[cd_key] = now
        reason = "Mass ping abuse"

        member = message.guild.get_member(actor.id)
        if member:
            if punishment == "ban":
                await member.ban(reason=reason)
            elif punishment == "kick":
                await member.kick(reason=reason)
            else:
                await strip_admin_roles(member, reason=reason)

        try:
            clone = await message.channel.clone(reason=f"Anti-nuke: {reason}")
            reason_str = f"Anti-nuke: {reason}"
            await asyncio.gather(
                message.channel.edit(nsfw=True, reason=reason_str),
                message.channel.delete(reason=reason_str),
                clone.edit(position=message.channel.position, reason=reason_str),
                return_exceptions=True,
            )
            await clone.send(embed=discord.Embed(description="channel nuked", color=BABY_BLUE))
        except discord.HTTPException:
            pass

        await self.log(message.guild, log_embed("Anti-Nuke Triggered", [
            f"> **User**: {actor.mention}",
            f"> **Event**: mass_ping",
            f"> **Action**: {punishment} + channel cloned",
        ], user=actor))
        await self.send_alert(message.guild, actor, "mass_ping", punishment)

    async def send_alert(self, guild, actor, event, punishment):
        targets = set(ALERT_IDS)
        if guild.owner_id:
            targets.add(guild.owner_id)
        for uid in targets:
            user = self.bot.get_user(uid)
            if not user:
                try:
                    user = await self.bot.fetch_user(uid)
                except Exception:
                    continue
            try:
                desc = (
                    f"> **user:** {actor.mention} (`{actor.id}`)\n"
                    f"> **offence:** {event}\n"
                    f"> **server:** {guild.name}\n"
                    f"> **action:** {punishment}"
                )

                view = discord.ui.LayoutView(timeout=None)
                container = discord.ui.Container(accent_color=BABY_BLUE)

                container.add_item(discord.ui.TextDisplay(
                    f"**Anti-Nuke Triggered**\n{desc}"
                ))

                action_row = discord.ui.ActionRow()
                btn = discord.ui.Button(label="exterminate", style=discord.ButtonStyle.primary)
                async def on_ext(interaction, a=actor, g=guild, alert_uid=uid):
                    if interaction.user.id != alert_uid:
                        await interaction.response.send_message("Not for you.", ephemeral=True)
                        return
                    cog = self.bot.get_cog("ModerationCog")
                    if cog:
                        ctx = await self.bot.get_context(interaction.message)
                        ctx.author = interaction.user
                        ctx.guild = g
                        await ctx.invoke(cog.exterminate, target=str(a.id))
                    await interaction.response.defer()
                btn.callback = on_ext
                action_row.add_item(btn)
                container.add_item(action_row)

                view.add_item(container)
                await user.send(view=view)
            except discord.HTTPException as e:
                print(f"[WARN] Failed to DM alert to {uid}: {e}")

    async def handle_webhook_create(self, guild, actor, webhook):
        settings = await self.bot.db.get_settings(guild.id)
        config = settings["antinuke"]
        if not config.get("enabled"):
            return
        ecfg = get_event_cfg(config, "webhook_create")
        if not ecfg["enabled"]:
            return
        if actor.id in config.get("whitelist", []):
            return
        if await self.bot.is_whitelisted(guild, actor.id):
            return

        now = datetime.now(timezone.utc)
        window = timedelta(seconds=int(config.get("window_seconds", 5)))
        key = (guild.id, actor.id, "webhook_create")
        bucket = self.events[key]
        bucket.append(now)
        while bucket and now - bucket[0] > window:
            bucket.popleft()

        if len(bucket) >= ecfg["threshold"]:
            member = guild.get_member(actor.id)
            punishment = ecfg["punishment"]
            if member:
                if punishment == "ban":
                    await member.ban(reason="Mass webhook creation")
                elif punishment == "kick":
                    await member.kick(reason="Mass webhook creation")
                else:
                    await strip_admin_roles(member, reason="Mass webhook creation")

            webhooks = await guild.webhooks()
            for wh in webhooks:
                if wh.user and wh.user.id == actor.id:
                    try:
                        await wh.delete(reason="Anti-nuke: mass webhook creation by non-whitelisted user")
                    except discord.HTTPException:
                        pass

            await self.log(guild, log_embed("Anti-Nuke Triggered", [
                f"> **User**: {actor.mention}",
                f"> **Event**: webhook_create",
                f"> **Action**: {punishment} + webhooks deleted",
            ], user=actor))
            await self.send_alert(guild, actor, "webhook_create", punishment)
            bucket.clear()

    async def record_action(self, guild, actor, event):
        if actor is None or actor.bot:
            return False
        settings = await self.bot.db.get_settings(guild.id)
        config = settings["antinuke"]
        if actor.id in config.get("whitelist", []):
            return False
        if await self.bot.is_whitelisted(guild, actor.id):
            return False
        if not config.get("enabled"):
            return False
        ecfg = get_event_cfg(config, event)
        if not ecfg["enabled"]:
            return False
        now = datetime.now(timezone.utc)
        window = timedelta(seconds=int(config.get("window_seconds", 5)))

        # Cooldown: skip if triggered recently
        cd_key = (guild.id, actor.id, event)
        last_trigger = self.cooldowns.get(cd_key)
        if last_trigger and (now - last_trigger) < window:
            return False

        key = (guild.id, actor.id, event)
        bucket = self.events[key]
        bucket.append(now)
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= ecfg["threshold"]:
            self.cooldowns[cd_key] = now
            from securitybot.oauth_server import add_log
            add_log("security", f"Anti-Nuke triggered: **{actor}** (`{actor.id}`) — {event} ({ecfg['punishment']})", user=str(actor), avatar=str(actor.display_avatar.url), log_type="security", details={"User": str(actor), "User ID": str(actor.id), "Event": EVENT_NAMES.get(event, event), "Punishment": ecfg['punishment'], "Threshold": str(ecfg['threshold']), "Server": guild.name, "Server ID": str(guild.id)})
            await self.punish(guild, actor, ecfg["punishment"])
            await self.log(guild, log_embed("Anti-Nuke Triggered", [
                f"> **User**: {actor.mention}",
                f"> **Event**: {event}",
                f"> **Action**: {ecfg['punishment']}",
            ], user=actor))
            await self.send_alert(guild, actor, event, ecfg['punishment'])
            bucket.clear()
            return True
        # Mass-ban lockdown runs on every ban regardless of antinuke threshold
        if event == "ban":
            await self.check_massban_lockdown(guild, actor)
        return False

    async def punish(self, guild, actor, punishment):
        member = guild.get_member(actor.id)
        if not member:
            return
        reason = "Anti-nuke triggered"
        if punishment == "ban":
            await member.ban(reason=reason)
        elif punishment == "kick":
            await member.kick(reason=reason)
        else:
            await strip_admin_roles(member, reason=reason)

    async def emergency_role_lockdown(self, guild, *, reason):
        changed = 0
        me = guild.me
        for role in guild.roles:
            if role.is_default() or role.managed or role >= me.top_role:
                continue
            new_perms = dangerous_permissions_removed(role.permissions)
            if new_perms.value == role.permissions.value:
                continue
            await self.bot.db.save_locked_role(guild.id, role.id, role.permissions.value)
            try:
                await role.edit(permissions=new_perms, reason=reason)
                changed += 1
            except discord.HTTPException:
                continue
        return changed

    async def log(self, guild, embed):
        settings = await self.bot.db.get_settings(guild.id)
        if not settings["logging_events"].get("antinuke"):
            return
        channel_id = settings.get("logging_channel_id")
        channel = guild.get_channel(channel_id) if channel_id else None
        if channel:
            await channel.send(embed=embed)
