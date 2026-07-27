from __future__ import annotations

import os
from urllib.parse import quote

import discord
from discord.ext import commands

from securitybot.utils import base_embed, log_embed

CHECK = discord.PartialEmoji(name="Check", id=1529617202141987027)
CROSS = discord.PartialEmoji(name="Cross", id=1529617223755370538)

LOGGING_EVENTS = ["bot_commands", "antinuke", "moderation", "audit_change"]
EVENT_LABELS = {
    "bot_commands": "Bot Commands",
    "antinuke": "Anti-Nuke",
    "moderation": "Moderation",
    "audit_change": "Audit Changes",
}

LEFT_ARROW = discord.PartialEmoji(name="leftarrow", id=1529588948127453255)
RIGHT_ARROW = discord.PartialEmoji(name="rightarrow", id=1529588910894743562)


class LoggingModal(discord.ui.Modal, title="Logging Settings"):
    channel = discord.ui.TextInput(label="Logging Channel ID", placeholder="123456789", max_length=20, required=False)
    bot_commands = discord.ui.TextInput(label="Bot Commands (on/off)", placeholder="on", max_length=3, required=False)
    antinuke = discord.ui.TextInput(label="Anti-Nuke (on/off)", placeholder="on", max_length=3, required=False)
    moderation = discord.ui.TextInput(label="Moderation (on/off)", placeholder="on", max_length=3, required=False)
    audit_change = discord.ui.TextInput(label="Audit Changes (on/off)", placeholder="on", max_length=3, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        v = self.view
        channel_raw = self.channel.value.strip()
        if channel_raw:
            try:
                channel_id = int(channel_raw.replace("<#", "").replace(">", ""))
                await self.view.cog.bot.db.update_settings(self.view.ctx.guild.id, logging_channel_id=channel_id)
            except ValueError:
                pass
        for key in LOGGING_EVENTS:
            val = getattr(self, key).value.strip().lower()
            if val in ("on", "off"):
                v.events[key] = val == "on"
        await self.view.cog.bot.db.update_settings(self.view.ctx.guild.id, logging_events=v.events)
        settings = await self.view.cog.bot.db.get_settings(self.view.ctx.guild.id)
        v.events = settings["logging_events"]
        v.rebuild()
        await interaction.response.edit_message(embed=self.view.cog.logging_embed(settings), view=v)


class LoggingView(discord.ui.View):
    def __init__(self, cog: "ConfigCog", ctx: commands.Context, events: dict) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.ctx = ctx
        self.events = dict(events)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Only the panel opener can edit this.", ephemeral=True)
            return False
        return True

    def rebuild(self):
        self.clear_items()
        edit = discord.ui.Button(label="Edit Settings", style=discord.ButtonStyle.primary)
        async def on_edit(i):
            m = LoggingModal()
            m.view = self
            m.bot_commands.default = "on" if self.events.get("bot_commands") else "off"
            m.antinuke.default = "on" if self.events.get("antinuke") else "off"
            m.moderation.default = "on" if self.events.get("moderation") else "off"
            m.audit_change.default = "on" if self.events.get("audit_change") else "off"
            await i.response.send_modal(m)
        edit.callback = on_edit
        self.add_item(edit)


class BlacklistModal(discord.ui.Modal, title="Blacklist Management"):
    add_user_id = discord.ui.TextInput(label="Add user ID", placeholder="123456789", max_length=20, required=False)
    remove_user_id = discord.ui.TextInput(label="Remove user ID", placeholder="123456789", max_length=20, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        v = self.view
        is_owner = interaction.user.id in v.cog.bot.owner_ids
        is_legacy = await v.cog.bot.db.is_whitelist_admin(v.ctx.guild.id, interaction.user.id)
        if not is_owner and not is_legacy:
            await interaction.response.send_message("i dont listen to you", ephemeral=True)
            return
        add_raw = self.add_user_id.value.strip()
        remove_raw = self.remove_user_id.value.strip()
        if add_raw:
            try:
                uid = int(add_raw)
                await v.cog.bot.db.add_blacklist(v.ctx.guild.id, uid, interaction.user.id)
            except ValueError:
                pass
        if remove_raw:
            try:
                uid = int(remove_raw)
                await v.cog.bot.db.remove_blacklist(v.ctx.guild.id, uid)
            except ValueError:
                pass
        bl = await v.cog.bot.db.list_blacklist(v.ctx.guild.id)
        v.blacklist = bl
        v.rebuild()
        await interaction.response.edit_message(view=v)


class WhitelistModal(discord.ui.Modal, title="Whitelist Management"):
    add_user_id = discord.ui.TextInput(label="Add user ID", placeholder="123456789", max_length=20, required=False)
    remove_user_id = discord.ui.TextInput(label="Remove user ID", placeholder="123456789", max_length=20, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        v = self.view
        add_raw = self.add_user_id.value.strip()
        remove_raw = self.remove_user_id.value.strip()
        is_legacy = v.page == 1
        is_owner = interaction.user.id in v.cog.bot.owner_ids
        is_legacy_user = await v.cog.bot.db.is_whitelist_admin(v.ctx.guild.id, interaction.user.id)

        if not is_owner and not is_legacy_user:
            await interaction.response.send_message("i dont listen to you", ephemeral=True)
            return

        if is_legacy and not is_owner:
            await interaction.response.send_message("i dont listen to you", ephemeral=True)
            return

        if add_raw:
            try:
                uid = int(add_raw)
                await v.cog.bot.db.remove_whitelist(v.ctx.guild.id, uid)
                await v.cog.bot.db.add_whitelist(v.ctx.guild.id, uid, interaction.user.id, admin=is_legacy)
            except ValueError:
                pass
        if remove_raw:
            try:
                uid = int(remove_raw)
                if uid != v.ctx.guild.owner_id:
                    await v.cog.bot.db.remove_whitelist(v.ctx.guild.id, uid)
            except ValueError:
                pass
        entries = await v.cog.bot.db.list_whitelist(v.ctx.guild.id)
        v.users = [e for e in entries if not e["admin"]]
        v.admins = [e for e in entries if e["admin"]]
        v.rebuild()
        await interaction.response.edit_message(view=v)


class WhitelistView(discord.ui.LayoutView):
    def __init__(self, cog: "ConfigCog", ctx: commands.Context, users: list[dict], admins: list[dict], page: int = 0, blacklist: list[int] | None = None) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.ctx = ctx
        self.users = users
        self.admins = admins
        self.blacklist = blacklist or []
        self.page = page
        self.rebuild()

    def build_text(self) -> str:
        if self.page == 0:
            title = "**Standard**"
            entries = self.users
            lines = []
            for e in entries:
                uid = e['user_id']
                user = self.cog.bot.get_user(uid)
                name = str(user) if user else str(uid)
                lines.append(f"▶ `<{uid}>` — **{name}**")
            desc = "\n".join(lines) if lines else "> No entries."
            return f"{title}\n{desc}"
        elif self.page == 1:
            title = "**Legacy**"
            entries = self.admins
            lines = []
            for e in entries:
                uid = e['user_id']
                user = self.cog.bot.get_user(uid)
                name = str(user) if user else str(uid)
                lines.append(f"▶ `<{uid}>` — **{name}**")
            desc = "\n".join(lines) if lines else "> No entries."
            return f"{title}\n{desc}"
        else:
            title = "**Blacklist**"
            lines = []
            for uid in self.blacklist:
                user = self.cog.bot.get_user(uid)
                name = str(user) if user else str(uid)
                lines.append(f"▶ `<{uid}>` — **{name}**")
            desc = "\n".join(lines) if lines else "> No entries."
            return f"{title}\n{desc}"

    def rebuild(self):
        self.clear_items()
        total_pages = 3
        container = discord.ui.Container(accent_color=0xA8D8EA)
        container.add_item(discord.ui.TextDisplay(self.build_text()))

        inner_row = discord.ui.ActionRow()
        manage_btn = discord.ui.Button(label="m", style=discord.ButtonStyle.primary)

        async def on_manage(i):
            is_owner = i.user.id in self.cog.bot.owner_ids
            is_legacy_user = await self.cog.bot.db.is_whitelist_admin(self.ctx.guild.id, i.user.id)
            if self.page == 2:
                # Blacklist — legacy only
                if not is_owner and not is_legacy_user:
                    await i.response.send_message("i dont listen to you", ephemeral=True)
                    return
                m = BlacklistModal()
                m.view = self
                await i.response.send_modal(m)
                return
            is_legacy = self.page == 1
            if not is_owner and not is_legacy_user:
                await i.response.send_message("i dont listen to you", ephemeral=True)
                return
            if is_legacy and not is_owner:
                await i.response.send_message("i dont listen to you", ephemeral=True)
                return
            m = WhitelistModal()
            m.view = self
            await i.response.send_modal(m)
        manage_btn.callback = on_manage

        info_btn = discord.ui.Button(label="i", style=discord.ButtonStyle.secondary)
        async def on_info(i):
            if self.page == 0:
                desc = (
                    "> `nuke` - clone and replace channel\n"
                    "> `strip` - remove admin roles\n"
                    "> `restore` - restore roles after rejoin\n"
                    "> `join` - set join channel\n"
                    "> `leave` - set leave channel\n"
                    "> `logging` - logging panel\n"
                    "> `lockdown` - server lockdown panel\n"
                    "> `activity public` - public count activity"
                )
            elif self.page == 1:
                desc = (
                    "> everything Standard has, plus...\n"
                    "> `exterminate` - hard-ban + auto-reban\n"
                    "> `unexterminate` - remove hard-ban\n"
                    "> `antinuke` - full security panel\n"
                    "> `template` - server templates\n"
                    "> `activity hr` - hr activity\n"
                    "> `activity delete` - delete activity"
                )
            else:
                desc = (
                    "> Users on the blacklist cannot hold admin permissions.\n"
                    "> If a blacklisted user is given a role with admin, the bot removes it automatically."
                )
            embed = discord.Embed(title="Whitelist Info", description=desc, color=0xA8D8EA)
            await i.response.send_message(embed=embed, ephemeral=True)
        info_btn.callback = on_info

        inner_row.add_item(manage_btn)
        inner_row.add_item(info_btn)
        container.add_item(inner_row)
        self.add_item(container)

        nav_row = discord.ui.ActionRow()
        prev_btn = discord.ui.Button(emoji=LEFT_ARROW, style=discord.ButtonStyle.secondary)
        async def on_prev(i):
            self.page = (self.page - 1) % total_pages
            self.rebuild()
            await i.response.edit_message(view=self)
        prev_btn.callback = on_prev

        page_btn = discord.ui.Button(label=f"{self.page + 1}/{total_pages}", style=discord.ButtonStyle.secondary, disabled=True)
        page_btn.callback = lambda i: None

        next_btn = discord.ui.Button(emoji=RIGHT_ARROW, style=discord.ButtonStyle.secondary)
        async def on_next(i):
            self.page = (self.page + 1) % total_pages
            self.rebuild()
            await i.response.edit_message(view=self)
        next_btn.callback = on_next

        nav_row.add_item(prev_btn)
        nav_row.add_item(page_btn)
        nav_row.add_item(next_btn)
        self.add_item(nav_row)


class ChannelMessageView(discord.ui.View):
    def __init__(self, cog: "ConfigCog", ctx: commands.Context, kind: str) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.ctx = ctx
        self.kind = kind

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Only the panel opener can edit this.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Set Channel", style=discord.ButtonStyle.primary)
    async def set_channel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message("Send a channel mention or ID in this channel.", ephemeral=True)
        msg = await self.cog.bot.wait_for(
            "message",
            timeout=90,
            check=lambda m: m.author.id == interaction.user.id and m.channel.id == self.ctx.channel.id,
        )
        channel_id = int(msg.content.strip().replace("<#", "").replace(">", ""))
        await self.cog.bot.db.update_settings(self.ctx.guild.id, **{f"{self.kind}_channel_id": channel_id})
        settings = await self.cog.bot.db.get_settings(self.ctx.guild.id)
        await interaction.message.edit(embed=self.cog.channel_message_embed(settings, self.kind), view=self)

    @discord.ui.button(label="Set Message", style=discord.ButtonStyle.secondary)
    async def set_message(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message("Send the message. Placeholders: `{mention}`, `{user}`, `{name}`, `{id}`, `{server}`.", ephemeral=True)
        msg = await self.cog.bot.wait_for(
            "message",
            timeout=180,
            check=lambda m: m.author.id == interaction.user.id and m.channel.id == self.ctx.channel.id,
        )
        await self.cog.bot.db.update_settings(self.ctx.guild.id, **{f"{self.kind}_message": msg.content[:1500]})
        settings = await self.cog.bot.db.get_settings(self.ctx.guild.id)
        await interaction.message.edit(embed=self.cog.channel_message_embed(settings, self.kind), view=self)


class VerifyView(discord.ui.View):
    def __init__(self, oauth_url: str | None) -> None:
        super().__init__(timeout=None)
        if oauth_url:
            verify_btn = discord.ui.Button(label="Verify", style=discord.ButtonStyle.success, url=oauth_url, row=0)
            self.add_item(verify_btn)
        info_btn = discord.ui.Button(label="Info", style=discord.ButtonStyle.secondary, row=0, custom_id="verify_info")
        async def on_info(interaction):
            embed = discord.Embed(
                title="About Verification",
                description="This verification system is made to prevent member loss if the server is ever mass banned. This is completely harmless and can be unauthorized at any time.",
                color=0xA8D8EA,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        info_btn.callback = on_info
        self.add_item(info_btn)


class ConfigCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        return True

    async def log(self, ctx: commands.Context, event: str, lines: list[str]) -> None:
        settings = await self.bot.db.get_settings(ctx.guild.id)
        if not settings["logging_events"].get("bot_commands"):
            return
        channel_id = settings.get("logging_channel_id")
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        if channel:
            await channel.send(embed=log_embed(event, lines, user=ctx.author))

    @commands.group(name="whitelist", invoke_without_command=True)
    async def whitelist(self, ctx: commands.Context) -> None:
        entries = await self.bot.db.list_whitelist(ctx.guild.id)
        users = [e for e in entries if not e["admin"]]
        admins = [e for e in entries if e["admin"]]
        bl = await self.bot.db.list_blacklist(ctx.guild.id)
        view = WhitelistView(self, ctx, users, admins, page=0, blacklist=bl)
        await ctx.send(view=view)

    @whitelist.command(name="list")
    async def whitelist_list(self, ctx: commands.Context) -> None:
        entries = await self.bot.db.list_whitelist(ctx.guild.id)
        users = [e for e in entries if not e["admin"]]
        admins = [e for e in entries if e["admin"]]
        bl = await self.bot.db.list_blacklist(ctx.guild.id)
        view = WhitelistView(self, ctx, users, admins, page=0, blacklist=bl)
        await ctx.send(view=view)

    def channel_message_embed(self, settings: dict, kind: str) -> discord.Embed:
        channel_key = f"{kind}_channel_id"
        message_key = f"{kind}_message"
        channel = f"<#{settings[channel_key]}>" if settings[channel_key] else "`not set`"
        return base_embed(
            f"{kind.title()} Setup",
            f"Channel: {channel}\nMessage: `{settings[message_key]}`",
            color=0xA8D8EA,
        )

    @commands.command(name="join")
    async def join_panel(self, ctx: commands.Context, channel: discord.TextChannel = None) -> None:
        target = channel or ctx.channel
        await self.bot.db.update_settings(ctx.guild.id, join_channel_id=target.id)
        await ctx.send("affirmative")

    @commands.command(name="leave")
    async def leave_panel(self, ctx: commands.Context, channel: discord.TextChannel = None) -> None:
        target = channel or ctx.channel
        await self.bot.db.update_settings(ctx.guild.id, leave_channel_id=target.id)
        await ctx.send("affirmative")

    def logging_embed(self, settings: dict) -> discord.Embed:
        events = settings["logging_events"]
        logging_channel = f"<#{settings['logging_channel_id']}>" if settings["logging_channel_id"] else "`not set`"
        status = lambda k: str(CHECK) if events.get(k) else str(CROSS)
        embed = discord.Embed(title="<:Security_Icon:1529617120210714624> Logging Setup", color=0xA8D8EA)
        left = [
            f"> **Channel**: {logging_channel}",
            f"> **Bot Commands**: {status('bot_commands')}",
            f"> **Anti-Nuke**: {status('antinuke')}",
        ]
        right = [
            f"> **Moderation**: {status('moderation')}",
            f"> **Audit Changes**: {status('audit_change')}",
        ]
        embed.add_field(name="Settings", value="\n".join(left), inline=True)
        embed.add_field(name="\u200b", value="\n".join(right), inline=True)
        return embed

    @commands.command(name="logging")
    async def logging_panel(self, ctx: commands.Context) -> None:
        settings = await self.bot.db.get_settings(ctx.guild.id)
        view = LoggingView(self, ctx, settings["logging_events"])
        view.rebuild()
        await ctx.send(embed=self.logging_embed(settings), view=view)

    @commands.command(name="verify")
    async def verify(self, ctx: commands.Context, role_id: str | None = None) -> None:
        if ctx.guild is None:
            await ctx.send("This command must be used in a server.")
            return

        from bot import _cfg
        client_id = _cfg.get("oauth_client_id")
        redirect_uri = _cfg.get("oauth_redirect_uri", "http://localhost:5000/verify")
        if not client_id:
            await ctx.send("OAuth not configured.")
            return

        settings = await self.bot.db.get_settings(ctx.guild.id)
        if role_id:
            try:
                role_id_int = int(role_id.strip())
            except ValueError:
                await ctx.send("Please provide a valid role ID.")
                return
            role = ctx.guild.get_role(role_id_int)
            if not role:
                await ctx.send("That role ID is not valid in this server.")
                return
            await self.bot.db.update_settings(ctx.guild.id, verify_role_id=role_id_int)
            settings["verify_role_id"] = role_id_int
            await ctx.send(f"Verify role configured to {role.mention}.")

        if not settings.get("verify_role_id"):
            await ctx.send("Set a verify role first by using `,verify <role_id>`.")
            return

        from urllib.parse import quote
        scopes = quote("identify guilds.join")
        state = quote(str(ctx.guild.id), safe="")
        oauth_url = (
            f"https://discord.com/oauth2/authorize?client_id={client_id}"
            f"&response_type=code&redirect_uri={quote(redirect_uri, safe='')}&scope={scopes}"
            f"&state={state}"
        )
        embed = discord.Embed(
            title="Verification",
            description="Click the button below to verify",
            color=0xA8D8EA,
        )
        await ctx.send(embed=embed, view=VerifyView(oauth_url))
