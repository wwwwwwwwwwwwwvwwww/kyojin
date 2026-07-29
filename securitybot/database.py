from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any

import aiosqlite


DEFAULT_ANTINUKE = {
    "enabled": False,
    "window_seconds": 5,
    "events": {
        "ban": {"enabled": True, "threshold": 1, "punishment": "strip"},
        "kick": {"enabled": True, "threshold": 1, "punishment": "strip"},
        "role_delete": {"enabled": True, "threshold": 1, "punishment": "strip"},
        "channel_delete": {"enabled": True, "threshold": 1, "punishment": "strip"},
        "channel_create": {"enabled": True, "threshold": 1, "punishment": "strip"},
        "webhook_create": {"enabled": True, "threshold": 1, "punishment": "strip"},
        "mass_ping": {"enabled": True, "threshold": 1, "punishment": "strip"},
        "audit_change": {"enabled": True, "threshold": 1, "punishment": "strip"},
    },
    "massban_lockdown": {"enabled": False, "threshold": 5, "duration": 300},
    "whitelist": [],
    "ping_channel_whitelist": [],
}

DEFAULT_LOGGING = {
    "audit_change": False,
    "bot_commands": False,
    "antinuke": True,
    "moderation": True,
}


class Database:
    def __init__(self, db_path: str = "securitybot.db") -> None:
        self.db_path = db_path
        self.db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.db = await aiosqlite.connect(self.db_path)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")

    async def close(self) -> None:
        if self.db:
            await self.db.close()

    def encode_json(self, value: Any) -> str:
        return json.dumps(value)

    def decode_json(self, value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value)
        return value

    async def migrate(self) -> None:
        await self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                prefix TEXT NOT NULL DEFAULT ',',
                antinuke TEXT NOT NULL DEFAULT '{}',
                join_channel_id INTEGER,
                join_message TEXT NOT NULL DEFAULT 'Welcome {mention} to {server}!',
                leave_channel_id INTEGER,
                leave_message TEXT NOT NULL DEFAULT '{user} left {server}.',
                logging_channel_id INTEGER,
                verify_role_id INTEGER,
                logging_events TEXT NOT NULL DEFAULT '{}',
                join_gif TEXT NOT NULL DEFAULT 'https://i.imgur.com/a2rksjN.gif',
                leave_gif TEXT NOT NULL DEFAULT 'https://i.imgur.com/K7aaTLk.gif'
            );

            CREATE TABLE IF NOT EXISTS whitelist (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                added_by INTEGER NOT NULL,
                admin INTEGER NOT NULL DEFAULT 0,
                added_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS exterminations (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                reason TEXT,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS restore_snapshots (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role_ids TEXT NOT NULL,
                left_at TEXT NOT NULL,
                rejoined_at TEXT,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS lockdown_roles (
                guild_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                permissions INTEGER NOT NULL,
                locked_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (guild_id, role_id)
            );

            CREATE TABLE IF NOT EXISTS templates (
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                channels TEXT NOT NULL DEFAULT '[]',
                roles TEXT NOT NULL DEFAULT '[]',
                save_channels INTEGER NOT NULL DEFAULT 0,
                save_roles INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (guild_id, name)
            );

            CREATE TABLE IF NOT EXISTS blacklist (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                added_by INTEGER NOT NULL,
                added_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS tracked_users (
                guild_id INTEGER NOT NULL,
                discord_user_id INTEGER NOT NULL,
                roblox_id INTEGER NOT NULL,
                roblox_username TEXT NOT NULL,
                roblox_display_name TEXT NOT NULL,
                avatar_url TEXT,
                PRIMARY KEY (guild_id, roblox_id)
            );

            CREATE TABLE IF NOT EXISTS access_keys (
                user_id INTEGER PRIMARY KEY,
                access_key TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS login_approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                access_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                session_token TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS trusted_users (
                user_id INTEGER PRIMARY KEY,
                added_by INTEGER NOT NULL,
                added_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        # Ping protection table
        try:
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS ping_protection (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    pings_allowed INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await self.db.commit()
        except Exception:
            pass
        # Tung lock table
        try:
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS tung_lock (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, channel_id)
                )
            """)
            await self.db.commit()
        except Exception:
            pass
        try:
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS tung_whitelist (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, channel_id, user_id)
                )
            """)
            await self.db.commit()
        except Exception:
            pass
        # Migration: drop old tung_whitelist if it had wrong schema
        try:
            cursor = await self.db.execute("PRAGMA table_info(tung_whitelist)")
            cols = [row[1] for row in await cursor.fetchall()]
            if "channel_id" not in cols:
                await self.db.execute("DROP TABLE IF EXISTS tung_whitelist")
                await self.db.execute("""
                    CREATE TABLE IF NOT EXISTS tung_whitelist (
                        guild_id INTEGER NOT NULL,
                        channel_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        PRIMARY KEY (guild_id, channel_id, user_id)
                    )
                """)
                await self.db.commit()
        except Exception:
            pass
        try:
            await self.db.execute("ALTER TABLE whitelist ADD COLUMN admin INTEGER NOT NULL DEFAULT 0")
            await self.db.commit()
        except Exception:
            pass

        # tracked_users table — added later, safe to run on existing DBs
        try:
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS tracked_users (
                    guild_id INTEGER NOT NULL,
                    discord_user_id INTEGER NOT NULL,
                    roblox_id INTEGER NOT NULL,
                    roblox_username TEXT NOT NULL,
                    roblox_display_name TEXT NOT NULL,
                    avatar_url TEXT,
                    PRIMARY KEY (guild_id, roblox_id)
                )
            """)
            await self.db.commit()
        except Exception:
            pass

        # join/leave GIF columns
        try:
            await self.db.execute("ALTER TABLE guild_settings ADD COLUMN join_gif TEXT NOT NULL DEFAULT 'https://i.imgur.com/a2rksjN.gif'")
            await self.db.commit()
        except Exception:
            pass
        try:
            await self.db.execute("ALTER TABLE guild_settings ADD COLUMN leave_gif TEXT NOT NULL DEFAULT 'https://i.imgur.com/K7aaTLk.gif'")
            await self.db.commit()
        except Exception:
            pass

        # Add session_token column to login_approvals if missing
        try:
            await self.db.execute("ALTER TABLE login_approvals ADD COLUMN session_token TEXT")
            await self.db.commit()
        except Exception:
            pass

        # Ensure all events in antinuke config are dicts (not bare booleans)
        try:
            cursor = await self.db.execute("SELECT guild_id, antinuke FROM guild_settings")
            rows = await cursor.fetchall()
            for row in rows:
                raw = row["antinuke"]
                data = json.loads(raw) if isinstance(raw, str) else {}
                changed = False
                events = data.get("events", {})
                for ek, ev in events.items():
                    if ev is True or ev is False:
                        events[ek] = {"enabled": bool(ev), "threshold": 1, "punishment": "strip"}
                        changed = True
                if changed:
                    data["events"] = events
                    await self.db.execute(
                        "UPDATE guild_settings SET antinuke=? WHERE guild_id=?",
                        (json.dumps(data), row["guild_id"]),
                    )
            await self.db.commit()
        except Exception:
            pass

    async def ensure_guild(self, guild_id: int, *, commit: bool = True) -> None:
        await self.db.execute(
            """
            INSERT OR IGNORE INTO guild_settings (guild_id, antinuke, logging_events)
            VALUES (?, ?, ?)
            """,
            (guild_id, self.encode_json(DEFAULT_ANTINUKE), self.encode_json(DEFAULT_LOGGING)),
        )
        if commit:
            await self.db.commit()

    async def get_raw_json(self, guild_id: int, column: str) -> dict[str, Any]:
        await self.ensure_guild(guild_id, commit=False)
        cursor = await self.db.execute(f"SELECT {column} FROM guild_settings WHERE guild_id=?", (guild_id,))
        row = await cursor.fetchone()
        if not row:
            return {}
        raw = row[column]
        return dict(self.decode_json(raw) or {}) if raw else {}

    async def set_raw_json(self, guild_id: int, column: str, data: dict[str, Any]) -> None:
        await self.ensure_guild(guild_id)
        await self.db.execute(
            f"UPDATE guild_settings SET {column}=? WHERE guild_id=?",
            (self.encode_json(data), guild_id),
        )
        await self.db.commit()

    async def get_settings(self, guild_id: int) -> dict[str, Any]:
        await self.ensure_guild(guild_id)
        cursor = await self.db.execute("SELECT * FROM guild_settings WHERE guild_id=?", (guild_id,))
        row = await cursor.fetchone()
        if not row:
            return {}
        data = dict(row)
        data["antinuke"] = DEFAULT_ANTINUKE | dict(self.decode_json(data.get("antinuke")) or {})
        stored_events = dict(data["antinuke"].get("events") or {})
        events = {}
        for k, v in DEFAULT_ANTINUKE["events"].items():
            if k in stored_events and isinstance(stored_events[k], dict):
                events[k] = {**v, **stored_events[k]}
            else:
                events[k] = dict(v)
        data["antinuke"]["events"] = events
        data["logging_events"] = DEFAULT_LOGGING | dict(self.decode_json(data.get("logging_events")) or {})
        data.setdefault("join_gif", "https://i.imgur.com/a2rksjN.gif")
        data.setdefault("leave_gif", "https://i.imgur.com/K7aaTLk.gif")
        return data

    async def update_settings(self, guild_id: int, **fields: Any) -> None:
        await self.ensure_guild(guild_id)
        parts = []
        values = []
        for key, value in fields.items():
            if key in {"antinuke", "logging_events"}:
                value = self.encode_json(value)
            parts.append(f"{key}=?")
            values.append(value)
        if not parts:
            return
        values.append(guild_id)
        await self.db.execute(
            f"UPDATE guild_settings SET {', '.join(parts)} WHERE guild_id=?",
            values,
        )
        await self.db.commit()

    async def add_whitelist(self, guild_id: int, user_id: int, added_by: int, admin: bool = False) -> None:
        await self.db.execute(
            """
            INSERT OR IGNORE INTO whitelist (guild_id, user_id, added_by, admin)
            VALUES (?, ?, ?, ?)
            """,
            (guild_id, user_id, added_by, int(admin)),
        )
        await self.db.commit()

    async def remove_whitelist(self, guild_id: int, user_id: int) -> None:
        await self.db.execute("DELETE FROM whitelist WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        await self.db.commit()

    async def is_whitelisted(self, guild_id: int, user_id: int) -> bool:
        cursor = await self.db.execute("SELECT 1 FROM whitelist WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        return (await cursor.fetchone()) is not None

    async def is_whitelist_admin(self, guild_id: int, user_id: int) -> bool:
        cursor = await self.db.execute("SELECT admin FROM whitelist WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        row = await cursor.fetchone()
        return bool(row["admin"]) if row else False

    async def list_whitelist(self, guild_id: int) -> list[dict[str, Any]]:
        cursor = await self.db.execute("SELECT user_id, admin FROM whitelist WHERE guild_id=? ORDER BY added_at", (guild_id,))
        rows = await cursor.fetchall()
        return [{"user_id": str(row["user_id"]), "admin": bool(row["admin"])} for row in rows]

    async def add_extermination(self, guild_id: int, user_id: int, reason: str, created_by: int) -> None:
        await self.db.execute(
            """
            INSERT INTO exterminations (guild_id, user_id, reason, created_by, created_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT (guild_id, user_id)
            DO UPDATE SET reason=excluded.reason, created_by=excluded.created_by, created_at=datetime('now')
            """,
            (guild_id, user_id, reason, created_by),
        )
        await self.db.commit()

    async def remove_extermination(self, guild_id: int, user_id: int) -> None:
        await self.db.execute("DELETE FROM exterminations WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        await self.db.commit()

    async def get_extermination(self, guild_id: int, user_id: int) -> dict[str, Any] | None:
        cursor = await self.db.execute("SELECT * FROM exterminations WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_exterminations(self, guild_id: int) -> list[dict[str, Any]]:
        cursor = await self.db.execute("SELECT * FROM exterminations WHERE guild_id=? ORDER BY created_at DESC", (guild_id,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def save_restore_snapshot(self, guild_id: int, user_id: int, role_ids: list[int]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            """
            INSERT INTO restore_snapshots (guild_id, user_id, role_ids, left_at, rejoined_at)
            VALUES (?, ?, ?, ?, NULL)
            ON CONFLICT (guild_id, user_id)
            DO UPDATE SET role_ids=excluded.role_ids, left_at=excluded.left_at, rejoined_at=NULL
            """,
            (guild_id, user_id, self.encode_json(role_ids), now),
        )
        await self.db.commit()

    async def mark_rejoined(self, guild_id: int, user_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            "UPDATE restore_snapshots SET rejoined_at=? WHERE guild_id=? AND user_id=?",
            (now, guild_id, user_id),
        )
        await self.db.commit()

    async def get_restore_snapshot(self, guild_id: int, user_id: int | None = None) -> dict[str, Any] | None:
        one_hour_ago = datetime.now(timezone.utc).isoformat()
        if user_id is None:
            cursor = await self.db.execute(
                """
                SELECT * FROM restore_snapshots
                WHERE guild_id=? AND rejoined_at IS NOT NULL AND rejoined_at >= datetime('now', '-2 hours')
                ORDER BY rejoined_at DESC
                LIMIT 1
                """,
                (guild_id,),
            )
        else:
            cursor = await self.db.execute(
                """
                SELECT * FROM restore_snapshots
                WHERE guild_id=? AND user_id=? AND rejoined_at IS NOT NULL
                  AND rejoined_at >= datetime('now', '-2 hours')
                """,
                (guild_id, user_id),
            )
        row = await cursor.fetchone()
        if not row:
            return None
        data = dict(row)
        data["role_ids"] = self.decode_json(data["role_ids"])
        return data

    async def save_locked_role(self, guild_id: int, role_id: int, permissions: int) -> None:
        await self.db.execute(
            """
            INSERT OR IGNORE INTO lockdown_roles (guild_id, role_id, permissions)
            VALUES (?, ?, ?)
            """,
            (guild_id, role_id, permissions),
        )
        await self.db.commit()

    # ── Templates ────────────────────────────────────────────────────────────

    async def save_template(
        self,
        guild_id: int,
        name: str,
        channels: list,
        roles: list,
        save_channels: bool,
        save_roles: bool,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO templates (guild_id, name, channels, roles, save_channels, save_roles)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (guild_id, name)
            DO UPDATE SET
                channels=excluded.channels,
                roles=excluded.roles,
                save_channels=excluded.save_channels,
                save_roles=excluded.save_roles,
                created_at=datetime('now')
            """,
            (
                guild_id,
                name,
                self.encode_json(channels),
                self.encode_json(roles),
                int(save_channels),
                int(save_roles),
            ),
        )
        await self.db.commit()

    async def get_template(self, guild_id: int, name: str) -> dict | None:
        cursor = await self.db.execute(
            "SELECT * FROM templates WHERE guild_id=? AND name=?",
            (guild_id, name),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        data = dict(row)
        data["channels"] = self.decode_json(data["channels"])
        data["roles"] = self.decode_json(data["roles"])
        data["save_channels"] = bool(data["save_channels"])
        data["save_roles"] = bool(data["save_roles"])
        return data

    async def list_templates(self, guild_id: int) -> list[str]:
        cursor = await self.db.execute(
            "SELECT name FROM templates WHERE guild_id=? ORDER BY created_at",
            (guild_id,),
        )
        rows = await cursor.fetchall()
        return [row["name"] for row in rows]

    async def delete_template(self, guild_id: int, name: str) -> None:
        await self.db.execute(
            "DELETE FROM templates WHERE guild_id=? AND name=?",
            (guild_id, name),
        )
        await self.db.commit()

    # ── Blacklist ─────────────────────────────────────────────────────────────

    async def add_blacklist(self, guild_id: int, user_id: int, added_by: int) -> None:
        await self.db.execute(
            """
            INSERT OR IGNORE INTO blacklist (guild_id, user_id, added_by)
            VALUES (?, ?, ?)
            """,
            (guild_id, user_id, added_by),
        )
        await self.db.commit()

    async def remove_blacklist(self, guild_id: int, user_id: int) -> None:
        await self.db.execute(
            "DELETE FROM blacklist WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        await self.db.commit()

    async def is_blacklisted(self, guild_id: int, user_id: int) -> bool:
        cursor = await self.db.execute(
            "SELECT 1 FROM blacklist WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        return (await cursor.fetchone()) is not None

    async def list_blacklist(self, guild_id: int) -> list[int]:
        cursor = await self.db.execute(
            "SELECT user_id FROM blacklist WHERE guild_id=? ORDER BY added_at",
            (guild_id,),
        )
        rows = await cursor.fetchall()
        return [int(row["user_id"]) for row in rows]

    # ── Tracked users ─────────────────────────────────────────────────────────

    async def add_tracked_user(self, guild_id: int, discord_user_id: int, roblox_id: int,
                                roblox_username: str, roblox_display_name: str, avatar_url: str | None) -> None:
        await self.db.execute(
            """
            INSERT INTO tracked_users (guild_id, discord_user_id, roblox_id, roblox_username, roblox_display_name, avatar_url)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (guild_id, roblox_id) DO UPDATE SET
                discord_user_id=excluded.discord_user_id,
                roblox_username=excluded.roblox_username,
                roblox_display_name=excluded.roblox_display_name,
                avatar_url=excluded.avatar_url
            """,
            (guild_id, discord_user_id, roblox_id, roblox_username, roblox_display_name, avatar_url),
        )
        await self.db.commit()

    async def remove_tracked_user(self, guild_id: int, roblox_id: int) -> None:
        await self.db.execute(
            "DELETE FROM tracked_users WHERE guild_id=? AND roblox_id=?",
            (guild_id, roblox_id),
        )
        await self.db.commit()

    async def list_tracked_users(self, guild_id: int) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM tracked_users WHERE guild_id=?",
            (guild_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ── Access Keys ──────────────────────────────────────────────────────────

    async def create_access_key(self, user_id: int, access_key: str, expires_at: str) -> None:
        await self.db.execute(
            """
            INSERT INTO access_keys (user_id, access_key, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT (user_id)
            DO UPDATE SET access_key=excluded.access_key, expires_at=excluded.expires_at, created_at=datetime('now')
            """,
            (user_id, access_key, expires_at),
        )
        await self.db.commit()

    async def validate_access_key(self, user_id: int, access_key: str) -> bool:
        cursor = await self.db.execute(
            "SELECT 1 FROM access_keys WHERE user_id=? AND access_key=? AND expires_at > datetime('now')",
            (user_id, access_key),
        )
        return (await cursor.fetchone()) is not None

    async def get_access_key_expiry(self, user_id: int) -> str | None:
        cursor = await self.db.execute(
            "SELECT expires_at FROM access_keys WHERE user_id=?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row["expires_at"] if row else None

    async def delete_access_key(self, user_id: int) -> None:
        await self.db.execute("DELETE FROM access_keys WHERE user_id=?", (user_id,))
        await self.db.commit()

    async def delete_access_key_by_value(self, access_key: str) -> None:
        await self.db.execute("DELETE FROM access_keys WHERE access_key=?", (access_key,))
        await self.db.commit()

    async def list_access_keys(self) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT user_id, access_key, expires_at FROM access_keys WHERE expires_at > datetime('now') ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ── Login Approvals ─────────────────────────────────────────────────────

    async def create_login_approval(self, user_id: int, access_key: str) -> str:
        approval_id = secrets.token_hex(16)
        await self.db.execute(
            "INSERT INTO login_approvals (id, user_id, access_key) VALUES (?, ?, ?)",
            (approval_id, user_id, access_key),
        )
        await self.db.commit()
        return approval_id

    async def get_login_approval(self, approval_id: str) -> dict | None:
        cursor = await self.db.execute(
            "SELECT * FROM login_approvals WHERE id=?", (approval_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_approval_status(self, approval_id: str, status: str, session_token: str = None) -> None:
        if session_token:
            await self.db.execute(
                "UPDATE login_approvals SET status=?, session_token=? WHERE id=?",
                (status, session_token, approval_id),
            )
        else:
            await self.db.execute(
                "UPDATE login_approvals SET status=? WHERE id=?",
                (status, approval_id),
            )
        await self.db.commit()

    # ── Trusted Users ────────────────────────────────────────────────────────

    async def add_trusted(self, user_id: int, added_by: int) -> None:
        await self.db.execute(
            "INSERT OR IGNORE INTO trusted_users (user_id, added_by) VALUES (?, ?)",
            (user_id, added_by),
        )
        await self.db.commit()

    async def remove_trusted(self, user_id: int) -> None:
        await self.db.execute("DELETE FROM trusted_users WHERE user_id=?", (user_id,))
        await self.db.commit()

    async def is_trusted(self, user_id: int) -> bool:
        cursor = await self.db.execute("SELECT 1 FROM trusted_users WHERE user_id=?", (user_id,))
        return (await cursor.fetchone()) is not None

    async def list_trusted(self) -> list[dict]:
        cursor = await self.db.execute("SELECT user_id, added_by, added_at FROM trusted_users ORDER BY added_at")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def set_ping_protection(self, guild_id: int, user_id: int, pings: int) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO ping_protection (guild_id, user_id, pings_allowed) VALUES (?, ?, ?)",
            (guild_id, user_id, pings),
        )
        await self.db.commit()

    async def use_ping_protection(self, guild_id: int, user_id: int) -> bool:
        cursor = await self.db.execute(
            "SELECT pings_allowed FROM ping_protection WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()
        if not row or row[0] <= 0:
            return False
        new_count = row[0] - 1
        if new_count <= 0:
            await self.db.execute("DELETE FROM ping_protection WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        else:
            await self.db.execute(
                "UPDATE ping_protection SET pings_allowed=? WHERE guild_id=? AND user_id=?",
                (new_count, guild_id, user_id),
            )
        await self.db.commit()
        return True

    async def get_ping_protection(self, guild_id: int, user_id: int) -> int:
        cursor = await self.db.execute(
            "SELECT pings_allowed FROM ping_protection WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def set_tung_lock(self, guild_id: int, channel_id: int) -> None:
        await self.db.execute(
            "INSERT OR IGNORE INTO tung_lock (guild_id, channel_id) VALUES (?, ?)",
            (guild_id, channel_id),
        )
        await self.db.commit()

    async def remove_tung_lock(self, guild_id: int, channel_id: int) -> None:
        await self.db.execute("DELETE FROM tung_lock WHERE guild_id=? AND channel_id=?", (guild_id, channel_id))
        await self.db.execute("DELETE FROM tung_whitelist WHERE guild_id=? AND channel_id=?", (guild_id, channel_id))
        await self.db.commit()

    async def is_tung_locked(self, guild_id: int, channel_id: int) -> bool:
        cursor = await self.db.execute("SELECT 1 FROM tung_lock WHERE guild_id=? AND channel_id=?", (guild_id, channel_id))
        return (await cursor.fetchone()) is not None

    async def add_tung_whitelist(self, guild_id: int, channel_id: int, user_id: int) -> None:
        await self.db.execute(
            "INSERT OR IGNORE INTO tung_whitelist (guild_id, user_id, channel_id) VALUES (?, ?, ?)",
            (guild_id, user_id, channel_id),
        )
        await self.db.commit()

    async def remove_tung_whitelist(self, guild_id: int, channel_id: int, user_id: int) -> None:
        await self.db.execute("DELETE FROM tung_whitelist WHERE guild_id=? AND channel_id=? AND user_id=?", (guild_id, channel_id, user_id))
        await self.db.commit()

    async def is_tung_whitelisted(self, guild_id: int, channel_id: int, user_id: int) -> bool:
        cursor = await self.db.execute("SELECT 1 FROM tung_whitelist WHERE guild_id=? AND channel_id=? AND user_id=?", (guild_id, channel_id, user_id))
        return (await cursor.fetchone()) is not None
