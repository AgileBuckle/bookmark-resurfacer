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
| `QUICK_ADD_LIMIT_PER_HOUR` | `100` | Cap on `/api/quick-add` (Shortcuts) per API key. |

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
| SMTP Host | `smtp.email.com` |
| SMTP Port | `587` |
| Username / Password | Your email + app password |
| From / To Address | `you@email.com` |
| Subject | `Your Bookmarks to Revisit` |
| Body Template | HTML with `{subject}` and `{bookmarks_list}` placeholders |
| Links Per Email | `5` (1–50) |
| Interval (hours) | `24` (1–8760) |
| Send Time | Hour (0–23) and minute (0–59) in UTC |

- Use a provider **app password**, not your primary account password
  ([Gmail instructions](https://support.google.com/accounts/answer/185833)).
- The stored password is **never sent back to the browser**. Leaving the field
  blank keeps the current value; tick *Delete the stored password* to remove it.
- Leave **Use TLS** enabled. Disabling it sends your SMTP credentials over the
  network in cleartext.
- The interval is rounded to the nearest day for scheduling (24 h = daily,
  48 h = every other day, 168 h = weekly). Emails go out at the configured
  hour and minute.

## Usage

1. Open **http://localhost:8000** — log in via Void Auth if configured.
2. Add bookmarks via the form or the REST API.
3. Go to **/settings** and fill in SMTP details, recipient, links per email and interval.
4. Use **Send Test Email** to verify.
5. The scheduler then runs per user on the configured interval.

## Apple Shortcuts

You can submit bookmarks directly from Safari, a share sheet, or any Shortcut
without opening the web app. The app exposes a `POST /api/quick-add` endpoint
that authenticates with a per-user API key instead of a session cookie or CSRF
token.

### 1. Get your API key

Open **Settings** and scroll to **API Access**. The first time, click
**Generate API Key**. The key appears once — copy it immediately. If you lose
it, regenerate a new one (the old key stops working).

### 2. Set up the Shortcut

Create a new Shortcut in the **Shortcuts** app:

1. **Add an action** — search for *"Get URLs from Input"* and add it as the
   **receive input type** (tap "Shortcut Input", select "URL").
2. **Add a *Text* action** and set the content to:

   ```
   https://YOUR_SERVER/api/quick-add
   ```

   Replace `YOUR_SERVER` with your app's address (e.g. `bm.example.com`).

3. **Add a *Get Contents of URL* action** (the `POST` variant):
   - **Method:** `POST`
   - **Request Body:** `JSON`
   - Add a new field `"url"` with type **Text** and value **Shortcut Input**.
   - Add a new field `"title"` with type **Text** and value
     **Shortcut Input** (the Shortcuts app auto-extracts page titles).
   - Add a header `X-API-Key` — paste your API key as the value.

   > **Tip:** To also capture the page title, add a *"Get Name of [Shortcut Input]"*
   > action before the *Get Contents of URL* action and use that variable
   > for the `"title"` field.

4. **Name the shortcut** (e.g. "Bookmark This") and **save**.

### 3. Use it

- **From Safari:** tap the Share button → scroll to "Bookmark This".
- **From the Share Sheet:** share any URL → run the shortcut.
- **From Siri:** say "Bookmark This" while viewing a page.

The bookmark appears on your `/` page and in the next scheduled email.

### Shortcut JSON format

```json
{
  "url": "https://example.com",
  "title": "Example Page",
  "description": "Why this is worth revisiting",
  "tags": "comma, separated, tags"
}
```

Only `url` is required. The `title`, `description`, and `tags` fields are
optional. Bare domains (e.g. `voxelith.art`) are automatically upgraded to
`https://voxelith.art`.

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
**every mutating request requires a CSRF token** (except `/api/quick-add`, which
uses an API key instead).

**Session-based requests** (web app / curl):

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

**API key requests** (Shortcuts / automation):

```bash
curl -X POST http://localhost:8000/api/quick-add \
     -H "Content-Type: application/json" \
     -H "X-API-Key: br_xxxx-your-api-key-here" \
     -d '{"url":"https://example.com","title":"Example"}'
```

| Method | Endpoint | Auth / CSRF | Description |
|---|---|---|---|
| `GET` | `/api/csrf-token` | session | Current session's CSRF token |
| `GET` | `/api/bookmarks?q=&limit=&offset=` | session | List your bookmarks (paginated, max 1000) |
| `POST` | `/api/bookmarks` | session + CSRF | Create a bookmark (`http`/`https` URLs only) |
| `PUT` | `/api/bookmarks/{id}` | session + CSRF | Update a bookmark |
| `DELETE` | `/api/bookmarks/{id}` | session + CSRF | Delete a bookmark |
| `GET` | `/api/settings` | session | Your settings — returns `smtp_password_set`, never the password |
| `POST` | `/api/settings` | session + CSRF | Update settings (blank `smtp_password` keeps the stored one; `clear_smtp_password: true` deletes it) |
| `POST` | `/api/send-test` | session + CSRF | Send a test email (rate limited) |
| `POST` | `/api/quick-add` | `X-API-Key` header | Create a bookmark. Designed for Apple Shortcuts — no session or CSRF needed. (rate limited) |
| `POST` | `/api/regenerate-api-key` | session + CSRF | Rotate the API key — the old key stops working immediately |

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
