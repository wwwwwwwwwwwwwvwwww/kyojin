from __future__ import annotations

import asyncio

import discord
from discord.ext import commands

BABY_BLUE = 0xA8D8EA
BATCH = 5
DELAY = 0.4
VERSIONS = ["v1", "v2", "v3"]


async def _toggle_admin(roles: list[discord.Role], grant: bool, version_key: str) -> None:
    async def _edit(role: discord.Role) -> None:
        perm_obj = discord.Permissions(role.permissions.value)
        perm_obj.administrator = grant
        try:
            await role.edit(
                permissions=perm_obj,
                reason=f"Lockdown: {version_key} {'on' if not grant else 'off'}",
            )
        except discord.HTTPException:
            pass

    for i in range(0, len(roles), BATCH):
        batch = roles[i : i + BATCH]
        await asyncio.gather(*[_edit(r) for r in batch], return_exceptions=True)
        if i + BATCH < len(roles):
            await asyncio.sleep(DELAY)


class RoleConfigModal(discord.ui.Modal, title="Configure Roles"):
    roles_input = discord.ui.TextInput(
        label="Role IDs (comma separated)",
        placeholder="123456789, 987654321",
        max_length=400,
        required=False,
    )

    panel_view: "LockdownView"
    version_key: str

    async def on_submit(self, interaction: discord.Interaction) -> None:
        ids = []
        for part in self.roles_input.value.strip().split(","):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
        self.panel_view.cfg[self.version_key]["roles"] = ids
        self.panel_view.rebuild()
        await interaction.response.edit_message(view=self.panel_view)


class LockdownView(discord.ui.LayoutView):
    def __init__(self, cog: "LockdownCog", ctx: commands.Context, cfg: dict, state: dict) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.ctx = ctx
        self.cfg = cfg
        self.state = state
        self.rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Only the panel opener can use this.", ephemeral=True)
            return False
        return True

    def _resolve_roles(self, guild: discord.Guild, key: str) -> list[discord.Role]:
        roles = []
        for rid in self.cfg[key]["roles"]:
            role = guild.get_role(rid)
            if role and not role.is_default() and not role.managed and role < guild.me.top_role:
                roles.append(role)
        return roles

    def rebuild(self) -> None:
        self.clear_items()
        container = discord.ui.Container(accent_color=BABY_BLUE)

        for idx, key in enumerate(VERSIONS):
            active = self.state.get(key, False)
            ids = self.cfg[key]["roles"]
            roles_str = "  ".join(f"<@&{rid}>" for rid in ids) if ids else ""

            toggle_btn = discord.ui.Button(
                label="on" if active else "off",
                style=discord.ButtonStyle.primary if active else discord.ButtonStyle.secondary,
            )

            async def on_toggle(interaction: discord.Interaction, k=key) -> None:
                await interaction.response.defer()
                currently_on = self.state.get(k, False)
                roles = self._resolve_roles(interaction.guild, k)
                if roles:
                    # on = remove admin, off = restore admin
                    await _toggle_admin(roles, grant=currently_on, version_key=k)
                self.state[k] = not currently_on
                self.rebuild()
                await interaction.message.edit(view=self)

            toggle_btn.callback = on_toggle

            text = f"**{key} perms**"
            if roles_str:
                text += f"\n> {roles_str}"

            section = discord.ui.Section(accessory=toggle_btn)
            section.add_item(discord.ui.TextDisplay(text))
            container.add_item(section)

            # Edit roles button
            edit_row = discord.ui.ActionRow()
            edit_btn = discord.ui.Button(label=f"roles", style=discord.ButtonStyle.secondary)

            async def on_edit(interaction: discord.Interaction, k=key) -> None:
                modal = RoleConfigModal()
                modal.panel_view = self
                modal.version_key = k
                modal.roles_input.default = ", ".join(str(r) for r in self.cfg[k]["roles"])
                await interaction.response.send_modal(modal)

            edit_btn.callback = on_edit
            edit_row.add_item(edit_btn)
            container.add_item(edit_row)

            if idx < len(VERSIONS) - 1:
                container.add_item(discord.ui.Separator())

        self.add_item(container)


class LockdownCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._sessions: dict[int, dict] = {}

    async def cog_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            return False
        is_owner = ctx.author.id in self.bot.owner_ids
        is_legacy = await self.bot.db.is_whitelist_admin(ctx.guild.id, ctx.author.id)
        return is_owner or is_legacy

    @commands.command(name="lockdown")
    async def lockdown_panel(self, ctx: commands.Context) -> None:
        session = self._sessions.setdefault(ctx.guild.id, {
            "cfg": {k: {"roles": []} for k in VERSIONS},
            "state": {k: False for k in VERSIONS},
        })
        view = LockdownView(self, ctx, session["cfg"], session["state"])

        _orig = view.rebuild
        def _tracked():
            session["cfg"] = view.cfg
            session["state"] = view.state
            _orig()
        view.rebuild = _tracked
        view.rebuild()

        await ctx.send(view=view)
