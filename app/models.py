import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


def utcnow() -> datetime.datetime:
    """Naive UTC timestamp (SQLite stores no offset; keep all rows consistent)."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id = Column(String(256), primary_key=True)
    email = Column(String(256), nullable=True)
    display_name = Column(String(256), nullable=True)
    last_email_sent_at = Column(DateTime, nullable=True)

    bookmarks = relationship("Bookmark", back_populates="user", cascade="all, delete-orphan")
    settings = relationship("Setting", back_populates="user", cascade="all, delete-orphan")


class Bookmark(Base):
    __tablename__ = "bookmarks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(256), ForeignKey("users.id"), nullable=False, index=True)
    url = Column(String(2048), nullable=False)
    title = Column(String(512), nullable=True)
    description = Column(Text, nullable=True)
    tags = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    user = relationship("User", back_populates="bookmarks")


class Setting(Base):
    __tablename__ = "settings"

    user_id = Column(String(256), ForeignKey("users.id"), primary_key=True)
    key = Column(String(128), primary_key=True)
    value = Column(Text, nullable=True)

    user = relationship("User", back_populates="settings")
