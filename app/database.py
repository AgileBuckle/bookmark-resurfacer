import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import config

DATABASE_URL = config.database_url

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

DB_PATH = config.data_dir / "bookmarks.db"


def secure_database_file() -> None:
    """
    Restrict the SQLite file to owner-only access.

    The database stores SMTP credentials in plaintext, so a world-readable file
    (the default 0644 under most umasks) leaks them to any local user or to
    anything that can read the bind-mounted ./data directory.
    """
    for path in (DB_PATH, DB_PATH.with_name(DB_PATH.name + "-wal"), DB_PATH.with_name(DB_PATH.name + "-shm")):
        try:
            if path.exists():
                os.chmod(path, 0o600)
        except OSError:
            pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
