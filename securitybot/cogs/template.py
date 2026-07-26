from __future__ import annotations

import asyncio

import discord
from discord.ext import commands

BABY_BLUE = 0xA8D8EA
SEC_ICON = discord.PartialEmoji(name="Security_Icon", id=1529617120210714624)
COPY_EMOJI = discord.PartialEmoji(name="copy", id=1529945864670412943)
PASTE_EMOJI = discord.PartialEmoji(name="paste", id=1529945742196740106)

# Concurrent batch size — how many deletes/creates fire at once before a short pause
BATCH_SIZE = 6
BATCH_PAUSE = 0.4  # seconds between batches


def _bool(value: str) -> bool:
    return value.strip().lower() in ("true", "yes", "1", "on")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _serialise_overwrites(overwrites: dict) -> list[dict]:
    result = []
    for target, overwrite in overwrites.items():
        allow, deny = overwrite.pair()
        result.append({
            "id": target.id,
            "type": "role" if isinstance(target, discord.Role) else "member",
            "allow": allow.value,
            "deny": deny.value,
        })
    return result


def _deserialise_overwrites(guild: discord.Guild, data: list[dict]) -> dict:
    overwrites: dict = {}
    for entry in data:
        target = (
            guild.get_role(entry["id"])
            if entry["type"] == "role"
            else guild.get_member(entry["id"])
        )
        if target is None:
            continue
        overwrite = discord.PermissionOverwrite.from_pair(
            discord.Permissions(entry["allow"]),
            discord.Permissions(entry["deny"]),
        )
        overwrites[target] = overwrite
    return overwrites


def _serialise_channel(ch: discord.abc.GuildChannel) -> dict:
    data: dict = {
        "name": ch.name,
        "position": ch.position,
        "overwrites": _serialise_overwrites(ch.overwrites),
    }
    if isinstance(ch, discord.TextChannel):
        data["type"] = "text"
        data["topic"] = ch.topic or ""
        data["slowmode"] = ch.slowmode_delay
        data["nsfw"] = ch.is_nsfw()
    elif isinstance(ch, discord.VoiceChannel):
        data["type"] = "voice"
        data["bitrate"] = ch.bitrate
        data["user_limit"] = ch.user_limit
    elif isinstance(ch, discord.ForumChannel):
        data["type"] = "forum"
        data["topic"] = ch.topic or ""
    elif isinstance(ch, discord.StageChannel):
        data["type"] = "stage"
        data["topic"] = getattr(ch, "topic", "") or ""
    else:
        data["type"] = "text"
    return data


async def _delete_batch(items: list, reason: str) -> None:
    """Delete a list of roles or channels in concurrent batches."""
    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i : i + BATCH_SIZE]
        await asyncio.gather(
            *[_safe_delete(item, reason) for item in batch],
            return_exceptions=True,
        )
        if i + BATCH_SIZE < len(items):
            await asyncio.sleep(BATCH_PAUSE)


async def _safe_delete(item: discord.abc.GuildChannel | discord.Role, reason: str) -> None:
    try:
        await item.delete(reason=reason)
    except discord.HTTPException:
        pass


async def _create_channel(
    guild: discord.Guild,
    data: dict,
    *,
    category: discord.CategoryChannel | None = None,
    reason: str = "",
) -> None:
    overwrites = _deserialise_overwrites(guild, data.get("overwrites", []))
    kwargs: dict = {"name": data["name"], "overwrites": overwrites, "reason": reason}
    if category:
        kwargs["category"] = category

    ch_type = data.get("type", "text")
    try:
        if ch_type == "voice":
            await guild.create_voice_channel(
                bitrate=data.get("bitrate", 64000),
                user_limit=data.get("user_limit", 0),
                **kwargs,
            )
        elif ch_type == "forum":
            await guild.create_forum(topic=data.get("topic", ""), **kwargs)
        elif ch_type == "stage":
            await guild.create_stage_channel(**kwargs)
        else:
            await guild.create_text_channel(
                topic=data.get("topic", ""),
                slowmode_delay=data.get("slowmode", 0),
                nsfw=data.get("nsfw", False),
                **kwargs,
            )
    except discord.HTTPException:
        pass


def _build_text(templates: list[str]) -> str:
    if templates:
        lines = [f"▶ `{t}`" for t in templates]
        header = f"**{len(templates)} Saved Template{'s' if len(templates) != 1 else ''}**"
        return f"{header}\n" + "\n".join(lines)
    return "**No Templates**\nUse **Copy** to save your first template."


# ── Modals ────────────────────────────────────────────────────────────────────

class DeleteModal(discord.ui.Modal, title="Delete Template"):
    name = discord.ui.TextInput(
        label="Template name to delete",
        placeholder="e.g. main-server-backup",
        max_length=50,
    )

    panel_view: "TemplateView"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        name = self.name.value.strip()
        template = await interaction.client.db.get_template(interaction.guild.id, name)
        if template is None:
            await interaction.response.send_message(
                f"No template named **{name}** found.", ephemeral=True
            )
            return

        await interaction.client.db.delete_template(interaction.guild.id, name)

        templates = await interaction.client.db.list_templates(interaction.guild.id)
        view = self.panel_view
        view.templates = templates
        view.rebuild()
        await interaction.response.edit_message(view=view)


class CopyModal(discord.ui.Modal, title="Copy Template"):
    name = discord.ui.TextInput(
        label="Template name",
        placeholder="e.g. main-server-backup",
        max_length=50,
    )
    save_channels = discord.ui.TextInput(
        label="Save channels? (true / false)",
        placeholder="true",
        max_length=5,
    )
    save_roles = discord.ui.TextInput(
        label="Save roles? (true / false)",
        placeholder="true",
        max_length=5,
    )

    panel_view: "TemplateView"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        name = self.name.value.strip()
        do_channels = _bool(self.save_channels.value)
        do_roles = _bool(self.save_roles.value)

        if not do_channels and not do_roles:
            await interaction.response.send_message(
                "You must save at least channels or roles.", ephemeral=True
            )
            return

        # ── Snapshot channels ──────────────────────────────────────────────
        channels_data: list[dict] = []
        if do_channels:
            for category in sorted(guild.categories, key=lambda c: c.position):
                channels_data.append({
                    "type": "category",
                    "name": category.name,
                    "position": category.position,
                    "overwrites": _serialise_overwrites(category.overwrites),
                    "children": [
                        _serialise_channel(ch)
                        for ch in sorted(category.channels, key=lambda c: c.position)
                    ],
                })
            for ch in sorted(guild.channels, key=lambda c: c.position):
                if ch.category is None and not isinstance(ch, discord.CategoryChannel):
                    channels_data.append(_serialise_channel(ch))

        # ── Snapshot roles ─────────────────────────────────────────────────
        roles_data: list[dict] = []
        if do_roles:
            for role in guild.roles:
                if role.is_default() or role.managed:
                    continue
                roles_data.append({
                    "name": role.name,
                    "permissions": role.permissions.value,
                    "color": role.color.value,
                    "hoist": role.hoist,
                    "mentionable": role.mentionable,
                    "position": role.position,
                })

        # Save immediately to DB
        await interaction.client.db.save_template(
            guild.id, name, channels_data, roles_data, do_channels, do_roles
        )

        templates = await interaction.client.db.list_templates(guild.id)
        view = self.panel_view
        view.templates = templates
        view.rebuild()
        await interaction.response.edit_message(view=view)


class PasteModal(discord.ui.Modal, title="Paste Template"):
    name = discord.ui.TextInput(
        label="Template name",
        placeholder="e.g. main-server-backup",
        max_length=50,
    )
    paste_channels = discord.ui.TextInput(
        label="Paste channels? (true / false)",
        placeholder="true",
        max_length=5,
    )
    paste_roles = discord.ui.TextInput(
        label="Paste roles? (true / false)",
        placeholder="true",
        max_length=5,
    )

    panel_view: "TemplateView"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        name = self.name.value.strip()
        do_channels = _bool(self.paste_channels.value)
        do_roles = _bool(self.paste_roles.value)

        template = await interaction.client.db.get_template(guild.id, name)
        if template is None:
            await interaction.response.send_message(
                f"No template named **{name}** found.", ephemeral=True
            )
            return

        if not do_channels and not do_roles:
            await interaction.response.send_message(
                "You must paste at least channels or roles.", ephemeral=True
            )
            return

        # Defer before any destructive work — no DMs, just silent
        await interaction.response.defer()

        # ── Restore roles ──────────────────────────────────────────────────
        if do_roles and template["save_roles"]:
            deletable_roles = [
                r for r in guild.roles
                if not r.is_default() and not r.managed and r < guild.me.top_role
            ]
            await _delete_batch(deletable_roles, reason=f"Template paste: {name}")

            sorted_roles = sorted(template["roles"], key=lambda r: r["position"])
            for i in range(0, len(sorted_roles), BATCH_SIZE):
                batch = sorted_roles[i : i + BATCH_SIZE]
                await asyncio.gather(
                    *[
                        guild.create_role(
                            name=r["name"],
                            permissions=discord.Permissions(r["permissions"]),
                            color=discord.Color(r["color"]),
                            hoist=r["hoist"],
                            mentionable=r["mentionable"],
                            reason=f"Template paste: {name}",
                        )
                        for r in batch
                    ],
                    return_exceptions=True,
                )
                if i + BATCH_SIZE < len(sorted_roles):
                    await asyncio.sleep(BATCH_PAUSE)

        # ── Restore channels ───────────────────────────────────────────────
        if do_channels and template["save_channels"]:
            await _delete_batch(list(guild.channels), reason=f"Template paste: {name}")

            # Categories must be created sequentially (children depend on them)
            for entry in template["channels"]:
                if entry["type"] != "category":
                    continue
                overwrites = _deserialise_overwrites(guild, entry["overwrites"])
                try:
                    cat = await guild.create_category(
                        name=entry["name"],
                        overwrites=overwrites,
                        reason=f"Template paste: {name}",
                    )
                except discord.HTTPException:
                    cat = None

                if cat and entry.get("children"):
                    # Create children inside this category in batches
                    children = entry["children"]
                    for i in range(0, len(children), BATCH_SIZE):
                        batch = children[i : i + BATCH_SIZE]
                        await asyncio.gather(
                            *[_create_channel(guild, c, category=cat, reason=f"Template paste: {name}") for c in batch],
                            return_exceptions=True,
                        )
                        if i + BATCH_SIZE < len(children):
                            await asyncio.sleep(BATCH_PAUSE)

                await asyncio.sleep(BATCH_PAUSE)

            # Orphan channels (no category)
            orphans = [e for e in template["channels"] if e["type"] != "category"]
            for i in range(0, len(orphans), BATCH_SIZE):
                batch = orphans[i : i + BATCH_SIZE]
                await asyncio.gather(
                    *[_create_channel(guild, c, reason=f"Template paste: {name}") for c in batch],
                    return_exceptions=True,
                )
                if i + BATCH_SIZE < len(orphans):
                    await asyncio.sleep(BATCH_PAUSE)


# ── View ──────────────────────────────────────────────────────────────────────

class TemplateView(discord.ui.LayoutView):
    def __init__(self, cog: "TemplateCog", ctx: commands.Context, templates: list[str]) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.ctx = ctx
        self.templates = templates
        self.rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "Only the panel opener can use this.", ephemeral=True
            )
            return False
        return True

    def rebuild(self) -> None:
        self.clear_items()

        container = discord.ui.Container(accent_color=BABY_BLUE)
        container.add_item(discord.ui.TextDisplay(_build_text(self.templates)))

        action_row = discord.ui.ActionRow()

        copy_btn = discord.ui.Button(label="Copy", style=discord.ButtonStyle.primary, emoji=COPY_EMOJI)
        async def on_copy(interaction: discord.Interaction) -> None:
            modal = CopyModal()
            modal.panel_view = self
            await interaction.response.send_modal(modal)
        copy_btn.callback = on_copy

        paste_btn = discord.ui.Button(label="Paste", style=discord.ButtonStyle.primary, emoji=PASTE_EMOJI)
        async def on_paste(interaction: discord.Interaction) -> None:
            modal = PasteModal()
            modal.panel_view = self
            await interaction.response.send_modal(modal)
        paste_btn.callback = on_paste

        manage_btn = discord.ui.Button(label="m", style=discord.ButtonStyle.secondary)
        async def on_manage(interaction: discord.Interaction) -> None:
            modal = DeleteModal()
            modal.panel_view = self
            await interaction.response.send_modal(modal)
        manage_btn.callback = on_manage

        action_row.add_item(copy_btn)
        action_row.add_item(paste_btn)
        action_row.add_item(manage_btn)
        container.add_item(action_row)
        self.add_item(container)


# ── Cog ───────────────────────────────────────────────────────────────────────

class TemplateCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            return False
        # Legacy whitelist only (owners always pass)
        is_owner = ctx.author.id in self.bot.owner_ids
        is_legacy = await self.bot.db.is_whitelist_admin(ctx.guild.id, ctx.author.id)
        return is_owner or is_legacy

    @commands.command(name="template")
    async def template_panel(self, ctx: commands.Context) -> None:
        templates = await self.bot.db.list_templates(ctx.guild.id)
        view = TemplateView(self, ctx, templates)
        await ctx.send(view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TemplateCog(bot))
