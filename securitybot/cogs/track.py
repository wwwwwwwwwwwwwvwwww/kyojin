from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import discord
from discord.ext import commands

BABY_BLUE = 0xA8D8EA
POLL_INTERVAL = 10  # seconds between batched presence checks

PRESENCE_OFFLINE  = 0
PRESENCE_WEBSITE  = 1
PRESENCE_INGAME   = 2
PRESENCE_INSTUDIO = 3


# ── Roblox API ────────────────────────────────────────────────────────────────

async def _get(session: aiohttp.ClientSession, url: str, **kwargs) -> Any:
    try:
        async with session.get(url, **kwargs) as r:
            return await r.json() if r.status == 200 else None
    except Exception:
        return None


async def _post(session: aiohttp.ClientSession, url: str, json: dict) -> Any:
    try:
        async with session.post(url, json=json) as r:
            return await r.json() if r.status == 200 else None
    except Exception:
        return None


async def resolve_username(session: aiohttp.ClientSession, username: str) -> dict | None:
    data = await _post(session, "https://users.roblox.com/v1/usernames/users",
                       json={"usernames": [username], "excludeBannedUsers": False})
    if data and data.get("data"):
        u = data["data"][0]
        return {"id": u["id"], "name": u["name"], "displayName": u.get("displayName", u["name"])}
    return None


async def get_presence_batch(session: aiohttp.ClientSession, user_ids: list[int]) -> dict[int, dict]:
    data = await _post(session, "https://presence.roblox.com/v1/presence/users",
                       json={"userIds": user_ids})
    result: dict[int, dict] = {}
    if data and data.get("userPresences"):
        for p in data["userPresences"]:
            result[p["userId"]] = p
    return result


async def get_game_name(session: aiohttp.ClientSession, universe_id: int) -> str:
    data = await _get(session, f"https://games.roblox.com/v1/games?universeIds={universe_id}")
    if data and data.get("data"):
        return data["data"][0].get("name", "Unknown Game")
    return "Unknown Game"


async def get_avatar_url(session: aiohttp.ClientSession, user_id: int) -> str | None:
    data = await _get(session,
        "https://thumbnails.roblox.com/v1/users/avatar-headshot",
        params={"userIds": user_id, "size": "150x150", "format": "Png", "isCircular": "false"})
    if data and data.get("data"):
        return data["data"][0].get("imageUrl")
    return None


# ── Tracked user ──────────────────────────────────────────────────────────────

class TrackedUser:
    def __init__(self, roblox_id: int, username: str, display_name: str,
                 dm_user: discord.User, avatar_url: str | None) -> None:
        self.roblox_id = roblox_id
        self.username = username
        self.display_name = display_name
        self.dm_user = dm_user          # always DM this user
        self.avatar_url = avatar_url
        self.last_presence_type: int | None = None
        self.last_universe_id: int | None = None
        self.last_game_name: str | None = None

    def _build_view(self, detail_line: str, universe_id: int | None = None) -> discord.ui.LayoutView:
        view = discord.ui.LayoutView(timeout=None)
        container = discord.ui.Container(accent_color=BABY_BLUE)

        container.add_item(discord.ui.TextDisplay("-# rawr - tracking"))
        container.add_item(discord.ui.Separator())

        if self.avatar_url:
            thumb = discord.ui.Thumbnail(media=discord.UnfurledMediaItem(url=self.avatar_url))
            section = discord.ui.Section(accessory=thumb)
            section.add_item(discord.ui.TextDisplay(detail_line))
            container.add_item(section)
        else:
            container.add_item(discord.ui.TextDisplay(detail_line))

        container.add_item(discord.ui.Separator())

        btn_row = discord.ui.ActionRow()
        profile_url = f"https://www.roblox.com/users/{self.roblox_id}/profile"
        btn_row.add_item(discord.ui.Button(label="v", style=discord.ButtonStyle.secondary, url=profile_url))
        if universe_id:
            join_url = f"https://www.roblox.com/games/{universe_id}"
            btn_row.add_item(discord.ui.Button(label="j", style=discord.ButtonStyle.primary, url=join_url))
        container.add_item(btn_row)

        view.add_item(container)
        return view

    async def post(self, detail_line: str, universe_id: int | None = None) -> None:
        try:
            view = self._build_view(detail_line, universe_id)
            await self.dm_user.send(view=view)
        except discord.HTTPException:
            pass

    async def update(self, session: aiohttp.ClientSession, presence: dict | None = None) -> None:
        if presence is None:
            presences = await get_presence_batch(session, [self.roblox_id])
            presence = presences.get(self.roblox_id)
        if presence is None:
            return

        ptype = presence.get("userPresenceType", PRESENCE_OFFLINE)
        universe_id = presence.get("universeId")
        game_name: str | None = None
        if ptype == PRESENCE_INGAME and universe_id:
            game_name = await get_game_name(session, universe_id)

        if ptype == self.last_presence_type and universe_id == self.last_universe_id:
            return

        n = f"[{self.display_name}](https://www.roblox.com/users/{self.roblox_id}/profile)"

        if ptype == PRESENCE_OFFLINE and self.last_presence_type not in (None, PRESENCE_OFFLINE):
            await self.post(f"{n} is now offline")
        elif ptype == PRESENCE_WEBSITE and self.last_presence_type != PRESENCE_WEBSITE:
            await self.post(f"{n} is browsing the Roblox website.")
        elif ptype == PRESENCE_INGAME and self.last_presence_type != PRESENCE_INGAME:
            await self.post(f"{n} just joined {game_name}", universe_id=universe_id)
        elif ptype == PRESENCE_INGAME and self.last_presence_type == PRESENCE_INGAME and universe_id != self.last_universe_id:
            await self.post(f"{n} left **{self.last_game_name}** → **{game_name}**", universe_id=universe_id)
        elif ptype == PRESENCE_INSTUDIO and self.last_presence_type != PRESENCE_INSTUDIO:
            await self.post(f"{n} is now 🔧 in Roblox Studio")

        self.last_presence_type = ptype
        self.last_universe_id = universe_id
        self.last_game_name = game_name


# ── Modals ────────────────────────────────────────────────────────────────────

class AddUserModal(discord.ui.Modal, title="Track User"):
    username = discord.ui.TextInput(label="Roblox username", placeholder="e.g. Builderman", max_length=50)
    panel_view: "TrackView"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        cog: TrackCog = interaction.client.get_cog("TrackCog")
        username = self.username.value.strip()

        user_data = await resolve_username(cog._session, username)
        if not user_data:
            await interaction.followup.send(f"Could not find **{username}** on Roblox.", ephemeral=True)
            return

        guild_id = self.panel_view.guild_id  # always reliable
        key = (guild_id, user_data["id"])
        if key in cog._tracked:
            await interaction.followup.send(f"**{user_data['name']}** is already being tracked.", ephemeral=True)
            return

        dm_user = interaction.user
        avatar_url = await get_avatar_url(cog._session, user_data["id"])
        tracked = TrackedUser(user_data["id"], user_data["name"], user_data["displayName"], dm_user, avatar_url)

        presences = await get_presence_batch(cog._session, [user_data["id"]])
        presence = presences.get(user_data["id"])
        if presence:
            tracked.last_presence_type = presence.get("userPresenceType", PRESENCE_OFFLINE)
            tracked.last_universe_id = presence.get("universeId")
            if tracked.last_presence_type == PRESENCE_INGAME and tracked.last_universe_id:
                tracked.last_game_name = await get_game_name(cog._session, tracked.last_universe_id)

        cog._tracked[key] = tracked

        await interaction.client.db.add_tracked_user(
            guild_id, interaction.user.id, user_data["id"],
            user_data["name"], user_data["displayName"], avatar_url,
        )

        v = self.panel_view
        if v.guild_id == 0:
            v.tracked_keys = [k for k, t in cog._tracked.items() if t.dm_user.id == interaction.user.id]
        else:
            v.tracked_keys = [k for k in cog._tracked if k[0] == guild_id]
        v.rebuild()
        await interaction.message.edit(view=v)


class RemoveUserModal(discord.ui.Modal, title="Remove User"):
    username = discord.ui.TextInput(label="Roblox username", placeholder="e.g. Builderman", max_length=50)
    panel_view: "TrackView"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        cog: TrackCog = interaction.client.get_cog("TrackCog")
        username = self.username.value.strip()

        user_data = await resolve_username(cog._session, username)
        if not user_data:
            await interaction.followup.send(f"Could not find **{username}** on Roblox.", ephemeral=True)
            return

        guild_id = self.panel_view.guild_id  # always reliable
        key = (guild_id, user_data["id"])
        if key not in cog._tracked:
            await interaction.followup.send(f"**{user_data['name']}** is not being tracked.", ephemeral=True)
            return

        del cog._tracked[key]
        await interaction.client.db.remove_tracked_user(guild_id, user_data["id"])

        v = self.panel_view
        if v.guild_id == 0:
            v.tracked_keys = [k for k, t in cog._tracked.items() if t.dm_user.id == interaction.user.id]
        else:
            v.tracked_keys = [k for k in cog._tracked if k[0] == guild_id]
        v.rebuild()
        await interaction.message.edit(view=v)


# ── Panel view ────────────────────────────────────────────────────────────────

class TrackView(discord.ui.LayoutView):
    def __init__(self, ctx_user_id: int, guild_id: int, cog: "TrackCog") -> None:
        super().__init__(timeout=None)
        self.ctx_user_id = ctx_user_id
        self.guild_id = guild_id
        self.cog = cog
        # In DM context (guild_id=0) show all users tracked by this discord user
        # In server context show all tracked in that guild
        if guild_id == 0:
            self.tracked_keys: list[tuple[int, int]] = [
                k for k, t in cog._tracked.items() if t.dm_user.id == ctx_user_id
            ]
        else:
            self.tracked_keys = [k for k in cog._tracked if k[0] == guild_id]
        self.rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx_user_id:
            await interaction.response.send_message("Only the panel opener can use this.", ephemeral=True)
            return False
        return True

    def rebuild(self) -> None:
        self.clear_items()
        container = discord.ui.Container(accent_color=BABY_BLUE)

        count = len(self.tracked_keys)
        container.add_item(discord.ui.TextDisplay(f"**Tracking ({count})**"))

        if self.tracked_keys:
            container.add_item(discord.ui.Separator())
            for idx, key in enumerate(self.tracked_keys):
                tracked = self.cog._tracked.get(key)
                if not tracked:
                    continue
                text = (
                    f"[{tracked.display_name}](https://www.roblox.com/users/{tracked.roblox_id}/profile) "
                    f"@{tracked.username}\n"
                    f"`{tracked.roblox_id}`"
                )
                if tracked.avatar_url:
                    try:
                        thumb = discord.ui.Thumbnail(media=discord.UnfurledMediaItem(url=tracked.avatar_url))
                        section = discord.ui.Section(accessory=thumb)
                        section.add_item(discord.ui.TextDisplay(text))
                        container.add_item(section)
                    except Exception:
                        container.add_item(discord.ui.TextDisplay(text))
                else:
                    container.add_item(discord.ui.TextDisplay(text))

                if idx < len(self.tracked_keys) - 1:
                    container.add_item(discord.ui.Separator())
        else:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay("-# Press **add** to start tracking someone."))

        container.add_item(discord.ui.Separator())

        btn_row = discord.ui.ActionRow()
        add_btn = discord.ui.Button(label="add", style=discord.ButtonStyle.primary)
        remove_btn = discord.ui.Button(label="remove", style=discord.ButtonStyle.secondary)

        async def on_add(interaction: discord.Interaction) -> None:
            modal = AddUserModal()
            modal.panel_view = self
            await interaction.response.send_modal(modal)

        async def on_remove(interaction: discord.Interaction) -> None:
            modal = RemoveUserModal()
            modal.panel_view = self
            await interaction.response.send_modal(modal)

        add_btn.callback = on_add
        remove_btn.callback = on_remove
        btn_row.add_item(add_btn)
        btn_row.add_item(remove_btn)
        container.add_item(btn_row)

        self.add_item(container)


# ── Cog ───────────────────────────────────────────────────────────────────────

class TrackCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # key: (guild_id, roblox_id)
        self._tracked: dict[tuple[int, int], TrackedUser] = {}
        self._session: aiohttp.ClientSession | None = None
        self._poll_task: asyncio.Task | None = None

    async def cog_load(self) -> None:
        self._session = aiohttp.ClientSession(headers={"User-Agent": "SecurityBot/1.0"})
        self._poll_task = self.bot.loop.create_task(self._start())

    async def cog_unload(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
        if self._session:
            await self._session.close()

    async def _start(self) -> None:
        await self.bot.wait_until_ready()
        await self._restore_from_db()
        await self._poll_loop()

    async def _restore_from_db(self) -> None:
        """Re-load all tracked users from DB after a restart."""
        for guild in self.bot.guilds:
            rows = await self.bot.db.list_tracked_users(guild.id)
            for row in rows:
                discord_user = self.bot.get_user(row["discord_user_id"])
                if discord_user is None:
                    try:
                        discord_user = await self.bot.fetch_user(row["discord_user_id"])
                    except Exception:
                        continue
                key = (guild.id, row["roblox_id"])
                tracked = TrackedUser(
                    row["roblox_id"], row["roblox_username"], row["roblox_display_name"],
                    discord_user, row["avatar_url"],
                )
                self._tracked[key] = tracked

    async def _poll_loop(self) -> None:
        while not self.bot.is_closed():
            users = list(self._tracked.values())
            if users:
                # Single batch presence request for all users
                user_ids = [t.roblox_id for t in users]
                try:
                    presence_map = await get_presence_batch(self._session, user_ids)
                except Exception:
                    presence_map = {}

                await asyncio.gather(
                    *[self._safe_update(t, presence_map.get(t.roblox_id)) for t in users],
                    return_exceptions=True,
                )
            await asyncio.sleep(POLL_INTERVAL)

    async def _safe_update(self, tracked: TrackedUser, presence: dict | None) -> None:
        try:
            await tracked.update(self._session, presence)
        except Exception:
            pass

    @discord.app_commands.command(name="track", description="Track a Roblox user")
    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def track(self, interaction: discord.Interaction) -> None:
        is_owner = interaction.user.id in self.bot.owner_ids
        guild_id = interaction.guild.id if interaction.guild else 0

        if not is_owner:
            is_legacy = await self.bot.db.is_whitelist_admin(guild_id, interaction.user.id) if guild_id else False
            if not is_legacy:
                await interaction.response.send_message("i dont listen to you", ephemeral=True)
                return

        view = TrackView(interaction.user.id, guild_id, self)
        await interaction.response.send_message(view=view)

