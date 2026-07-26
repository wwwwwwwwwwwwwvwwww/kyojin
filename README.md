# Discord Security Bot

A Python `discord.py` bot with PostgreSQL-backed whitelist, moderation tools, exterminate bans, configurable prefix, join/leave/logging panels, and anti-nuke protections.

## Setup

1. Install Python 3.11+.
2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Create `.env` from `.env.example` and fill in your bot token, PostgreSQL URL, and owner IDs.
4. In the Discord developer portal, enable these privileged intents:
   - Server Members Intent
   - Message Content Intent
5. Put the bot role as high as possible. It can only remove roles/permissions below its own top role.
6. Run:

```powershell
python bot.py
```

Default prefix is `,`. You can change it with `,prefix set <new_prefix>`.

## Important Commands

- `,help` reaction-paged help menu
- `,whitelist add <user_id>` / `,whitelist remove <user_id>` / `,whitelist list`
- `,antinuke` interactive anti-nuke panel
- `,exterminate <user_id> [reason]` hard-ban and auto-reban on rejoin
- `,unexterminate <user_id>` remove hard-ban status
- `,nuke` clone current channel and delete the old one
- `,restore [user_id]` restore roles for the last rejoined user, or a specific user, if they rejoined within 1 hour
- `,strip <user_id>` remove roles with Administrator from a user
- `,mute <user_id> [minutes] [reason]` timeout a user
- `,join`, `,leave`, `,logging` interactive setup panels

