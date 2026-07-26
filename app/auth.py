import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import config
from app.database import get_db
from app.models import User
from app.security import safe_relative_path

# HTTP calls to the identity provider must not hang a worker indefinitely.
OAUTH_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class VoidAuthClient:
    """
    Void Auth SSO client (OAuth 2.0 authorization code flow with PKCE).

    Endpoints, relative to VOID_AUTH_DOMAIN:
    - Authorization: /oidc/auth
    - Token:         /oidc/token
    - User info:     /oidc/me

    Security notes:
    - VOID_AUTH_DOMAIN is required to be https (enforced in app/config.py).
    - PKCE (S256) is always sent, so an intercepted authorization code cannot
      be redeemed without the verifier held in the user's session.
    - TLS verification is left at httpx's default (enabled); do not disable it.
    """

    def __init__(self) -> None:
        self.client_id = config.void_auth_client_id
        self.client_secret = config.void_auth_client_secret
        self.redirect_uri = config.void_auth_redirect_uri
        self.domain = config.void_auth_domain

    @property
    def is_configured(self) -> bool:
        return config.sso_enabled

    @staticmethod
    def generate_pkce_pair() -> tuple[str, str]:
        verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return verifier, challenge

    def get_authorization_url(self, state: str, code_challenge: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "state": state,
            "scope": "openid profile email",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.domain}/oidc/auth?{urlencode(params)}"

    async def exchange_code(self, code: str, code_verifier: str) -> dict | None:
        async with httpx.AsyncClient(timeout=OAUTH_TIMEOUT) as client:
            try:
                resp = await client.post(
                    f"{self.domain}/oidc/token",
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": self.redirect_uri,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "code_verifier": code_verifier,
                    },
                    headers={"Accept": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, dict) else None
            except Exception as exc:
                # Never surface provider responses to the client: they can
                # contain the client secret or token material.
                print(f"OAuth token exchange failed: {type(exc).__name__}")
                return None

    async def get_user_info(self, access_token: str) -> dict | None:
        async with httpx.AsyncClient(timeout=OAUTH_TIMEOUT) as client:
            try:
                resp = await client.get(
                    f"{self.domain}/oidc/me",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, dict) else None
            except Exception as exc:
                print(f"OAuth user-info request failed: {type(exc).__name__}")
                return None


void_auth = VoidAuthClient()

SESSION_COOKIE_NAME = "br_session"
DEFAULT_USER_ID = "default"


def is_email_allowed(email: str) -> bool:
    """Enforce the optional ALLOWED_EMAILS allowlist."""
    if not config.allowed_emails:
        return True
    return (email or "").strip().lower() in config.allowed_emails


def _get_or_create_default_user(db: Session) -> User:
    user = db.query(User).filter(User.id == DEFAULT_USER_ID).first()
    if not user:
        user = User(id=DEFAULT_USER_ID, email="", display_name="Local User")
        db.add(user)
        db.commit()
    return user


def _get_user_from_session(request: Request, db: Session) -> User | None:
    session_data = request.session.get("user")
    if not isinstance(session_data, dict):
        return None
    user_id = session_data.get("id")
    if not user_id or not isinstance(user_id, str):
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
        # Store only the relative path: an absolute URL is derived from the
        # client-supplied Host header and would enable an open redirect.
        request.session["post_login_redirect"] = safe_relative_path(
            str(request.url.path) + (f"?{request.url.query}" if request.url.query else "")
        )
        raise HTTPException(
            status_code=302,
            headers={"Location": "/auth/login"},
        )
    return user
