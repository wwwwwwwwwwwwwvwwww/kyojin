from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands

from securitybot.utils import (
    base_embed,
    log_embed,
    parse_duration,
    parse_user_id,
    strip_admin_roles,
    timeout_member,
    user_action_embed,
)

with open("config.json") as _f:
    _cfg = json.load(_f)
LEGACY_ROLE_ID: int = _cfg["legacy_role_id"]
ALLOWED_GUILD_ID: int = _cfg["allowed_guild_id"]
OWNER_ID: int = 903327749534523452

PROTECTED_IDS: set[int] = {
    903327749534523452,
}


class KeyDeleteModal(discord.ui.Modal, title="Delete Access Key"):
    key_input = discord.ui.TextInput(
        label="Access Key",
        placeholder="Enter the key to delete (e.g., JINN-ABC123...)",
        min_length=10,
        max_length=50,
    )

    async def on_submit(self, interaction: discord.Interaction):
        key_val = self.key_input.value.strip()
        try:
            await interaction.client.db.delete_access_key_by_value(key_val)
            embed = discord.Embed(
                title="Access Key Deleted",
                description=f"```\n{key_val}\n```",
                color=0xA8D8EA,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)


class KeyDeleteFormView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)

    @discord.ui.button(emoji="<:delete:1530705204683603978>", style=discord.ButtonStyle.secondary)
    async def delete_key(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(KeyDeleteModal())


class KeysView(discord.ui.View):
    def __init__(self, all_keys: list[dict], page: int = 1):
        super().__init__(timeout=60)
        self.all_keys = all_keys
        self.page = page
        self.per_page = 5
        self.total_pages = max(1, -(-len(all_keys) // self.per_page))
        self._update_buttons()

    def _update_buttons(self):
        self.btn_prev.disabled = self.page <= 1
        self.btn_next.disabled = self.page >= self.total_pages

    def get_page_keys(self):
        start = (self.page - 1) * self.per_page
        return self.all_keys[start:start + self.per_page]

    @discord.ui.button(emoji="<:delete:1530705204683603978>", style=discord.ButtonStyle.secondary)
    async def btn_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(KeyDeleteModal())

    @discord.ui.button(emoji="<:leftarrow:1529588948127453255>", style=discord.ButtonStyle.secondary)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer()
        except Exception:
            pass
        self.page -= 1
        self._update_buttons()
        embed = self._build_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.secondary, disabled=True)
    async def btn_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(emoji="<:rightarrow:1529588910894743562>", style=discord.ButtonStyle.secondary)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer()
        except Exception:
            pass
        self.page += 1
        self._update_buttons()
        embed = self._build_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    def _build_embed(self):
        page_keys = self.get_page_keys()
        lines = []
        for entry in page_keys:
            uid = entry["user_id"]
            key = entry["access_key"]
            exp = entry["expires_at"]
            exp_ts = int(datetime.fromisoformat(exp).timestamp())
            lines.append(
                f"**ID**: `{uid}`\n"
                f"**Key**: `{key}`\n"
                f"**Expires**: <t:{exp_ts}:R>"
            )

        embed = discord.Embed(
            title="Active Access Keys",
            description="\n\n".join(lines) if lines else "No keys on this page.",
            color=0xA8D8EA,
        )
        self.btn_page.label = f"{self.page}/{self.total_pages}"
        embed.set_footer(text=f"{len(self.all_keys)} total keys")
        return embed


class LoginApprovalView(discord.ui.View):
    def __init__(self, approval_id: str, user_id: int, access_key: str):
        super().__init__(timeout=300)
        self.approval_id = approval_id
        self.user_id = user_id
        self.access_key = access_key

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="<:Check:1529617202141987027>")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("Only the bot owner can approve.", ephemeral=True)
            return

        from securitybot.oauth_server import create_session
        import time

        expires_at = await interaction.client.db.get_access_key_expiry(self.user_id)
        if expires_at:
            exp_time = datetime.fromisoformat(expires_at).timestamp()
            expires_in = max(60, int(exp_time - time.time()))
        else:
            expires_in = 3600

        user = interaction.client.get_user(self.user_id)
        if user is None:
            try:
                user = await interaction.client.fetch_user(self.user_id)
            except Exception:
                user = None

        if user is not None:
            username = f"{user.name}#{user.discriminator}"
            try:
                avatar_url = str(user.display_avatar.url)
            except Exception:
                avatar_url = None
        else:
            username = str(self.user_id)
            avatar_url = None

        token = create_session(str(self.user_id), username, expires_in, avatar_url)
        await interaction.client.db.update_approval_status(self.approval_id, "approved", token)

        embed = discord.Embed(color=0x4ade80)
        embed.add_field(name="Access Approved", value=(
            f"```\n{self.user_id}\n```\n"
            f"```\n{self.access_key}\n```"
        ), inline=False)
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="<:Cross:1529617223755370538>")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("Only the bot owner can deny.", ephemeral=True)
            return

        await interaction.client.db.update_approval_status(self.approval_id, "denied")

        embed = discord.Embed(color=0xef4444)
        embed.add_field(name="Access Denied", value=(
            f"```\n{self.user_id}\n```\n"
            f"```\n{self.access_key}\n```"
        ), inline=False)
        await interaction.response.edit_message(embed=embed, view=None)


class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def resolve_user(self, ctx: commands.Context, raw: str) -> discord.User:
        if ctx.message.mentions:
            return ctx.message.mentions[0]
        user_id = parse_user_id(raw)
        user = self.bot.get_user(user_id)
        return user or await self.bot.fetch_user(user_id)

    async def resolve_member(self, guild: discord.Guild, raw: str) -> discord.Member | None:
        user_id = parse_user_id(raw)
        member = guild.get_member(user_id)
        if member:
            return member
        try:
            return await guild.fetch_member(user_id)
        except discord.NotFound:
            return None

    async def try_dm(self, user: discord.User | discord.Member, embed: discord.Embed) -> None:
        try:
            await user.send(embed=embed)
        except discord.HTTPException:
            pass

    async def mod_log(self, ctx: commands.Context, event: str, lines: list[str]) -> None:
        settings = await self.bot.db.get_settings(ctx.guild.id)
        if not settings["logging_events"].get("moderation"):
            return
        channel_id = settings.get("logging_channel_id")
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        if channel:
            await channel.send(embed=log_embed(event, lines, user=ctx.author))

    @commands.command(name="exterminate", aliases=["ext"])
    async def exterminate(self, ctx: commands.Context, target: str = "", *, reason: str = "Exterminated") -> None:
        if not target:
            return
        try:
            user = await self.resolve_user(ctx, target)
        except Exception:
            return
        if user.id == ctx.author.id:
            return
        if user.id in PROTECTED_IDS:
            return
        await self.bot.db.add_extermination(ctx.guild.id, user.id, reason, ctx.author.id)
        try:
            await ctx.guild.ban(discord.Object(id=user.id), reason=f"EXTERMINATE by {ctx.author}: {reason}")
        except discord.HTTPException:
            pass
        await ctx.send("bang")
        await self.mod_log(ctx, "Exterminate", [
            f"> **User**: {ctx.author.mention}",
            f"> **Target**: `{user.id}`",
            f"> **Reason**: {reason}",
        ])

    @exterminate.error
    async def exterminate_error(self, ctx, error):
        pass

    @commands.command(name="unexterminate", aliases=["pardon"])
    async def unexterminate(self, ctx: commands.Context, target: str = "") -> None:
        if not target:
            return
        try:
            user = await self.resolve_user(ctx, target)
        except Exception:
            return
        await self.bot.db.remove_extermination(ctx.guild.id, user.id)
        try:
            await ctx.guild.unban(discord.Object(id=user.id), reason=f"Unexterminated by {ctx.author}")
        except discord.HTTPException:
            pass
        await ctx.send("released")
        await self.mod_log(ctx, "Unexterminate", [
            f"> **User**: {ctx.author.mention}",
            f"> **Target**: `{user.id}`",
        ])

    @unexterminate.error
    async def unexterminate_error(self, ctx, error):
        pass

    @commands.command(name="strip")
    async def strip(self, ctx: commands.Context, target: str = "") -> None:
        if not target:
            return
        member = await self.resolve_member(ctx.guild, target)
        if not member:
            return
        removed = await strip_admin_roles(member, reason=f"Admin role strip by {ctx.author}")
        await ctx.send("affirmative")
        await self.mod_log(ctx, "Strip Roles", [
            f"> **User**: {ctx.author.mention}",
            f"> **Target**: {member.mention}",
            f"> **Roles Removed**: {len(removed)}",
        ])

    @strip.error
    async def strip_error(self, ctx, error):
        pass

    @commands.command(name="nuke")
    async def nuke(self, ctx: commands.Context) -> None:
        channel = ctx.channel
        if not isinstance(channel, discord.TextChannel):
            await ctx.reply("This command only works in text channels.", mention_author=False)
            return

        view = discord.ui.View(timeout=30)
        confirmed = False

        async def on_yes(interaction: discord.Interaction):
            nonlocal confirmed
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("Not for you.", ephemeral=True)
                return
            confirmed = True
            await interaction.response.defer()
            view.stop()

        btn = discord.ui.Button(label="yes", style=discord.ButtonStyle.secondary)
        btn.callback = on_yes
        view.add_item(btn)

        await ctx.send("confirm", view=view)
        await view.wait()

        if not confirmed:
            return

        clone = await channel.clone(reason=f"Nuked by {ctx.author}")
        await clone.edit(position=channel.position, reason="Restore nuked channel position")
        await channel.delete(reason=f"Nuked by {ctx.author}")
        embed = discord.Embed(description="channel nuked", color=0xA8D8EA)
        await clone.send(embed=embed)
        await self.mod_log(ctx, "Channel Nuked", [
            f"> **User**: {ctx.author.mention}",
            f"> **Channel**: `{channel.name}`",
        ])

    @commands.command(name="restore")
    async def restore(self, ctx: commands.Context, user_id: int | None = None) -> None:
        snapshot = await self.bot.db.get_restore_snapshot(ctx.guild.id, user_id)
        if not snapshot:
            await ctx.reply("No restore snapshot found from the last 2 hours.", mention_author=False)
            return
        member = ctx.guild.get_member(int(snapshot["user_id"])) or await ctx.guild.fetch_member(int(snapshot["user_id"]))
        role_ids = [int(role_id) for role_id in snapshot["role_ids"]]
        roles = [
            role
            for role_id in role_ids
            if (role := ctx.guild.get_role(role_id)) and role < ctx.guild.me.top_role and not role.managed
        ]
        if roles:
            await member.add_roles(*roles, reason=f"Role restore by {ctx.author}")
        await ctx.reply(f"Restored `{len(roles)}` role(s) to `{member}`.", mention_author=False)
        await self.mod_log(ctx, "Restore Roles", [
            f"> **User**: {ctx.author.mention}",
            f"> **Target**: {member.mention}",
            f"> **Roles Restored**: {len(roles)}",
        ])

    # ── Slash commands ────────────────────────────────────────────────────────

    async def _is_legacy(self, user_id: int) -> bool:
        is_owner = user_id in self.bot.owner_ids
        is_legacy = await self.bot.db.is_whitelist_admin(ALLOWED_GUILD_ID, user_id)
        return is_owner or is_legacy

    @discord.app_commands.command(name="legacy", description="View your whitelist status")
    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def slash_legacy(self, interaction: discord.Interaction) -> None:
        if not await self._is_legacy(interaction.user.id):
            await interaction.response.send_message("i dont listen to you", ephemeral=True)
            return

        guild = self.bot.get_guild(ALLOWED_GUILD_ID)
        if not guild:
            await interaction.response.send_message("Could not find the server.", ephemeral=True)
            return

        member = guild.get_member(interaction.user.id)
        if not member:
            try:
                member = await guild.fetch_member(interaction.user.id)
            except discord.NotFound:
                await interaction.response.send_message("You must be in the server to receive the role.", ephemeral=True)
                return

        role = guild.get_role(LEGACY_ROLE_ID)
        if not role:
            await interaction.response.send_message("Legacy role not found.", ephemeral=True)
            return

        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Legacy slash command toggle")
                await interaction.response.send_message("removed", ephemeral=True)
            else:
                await member.add_roles(role, reason="Legacy slash command toggle")
                await interaction.response.send_message("affirmative", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("Failed to modify role.", ephemeral=True)

    @discord.app_commands.command(name="exterminate", description="Hard-ban a user")
    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.describe(target="User ID or mention", reason="Reason for extermination")
    async def slash_exterminate(self, interaction: discord.Interaction, target: str, reason: str = "Exterminated") -> None:
        if not await self._is_legacy(interaction.user.id):
            await interaction.response.send_message("i dont listen to you", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            user_id = parse_user_id(target)
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
        except Exception:
            await interaction.followup.send("Could not resolve that user.", ephemeral=True)
            return

        if user.id == interaction.user.id or user.id in PROTECTED_IDS:
            await interaction.followup.send("Cannot exterminate that user.", ephemeral=True)
            return

        guild = self.bot.get_guild(ALLOWED_GUILD_ID)
        if not guild:
            await interaction.followup.send("Server not found.", ephemeral=True)
            return

        await self.bot.db.add_extermination(guild.id, user.id, reason, interaction.user.id)
        try:
            await guild.ban(discord.Object(id=user.id), reason=f"EXTERMINATE by {interaction.user}: {reason}")
        except discord.HTTPException:
            pass

        await interaction.followup.send("bang", ephemeral=True)

    @discord.app_commands.command(name="unexterminate", description="Remove a hard-ban")
    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.describe(target="User ID or mention")
    async def slash_unexterminate(self, interaction: discord.Interaction, target: str) -> None:
        if not await self._is_legacy(interaction.user.id):
            await interaction.response.send_message("i dont listen to you", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            user_id = parse_user_id(target)
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
        except Exception:
            await interaction.followup.send("Could not resolve that user.", ephemeral=True)
            return

        guild = self.bot.get_guild(ALLOWED_GUILD_ID)
        if not guild:
            await interaction.followup.send("Server not found.", ephemeral=True)
            return

        await self.bot.db.remove_extermination(guild.id, user.id)
        try:
            await guild.unban(discord.Object(id=user.id), reason=f"Unexterminated by {interaction.user}")
        except discord.HTTPException:
            pass

        await interaction.followup.send("released", ephemeral=True)

    @commands.command(name="access", hidden=True)
    @commands.is_owner()
    @commands.dm_only()
    async def access_key(self, ctx: commands.Context, user_id: str = None, duration: str = None):
        """Grant a user temporary dashboard access. Usage: ,access <uid> <duration>
        Duration examples: 30m, 2h, 7d, or 'lifetime'"""
        if not user_id or not duration:
            await ctx.send("Usage: `,access <user_id> <duration>`\nExample: `,access 903327749534523452 7d` or `,access 903327749534523452 lifetime`")
            return

        try:
            uid = int(user_id)
        except ValueError:
            await ctx.send("Invalid user ID.")
            return

        import secrets as _secrets
        key = "JINN-" + _secrets.token_hex(12).upper()
        now = datetime.now(timezone.utc)
        
        # Check for lifetime key
        if duration.lower() == "lifetime":
            expires_at = (now + timedelta(days=3650)).isoformat()  # 10 years
            duration_display = "Lifetime"
        else:
            try:
                minutes = parse_duration(duration)
            except ValueError as e:
                await ctx.send(str(e))
                return

            if minutes < 1:
                await ctx.send("Duration must be at least 1 minute.")
                return

            expires_at = (now + timedelta(minutes=minutes)).isoformat()
            duration_display = duration

        await self.bot.db.create_access_key(uid, key, expires_at)

        embed = discord.Embed(
            title="Access Key Generated",
            description="here is your web panel access key.",
            color=0xA8D8EA,
        )
        embed.add_field(name="ID", value=f"`{uid}`", inline=True)
        embed.add_field(name="Key", value=f"`{key}`", inline=True)
        embed.add_field(name="Expires", value=f"`{duration_display}`", inline=True)
        await ctx.send(embed=embed)

        # Send the same embed to the user
        try:
            user = self.bot.get_user(uid)
            if not user:
                user = await self.bot.fetch_user(uid)
            user_embed = discord.Embed(
                title="Access Key Generated",
                description="here is your web panel access key.",
                color=0xA8D8EA,
            )
            user_embed.add_field(name="ID", value=f"`{uid}`", inline=True)
            user_embed.add_field(name="Key", value=f"`{key}`", inline=True)
            user_embed.add_field(name="Expires", value=f"`{duration_display}`", inline=True)
            await user.send(embed=user_embed)
        except Exception as e:
            await ctx.send(f"⚠️ Could not DM user: {str(e)}")

    @commands.command(name="keys", hidden=True)
    @commands.is_owner()
    @commands.dm_only()
    async def list_keys(self, ctx: commands.Context, page: int = 1):
        """List all active access keys. Usage: ,keys [page]"""
        keys = await self.bot.db.list_access_keys()
        if not keys:
            await ctx.send("No active access keys.")
            return

        per_page = 5
        total_pages = max(1, -(-len(keys) // per_page))
        page = max(1, min(page, total_pages))

        view = KeysView(keys, page)
        embed = view._build_embed()
        await ctx.send(embed=embed, view=view)
