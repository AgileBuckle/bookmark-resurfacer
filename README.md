# Bookmark Resurfacer

Stores bookmarks and periodically emails you a random set to revisit.

Supports multiple users via **Void Auth SSO**. All bookmarks and settings are scoped per user.

> **Read [SECURITY.md](SECURITY.md) before exposing this to a network.** It holds
> your SMTP credentials, and it has no authentication at all unless Void Auth is
> configured.

## Quick Start (Docker)

```bash
git clone <repo-url> bookmark-resurfacer
cd bookmark-resurfacer
cp .env.example .env
chmod 600 .env

# REQUIRED: generate a session signing key
echo "SESSION_SECRET=$(openssl rand -hex 32)" >> .env

# Match the data volume to your own user so the non-root container can write
echo "APP_UID=$(id -u)" >> .env
echo "APP_GID=$(id -g)" >> .env

docker compose up --build
```

The app will be available at **http://localhost:8000** (published on `127.0.0.1`
only — see [Production](#production)).

Data persists in the `./data` directory (SQLite). That file contains your SMTP
password in plaintext; the app keeps it at mode `0600` inside a `0700`
directory.

## Configuration

All configuration is read from environment variables, loaded from `.env` at the
project root (`app/config.py`). Real environment variables override the file.
`docker compose` passes `.env` through via `env_file:`.

### Core

| Variable | Default | Description |
|---|---|---|
| `ENVIRONMENT` | `development` | `production` enables strict startup checks, HSTS, secure cookies, and hides `/docs`. |
| `SESSION_SECRET` | — | **Required.** ≥32 random chars signing the session cookie. `openssl rand -hex 32`. A weak value lets anyone forge a session for any user, so startup fails in production or when SSO is on. Blank in development yields a random ephemeral secret. |
| `ALLOWED_HOSTS` | `*` | Comma-separated hostnames accepted in the `Host` header. Set this in production. |
| `COOKIE_SECURE` | auto | Send the session cookie only over HTTPS. Defaults to true in production. |
| `SESSION_MAX_AGE_SECONDS` | `604800` | Session lifetime. Sessions are stateless, so this is also the window a stolen cookie stays valid. |
| `EXPOSE_DOCS` | dev only | Serve `/docs`, `/redoc`, `/openapi.json`. |
| `DATA_DIR` | `./data` | Where `bookmarks.db` lives. |
| `TEST_EMAIL_LIMIT_PER_HOUR` | `5` | Cap on `/api/send-test` per user. |
| `LOGIN_LIMIT_PER_HOUR` | `20` | Cap on login attempts per client IP. |

### Void Auth SSO

Multi-user login via **Void Auth** (OAuth 2.0 authorization code flow with
PKCE). When configured, each user gets their own bookmarks and settings.

| Variable | Description | Example |
|---|---|---|
| `VOID_AUTH_CLIENT_ID` | OAuth client ID | `abc123...` |
| `VOID_AUTH_CLIENT_SECRET` | OAuth client secret | `xyz789...` |
| `VOID_AUTH_DOMAIN` | Your Void Auth instance URL — **must be `https`** | `https://auth.example.com` |
| `VOID_AUTH_REDIRECT_URI` | Callback URL (must match Void Auth config) | `https://bm.example.com/auth/callback` |
| `ALLOWED_EMAILS` | Optional comma-separated allowlist of addresses permitted to sign in | `me@example.com` |

**Authorization endpoint:** `{VOID_AUTH_DOMAIN}/oauth/authorize`
**Token endpoint:** `{VOID_AUTH_DOMAIN}/oauth/token`
**User info endpoint:** `{VOID_AUTH_DOMAIN}/api/user`

The client sends `code_challenge_method=S256` and validates `state` on the
callback. If your provider does not support PKCE it will ignore the extra
parameters.

> **Without `VOID_AUTH_CLIENT_ID` the app has no authentication.** Every visitor
> shares a single `default` account and can read the stored SMTP password.
> Acceptable for localhost-only use; never expose it to a network.

> **Account provisioning:** any account on your Void Auth instance can sign in
> and create its own space unless you set `ALLOWED_EMAILS`.

> The user info response must include at least `id` (or `sub`), `email`, and
> `name` (or `display_name`). Adjust the mapping in `app/main.py` if your
> instance uses different field names.

### Email (SMTP)

Email settings are per user and managed at `/settings`.

| Field | Example |
|---|---|
| SMTP Host | `smtp.gmail.com` |
| SMTP Port | `587` |
| Username / Password | Your email + app password |
| From / To Address | `you@gmail.com` |
| Links Per Email | `5` (1–50) |
| Interval (hours) | `24` (1–8760) |

- Use a provider **app password**, not your primary account password
  ([Gmail instructions](https://support.google.com/accounts/answer/185833)).
- The stored password is **never sent back to the browser**. Leaving the field
  blank keeps the current value; tick *Delete the stored password* to remove it.
- Leave **Use TLS** enabled. Disabling it sends your SMTP credentials over the
  network in cleartext.

## Usage

1. Open **http://localhost:8000** — log in via Void Auth if configured.
2. Add bookmarks via the form or the REST API.
3. Go to **/settings** and fill in SMTP details, recipient, links per email and interval.
4. Use **Send Test Email** to verify.
5. The scheduler then runs per user on the configured interval.

## Production

The app serves plain HTTP and expects to sit behind a TLS-terminating reverse
proxy. The container image runs as a non-root user with all capabilities
dropped and a read-only root filesystem.

```bash
ENVIRONMENT=production
SESSION_SECRET=<openssl rand -hex 32>
ALLOWED_HOSTS=bm.example.com
COOKIE_SECURE=true
VOID_AUTH_REDIRECT_URI=https://bm.example.com/auth/callback
```

`docker-compose.yml` publishes the port on `127.0.0.1` only. Point your proxy
at that address rather than changing the binding. Uvicorn runs with
`--proxy-headers --forwarded-allow-ips 127.0.0.1`, so widen
`--forwarded-allow-ips` only if your proxy is on a different address.

Work through the [deployment checklist](SECURITY.md#deployment-checklist) before
going live.

## API

All endpoints require an authenticated session when Void Auth is enabled, and
**every mutating request requires a CSRF token**.

```bash
# 1. Get a token for your session
curl -c jar -b jar http://localhost:8000/api/csrf-token
# {"csrf_token":"..."}

# 2. Send it in the X-CSRF-Token header
curl -b jar -X POST http://localhost:8000/api/bookmarks \
     -H "Content-Type: application/json" \
     -H "X-CSRF-Token: <token>" \
     -d '{"url":"https://example.com","title":"Example"}'
```

| Method | Endpoint | CSRF | Description |
|---|---|---|---|
| `GET` | `/api/csrf-token` | — | Current session's CSRF token |
| `GET` | `/api/bookmarks?q=&limit=&offset=` | — | List your bookmarks (paginated, max 1000) |
| `POST` | `/api/bookmarks` | yes | Create a bookmark (`http`/`https` URLs only) |
| `PUT` | `/api/bookmarks/{id}` | yes | Update a bookmark |
| `DELETE` | `/api/bookmarks/{id}` | yes | Delete a bookmark |
| `GET` | `/api/settings` | — | Your settings — returns `smtp_password_set`, never the password |
| `POST` | `/api/settings` | yes | Update settings (blank `smtp_password` keeps the stored one; `clear_smtp_password: true` deletes it) |
| `POST` | `/api/send-test` | yes | Send a test email (rate limited) |

## Architecture

- **Config:** `app/config.py` — `.env` loading, startup validation, fail-fast on weak secrets
- **Security:** `app/security.py` — CSRF, input sanitisation, rate limiting, log redaction
- **Auth:** `app/auth.py` — Void Auth OAuth/PKCE client, session dependencies
- **Models:** `app/models.py` — `User`, `Bookmark`, `Setting` (all scoped to user)
- **Routes:** `app/routes.py` — HTML and REST API, per-user filtering
- **Settings:** `app/settings_service.py` — per-user key-value settings, secret masking
- **Email:** `app/email_service.py` — escaped HTML composition and SMTP sending
- **Scheduler:** `app/scheduler.py` — per-user APScheduler jobs

## Security

See **[SECURITY.md](SECURITY.md)** for the threat model, the audit findings and
their remediations, known limitations, and the deployment checklist.
