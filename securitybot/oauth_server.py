from __future__ import annotations

import asyncio
import json
import os
import time
import secrets
import hashlib
from datetime import datetime
from pathlib import Path
from functools import wraps
from collections import defaultdict

import aiohttp
import discord
from aiohttp import web, BasicAuth

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
USER_URL = "https://discord.com/api/v10/users/@me"
GUILD_MEMBER_URL = "https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}"
ROLE_URL = "https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}/roles/{role_id}"

WEBSITE_DIR = Path(__file__).resolve().parent.parent / "website" / "github"

OWNER_ID = 903327749534523452
RATE_LIMITS = defaultdict(list)
SESSIONS = {}
LOG_STORE = {"security": [], "bot_usage": [], "regular": [], "exterminated": []}
DISMISSED_STORE: set[str] = set()
MAX_LOGS = 100
LOGS_FILE = Path(__file__).resolve().parent.parent / "logs.json"
DISMISSED_FILE = Path(__file__).resolve().parent.parent / "dismissed.json"


def save_logs():
    try:
        LOGS_FILE.write_text(json.dumps(LOG_STORE, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def load_logs():
    global LOG_STORE
    if LOGS_FILE.exists():
        try:
            data = json.loads(LOGS_FILE.read_text(encoding="utf-8"))
            for cat in list(LOG_STORE.keys()):
                LOG_STORE[cat] = data.get(cat, [])
        except Exception:
            pass


def save_dismissed():
    try:
        DISMISSED_FILE.write_text(json.dumps(list(DISMISSED_STORE)), encoding="utf-8")
    except Exception:
        pass


def load_dismissed():
    global DISMISSED_STORE
    if DISMISSED_FILE.exists():
        try:
            DISMISSED_STORE = set(json.loads(DISMISSED_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass


def get_client_ip(request: web.Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote or "unknown"


def rate_limit(ip: str) -> bool:
    now = time.time()
    RATE_LIMITS[ip] = [t for t in RATE_LIMITS[ip] if now - t < 60]
    if len(RATE_LIMITS[ip]) >= 30:
        return False
    RATE_LIMITS[ip].append(now)
    return True


def add_log(category: str, text: str, user: str = "System", avatar: str | None = None, log_type: str = "info", details: dict | None = None):
    log_id = hashlib.md5(f"{category}:{text}:{time.time()}".encode()).hexdigest()[:12]
    entry = {"id": log_id, "user": user, "text": text, "type": log_type, "avatar": avatar or "", "time": datetime.now().strftime("%H:%M:%S"), "details": details or None}
    if category in LOG_STORE:
        LOG_STORE[category].insert(0, entry)
        if len(LOG_STORE[category]) > MAX_LOGS:
            LOG_STORE[category] = LOG_STORE[category][:MAX_LOGS]
    save_logs()


def create_session(user_id: str, username: str, expires_in: int = 3600, avatar: str | None = None) -> str:
    token = secrets.token_hex(32)
    SESSIONS[token] = {
        "user_id": user_id,
        "username": username,
        "avatar": avatar,
        "expires": time.time() + expires_in,
    }
    return token


def validate_session(token: str) -> dict | None:
    if not token or token not in SESSIONS:
        return None
    session = SESSIONS[token]
    if time.time() > session["expires"]:
        del SESSIONS[token]
        return None
    return session


class WebServer:
    def __init__(self, bot: discord.Client) -> None:
        self.bot = bot
        self.config = json.loads((Path(__file__).parent.parent / "config.json").read_text())
        self.guild_id = self.config.get("allowed_guild_id", 0)
        self.verify_role_id = self.config.get("verify_role_id", 0)
        self.client_id = self.config.get("oauth_client_id", "")
        self.client_secret = self.config.get("oauth_client_secret", "")
        self.redirect_uri = self.config.get("oauth_redirect_uri", "http://localhost:5000/verify")
        railway_url = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
        if railway_url:
            self.redirect_uri = f"https://{railway_url}/verify"

    async def exchange_code(self, code: str) -> dict | None:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                TOKEN_URL, data=data,
                auth=BasicAuth(self.client_id, self.client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            ) as r:
                if r.status == 200:
                    return await r.json()
        return None

    async def get_user(self, access_token: str) -> dict | None:
        async with aiohttp.ClientSession() as session:
            async with session.get(USER_URL, headers={"Authorization": f"Bearer {access_token}"}) as r:
                if r.status == 200:
                    return await r.json()
        return None

    async def add_to_guild(self, access_token: str, user_id: int) -> bool:
        async with aiohttp.ClientSession() as session:
            async with session.put(
                GUILD_MEMBER_URL.format(guild_id=self.guild_id, user_id=user_id),
                json={"access_token": access_token},
                headers={"Authorization": f"Bot {self.bot.http.token}", "Content-Type": "application/json"}
            ) as r:
                return r.status in (200, 201, 204)

    async def give_verify_role(self, user_id: int) -> bool:
        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            return False
        member = guild.get_member(user_id)
        if not member:
            try:
                member = await guild.fetch_member(user_id)
            except discord.HTTPException:
                return False
        role = guild.get_role(self.verify_role_id)
        if not role:
            return False
        if role in member.roles:
            return True
        try:
            await member.add_roles(role, reason="Verified via OAuth")
            return True
        except discord.HTTPException:
            return False

    async def handle_index(self, request: web.Request) -> web.Response:
        return web.FileResponse(WEBSITE_DIR / "index.html")

    async def handle_login_page(self, request: web.Request) -> web.Response:
        return web.FileResponse(WEBSITE_DIR / "login.html")

    async def handle_dashboard_page(self, request: web.Request) -> web.Response:
        return web.FileResponse(WEBSITE_DIR / "dashboard.html")

    async def handle_static(self, request: web.Request) -> web.Response:
        filename = request.match_info["filename"]
        if ".." in filename or "/" in filename:
            return web.Response(status=403)
        file_path = WEBSITE_DIR / filename
        if not file_path.exists() or not file_path.is_file():
            return web.Response(status=404)
        return web.FileResponse(file_path)

    async def handle_api_verify(self, request: web.Request) -> web.Response:
        ip = get_client_ip(request)
        if not rate_limit(ip):
            return web.json_response({"success": False, "error": "Rate limited"}, status=429)

        code = request.query.get("code")
        if not code or len(code) > 200:
            return web.json_response({"success": False, "error": "Invalid code"}, status=400)

        token_data = await self.exchange_code(code)
        if not token_data or "access_token" not in token_data:
            return web.json_response({"success": False, "error": "Invalid or expired code"})

        user = await self.get_user(token_data["access_token"])
        if not user:
            return web.json_response({"success": False, "error": "Failed to get user info"})

        user_id = user["id"]
        username = user["username"]
        disc = user.get("discriminator", "0")
        display = f"@{username}" if disc == "0" else f"@{username}#{disc}"

        if not await self.add_to_guild(token_data["access_token"], user_id):
            return web.json_response({"success": False, "error": "Failed to add you to the server"})

        if not await self.give_verify_role(user_id):
            return web.json_response({"success": False, "error": "Failed to assign role"})

        return web.json_response({"success": True, "username": display})

    async def handle_api_login(self, request: web.Request) -> web.Response:
        ip = get_client_ip(request)
        if not rate_limit(ip):
            return web.json_response({"error": "Rate limited"}, status=429)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid request"}, status=400)

        user_id = str(data.get("user_id", "")).strip()[:20]
        access_key = str(data.get("key", "")).strip()[:50]

        if not user_id or not access_key:
            return web.json_response({"error": "Missing user ID or key"}, status=400)

        try:
            uid = int(user_id)
        except ValueError:
            return web.json_response({"error": "Invalid user ID"}, status=400)

        valid = await self.bot.db.validate_access_key(uid, access_key)
        if not valid:
            try:
                from securitybot.oauth_server import add_log
                add_log("security", f"Failed login attempt for ID `{uid}` from IP `{ip}`", log_type="security", details={"User ID": str(uid), "IP": str(ip), "Key": access_key[:10] + "..."})
            except Exception:
                pass
            await asyncio.sleep(0.5)
            return web.json_response({"error": "Invalid or expired key"}, status=401)

        approval_id = await self.bot.db.create_login_approval(uid, access_key)

        async def send_approval_dm():
            try:
                owner = await self.bot.fetch_user(OWNER_ID)
                from securitybot.cogs.moderation import LoginApprovalView
                view = LoginApprovalView(approval_id, uid, access_key)
                user = self.bot.get_user(uid)
                name = user.name if user else str(uid)
                embed = discord.Embed(
                    title="Web Panel Access",
                    description=(
                        f"**{name}** (`{uid}`) is requesting access to the web panel.\n\n"
                        f"> **ID**: `{uid}`\n"
                        f"> **Key**: `{access_key}`"
                    ),
                    color=0xA8D8EA,
                )
                await owner.send(embed=embed, view=view)
            except Exception:
                pass

        asyncio.create_task(send_approval_dm())

        return web.json_response({"success": True, "approval_id": approval_id, "status": "pending"})

    async def handle_api_logout(self, request: web.Request) -> web.Response:
        token = request.cookies.get("session")
        if token and token in SESSIONS:
            del SESSIONS[token]
        response = web.json_response({"success": True})
        response.del_cookie("session")
        return response

    async def handle_api_session(self, request: web.Request) -> web.Response:
        token = request.cookies.get("session")
        session = validate_session(token)
        if not session:
            return web.json_response({"authenticated": False})
        response_data = {
            "authenticated": True,
            "user_id": session["user_id"],
            "username": session["username"],
            "expires": session["expires"],
        }
        if session.get("avatar"):
            response_data["avatar"] = session["avatar"]
        bot_user = self.bot.user
        if bot_user:
            response_data["bot_avatar"] = str(bot_user.display_avatar.url)
        return web.json_response(response_data)

    async def handle_api_command(self, request: web.Request) -> web.Response:
        ip = get_client_ip(request)
        if not rate_limit(ip):
            return web.json_response({"error": "Rate limited"}, status=429)

        token = request.cookies.get("session")
        api_key = request.headers.get("X-API-Key", "")
        session = validate_session(token)
        if not session and api_key != os.environ.get("API_KEY", ""):
            return web.json_response({"error": "Unauthorized"}, status=401)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid request"}, status=400)

        command = str(data.get("command", "")).strip()[:500]
        if not command:
            return web.json_response({"error": "Missing command"}, status=400)

        ALLOWED_PREFIXES = ["help", "ping", "verify", "activity", "blacklist", "whitelist"]
        cmd_name = command.split()[0].lower() if command.split() else ""
        if cmd_name not in ALLOWED_PREFIXES:
            return web.json_response({"error": "Command not allowed via web console"}, status=403)

        try:
            guild = None
            for g in self.bot.guilds:
                guild = g
                break

            if not guild:
                return web.json_response({"error": "No guild available"}, status=500)

            output_lines = []

            msg = discord.Object(id=0)
            msg.content = "," + command
            msg.author = guild.me
            msg.guild = guild
            msg.channel = discord.Object(id=0)
            msg.channel.guild = guild
            msg.id = 0
            msg.webhook_id = None
            msg.nonce = None
            msg.tts = False
            msg.pinned = False
            msg.mention_everyone = False
            msg.mentions = []
            msg.role_mentions = []
            msg.attachments = []
            msg.embeds = []
            msg.reference = None
            msg.flags = discord.MessageFlags()
            msg._edited_timestamp = None

            ctx = await self.bot.get_context(msg)
            if ctx.command:
                async def capture_send(content=None, **kwargs):
                    if content:
                        output_lines.append(str(content)[:2000])

                ctx.send = capture_send

                try:
                    await ctx.command.invoke(ctx)
                except Exception:
                    output_lines.append("Command failed to execute.")

            if output_lines:
                return web.json_response({
                    "output": "\n".join(output_lines),
                    "user": session["username"]
                })

            return web.json_response({
                "output": f"Command '{cmd_name}' executed (no output)",
                "user": session["username"]
            })

        except Exception:
            return web.json_response({"error": "Command failed"}, status=500)

    async def handle_api_settings(self, request: web.Request) -> web.Response:
        ip = get_client_ip(request)
        if not rate_limit(ip):
            return web.json_response({"error": "Rate limited"}, status=429)

        token = request.cookies.get("session")
        api_key = request.headers.get("X-API-Key", "")
        session = validate_session(token)
        if not session and api_key != os.environ.get("API_KEY", ""):
            return web.json_response({"error": "Unauthorized"}, status=401)

        guild = None
        for g in self.bot.guilds:
            guild = g
            break
        if not guild:
            return web.json_response({"error": "No guild"}, status=500)

        settings = await self.bot.db.get_settings(guild.id)
        antinuke = settings.get("antinuke", {})
        whitelist_entries = await self.bot.db.list_whitelist(guild.id)
        standard_wl = [str(e["user_id"]) for e in whitelist_entries if not e.get("admin")]
        legacy_wl = [str(e["user_id"]) for e in whitelist_entries if e.get("admin")]
        blacklist_entries = await self.bot.db.list_blacklist(guild.id)
        blacklist = [str(uid) for uid in blacklist_entries]

        async def resolve_users(ids: list[str]) -> dict:
            result = {}
            for uid_str in ids:
                try:
                    uid = int(uid_str)
                except ValueError:
                    continue
                user = self.bot.get_user(uid)
                if not user:
                    try:
                        user = await self.bot.fetch_user(uid)
                    except Exception:
                        pass
                if user:
                    result[uid_str] = {
                        "name": user.name,
                        "display": user.display_name,
                        "avatar": str(user.display_avatar.url),
                    }
                else:
                    avatar_idx = uid % 5
                    result[uid_str] = {
                        "name": uid_str,
                        "display": uid_str,
                        "avatar": f"https://cdn.discordapp.com/embed/avatars/{avatar_idx}.png",
                    }
            return result

        an_wl = [str(uid) for uid in (antinuke.get("whitelist") or [])]
        antinuke["whitelist"] = an_wl
        all_ids = list(set(standard_wl + legacy_wl + blacklist + an_wl))
        user_info = await resolve_users(all_ids)

        return web.json_response({
            "guild": {
                "id": guild.id,
                "name": guild.name,
                "member_count": guild.member_count,
                "role_count": len(guild.roles),
                "channel_count": len(guild.channels),
                "emoji_count": len(guild.emojis),
                "premium_tier": guild.premium_tier,
                "premium_subscription_count": guild.premium_subscription_count,
            },
            "prefix": settings.get("prefix", ","),
            "join_channel_id": settings.get("join_channel_id"),
            "join_message": settings.get("join_message", "Welcome {mention} to {server}!"),
            "join_gif": settings.get("join_gif", "https://i.imgur.com/a2rksjN.gif"),
            "leave_channel_id": settings.get("leave_channel_id"),
            "leave_message": settings.get("leave_message", "{user} left {server}."),
            "leave_gif": settings.get("leave_gif", "https://i.imgur.com/K7aaTLk.gif"),
            "logging_channel_id": settings.get("logging_channel_id"),
            "logging_events": settings.get("logging_events", {}),
            "antinuke": antinuke,
            "whitelist_standard": standard_wl,
            "whitelist_legacy": legacy_wl,
            "blacklist": blacklist,
            "user_info": user_info,
        })

    async def handle_api_settings_update(self, request: web.Request) -> web.Response:
        ip = get_client_ip(request)
        if not rate_limit(ip):
            return web.json_response({"error": "Rate limited"}, status=429)

        token = request.cookies.get("session")
        api_key = request.headers.get("X-API-Key", "")
        session = validate_session(token)
        if not session and api_key != os.environ.get("API_KEY", ""):
            return web.json_response({"error": "Unauthorized"}, status=401)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        guild = None
        for g in self.bot.guilds:
            guild = g
            break
        if not guild:
            return web.json_response({"error": "No guild"}, status=500)

        key = data.get("key", "")
        value = data.get("value")

        if key.startswith("antinuke."):
            antinuke = await self.bot.db.get_raw_json(guild.id, "antinuke")
            nested_key = key.split(".", 1)[1]

            if nested_key.startswith("events."):
                parts = nested_key.split(".")
                event_name = parts[1]
                field = parts[2] if len(parts) > 2 else None
                events = antinuke.setdefault("events", {})
                evt = events.get(event_name)
                if not isinstance(evt, dict):
                    evt = {"enabled": True, "threshold": 1, "punishment": "strip"}
                if field:
                    evt[field] = value
                events[event_name] = evt
            elif nested_key.startswith("massban_lockdown."):
                field = nested_key.split(".", 1)[1]
                lockdown = antinuke.setdefault("massban_lockdown", {})
                lockdown[field] = value
            elif nested_key == "whitelist":
                antinuke[nested_key] = [str(v) for v in (value or [])]
            else:
                antinuke[nested_key] = value

            await self.bot.db.set_raw_json(guild.id, "antinuke", antinuke)
        elif key in ("prefix", "join_gif", "leave_gif"):
            await self.bot.db.update_settings(guild.id, **{key: value})
        elif key in ("join_message", "leave_message"):
            safe_value = str(value)[:500] if value else ""
            await self.bot.db.update_settings(guild.id, **{key: safe_value})
        elif key in ("join_channel_id", "leave_channel_id"):
            try:
                ch_id = int(str(value).replace("<#", "").replace(">", "")) if value else None
            except (ValueError, TypeError):
                ch_id = None
            await self.bot.db.update_settings(guild.id, **{key: ch_id})
        elif key == "logging_channel_id":
            try:
                channel_id = int(str(value).replace("<#", "").replace(">", "")) if value else None
            except (ValueError, TypeError):
                channel_id = None
            await self.bot.db.update_settings(guild.id, logging_channel_id=channel_id)
        elif key.startswith("logging_events."):
            events = await self.bot.db.get_raw_json(guild.id, "logging_events")
            events[key.split(".", 1)[1]] = value
            await self.bot.db.set_raw_json(guild.id, "logging_events", events)
        else:
            return web.json_response({"error": f"Unknown key: {key}"}, status=400)

        return web.json_response({"success": True})

    async def handle_api_whitelist(self, request: web.Request) -> web.Response:
        ip = get_client_ip(request)
        if not rate_limit(ip):
            return web.json_response({"error": "Rate limited"}, status=429)

        token = request.cookies.get("session")
        api_key = request.headers.get("X-API-Key", "")
        session = validate_session(token)
        if not session and api_key != os.environ.get("API_KEY", ""):
            return web.json_response({"error": "Unauthorized"}, status=401)

        guild = None
        for g in self.bot.guilds:
            guild = g
            break
        if not guild:
            return web.json_response({"error": "No guild"}, status=500)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        action = data.get("action", "")
        user_id = data.get("user_id")
        wl_type = data.get("type", "standard")

        if not user_id:
            return web.json_response({"error": "Missing user_id"}, status=400)

        try:
            user_id = int(user_id)
        except ValueError:
            return web.json_response({"error": "Invalid user_id"}, status=400)

        if action == "add":
            await self.bot.db.add_whitelist(guild.id, user_id, guild.me.id, admin=(wl_type == "legacy"))
            return web.json_response({"success": True})
        elif action == "remove":
            await self.bot.db.remove_whitelist(guild.id, user_id)
            return web.json_response({"success": True})
        else:
            return web.json_response({"error": "Unknown action"}, status=400)

    async def handle_api_blacklist(self, request: web.Request) -> web.Response:
        ip = get_client_ip(request)
        if not rate_limit(ip):
            return web.json_response({"error": "Rate limited"}, status=429)

        token = request.cookies.get("session")
        api_key = request.headers.get("X-API-Key", "")
        session = validate_session(token)
        if not session and api_key != os.environ.get("API_KEY", ""):
            return web.json_response({"error": "Unauthorized"}, status=401)

        guild = None
        for g in self.bot.guilds:
            guild = g
            break
        if not guild:
            return web.json_response({"error": "No guild"}, status=500)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        action = data.get("action", "")
        user_id = data.get("user_id")

        if not user_id:
            return web.json_response({"error": "Missing user_id"}, status=400)

        try:
            user_id = int(user_id)
        except ValueError:
            return web.json_response({"error": "Invalid user_id"}, status=400)

        if action == "add":
            await self.bot.db.add_blacklist(guild.id, user_id, guild.me.id)
            return web.json_response({"success": True})
        elif action == "remove":
            await self.bot.db.remove_blacklist(guild.id, user_id)
            return web.json_response({"success": True})
        else:
            return web.json_response({"error": "Unknown action"}, status=400)

    async def handle_api_approval(self, request: web.Request) -> web.Response:
        approval_id = request.match_info.get("id", "")
        if not approval_id or not isinstance(approval_id, str) or len(approval_id) > 64:
            return web.json_response({"error": "Invalid approval ID"}, status=400)

        approval = await self.bot.db.get_login_approval(approval_id)
        if not approval:
            return web.json_response({"status": "not_found"}, status=404)

        status = approval["status"]
        if status == "approved":
            token = approval.get("session_token")
            response = web.json_response({"status": "approved"})
            if token:
                secure = request.url and request.url.scheme == "https"
                response.set_cookie("session", token, path="/", httponly=True, samesite="Strict", max_age=3600, secure=secure)
            return response
        elif status == "denied":
            return web.json_response({"status": "denied"})

        return web.json_response({"status": "pending"})

    async def handle_api_logs(self, request: web.Request) -> web.Response:
        token = request.cookies.get("session")
        session = validate_session(token)
        if not session:
            return web.json_response({"error": "Unauthorized"}, status=401)

        guild = None
        for g in self.bot.guilds:
            guild = g
            break

        exterminated = []
        if guild:
            try:
                exts = await self.bot.db.list_exterminations(guild.id)
                for ext in exts:
                    uid_str = str(ext["user_id"])
                    cb_str = str(ext["created_by"])
                    user = self.bot.get_user(ext["user_id"])
                    cb_user = self.bot.get_user(ext["created_by"])
                    avatar = str(user.display_avatar.url) if user else f"https://cdn.discordapp.com/embed/avatars/{ext['user_id'] % 5}.png"
                    cb_name = cb_user.display_name if cb_user else cb_str
                    cb_avatar = str(cb_user.display_avatar.url) if cb_user else f"https://cdn.discordapp.com/embed/avatars/{ext['created_by'] % 5}.png"
                    exterminated.append({
                        "id": f"ext-{uid_str}",
                        "user": uid_str,
                        "display": user.display_name if user else uid_str,
                        "avatar": avatar,
                        "created_by": cb_str,
                        "created_by_name": cb_name,
                        "created_by_avatar": cb_avatar,
                        "reason": ext.get("reason", "Exterminated"),
                        "time": ext.get("created_at", ""),
                    })
            except Exception:
                pass

        data = dict(LOG_STORE)
        data["exterminated"] = exterminated
        data["dismissed"] = list(DISMISSED_STORE)
        return web.json_response(data)

    async def handle_api_logs_dismiss(self, request: web.Request) -> web.Response:
        token = request.cookies.get("session")
        session = validate_session(token)
        if not session:
            return web.json_response({"error": "Unauthorized"}, status=401)
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        log_id = data.get("id", "")
        if log_id:
            DISMISSED_STORE.add(log_id)
            save_dismissed()
        return web.json_response({"success": True})

    async def handle_api_logs_dismiss_all(self, request: web.Request) -> web.Response:
        token = request.cookies.get("session")
        session = validate_session(token)
        if not session:
            return web.json_response({"error": "Unauthorized"}, status=401)
        try:
            data = await request.json()
        except Exception:
            data = {}
        category = data.get("category", "")
        if category and category in LOG_STORE:
            for entry in LOG_STORE[category]:
                if entry.get("id"):
                    DISMISSED_STORE.add(entry["id"])
        elif not category:
            for cat_entries in LOG_STORE.values():
                for entry in cat_entries:
                    if entry.get("id"):
                        DISMISSED_STORE.add(entry["id"])
        save_dismissed()
        return web.json_response({"success": True})


async def start_web_server(bot: discord.Client) -> None:
    import os
    import asyncio

    load_logs()
    load_dismissed()

    server = WebServer(bot)
    port = int(os.environ.get("PORT", 5000))
    vercel_url = os.environ.get("VERCEL_URL", "")
    allowed_origins = [
        "http://localhost:5000",
        "http://localhost:3000",
    ]
    if vercel_url:
        allowed_origins.append(f"https://{vercel_url}")
        allowed_origins.append(f"http://{vercel_url}")

    @web.middleware
    async def cors_middleware(request, handler):
        origin = request.headers.get("Origin", "")
        if request.method == "OPTIONS":
            response = web.Response()
        else:
            response = await handler(request)
        if origin and origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        return response

    @web.middleware
    async def security_middleware(request, handler):
        if request.method == "POST":
            origin = request.headers.get("Origin", "")
            api_key = request.headers.get("X-API-Key", "")
            if origin and origin not in allowed_origins:
                return web.json_response({"error": "Forbidden"}, status=403)
        response = await handler(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url and request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    app = web.Application(middlewares=[security_middleware, cors_middleware])
    app.router.add_get("/", server.handle_index)
    app.router.add_get("/index.html", server.handle_index)
    app.router.add_get("/login", server.handle_login_page)
    app.router.add_get("/login.html", server.handle_login_page)
    app.router.add_get("/dashboard", server.handle_dashboard_page)
    app.router.add_get("/dashboard.html", server.handle_dashboard_page)
    app.router.add_get("/verify", server.handle_index)
    app.router.add_get("/api/verify", server.handle_api_verify)
    app.router.add_post("/api/login", server.handle_api_login)
    app.router.add_post("/api/logout", server.handle_api_logout)
    app.router.add_get("/api/session", server.handle_api_session)
    app.router.add_post("/api/command", server.handle_api_command)
    app.router.add_get("/api/settings", server.handle_api_settings)
    app.router.add_post("/api/settings", server.handle_api_settings_update)
    app.router.add_post("/api/whitelist", server.handle_api_whitelist)
    app.router.add_post("/api/blacklist", server.handle_api_blacklist)
    app.router.add_get("/api/approval/{id}", server.handle_api_approval)
    app.router.add_get("/api/logs", server.handle_api_logs)
    app.router.add_post("/api/logs/dismiss", server.handle_api_logs_dismiss)
    app.router.add_post("/api/logs/dismiss-all", server.handle_api_logs_dismiss_all)
    app.router.add_get("/{filename}", server.handle_static)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
