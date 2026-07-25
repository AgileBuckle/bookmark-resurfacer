import os
import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

VOID_AUTH_CLIENT_ID = os.getenv("VOID_AUTH_CLIENT_ID", "")
VOID_AUTH_CLIENT_SECRET = os.getenv("VOID_AUTH_CLIENT_SECRET", "")
VOID_AUTH_REDIRECT_URI = os.getenv("VOID_AUTH_REDIRECT_URI", "http://localhost:8000/auth/callback")
VOID_AUTH_DOMAIN = os.getenv("VOID_AUTH_DOMAIN", "https://voidauth.example.com")
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-me-in-production")


class VoidAuthClient:
    """
    Void Auth SSO client.

    Replace the URL templates below with the actual Void Auth endpoints
    once you have your Void Auth instance configured.

    Example flow:
    - Authorization URL:  VOID_AUTH_DOMAIN + "/oauth/authorize"
    - Token URL:          VOID_AUTH_DOMAIN + "/oauth/token"
    - User info URL:      VOID_AUTH_DOMAIN + "/api/user"
    """

    def __init__(self):
        self.client_id = VOID_AUTH_CLIENT_ID
        self.client_secret = VOID_AUTH_CLIENT_SECRET
        self.redirect_uri = VOID_AUTH_REDIRECT_URI
        self.domain = VOID_AUTH_DOMAIN

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def get_authorization_url(self, state: str) -> str:
        return (
            f"{self.domain}/oauth/authorize"
            f"?client_id={self.client_id}"
            f"&redirect_uri={self.redirect_uri}"
            f"&response_type=code"
            f"&state={state}"
            f"&scope=openid+profile+email"
        )

    async def exchange_code(self, code: str) -> dict | None:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{self.domain}/oauth/token",
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": self.redirect_uri,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                    headers={"Accept": "application/json"},
                )
                resp.raise_for_status()
                return resp.json()
            except Exception:
                return None

    async def get_user_info(self, access_token: str) -> dict | None:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{self.domain}/api/user",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                    },
                )
                resp.raise_for_status()
                return resp.json()
            except Exception:
                return None


void_auth = VoidAuthClient()

SESSION_COOKIE_NAME = "br_session"
DEFAULT_USER_ID = "default"


def _get_or_create_default_user(db: Session) -> User:
    user = db.query(User).filter(User.id == DEFAULT_USER_ID).first()
    if not user:
        user = User(id=DEFAULT_USER_ID, email="", display_name="Local User")
        db.add(user)
        db.commit()
    return user


def _get_user_from_session(request: Request, db: Session) -> User | None:
    session_data = request.session.get("user")
    if not session_data:
        return None
    user_id = session_data.get("id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    if not void_auth.is_configured:
        return _get_or_create_default_user(db)
    user = _get_user_from_session(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    if not void_auth.is_configured:
        return _get_or_create_default_user(db)
    return _get_user_from_session(request, db)


def require_user_or_redirect(request: Request, db: Session = Depends(get_db)) -> User:
    if not void_auth.is_configured:
        return _get_or_create_default_user(db)
    user = _get_user_from_session(request, db)
    if user is None:
        request.session["post_login_redirect"] = str(request.url)
        raise HTTPException(
            status_code=302,
            headers={"Location": "/auth/login"},
        )
    return user
