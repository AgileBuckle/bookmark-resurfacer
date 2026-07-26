from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.security import (
    MAX_DESCRIPTION_LENGTH,
    MAX_TAGS_LENGTH,
    MAX_TITLE_LENGTH,
    MAX_URL_LENGTH,
    is_valid_email,
    sanitize_header,
)


class BookmarkCreate(BaseModel):
    """Length caps prevent unbounded rows; the URL scheme is checked in routes."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: str = Field(min_length=1, max_length=MAX_URL_LENGTH)
    title: Optional[str] = Field(default=None, max_length=MAX_TITLE_LENGTH)
    description: Optional[str] = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    tags: Optional[str] = Field(default=None, max_length=MAX_TAGS_LENGTH)


class BookmarkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: Optional[str] = Field(default=None, min_length=1, max_length=MAX_URL_LENGTH)
    title: Optional[str] = Field(default=None, max_length=MAX_TITLE_LENGTH)
    description: Optional[str] = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    tags: Optional[str] = Field(default=None, max_length=MAX_TAGS_LENGTH)


class BookmarkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    title: Optional[str]
    description: Optional[str]
    tags: Optional[str]
    created_at: datetime


class EmailSettings(BaseModel):
    """
    Inbound settings payload.

    `smtp_password` is write-only: leave it out (or blank) to keep the stored
    value, and set `clear_smtp_password` to delete it.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    smtp_host: str = Field(default="", max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = Field(default="", max_length=320)
    smtp_password: str = Field(default="", max_length=1024)
    clear_smtp_password: bool = False
    smtp_use_tls: bool = True
    email_from: str = Field(default="", max_length=320)
    email_to: str = Field(default="", max_length=320)
    email_subject: str = Field(default="Your Bookmarks to Revisit", max_length=255)
    email_body_template: str = Field(default="", max_length=16384)
    links_per_email: int = Field(default=5, ge=1, le=50)
    schedule_interval_hours: int = Field(default=24, ge=1, le=8760)
    schedule_hour: int = Field(default=9, ge=0, le=23)
    schedule_minute: int = Field(default=0, ge=0, le=59)

    @field_validator("smtp_host", "smtp_username", "email_subject")
    @classmethod
    def _strip_control_chars(cls, value: str) -> str:
        return sanitize_header(value)

    @field_validator("email_from", "email_to")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        cleaned = sanitize_header(value)
        if cleaned and not is_valid_email(cleaned):
            raise ValueError("must be a single valid email address")
        return cleaned


class EmailSettingsOut(BaseModel):
    """Outbound settings view — deliberately omits `smtp_password`."""

    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_use_tls: bool
    email_from: str
    email_to: str
    email_subject: str
    email_body_template: str
    links_per_email: int
    schedule_interval_hours: int
    schedule_hour: int
    schedule_minute: int
    smtp_password_set: bool
