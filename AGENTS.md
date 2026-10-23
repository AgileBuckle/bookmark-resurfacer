# AGENTS.md

Guide for AI coding agents working in this repo.

## What this is

**Bookmark Resurfacer**: a small self-hosted FastAPI app that stores bookmarks and periodically
emails each user a random set to revisit. Multi-user via Void Auth SSO (OAuth 2.0 + PKCE);
data is SQLite. It stores users' SMTP passwords, so treat security as the top concern.

## Layout

- `app/main.py` - FastAPI app, middleware (sessions, trusted hosts, CSP), login/callback routes.
- `app/config.py` - the only place that reads env vars / `.env`; fails fast on weak secrets.
- `app/routes.py` - HTML pages and the REST API (`/api/...`), filtered per user.
- `app/auth.py` (Void Auth client), `app/security.py` (CSRF, sanitising, rate limits, log
  redaction), `app/models.py` (`User`, `Bookmark`, `Setting`), `app/database.py`,
  `app/settings_service.py`, `app/email_service.py`, `app/scheduler.py` (per-user APScheduler jobs).
- `app/templates/` (Jinja2), `app/static/` (plain JS/CSS, no build step).
- `README.md` (config, API table), `SECURITY.md` (threat model, audit, deployment checklist),
  `todo.md` (owner's task list).

## Run

```sh
cp .env.example .env && chmod 600 .env
echo "SESSION_SECRET=$(openssl rand -hex 32)" >> .env
echo "APP_UID=$(id -u)" >> .env; echo "APP_GID=$(id -g)" >> .env
docker compose up --build          # http://localhost:8000
```

Without Docker (Python 3.12, as in the `Dockerfile`):

```sh
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

There is no test suite, linter config, or CI in this repo. Verify changes by running the app.
Tables are created with `Base.metadata.create_all` at startup; there are no migrations, so
schema changes need care with existing `data/bookmarks.db` files.

## Conventions and gotchas

- All config goes through `app/config.py`; don't read `os.environ` elsewhere. Document new
  variables in the README tables and `.env.example`.
- Every query must filter on `user_id`; there is no cross-user path and no admin role.
- Every mutating endpoint needs a CSRF token, except `/api/quick-add` (uses `X-API-Key`).
- Never return the SMTP password to the browser (`/api/settings` only exposes `smtp_password_set`).
- Without `VOID_AUTH_CLIENT_ID` there is no authentication (single shared `default` user).
- Never commit `.env`, `data/`, `*.db` or keys (all gitignored); the DB holds SMTP passwords.
- The container runs non-root with a read-only root FS; write only to `/app/data` or `/tmp`.
- If you change security behavior, update `SECURITY.md` to match.
- Note: README says the port is published on `127.0.0.1` only, but `docker-compose.yml`
  currently maps `8000:8000` and the `Dockerfile` uses `--forwarded-allow-ips "*"`. Don't
  "fix" either without being asked; just be aware.
