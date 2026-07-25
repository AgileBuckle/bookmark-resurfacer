from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class BookmarkCreate(BaseModel):
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[str] = None


class BookmarkOut(BaseModel):
    id: int
    url: str
    title: Optional[str]
    description: Optional[str]
    tags: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class EmailSettings(BaseModel):
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    email_from: str = ""
    email_to: str = ""
    email_subject: str = "Your Bookmarks to Revisit"
    links_per_email: int = 5
    schedule_interval_hours: int = 24


class EmailSettingsOut(BaseModel):
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_use_tls: bool
    email_from: str
    email_to: str
    email_subject: str
    links_per_email: int
    schedule_interval_hours: int