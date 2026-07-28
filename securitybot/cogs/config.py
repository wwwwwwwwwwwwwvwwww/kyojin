from __future__ import annotations

import asyncio
import os
from urllib.parse import quote

import discord
from discord.ext import commands

from securitybot.utils import base_embed, log_embed, parse_user_id

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
        await v.rebuild()
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
        await v.rebuild()
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
        await v.rebuild()
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

    async def resolve_name(self, uid: int) -> str:
        user = self.cog.bot.get_user(uid)
        if user:
            return user.name
        guild = self.ctx.guild
        if guild:
            member = guild.get_member(uid)
            if member:
                return member.name
        try:
            user = await self.cog.bot.fetch_user(uid)
            return user.name
        except Exception:
            return str(uid)

    async def build_text(self) -> str:
        if self.page == 0:
            title = "**Standard**"
            entries = self.users
            lines = []
            for e in entries:
                uid = e['user_id']
                name = await self.resolve_name(uid)
                lines.append(f"▶ `<{uid}>` — **{name}**")
            desc = "\n".join(lines) if lines else "> No entries."
            return f"{title}\n{desc}"
        elif self.page == 1:
            title = "**Legacy**"
            entries = self.admins
            lines = []
            for e in entries:
                uid = e['user_id']
                name = await self.resolve_name(uid)
                lines.append(f"▶ `<{uid}>` — **{name}**")
            desc = "\n".join(lines) if lines else "> No entries."
            return f"{title}\n{desc}"
        else:
            title = "**Blacklist**"
            lines = []
            for uid in self.blacklist:
                name = await self.resolve_name(uid)
                lines.append(f"▶ `<{uid}>` — **{name}**")
            desc = "\n".join(lines) if lines else "> No entries."
            return f"{title}\n{desc}"

    async def rebuild(self):
        self.clear_items()
        total_pages = 3
        container = discord.ui.Container(accent_color=0xA8D8EA)
        container.add_item(discord.ui.TextDisplay(await self.build_text()))

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
            await self.rebuild()
            await i.response.edit_message(view=self)
        prev_btn.callback = on_prev

        page_btn = discord.ui.Button(label=f"{self.page + 1}/{total_pages}", style=discord.ButtonStyle.secondary, disabled=True)
        page_btn.callback = lambda i: None

        next_btn = discord.ui.Button(emoji=RIGHT_ARROW, style=discord.ButtonStyle.secondary)
        async def on_next(i):
            self.page = (self.page + 1) % total_pages
            await self.rebuild()
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
    def __init__(self, bot: commands.Bot, guild_id: int) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        verify_btn = discord.ui.Button(label="Verify", style=discord.ButtonStyle.primary, custom_id="verify_btn", row=0)
        verify_btn.callback = self.on_verify
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

    async def on_verify(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
            return
        settings = await self.bot.db.get_settings(self.guild_id)
        verify_role_id = settings.get("verify_role_id")
        if not verify_role_id:
            await interaction.response.send_message("No verify role is configured.", ephemeral=True)
            return
        role = guild.get_role(verify_role_id)
        if not role:
            await interaction.response.send_message("The verify role no longer exists.", ephemeral=True)
            return
        member = guild.get_member(interaction.user.id)
        if not member:
            await interaction.response.send_message("Could not find you in this server.", ephemeral=True)
            return
        if role in member.roles:
            await interaction.response.send_message("You are already verified.", ephemeral=True)
            return
        try:
            await member.add_roles(role, reason="Verified via button")
            await interaction.response.send_message(f"You have been given the {role.mention} role.", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("Failed to assign the role.", ephemeral=True)


class ConfigCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.clean_channels: set[int] = set()

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
        await view.rebuild()
        await ctx.send(view=view)

    @whitelist.command(name="list")
    async def whitelist_list(self, ctx: commands.Context) -> None:
        entries = await self.bot.db.list_whitelist(ctx.guild.id)
        users = [e for e in entries if not e["admin"]]
        admins = [e for e in entries if e["admin"]]
        bl = await self.bot.db.list_blacklist(ctx.guild.id)
        view = WhitelistView(self, ctx, users, admins, page=0, blacklist=bl)
        await view.rebuild()
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

        verify_role_id = settings.get("verify_role_id")
        if not verify_role_id:
            from bot import _cfg
            verify_role_id = _cfg.get("verify_role_id")
        if not verify_role_id:
            await ctx.send("Set a verify role first by using `,verify <role_id>`.")
            return

        embed = discord.Embed(
            title="Verification",
            description="Click the button below to verify",
            color=0xA8D8EA,
        )
        await ctx.send(embed=embed, view=VerifyView(self.bot, ctx.guild.id))

    @commands.command(name="accessrole")
    async def accessrole(self, ctx: commands.Context, role: discord.Role = None) -> None:
        if not role:
            await ctx.send("Usage: `,accessrole @role`")
            return
        antinuke = await self.bot.db.get_raw_json(ctx.guild.id, "antinuke")
        mb = antinuke.setdefault("massban_lockdown", {})
        mb["access_role_id"] = role.id
        await self.bot.db.set_raw_json(ctx.guild.id, "antinuke", antinuke)
        events_cog = self.bot.get_cog("EventCog")
        if events_cog:
            events_cog._locked_positions[ctx.guild.id] = role.position
        await ctx.send(f"Access role set to {role.mention}. It will be locked in position and cannot be moved.")

    @commands.command(name="lockrole")
    async def lockrole(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        is_legacy = await self.bot.db.is_whitelist_admin(ctx.guild.id, ctx.author.id)
        is_owner = ctx.author.id in self.bot.owner_ids or ctx.author.id == ctx.guild.owner_id
        if not is_legacy and not is_owner:
            return
        antinuke = await self.bot.db.get_raw_json(ctx.guild.id, "antinuke")
        mb = antinuke.get("massban_lockdown", {})
        access_role_id = mb.get("access_role_id")
        if not access_role_id:
            await ctx.send("No access role is set.")
            return
        role = ctx.guild.get_role(access_role_id)
        if not role:
            await ctx.send("Access role not found.")
            return
        events_cog = self.bot.get_cog("EventCog")
        if events_cog and ctx.guild.id in events_cog._locked_positions:
            del events_cog._locked_positions[ctx.guild.id]
            await ctx.send("Unlocked")
        else:
            if events_cog:
                events_cog._locked_positions[ctx.guild.id] = role.position
            await ctx.send("Locked")

    @commands.command(name="pic")
    async def pic(self, ctx: commands.Context, member: discord.Member = None) -> None:
        await self._give_role(ctx, member, "pic_role_id", "PIC")

    @commands.command(name="vc")
    async def vc(self, ctx: commands.Context, member: discord.Member = None) -> None:
        await self._give_role(ctx, member, "vc_role_id", "VC")

    @commands.command(name="vcjoin")
    async def vcjoin(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.send("You must be in a voice channel.")
            return
        channel = ctx.author.voice.channel
        try:
            vc = await channel.connect(self_deaf=True)
            await ctx.send("Affirmative.")
        except discord.HTTPException:
            await ctx.send("Failed to join voice channel.")

    @commands.command(name="hr")
    async def hr(self, ctx: commands.Context, member: discord.Member = None) -> None:
        await self._give_role(ctx, member, "hr_role_id", "HR")

    async def _give_role(self, ctx: commands.Context, member: discord.Member | None, config_key: str, label: str) -> None:
        if ctx.guild is None:
            return
        if not member:
            await ctx.send(f"Usage: `,{label.lower()} @user`")
            return
        from bot import _cfg
        role_id = _cfg.get(config_key)
        if not role_id:
            await ctx.send(f"No {label} role configured.")
            return
        role = ctx.guild.get_role(role_id)
        if not role:
            await ctx.send(f"{label} role not found.")
            return
        if role in member.roles:
            try:
                await member.remove_roles(role, reason=f"Removed by {ctx.author}")
                await ctx.send(f"Removed {role.mention} from {member.mention}.")
            except discord.HTTPException:
                await ctx.send("Failed to remove role.")
        else:
            try:
                await member.add_roles(role, reason=f"Given by {ctx.author}")
                await ctx.send(f"Given {role.mention} to {member.mention}.")
            except discord.HTTPException:
                await ctx.send("Failed to add role.")

    @commands.command(name="hrsync")
    @commands.has_permissions(administrator=True)
    async def hrsync(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        from bot import _cfg
        role_id = _cfg.get("hr_role_id")
        if not role_id:
            await ctx.send("No HR role configured.")
            return
        hr_role = ctx.guild.get_role(role_id)
        if not hr_role:
            await ctx.send("HR role not found.")
            return
        count = 0
        to_give = []
        for member in ctx.guild.members:
            if hr_role in member.roles:
                continue
            if any(r.permissions.administrator for r in member.roles):
                to_give.append(member)
        if to_give:
            results = await asyncio.gather(
                *[m.add_roles(hr_role, reason="HR Sync") for m in to_give],
                return_exceptions=True,
            )
            count = sum(1 for r in results if not isinstance(r, Exception))
        await ctx.send(f"Affirmative.")

    @commands.command(name="clean")
    async def clean(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        if ctx.channel.id in self.clean_channels:
            self.clean_channels.discard(ctx.channel.id)
            await ctx.send("Cleaning stopped.")
        else:
            self.clean_channels.add(ctx.channel.id)
            await ctx.send("Cleaning")

    @commands.command(name="rrm")
    async def rrm(self, ctx: commands.Context, role: discord.Role = None) -> None:
        if ctx.guild is None:
            return
        if ctx.author.id not in self.bot.owner_ids:
            return
        if not role:
            await ctx.send("Usage: `,rrm <role>`")
            return
        if role.members:
            await asyncio.gather(
                *[m.remove_roles(role, reason=f"Mass remove by {ctx.author}") for m in role.members],
                return_exceptions=True,
            )
        await ctx.send("Affirmative.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None:
            return
        if message.author.bot:
            return
        if message.channel.id not in self.clean_channels:
            return
        if message.author.id in self.bot.owner_ids:
            return
        if await self.bot.db.is_whitelist_admin(message.guild.id, message.author.id):
            return
        try:
            await message.delete()
        except discord.HTTPException:
            pass

    @commands.command(name="avoid")
    async def avoid(self, ctx: commands.Context, role: discord.Role = None) -> None:
        if ctx.guild is None:
            return
        is_legacy = await self.bot.db.is_whitelist_admin(ctx.guild.id, ctx.author.id)
        is_owner = ctx.author.id in self.bot.owner_ids or ctx.author.id == ctx.guild.owner_id
        if not is_legacy and not is_owner:
            return
        if not role:
            await ctx.send("Usage: `,avoid @role` to add/remove a role from the avoided list.")
            return
        antinuke = await self.bot.db.get_raw_json(ctx.guild.id, "antinuke")
        avoided = antinuke.setdefault("avoided_roles", [])
        if role.id in avoided:
            avoided.remove(role.id)
            await self.bot.db.set_raw_json(ctx.guild.id, "antinuke", antinuke)
            await ctx.send(f"Removed from list.")
        else:
            avoided.append(role.id)
            await self.bot.db.set_raw_json(ctx.guild.id, "antinuke", antinuke)
            await ctx.send(f"Added to list.")

    @commands.command(name="avoidlist")
    async def avoidlist(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        antinuke = await self.bot.db.get_raw_json(ctx.guild.id, "antinuke")
        avoided = antinuke.get("avoided_roles", [])
        if not avoided:
            await ctx.send("No avoided roles.")
            return
        lines = []
        for rid in avoided:
            role = ctx.guild.get_role(rid)
            lines.append(f"• {role.mention if role else f'`{rid}`'}")
        embed = discord.Embed(
            title="Avoided Roles",
            description="\n".join(lines) if lines else "No avoided roles.",
            color=0xA8D8EA,
        )
        await ctx.send(embed=embed)

    @commands.command(name="blacklist")
    async def blacklist_cmd(self, ctx: commands.Context) -> None:
        entries = await self.bot.db.list_whitelist(ctx.guild.id)
        users = [e for e in entries if not e["admin"]]
        admins = [e for e in entries if e["admin"]]
        bl = await self.bot.db.list_blacklist(ctx.guild.id)
        view = WhitelistView(self, ctx, users, admins, page=2, blacklist=bl)
        await view.rebuild()
        await ctx.send(view=view)

    # ── Antinuke Shortcut ────────────────────────────────────────────────────

    async def _open_an_page(self, ctx: commands.Context, page: int) -> None:
        antinuke_cog = self.bot.get_cog("AntiNukeCog")
        if not antinuke_cog:
            await ctx.send("Anti-Nuke cog not loaded.")
            return
        settings = await self.bot.db.get_settings(ctx.guild.id)
        config = settings["antinuke"]
        from securitybot.cogs.antinuke import AntinukeView
        view = AntinukeView(antinuke_cog, ctx.guild.id, ctx.author.id, config)
        view.page = page
        view.rebuild()
        await ctx.send(embed=antinuke_cog.render_page(config, page, ctx.guild), view=view)

    @commands.group(name="an", invoke_without_command=True)
    async def an(self, ctx: commands.Context) -> None:
        antinuke_cog = self.bot.get_cog("AntiNukeCog")
        if not antinuke_cog:
            await ctx.send("Anti-Nuke cog not loaded.")
            return
        await antinuke_cog.antinuke_panel(ctx)

    @an.group(name="whitelist", invoke_without_command=True)
    async def an_whitelist(self, ctx: commands.Context) -> None:
        await self._open_an_page(ctx, 9)

    @an_whitelist.command(name="add")
    async def an_whitelist_add(self, ctx: commands.Context, uid: int = None) -> None:
        if ctx.author.id not in self.bot.owner_ids:
            return
        if not uid:
            await ctx.send("Usage: `,an whitelist add <uid>`")
            return
        antinuke = await self.bot.db.get_raw_json(ctx.guild.id, "antinuke")
        wl = antinuke.setdefault("whitelist", [])
        if uid not in wl:
            wl.append(uid)
            await self.bot.db.set_raw_json(ctx.guild.id, "antinuke", antinuke)
        await ctx.send("Affirmative.")

    @an_whitelist.command(name="remove")
    async def an_whitelist_remove(self, ctx: commands.Context, uid: int = None) -> None:
        if ctx.author.id not in self.bot.owner_ids:
            return
        if not uid:
            await ctx.send("Usage: `,an whitelist remove <uid>`")
            return
        antinuke = await self.bot.db.get_raw_json(ctx.guild.id, "antinuke")
        wl = antinuke.get("whitelist", [])
        if uid in wl:
            wl.remove(uid)
            await self.bot.db.set_raw_json(ctx.guild.id, "antinuke", antinuke)
        await ctx.send("Affirmative.")

    @an.command(name="channel")
    async def an_channel(self, ctx: commands.Context) -> None:
        await self._open_an_page(ctx, 3)

    @an.command(name="role")
    async def an_role(self, ctx: commands.Context) -> None:
        await self._open_an_page(ctx, 4)

    @an.command(name="ban")
    async def an_ban(self, ctx: commands.Context) -> None:
        await self._open_an_page(ctx, 5)

    @an.command(name="kick")
    async def an_kick(self, ctx: commands.Context) -> None:
        await self._open_an_page(ctx, 6)

    @an.command(name="ping")
    async def an_ping(self, ctx: commands.Context) -> None:
        await self._open_an_page(ctx, 2)

    @an.command(name="webhook")
    async def an_webhook(self, ctx: commands.Context) -> None:
        await self._open_an_page(ctx, 1)

    @an.command(name="audit")
    async def an_audit(self, ctx: commands.Context) -> None:
        await self._open_an_page(ctx, 7)

    @an.command(name="lockdown")
    async def an_lockdown(self, ctx: commands.Context) -> None:
        await self._open_an_page(ctx, 8)

    # ── Whitelist Legacy/Standard Commands ───────────────────────────────────

    @whitelist.group(name="legacy", invoke_without_command=True)
    async def whitelist_legacy(self, ctx: commands.Context) -> None:
        entries = await self.bot.db.list_whitelist(ctx.guild.id)
        users = [e for e in entries if not e["admin"]]
        admins = [e for e in entries if e["admin"]]
        bl = await self.bot.db.list_blacklist(ctx.guild.id)
        view = WhitelistView(self, ctx, users, admins, page=1, blacklist=bl)
        await view.rebuild()
        await ctx.send(view=view)

    @whitelist_legacy.command(name="add")
    async def whitelist_legacy_add(self, ctx: commands.Context, uid: str = None) -> None:
        if ctx.guild is None:
            return
        if ctx.author.id not in self.bot.owner_ids:
            return
        if not uid:
            await ctx.send("Usage: `,whitelist legacy add <uid/@mention>`")
            return
        try:
            uid_int = parse_user_id(uid)
        except (ValueError, TypeError):
            await ctx.send("Invalid user ID or mention.")
            return
        await self.bot.db.remove_whitelist(ctx.guild.id, uid_int)
        await self.bot.db.add_whitelist(ctx.guild.id, uid_int, ctx.author.id, admin=True)
        await ctx.send("Affirmative.")

    @whitelist_legacy.command(name="remove")
    async def whitelist_legacy_remove(self, ctx: commands.Context, uid: str = None) -> None:
        if ctx.guild is None:
            return
        if ctx.author.id not in self.bot.owner_ids:
            return
        if not uid:
            await ctx.send("Usage: `,whitelist legacy remove <uid/@mention>`")
            return
        try:
            uid_int = parse_user_id(uid)
        except (ValueError, TypeError):
            await ctx.send("Invalid user ID or mention.")
            return
        if uid_int == ctx.guild.owner_id:
            await ctx.send("Cannot remove the guild owner.")
            return
        await self.bot.db.remove_whitelist(ctx.guild.id, uid_int)
        await ctx.send("Affirmative.")

    @whitelist.group(name="standard", invoke_without_command=True)
    async def whitelist_standard(self, ctx: commands.Context) -> None:
        await ctx.send("Usage: `,whitelist standard add/remove <uid>`")

    @whitelist_standard.command(name="add")
    async def whitelist_standard_add(self, ctx: commands.Context, uid: str = None) -> None:
        if ctx.guild is None:
            return
        if ctx.author.id not in self.bot.owner_ids:
            return
        if not uid:
            await ctx.send("Usage: `,whitelist standard add <uid/@mention>`")
            return
        try:
            uid_int = parse_user_id(uid)
        except (ValueError, TypeError):
            await ctx.send("Invalid user ID or mention.")
            return
        await self.bot.db.remove_whitelist(ctx.guild.id, uid_int)
        await self.bot.db.add_whitelist(ctx.guild.id, uid_int, ctx.author.id, admin=False)
        await ctx.send("Affirmative.")

    @whitelist_standard.command(name="remove")
    async def whitelist_standard_remove(self, ctx: commands.Context, uid: str = None) -> None:
        if ctx.guild is None:
            return
        if ctx.author.id not in self.bot.owner_ids:
            return
        if not uid:
            await ctx.send("Usage: `,whitelist standard remove <uid/@mention>`")
            return
        try:
            uid_int = parse_user_id(uid)
        except (ValueError, TypeError):
            await ctx.send("Invalid user ID or mention.")
            return
        if uid_int == ctx.guild.owner_id:
            await ctx.send("Cannot remove the guild owner.")
            return
        await self.bot.db.remove_whitelist(ctx.guild.id, uid_int)
        await ctx.send("Affirmative.")

    # ── Trust Commands ───────────────────────────────────────────────────────

    @commands.group(name="trust", invoke_without_command=True)
    async def trust(self, ctx: commands.Context) -> None:
        if ctx.author.id not in self.bot.owner_ids:
            return
        entries = await self.bot.db.list_trusted()
        if not entries:
            await ctx.send("No trusted users.")
            return
        lines = []
        for e in entries:
            uid = e["user_id"]
            user = self.bot.get_user(uid)
            name = user.name if user else str(uid)
            lines.append(f"• `<{uid}>` — **{name}**")
        embed = discord.Embed(
            title="Trusted Users",
            description="\n".join(lines),
            color=0xA8D8EA,
        )
        await ctx.send(embed=embed)

    @trust.command(name="add")
    async def trust_add(self, ctx: commands.Context, uid: int = None) -> None:
        if ctx.author.id not in self.bot.owner_ids:
            return
        if not uid:
            await ctx.send("Usage: `,trust add <uid>`")
            return
        await self.bot.db.add_trusted(uid, ctx.author.id)
        await ctx.send("Affirmative.")

    @trust.command(name="remove")
    async def trust_remove(self, ctx: commands.Context, uid: int = None) -> None:
        if ctx.author.id not in self.bot.owner_ids:
            return
        if not uid:
            await ctx.send("Usage: `,trust remove <uid>`")
            return
        await self.bot.db.remove_trusted(uid)
        await ctx.send("Affirmative.")
