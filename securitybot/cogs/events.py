from __future__ import annotations

import os
import discord
from discord.ext import commands

from securitybot.utils import base_embed, log_embed, CMD_ICON, render_template, user_action_embed


class EventCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def latest_actor(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int | None = None):
        try:
            async for entry in guild.audit_logs(limit=5, action=action):
                if target_id is None or getattr(entry.target, "id", None) == target_id:
                    return entry.user
        except discord.Forbidden:
            return None
        return None

    async def log(self, guild: discord.Guild, event: str, embed: discord.Embed) -> None:
        settings = await self.bot.db.get_settings(guild.id)
        if not settings["logging_events"].get(event):
            return
        channel_id = settings.get("logging_channel_id")
        channel = guild.get_channel(channel_id) if channel_id else None
        if channel:
            await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        extermination = await self.bot.db.get_extermination(member.guild.id, member.id)
        if extermination:
            moderator = self.bot.get_user(int(extermination["created_by"]))
            if moderator is None:
                moderator = await self.bot.fetch_user(int(extermination["created_by"]))
            try:
                await member.send(
                    embed=user_action_embed(
                        "Exterminated",
                        member.guild,
                        moderator,
                        extermination.get("reason") or "No reason provided",
                    )
                )
            except discord.HTTPException:
                pass
            await member.ban(reason=f"Exterminated user rejoined: {extermination.get('reason') or 'No reason'}")
            return

        await self.bot.db.mark_rejoined(member.guild.id, member.id)
        settings = await self.bot.db.get_settings(member.guild.id)
        channel = member.guild.get_channel(settings.get("join_channel_id") or 0)
        if channel:
            embed = discord.Embed(description=f"{member.mention} has joined {member.guild.name}", color=0xA8D8EA)
            embed.set_author(name=member.name, icon_url=member.display_avatar.url)
            embed.set_image(url=settings.get("join_gif") or "https://i.imgur.com/a2rksjN.gif")
            await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        role_ids = [role.id for role in member.roles if role != member.guild.default_role and not role.managed]
        await self.bot.db.save_restore_snapshot(member.guild.id, member.id, role_ids)
        actor = await self.latest_actor(member.guild, discord.AuditLogAction.kick, member.id)
        if actor:
            cog = self.bot.get_cog("AntiNukeCog")
            if cog:
                await cog.record_action(member.guild, actor, "kick")
        settings = await self.bot.db.get_settings(member.guild.id)
        channel = member.guild.get_channel(settings.get("leave_channel_id") or 0)
        if channel:
            embed = discord.Embed(description=f"{member.mention} has left {member.guild.name}", color=0xA8D8EA)
            embed.set_author(name=member.name, icon_url=member.display_avatar.url)
            embed.set_image(url=settings.get("leave_gif") or "https://i.imgur.com/K7aaTLk.gif")
            await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        actor = await self.latest_actor(guild, discord.AuditLogAction.ban, user.id)
        cog = self.bot.get_cog("AntiNukeCog")
        if cog:
            await cog.record_action(guild, actor, "ban")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        actor = await self.latest_actor(role.guild, discord.AuditLogAction.role_delete, role.id)
        cog = self.bot.get_cog("AntiNukeCog")
        if cog:
            await cog.record_action(role.guild, actor, "role_delete")

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        actor = await self.latest_actor(role.guild, discord.AuditLogAction.role_create, role.id)
        cog = self.bot.get_cog("AntiNukeCog")
        if cog:
            await cog.record_action(role.guild, actor, "role_create")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        actor = await self.latest_actor(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        cog = self.bot.get_cog("AntiNukeCog")
        if cog:
            await cog.record_action(channel.guild, actor, "channel_delete")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        actor = await self.latest_actor(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        cog = self.bot.get_cog("AntiNukeCog")
        if cog:
            await cog.record_action(channel.guild, actor, "channel_create")

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild) -> None:
        actor = await self.latest_actor(after, discord.AuditLogAction.guild_update)
        actor_str = str(actor) if actor else "Unknown"
        changes = []
        detail_changes = {}
        if before.name != after.name:
            changes.extend([
                f"> **Change**: Server Name",
                f"> **Before**: `{before.name}`",
                f"> **After**: `{after.name}`",
                f"> **Executor**: {actor_str}",
            ])
            detail_changes["Change"] = "Server Name"
            detail_changes["Before"] = before.name
            detail_changes["After"] = after.name
        if before.icon != after.icon:
            changes.extend([
                f"> **Change**: Server Icon",
                f"> **Executor**: {actor_str}",
            ])
            detail_changes["Change"] = "Server Icon"
        if changes:
            await self.log(after, "audit_change", log_embed("Guild Updated", changes))
            from securitybot.oauth_server import add_log
            text = f"Server {detail_changes.get('Change','Updated')}: {after.name}"
            if "Before" in detail_changes:
                text += f" (`{detail_changes['Before']}` → `{detail_changes['After']}`)"
            add_log("regular", text, user=actor_str, avatar=str(actor.display_avatar.url) if actor else None, log_type="info", details={"Server": after.name, "Server ID": str(after.id), "Executor": actor_str, "Executor ID": str(actor.id) if actor else "Unknown", **detail_changes})
            if actor and not actor.bot and actor.id != after.owner_id:
                from securitybot.cogs.antinuke import AntiNukeCog
                cog = self.bot.get_cog("AntiNuke")
                if cog:
                    await cog.record_action(after, actor, "guild_update")

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        actor = await self.latest_actor(after.guild, discord.AuditLogAction.role_update, after.id)
        actor_str = str(actor) if actor else "Unknown"
        changes = []
        if before.name != after.name:
            changes.extend([
                f"> **Change**: Role Name",
                f"> **Before**: `{before.name}`",
                f"> **After**: `{after.name}`",
                f"> **Executor**: {actor_str}",
            ])
        if before.permissions != after.permissions:
            changes.extend([
                f"> **Change**: Role Permissions",
                f"> **Executor**: {actor_str}",
            ])
            if after.permissions.administrator and not before.permissions.administrator:
                bl = await self.bot.db.list_blacklist(after.guild.id)
                for uid in bl:
                    member = after.guild.get_member(uid)
                    if member and after in member.roles:
                        try:
                            await member.remove_roles(after, reason="Blacklist")
                        except discord.HTTPException:
                            pass
        if before.color != after.color:
            changes.extend([
                f"> **Change**: Role Color",
                f"> **Before**: `{before.color}`",
                f"> **After**: `{after.color}`",
                f"> **Executor**: {actor_str}",
            ])
        if changes:
            await self.log(after.guild, "audit_change", log_embed("Role Updated", changes))
            from securitybot.oauth_server import add_log
            add_log("regular", f"Role **{after.name}** updated in {after.guild.name}", user=actor_str, avatar=str(actor.display_avatar.url) if actor else None, log_type="info", details={"Server": after.guild.name, "Server ID": str(after.guild.id), "Role": after.name, "Role ID": str(after.id), "Executor": actor_str, "Executor ID": str(actor.id) if actor else "Unknown"})
            if actor and not actor.bot and actor.id != after.guild.owner_id:
                cog = self.bot.get_cog("AntiNuke")
                if cog:
                    await cog.record_action(after.guild, actor, "role_update")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Strip admin roles from blacklisted members the moment they receive one."""
        if before.roles == after.roles:
            return
        is_blacklisted = await self.bot.db.is_blacklisted(after.guild.id, after.id)
        if not is_blacklisted:
            return
        # Find newly added roles that have admin
        new_roles = set(after.roles) - set(before.roles)
        admin_roles = [r for r in new_roles if r.permissions.administrator]
        if admin_roles:
            try:
                await after.remove_roles(*admin_roles, reason="Blacklist")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
        actor = await self.latest_actor(after.guild, discord.AuditLogAction.channel_update, after.id)
        actor_str = str(actor) if actor else "Unknown"
        changes = []
        if before.name != after.name:
            changes.extend([
                f"> **Change**: Channel Name",
                f"> **Before**: `{before.name}`",
                f"> **After**: `{after.name}`",
                f"> **Executor**: {actor_str}",
            ])
        if before.position != after.position:
            changes.extend([
                f"> **Change**: Channel Position",
                f"> **Before**: `{before.position}`",
                f"> **After**: `{after.position}`",
                f"> **Executor**: {actor_str}",
            ])
        if changes:
            await self.log(after.guild, "audit_change", log_embed("Channel Updated", changes))
            from securitybot.oauth_server import add_log
            add_log("regular", f"Channel **#{after.name}** updated in {after.guild.name}", user=actor_str, avatar=str(actor.display_avatar.url) if actor else None, log_type="info", details={"Server": after.guild.name, "Server ID": str(after.guild.id), "Channel": f"#{after.name}", "Channel ID": str(after.id), "Executor": actor_str, "Executor ID": str(actor.id) if actor else "Unknown"})
            if actor and not actor.bot and actor.id != after.guild.owner_id:
                cog = self.bot.get_cog("AntiNuke")
                if cog:
                    await cog.record_action(after.guild, actor, "channel_update")

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel) -> None:
        try:
            async for entry in channel.guild.audit_logs(limit=5, action=discord.AuditLogAction.webhook_create):
                actor = entry.user
                target = entry.target
                break
            else:
                return
        except discord.Forbidden:
            return
        if actor is None or actor.bot:
            return
        cog = self.bot.get_cog("AntiNukeCog")
        if cog and target:
            await cog.handle_webhook_create(channel.guild, actor, target)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return
        if message.mention_everyone or "@everyone" in message.content or "@here" in message.content:
            cog = self.bot.get_cog("AntiNukeCog")
            if cog:
                await cog.handle_mass_ping(message)

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        from securitybot.oauth_server import add_log
        add_log("bot_usage", f"`{ctx.message.content[:100]}` in {ctx.channel.mention}", user=ctx.author.display_name, avatar=str(ctx.author.display_avatar.url), log_type="command")
        await self.log(ctx.guild, "bot_commands", log_embed(f"Command Used", [
            f"> **User**: {ctx.author.mention}",
            f"> **Command**: `{ctx.message.content[:500]}`",
            f"> **Channel**: {ctx.channel.mention}",
        ], user=ctx.author))

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        from securitybot.oauth_server import add_log
        inviter = None
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.bot_add):
                inviter = entry.user
                break
        except Exception:
            pass
        inviter_text = f" by {inviter} (`{inviter.id}`)" if inviter else ""
        add_log("security", f"Bot added to **{guild.name}** (`{guild.id}`){inviter_text}", user=str(inviter) if inviter else "Unknown", avatar=str(inviter.display_avatar.url) if inviter else None, log_type="security", details={"Server": guild.name, "Server ID": str(guild.id), "Members": str(guild.member_count), "Invited by": f"{inviter} (`{inviter.id}`)" if inviter else "Unknown", "Owner": f"{guild.owner} (`{guild.owner_id}`)" if guild.owner else "Unknown", "Boost Tier": str(guild.premium_tier), "Channels": str(len(guild.channels))})
        from securitybot.oauth_server import OWNER_ID
        try:
            owner = await self.bot.fetch_user(OWNER_ID)
            embed = discord.Embed(
                title="Bot Added to Server",
                description=f"> **Server**: {guild.name} (`{guild.id}`)\n> **Members**: {guild.member_count}\n> **Invited by**: {inviter.mention if inviter else 'Unknown'}",
                color=0xA8D8EA,
            )
            await owner.send(embed=embed)
        except Exception:
            pass
        ALLOWED_GUILD_ID = 1529582624635359402
        if guild.id != ALLOWED_GUILD_ID:
            await guild.leave()

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if not message.guild or not message.author or message.author.bot:
            return
        from securitybot.oauth_server import add_log
        content = message.content[:200] if message.content else "(no text)"
        add_log("regular", f"Message deleted in {message.channel.mention}: \"{content}\"", user=message.author.display_name, avatar=str(message.author.display_avatar.url), log_type="info")
