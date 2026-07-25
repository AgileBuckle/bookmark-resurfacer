# Bookmark Resurfacer

Stores bookmarks and periodically emails you a random set to revisit.

## Quick Start (Docker)

```bash
docker compose up --build
```

The app will be available at **http://localhost:8000**.

Data persists in the `./data` directory (SQLite).

## Usage

1. Open **http://localhost:8000** — add bookmarks via the form or REST API.
2. Go to **/settings** — enter your SMTP credentials, recipient email, links-per-email count, and schedule interval.
3. Use **Send Test Email** on the settings page to verify everything works.
4. The scheduler runs automatically on the configured interval.

## Configuration

All email settings are managed through the web UI at `/settings`. For first-time setup, fill in:

| Field | Example |
|---|---|
| SMTP Host | `smtp.gmail.com` |
| SMTP Port | `587` |
| Username / Password | Your email + app password |
| From / To Address | `you@gmail.com` |
| Links Per Email | `5` |
| Interval (hours) | `24` |

> For Gmail, you'll need an [app password](https://support.google.com/accounts/answer/185833).

## API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/bookmarks` | List all bookmarks |
| `POST` | `/api/bookmarks` | Create a bookmark |
| `DELETE` | `/api/bookmarks/{id}` | Delete a bookmark |
| `GET` | `/api/settings` | Get current settings |
| `POST` | `/api/settings` | Update settings |