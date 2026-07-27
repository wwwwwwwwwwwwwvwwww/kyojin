from __future__ import annotations

import os
import asyncio
import logging
from datetime import datetime

import discord
from discord.ext import commands
from dotenv import load_dotenv

from securitybot.database import Database
from securitybot.cogs.antinuke import AntiNukeCog
from securitybot.cogs.config import ConfigCog
from securitybot.cogs.events import EventCog
from securitybot.cogs.help import HelpCog
from securitybot.cogs.moderation import ModerationCog
from securitybot.cogs.activity import ActivityCog, ActivityPublicView, ActivityHRView
from securitybot.oauth_server import start_web_server, add_log
from securitybot.cogs.template import TemplateCog
from securitybot.cogs.lockdown import LockdownCog
from securitybot.cogs.track import TrackCog


load_dotenv()

# ── Load config ───────────────────────────────────────────────────────────────
import json as _json
with open("config.json") as _f:
    _cfg = _json.load(_f)

DM_ALLOWED_IDS: set[int] = set(_cfg["dm_allowed_ids"])
ALLOWED_GUILD_ID: int = int(os.getenv("ALLOWED_GUILD_ID", str(_cfg["allowed_guild_id"])))

logging.disable(logging.INFO)

DEBUG_LOGS: list[str] = []
MAX_LOGS = 12


def debug_log(msg: str, level: str = "info") -> None:
    now = datetime.now().strftime("%H:%M:%S")
    prefix_map = {
        "info": "\033[92m[+]\033[0m",
        "warn": "\033[93m[!]\033[0m",
        "error": "\033[91m[x]\033[0m",
        "sus": "\033[91m[!!]\033[0m",
    }
    prefix = prefix_map.get(level, prefix_map["info"])
    entry = f"  {prefix} {now} {msg}"
    DEBUG_LOGS.append(entry)
    if len(DEBUG_LOGS) > MAX_LOGS:
        DEBUG_LOGS.pop(0)
    print_color(entry, "dim")


ASCII_ART = r"""
              ___           ___           ___           ___
             /\  \         /\  \         /\  \         /\  \
            /  \  \       /  \  \       /  \  \       /  \  \
           / /\ \  \     / /\ \  \     / /\ \  \     / /\ \  \
          / /  \ \  \   / /  \ \  \   / /  \ \  \   / /  \ \  \
         / /    \ \  \ / /    \ \  \ / /    \ \  \ / /    \ \  \
        / /      \ \  / /      \ \  / /      \ \  / /      \ \  \
       /_/        \ \/_/        \ \/_/        \ \/_/        \ \/_\
                     ___           ___           ___
                    /\  \         /\  \         /\  \
                   /  \  \       /  \  \       /  \  \
                  / /\ \  \     / /\ \  \     / /\ \  \
                 / /  \ \  \   / /  \ \  \   / /  \ \  \
                / /    \ \  \ / /    \ \  \ / /    \ \  \
               / /      \ \  / /      \ \  / /      \ \  \
              /_/        \ \/_/        \ \/_/        \ \/_\
"""


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def print_color(text: str, color: str = "lightcyan") -> None:
    colors = {
        "lightcyan": "\033[96m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "red": "\033[91m",
        "white": "\033[97m",
        "cyan": "\033[36m",
        "magenta": "\033[35m",
        "reset": "\033[0m",
        "bold": "\033[1m",
        "dim": "\033[2m",
    }
    c = colors.get(color, "")
    r = colors["reset"]
    print(f"{c}{text}{r}")


def parse_owner_ids() -> set[int]:
    raw = os.getenv("OWNER_IDS", "")
    return {int(item.strip()) for item in raw.split(",") if item.strip().isdigit()}


async def get_prefix_for_message(bot: "SecurityBot", message: discord.Message):
    if not message.guild:
        return commands.when_mentioned_or(",")(bot, message)
    settings = await bot.db.get_settings(message.guild.id)
    return commands.when_mentioned_or(settings["prefix"])(bot, message)


class SecurityBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.all()

        super().__init__(
            command_prefix=get_prefix_for_message,
            intents=intents,
            owner_ids=parse_owner_ids(),
            help_command=None,
            case_insensitive=True,
        )
        self.db = Database("securitybot.db")
        self._web_runner = None
        self._web_site = None

    async def setup_hook(self) -> None:
        await self.db.connect()
        await self.db.migrate()

        # Slash commands work everywhere — individual commands handle their own auth
        await self.add_cog(HelpCog(self))
        await self.add_cog(ConfigCog(self))
        await self.add_cog(ModerationCog(self))
        await self.add_cog(AntiNukeCog(self))
        await self.add_cog(EventCog(self))
        await self.add_cog(ActivityCog(self))
        await self.add_cog(TemplateCog(self))
        await self.add_cog(LockdownCog(self))
        await self.add_cog(TrackCog(self))
        # Only sync on first run or when explicitly needed — not every restart
        # To force a sync, set SYNC_COMMANDS=1 in your .env
        if os.getenv("SYNC_COMMANDS") == "1":
            await self.tree.sync()
        self.add_view(ActivityPublicView("default"))
        self.add_view(ActivityHRView("default"))

        await start_web_server(self)
        print_color("  ◄  Web server: localhost:5000", "cyan")

    async def close(self) -> None:
        await self.db.close()
        await super().close()

    async def is_whitelisted(self, guild: discord.Guild, user_id: int) -> bool:
        if user_id in self.owner_ids or user_id == guild.owner_id:
            return True
        return await self.db.is_whitelisted(guild.id, user_id)

    async def is_whitelist_admin(self, guild: discord.Guild, user_id: int) -> bool:
        if user_id in self.owner_ids or user_id == guild.owner_id:
            return True
        return await self.db.is_whitelist_admin(guild.id, user_id)

    async def on_ready(self) -> None:
        clear()
        # Loading bar
        bar_len = 30
        print_color("  ◄──── LOADING ────►", "cyan")
        print()
        for i in range(bar_len + 1):
            filled = "█" * i
            empty = "░" * (bar_len - i)
            pct = int((i / bar_len) * 100)
            print(f"\r  {filled}{empty}  {pct}%", end="", flush=True)
            await asyncio.sleep(0.04)
        print()
        print()
        await asyncio.sleep(0.3)
        clear()
        # ASCII art falls down
        for line in ASCII_ART.splitlines():
            print_color(line, "lightcyan")
            await asyncio.sleep(0.03)
        print()
        print_color("  ◄─────────────── SECURITY BOT - ONLINE ───────────────►", "cyan")
        print_color(f"  ◄  Bot:       {str(self.user):<37}►", "white")
        print_color(f"  ◄  ID:        {str(self.user.id):<37}►", "white")
        print_color(f"  ◄  Servers:   {str(len(self.guilds)):<37}►", "white")
        print_color(f"  ◄  Cogs:      {str(len(self.cogs)):<37}►", "white")
        print_color(f"  ◄  Commands:  {str(len(self.commands)):<37}►", "white")
        print_color("  ◄──────────────────────────────────────────────────────►", "cyan")
        print()
        print_color("  ◄──── DEBUG LOG ────►", "yellow")
        if not DEBUG_LOGS:
            for g in self.guilds:
                print_color(f"  ◄  {g.name} ({g.id})  ►", "dim")
        else:
            for log in DEBUG_LOGS:
                print_color(log, "dim")
        print()

        add_log("security", f"Bot started in {len(self.guilds)} server(s)", user=str(self.user), avatar=str(self.user.display_avatar.url) if self.user else None, log_type="security", details={"Servers": ", ".join(f"{g.name} (`{g.id}`)" for g in self.guilds), "Bot ID": str(self.user.id), "Cogs": str(len(self.cogs)), "Commands": str(len(self.commands))})
        add_log("bot_usage", f"Bot online — {len(self.commands)} commands loaded", user=str(self.user), avatar=str(self.user.display_avatar.url) if self.user else None, log_type="command")


bot = SecurityBot()


@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
    if guild.id != ALLOWED_GUILD_ID:
        debug_log(f"Left unauthorized server: {guild.name} ({guild.id})", "warn")
        await guild.leave()
        return
    debug_log(f"Joined server: {guild.name} ({guild.member_count} members)", "info")
    debug_log(f"  Owner: {guild.owner} ({guild.owner_id})", "info")


@bot.event
async def on_guild_remove(guild: discord.Guild) -> None:
    debug_log(f"Left server: {guild.name} ({guild.id}) — triggered by Discord gateway", "warn")


@bot.event
async def on_command(ctx: commands.Context) -> None:
    if ctx.guild:
        debug_log(f"{ctx.author} used '{ctx.message.content[:50]}' in #{ctx.channel}", "info")


@bot.event
async def on_guild_update(before: discord.Guild, after: discord.Guild) -> None:
    if before.name != after.name:
        debug_log(f"Server renamed: {before.name} -> {after.name}", "sus")
    if before.owner_id != after.owner_id:
        debug_log(f"Owner changed in {after.name}!", "sus")


@bot.check
async def whitelist_only(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        return ctx.author.id in bot.owner_ids
    return await bot.is_whitelisted(ctx.guild, ctx.author.id)


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    error = getattr(error, "original", error)
    if ctx.command and ctx.command.name in ("exterminate", "unexterminate"):
        return
    if isinstance(error, commands.CheckFailure):
        return  # silently ignore — no response
    if isinstance(error, commands.MissingRequiredArgument):
        if ctx.guild:  # only reply in servers
            await ctx.reply(f"Missing argument: `{error.param.name}`", mention_author=False)
        return
    if isinstance(error, commands.BadArgument):
        if ctx.guild:
            await ctx.reply("I could not parse that argument.", mention_author=False)
        return
    if isinstance(error, commands.CommandNotFound):
        return
    if ctx.guild:
        await ctx.reply(f"Command failed: `{type(error).__name__}: {error}`", mention_author=False)
    raise error


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is missing. Copy .env.example to .env and fill it in.")
    bot.run(token)
