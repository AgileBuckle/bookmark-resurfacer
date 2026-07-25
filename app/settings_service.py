from sqlalchemy.orm import Session

from app.models import Setting
from app.security import (
    MAX_HEADER_LENGTH,
    sanitize_header,
)

SETTINGS_DEFAULTS = {
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_username": "",
    "smtp_password": "",
    "smtp_use_tls": "true",
    "email_from": "",
    "email_to": "",
    "email_subject": "Your Bookmarks to Revisit",
    "links_per_email": "5",
    "schedule_interval_hours": "24",
}

# Never returned to a client, never rendered into a template.
SECRET_KEYS = frozenset({"smtp_password"})

# Keys that end up in email headers or SMTP dialogue and must not contain
# control characters.
HEADER_KEYS = frozenset(
    {"smtp_host", "smtp_username", "email_from", "email_to", "email_subject"}
)

_NUMERIC_BOUNDS = {
    "smtp_port": (1, 65535, 587),
    "links_per_email": (1, 50, 5),
    "schedule_interval_hours": (1, 8760, 24),
}


def get_settings(db: Session, user_id: str) -> dict:
    """Full settings, including secrets. Server-side use only."""
    rows = {
        row.key: row.value
        for row in db.query(Setting).filter(Setting.user_id == user_id).all()
    }
    return {
        key: rows.get(key) if rows.get(key) is not None else default
        for key, default in SETTINGS_DEFAULTS.items()
    }


def get_settings_public(db: Session, user_id: str) -> dict:
    """
    Settings safe to send to a client or render in a template.

    Secrets are replaced with an empty string plus a `*_set` boolean so the UI
    can show whether a value is stored without ever disclosing it.
    """
    settings = get_settings(db, user_id)
    for key in SECRET_KEYS:
        settings[f"{key}_set"] = bool(settings.get(key))
        settings[key] = ""
    return settings


def get_setting(db: Session, user_id: str, key: str) -> str:
    row = (
        db.query(Setting)
        .filter(Setting.user_id == user_id, Setting.key == key)
        .first()
    )
    return row.value if row else SETTINGS_DEFAULTS.get(key, "")


def _normalize(key: str, raw) -> str:
    if isinstance(raw, bool):
        return "true" if raw else "false"

    value = "" if raw is None else str(raw)

    if key in _NUMERIC_BOUNDS:
        low, high, fallback = _NUMERIC_BOUNDS[key]
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            number = fallback
        return str(max(low, min(number, high)))

    if key in HEADER_KEYS:
        return sanitize_header(value, MAX_HEADER_LENGTH)

    return value[:1024]


def _write(db: Session, user_id: str, key: str, value: str) -> None:
    row = (
        db.query(Setting)
        .filter(Setting.user_id == user_id, Setting.key == key)
        .first()
    )
    if row:
        row.value = value
    else:
        db.add(Setting(user_id=user_id, key=key, value=value))


def save_settings(
    db: Session,
    user_id: str,
    data: dict,
    *,
    clear_secrets: frozenset[str] | set[str] = frozenset(),
) -> None:
    """
    Persist settings.

    A blank secret means "leave the stored value alone" — the UI never receives
    the current password, so it cannot echo it back. Pass the key in
    `clear_secrets` to explicitly delete a stored secret.
    """
    for key in SETTINGS_DEFAULTS:
        if key in SECRET_KEYS:
            if key in clear_secrets:
                _write(db, user_id, key, "")
                continue
            submitted = str(data.get(key) or "")
            if not submitted.strip():
                continue
            _write(db, user_id, key, submitted)
            continue

        if key in data:
            _write(db, user_id, key, _normalize(key, data[key]))

    db.commit()
