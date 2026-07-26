from __future__ import annotations

import json
import os

import discord
from discord.ext import commands

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "activity_data.json")

# Change this to your HR role ID
HR_ROLE_ID = 1529946834196496615


def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}


def save_data(data: dict) -> None:
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


class ActivityPublicView(discord.ui.View):
    def __init__(self, activity_id: str):
        super().__init__(timeout=None)
        self.activity_id = activity_id
        data = load_data()
        entry = data.get(activity_id, {"count": 0, "pressed": []})
        self.count = entry["count"]
        self.pressed_users = set(entry["pressed"])
        self.count_btn.label = str(self.count)

    def save(self):
        data = load_data()
        data[self.activity_id] = {
            "count": self.count,
            "pressed": list(self.pressed_users),
        }
        save_data(data)

    def load_from_message(self, message):
        embed = message.embeds[0] if message.embeds else None
        if embed and embed.description:
            import re
            match = re.search(r"Activity \*\*(.+?)\*\*", embed.description)
            if match:
                self.activity_id = match.group(1)
                data = load_data()
                entry = data.get(self.activity_id, {"count": 0, "pressed": []})
                self.count = entry["count"]
                self.pressed_users = set(entry["pressed"])
                self.count_btn.label = str(self.count)

    @discord.ui.button(label="0", style=discord.ButtonStyle.secondary, custom_id="activity_public_count")
    async def count_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.load_from_message(interaction.message)
        if interaction.user.id in self.pressed_users:
            await interaction.response.send_message("You already pressed it.", ephemeral=True)
            return
        self.count += 1
        self.pressed_users.add(interaction.user.id)
        button.label = str(self.count)
        self.save()
        await interaction.response.edit_message(view=self)


class ActivityHRView(discord.ui.View):
    def __init__(self, activity_id: str):
        super().__init__(timeout=None)
        self.activity_id = activity_id
        data = load_data()
        entry = data.get(activity_id, {"count": 0, "pressed": []})
        self.count = entry["count"]
        self.pressed_users = set(entry["pressed"])
        self.count_btn.label = str(self.count)

    def save(self):
        data = load_data()
        data[self.activity_id] = {
            "count": self.count,
            "pressed": list(self.pressed_users),
        }
        save_data(data)

    def load_from_message(self, message):
        embed = message.embeds[0] if message.embeds else None
        if embed and embed.description:
            import re
            match = re.search(r"HR Activity \*\*(.+?)\*\*", embed.description)
            if match:
                self.activity_id = match.group(1)
                data = load_data()
                entry = data.get(self.activity_id, {"count": 0, "pressed": []})
                self.count = entry["count"]
                self.pressed_users = set(entry["pressed"])
                self.count_btn.label = str(self.count)

    @discord.ui.button(label="0", style=discord.ButtonStyle.secondary, custom_id="activity_hr_count")
    async def count_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.load_from_message(interaction.message)
        if interaction.user.id in self.pressed_users:
            await interaction.response.send_message("You already pressed it.", ephemeral=True)
            return
        self.count += 1
        self.pressed_users.add(interaction.user.id)
        button.label = str(self.count)
        self.save()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="list", style=discord.ButtonStyle.secondary, custom_id="activity_hr_list")
    async def list_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.load_from_message(interaction.message)
        is_owner = interaction.user.id in interaction.client.owner_ids
        is_legacy = await interaction.client.db.is_whitelist_admin(interaction.guild_id, interaction.user.id)
        if not is_owner and not is_legacy:
            await interaction.response.send_message("i dont listen to you", ephemeral=True)
            return
        role = interaction.guild.get_role(HR_ROLE_ID)
        if not role:
            await interaction.response.send_message("Role not found.", ephemeral=True)
            return
        not_pressed = [m for m in role.members if m.id not in self.pressed_users]
        if not not_pressed:
            desc = "Everyone with the role has pressed it."
        else:
            desc = "\n".join(f"> {m.mention} (`{m.id}`)" for m in not_pressed)
        view = StripAllLayoutView(not_pressed, HR_ROLE_ID)
        await interaction.response.send_message(view=view, ephemeral=True)


class StripAllLayoutView(discord.ui.LayoutView):
    def __init__(self, members: list, role_id: int):
        super().__init__(timeout=60)
        self.members = members
        self.role_id = role_id

        container = discord.ui.Container(accent_color=0xA8D8EA)
        if not members:
            desc = "Everyone with the role has pressed it."
        else:
            desc = "\n".join(f"> {m.mention} (`{m.id}`)" for m in members)
        container.add_item(discord.ui.TextDisplay(f"**Haven't Pressed**\n{desc}"))

        row = discord.ui.ActionRow()
        strip_btn = discord.ui.Button(label="strip all", style=discord.ButtonStyle.secondary)
        async def on_strip(i):
            is_owner = i.user.id in i.client.owner_ids
            is_legacy = await i.client.db.is_whitelist_admin(i.guild_id, i.user.id)
            if not is_owner and not is_legacy:
                await i.response.send_message("i dont listen to you", ephemeral=True)
                return
            role = i.guild.get_role(self.role_id)
            stripped = []
            for member in self.members:
                try:
                    await member.remove_roles(role, reason="Activity check - no reaction")
                    stripped.append(member)
                except discord.HTTPException:
                    pass
            if stripped:
                desc = "\n".join(f"> {m.mention} (`{m.id}`)" for m in stripped)
            else:
                desc = "No one was stripped."
            await i.response.send_message(content=f"**Stripped**\n{desc}", ephemeral=True)
        strip_btn.callback = on_strip
        row.add_item(strip_btn)
        container.add_item(row)
        self.add_item(container)


class ActivityCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        return True

    @commands.group(name="activity", invoke_without_command=True)
    async def activity(self, ctx: commands.Context) -> None:
        return

    @activity.command(name="public")
    async def activity_public(self, ctx: commands.Context, activity_id: str = None) -> None:
        if not activity_id:
            return
        embed = discord.Embed(description=f"Activity **{activity_id}** — react to boost the activity count.", color=0xA8D8EA)
        await ctx.send(embed=embed, view=ActivityPublicView(activity_id))

    @activity.command(name="hr")
    async def activity_hr(self, ctx: commands.Context, activity_id: str = None) -> None:
        if not activity_id:
            return
        embed = discord.Embed(description=f"HR Activity **{activity_id}** — if you don't react you're role may be taken.", color=0xA8D8EA)
        await ctx.send(embed=embed, view=ActivityHRView(activity_id))

    @activity.command(name="delete")
    async def activity_delete(self, ctx: commands.Context, activity_type: str = None, activity_id: str = None) -> None:
        is_owner = ctx.author.id in self.bot.owner_ids
        is_legacy = await self.bot.db.is_whitelist_admin(ctx.guild.id, ctx.author.id)
        if not is_owner and not is_legacy:
            await ctx.send("i dont listen to you")
            return
        if not activity_type or not activity_id:
            return
        if activity_type not in ("public", "hr"):
            return
        data = load_data()
        if activity_id in data:
            del data[activity_id]
            save_data(data)
        await ctx.send("affirmative")
