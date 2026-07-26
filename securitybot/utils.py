from __future__ import annotations

import re
from datetime import timedelta

import discord


DANGER_PERMS = (
    "administrator",
    "ban_members",
    "kick_members",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "manage_webhooks",
    "manage_messages",
    "mention_everyone",
)

SEC_ICON = "\U0001f6e1"
CMD_ICON = "<:command:1529665253804216502>"
LOG_COLOR = 0xA8D8EA


def base_embed(title: str, description: str | None = None, *, color: int = LOG_COLOR) -> discord.Embed:
    embed = discord.Embed(title=title, description=description or "", color=color)
    return embed


def log_embed(title: str, lines: list[str] | None = None, *, color: int = LOG_COLOR, footer: str | None = None, user: discord.User | discord.Member | None = None) -> discord.Embed:
    embed = discord.Embed(title=f"{CMD_ICON} {title}", color=color)
    if lines:
        embed.description = "\n".join(lines)
    if user:
        embed.set_thumbnail(url=user.display_avatar.url)
    if footer:
        embed.set_footer(text=footer)
    return embed


def parse_user_id(raw: str) -> int:
    cleaned = raw.strip().replace("<@", "").replace(">", "").replace("!", "")
    return int(cleaned)


def parse_duration(value: str | int | None, default_minutes: int = 60) -> int:
    if value is None:
        return default_minutes
    if isinstance(value, int):
        return value
    raw = value.strip().lower()
    if raw.isdigit():
        return int(raw)
    match = re.fullmatch(r"(\d+)([smhd])", raw)
    if not match:
        raise ValueError("Duration must look like 30m, 2h, 1d, or a minute number.")
    amount = int(match.group(1))
    unit = match.group(2)
    multipliers = {"s": 1 / 60, "m": 1, "h": 60, "d": 1440}
    return max(1, round(amount * multipliers[unit]))


def user_action_embed(
    title: str,
    guild: discord.Guild,
    moderator: discord.abc.User,
    reason: str,
    *,
    color: int = 0xA8D8EA,
    duration: str | None = None,
) -> discord.Embed:
    description = f"You were **{title.lower()}** in **{guild.name}**."
    embed = base_embed(title, description, color=color)
    embed.add_field(name="Moderator", value=f"{moderator} (`{moderator.id}`)", inline=False)
    embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)
    if duration:
        embed.add_field(name="Duration", value=duration, inline=False)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    return embed


def render_template(template: str, member: discord.Member) -> str:
    return (
        template.replace("{mention}", member.mention)
        .replace("{user}", str(member))
        .replace("{name}", member.name)
        .replace("{id}", str(member.id))
        .replace("{server}", member.guild.name)
    )


def dangerous_permissions_removed(perms: discord.Permissions) -> discord.Permissions:
    values = {name: getattr(perms, name) for name, _ in discord.Permissions.VALID_FLAGS.items()}
    for name in DANGER_PERMS:
        values[name] = False
    return discord.Permissions(**values)


async def strip_admin_roles(member: discord.Member, *, reason: str) -> list[discord.Role]:
    removable = [
        role
        for role in member.roles
        if role != member.guild.default_role
        and role.permissions.administrator
        and role < member.guild.me.top_role
        and not role.managed
    ]
    if removable:
        await member.remove_roles(*removable, reason=reason)
    return removable


async def timeout_member(member: discord.Member, minutes: int, *, reason: str) -> None:
    minutes = max(1, min(minutes, 40320))
    await member.timeout(timedelta(minutes=minutes), reason=reason)
