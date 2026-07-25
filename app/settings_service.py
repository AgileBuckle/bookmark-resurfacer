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


def get_settings(db: Session) -> dict:
    settings = {}
    for key in SETTINGS_DEFAULTS:
        row = db.query(Setting).filter(Setting.key == key).first()
        settings[key] = row.value if row else SETTINGS_DEFAULTS[key]
    return settings


def get_setting(db: Session, key: str) -> str:
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row else SETTINGS_DEFAULTS.get(key, "")


def save_settings(db: Session, data: dict) -> None:
    for key in SETTINGS_DEFAULTS:
        if key in data:
            value = str(data[key]).lower() if isinstance(data[key], bool) else str(data[key])
            row = db.query(Setting).filter(Setting.key == key).first()
            if row:
                row.value = value
            else:
                db.add(Setting(key=key, value=value))
    db.commit()