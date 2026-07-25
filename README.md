# Bookmark Resurfacer

Stores bookmarks and periodically emails you a random set to revisit.

Supports multiple users via **Void Auth SSO**. All bookmarks and settings are scoped per user.

## Quick Start (Docker)

```bash
git clone <repo-url> bookmark-resurfacer
cd bookmark-resurfacer
cp .env.example .env
# Edit .env — see Configuration section below
docker compose up --build
```

The app will be available at **http://localhost:8000**.

Data persists in the `./data` directory (SQLite).

## Configuration

### Void Auth SSO

This app supports multi-user login via **Void Auth** (OIDC/OAuth 2.0). When configured, each user gets their own bookmarks and settings.

Set these environment variables in your `.env` file:

| Variable | Description | Example |
|---|---|---|
| `SESSION_SECRET` | Random string for encrypting session cookies | `openssl rand -hex 32` |
| `VOID_AUTH_CLIENT_ID` | Your Void Auth OAuth client ID | `abc123...` |
| `VOID_AUTH_CLIENT_SECRET` | Your Void Auth OAuth client secret | `xyz789...` |
| `VOID_AUTH_DOMAIN` | Your Void Auth instance URL | `https://auth.yourcompany.com` |
| `VOID_AUTH_REDIRECT_URI` | Callback URL (must match Void Auth config) | `http://localhost:8000/auth/callback` |

**Authorization endpoint:** `{VOID_AUTH_DOMAIN}/oauth/authorize`  
**Token endpoint:** `{VOID_AUTH_DOMAIN}/oauth/token`  
**User info endpoint:** `{VOID_AUTH_DOMAIN}/api/user`

> **Single-user / dev mode:** If `VOID_AUTH_CLIENT_ID` is left blank, the app runs without authentication (single default user). Useful for local development.

> The expected user info JSON shape from Void Auth should include at least `id` (or `sub`), `email`, and `name` (or `display_name`). Update the mapping in `app/auth.py:71` if your Void Auth instance returns different field names.

### Email (SMTP)

All email settings are managed through the web UI at `/settings` on a per-user basis. For first-time setup, fill in:

| Field | Example |
|---|---|
| SMTP Host | `smtp.gmail.com` |
| SMTP Port | `587` |
| Username / Password | Your email + app password |
| From / To Address | `you@gmail.com` |
| Links Per Email | `5` |
| Interval (hours) | `24` |

> For Gmail, you'll need an [app password](https://support.google.com/accounts/answer/185833).

## Usage

1. Open **http://localhost:8000** — log in via Void Auth if configured, or use directly in single-user mode.
2. Add bookmarks via the form or REST API.
3. Go to **/settings** — enter your SMTP credentials, recipient email, links-per-email count, and schedule interval.
4. Use **Send Test Email** on the settings page to verify everything works.
5. The scheduler runs automatically for each user on their configured interval.

## API

All API endpoints require authentication when Void Auth is enabled (use browser session cookie or copy from browser).

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/bookmarks` | List your bookmarks |
| `POST` | `/api/bookmarks` | Create a bookmark |
| `DELETE` | `/api/bookmarks/{id}` | Delete a bookmark |
| `GET` | `/api/settings` | Get your settings |
| `POST` | `/api/settings` | Update your settings |
| `POST` | `/api/send-test` | Send a test email |

## Architecture

- **Auth:** `app/auth.py` — Void Auth OIDC client, session-based dependencies
- **Models:** `app/models.py` — `User`, `Bookmark`, `Setting` (all scoped to user)
- **Routes:** `app/routes.py` — HTML and REST API, per-user filtering
- **Settings:** `app/settings_service.py` — Per-user key-value settings in SQLite
- **Email:** `app/email_service.py` — Per-user email composition and SMTP sending
- **Scheduler:** `app/scheduler.py` — Per-user APScheduler jobs

### How Void Auth mapping works

The OAuth callback handler in `app/auth.py` line 71 maps Void Auth user info fields:

```python
user_id = str(user_info.get("id") or user_info.get("sub", ""))
email = str(user_info.get("email", ""))
display_name = str(user_info.get("name") or user_info.get("display_name", email))
```

If your Void Auth instance returns different field names, adjust these mappings in `app/auth.py`.
