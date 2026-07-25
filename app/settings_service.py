from sqlalchemy.orm import Session
from app.models import Setting

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


def get_settings(db: Session, user_id: str) -> dict:
    settings = {}
    for key in SETTINGS_DEFAULTS:
        row = (
            db.query(Setting)
            .filter(Setting.user_id == user_id, Setting.key == key)
            .first()
        )
        settings[key] = row.value if row else SETTINGS_DEFAULTS[key]
    return settings


def get_setting(db: Session, user_id: str, key: str) -> str:
    row = (
        db.query(Setting)
        .filter(Setting.user_id == user_id, Setting.key == key)
        .first()
    )
    return row.value if row else SETTINGS_DEFAULTS.get(key, "")


def save_settings(db: Session, user_id: str, data: dict) -> None:
    for key in SETTINGS_DEFAULTS:
        if key in data:
            value = str(data[key]).lower() if isinstance(data[key], bool) else str(data[key])
            row = (
                db.query(Setting)
                .filter(Setting.user_id == user_id, Setting.key == key)
                .first()
            )
            if row:
                row.value = value
            else:
                db.add(Setting(user_id=user_id, key=key, value=value))
    db.commit()
