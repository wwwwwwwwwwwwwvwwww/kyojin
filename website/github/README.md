# Jinn Security Bot - Website

Secure OAuth verification page and admin dashboard for a Discord bot.

## Security Features

- **Session-based auth**: HttpOnly cookies, no localStorage
- **Rate limiting**: 30 requests per minute per IP
- **CSRF protection**: SameSite cookies
- **Input validation**: All inputs sanitized and length-limited
- **Security headers**: CSP, X-Frame-Options, X-XSS-Protection
- **Password hashing**: SHA-256 (use bcrypt in production)
- **Command blocking**: Dangerous commands blocked in console
- **No secrets in frontend**: All API keys stay on server

## Setup

### Backend

```bash
cd backend
pip install -r requirements.txt
```

Create `config.json` or `.env`:
```json
{
  "BOT_TOKEN": "YOUR_BOT_TOKEN",
  "CLIENT_ID": "YOUR_CLIENT_ID",
  "CLIENT_SECRET": "YOUR_CLIENT_SECRET",
  "GUILD_ID": "YOUR_GUILD_ID",
  "VERIFY_ROLE_ID": "YOUR_ROLE_ID",
  "REDIRECT_URI": "https://your-site.com/verify",
  "ADMIN_USERNAME": "admin",
  "ADMIN_PASSWORD": "CHANGE_THIS",
  "SECRET_KEY": "CHANGE_THIS",
  "HOST": "0.0.0.0",
  "PORT": 5000
}
```

Run:
```bash
python server.py
```

### Frontend

Upload all HTML files to your hosting. Set Discord OAuth redirect URI to your verify URL.

## Files

```
github/
├── index.html          # Home page
├── login.html          # Login page
├── dashboard.html      # Admin dashboard
├── icon.png            # Bot avatar
├── .gitignore
├── README.md
└── backend/
    ├── server.py       # Secure API server
    ├── config.json     # Secrets (DO NOT commit)
    └── requirements.txt
```

## Environment Variables

All config can be set via environment variables or config.json:

| Variable | Description |
|----------|-------------|
| BOT_TOKEN | Discord bot token |
| CLIENT_ID | OAuth client ID |
| CLIENT_SECRET | OAuth client secret |
| GUILD_ID | Server ID |
| VERIFY_ROLE_ID | Role to assign |
| REDIRECT_URI | OAuth redirect URL |
| ADMIN_USERNAME | Login username |
| ADMIN_PASSWORD | Login password |
| SECRET_KEY | Session secret |
| HOST | Server host |
| PORT | Server port |
