from __future__ import annotations

import discord
from discord.ext import commands

from securitybot.utils import base_embed

LEFT_ARROW = discord.PartialEmoji(name="leftarrow", id=1529588948127453255)
RIGHT_ARROW = discord.PartialEmoji(name="rightarrow", id=1529588910894743562)


class HelpView(discord.ui.View):
    def __init__(self, cog: "HelpCog", prefix: str, author_id: int) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.prefix = prefix
        self.author_id = author_id
        self.index = 0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This help menu belongs to someone else.", ephemeral=True)
            return False
        return True

    @discord.ui.button(emoji=LEFT_ARROW, style=discord.ButtonStyle.primary)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.index = (self.index - 1) % len(self.cog.pages)
        await interaction.response.edit_message(embed=self.cog.make_page(self.prefix, self.index), view=self)

    @discord.ui.button(emoji=RIGHT_ARROW, style=discord.ButtonStyle.primary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.index = (self.index + 1) % len(self.cog.pages)
        await interaction.response.edit_message(embed=self.cog.make_page(self.prefix, self.index), view=self)


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.pages = [
            (
                "Security",
                [
                    "\u25b6 `{p}antinuke` - anti-nuke panel",
                    "\u25b6 `{p}verify [role_id]` - verification panel",
                    "\u25b6 `{p}lockdown` - server lockdown panel",
                    "\u25b6 `{p}lockrole` - lock/unlock access role position",
                    "\u25b6 `{p}accessrole @role` - set the access role",
                    "\u25b6 `{p}activity public` - public count activity",
                    "\u25b6 `{p}activity hr <role>` - role-based activity",
                ],
            ),
            (
                "Moderation",
                [
                    "\u25b6 `{p}exterminate <user|id> [reason]` - hard-ban + auto-reban",
                    "\u25b6 `{p}unexterminate <user|id>` - remove hard-ban",
                    "\u25b6 `{p}strip <user|id>` - remove admin roles",
                    "\u25b6 `{p}nuke` - clone and replace channel",
                    "\u25b6 `{p}restore [user_id]` - restore roles after rejoin",
                    "\u25b6 `{p}template` - server template panel",
                ],
            ),
            (
                "Roles",
                [
                    "\u25b6 `{p}pic <@user>` - give PIC role",
                    "\u25b6 `{p}vc <@user>` - give VC role",
                    "\u25b6 `{p}hr <@user>` - give HR role",
                    "\u25b6 `{p}clean` - toggle cleaning (deletes non-whitelisted messages)",
                ],
            ),
            (
                "Configuration",
                [
                    "\u25b6 `{p}whitelist` - whitelist panel (standard & legacy)",
                    "\u25b6 `{p}join` - set join channel",
                    "\u25b6 `{p}leave` - set leave channel",
                    "\u25b6 `{p}logging` - logging panel",
                    "\u25b6 `{p}verify [role_id]` - set verify role",
                    "\u25b6 `{p}avoid @role` - toggle avoided role",
                    "\u25b6 `{p}avoidlist` - list avoided roles",
                ],
            ),
        ]

    def make_page(self, prefix: str, index: int) -> discord.Embed:
        title, lines = self.pages[index]
        embed = base_embed(f"Help - {title}", "\n".join(line.format(p=prefix) for line in lines), color=0xA8D8EA)
        embed.set_footer(text=f"Page {index + 1}/{len(self.pages)}")
        return embed

    @commands.command(name="help")
    async def help_command(self, ctx: commands.Context) -> None:
        settings = await self.bot.db.get_settings(ctx.guild.id)
        view = HelpView(self, settings["prefix"], ctx.author.id)
        await ctx.send(embed=self.make_page(settings["prefix"], 0), view=view)
