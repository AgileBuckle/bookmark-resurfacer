"""
Central configuration.

Loads `.env` explicitly (nothing else in the app reads `os.environ` directly)
and fails fast on insecure production configuration.
"""

import os
import secrets
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

# Load .env from the project root. Real environment variables win, so
# `docker compose` / systemd / shell exports always override the file.
load_dotenv(PROJECT_ROOT / ".env", override=False)

INSECURE_SECRETS = {"", "change-me-in-production", "changeme", "secret"}
MIN_SECRET_LENGTH = 32


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


class Config:
    def __init__(self) -> None:
        self.environment = _env("ENVIRONMENT", "development").lower()

        # --- Void Auth SSO ---
        self.void_auth_client_id = _env("VOID_AUTH_CLIENT_ID")
        self.void_auth_client_secret = _env("VOID_AUTH_CLIENT_SECRET")
        self.void_auth_domain = _env("VOID_AUTH_DOMAIN").rstrip("/")
        self.void_auth_redirect_uri = _env(
            "VOID_AUTH_REDIRECT_URI", "http://localhost:8000/auth/callback"
        )
        # Optional allowlist: only these emails may create/keep an account.
        self.allowed_emails = {
            e.strip().lower()
            for e in _env("ALLOWED_EMAILS").split(",")
            if e.strip()
        }

        # --- Storage ---
        self.data_dir = Path(_env("DATA_DIR", str(PROJECT_ROOT / "data")))
        self.database_url = f"sqlite:///{self.data_dir / 'bookmarks.db'}"

        # --- HTTP hardening ---
        # Comma-separated hostnames accepted in the Host header. "*" disables
        # the check (only safe when a trusted reverse proxy sets Host).
        self.allowed_hosts = [
            h.strip() for h in _env("ALLOWED_HOSTS", "*").split(",") if h.strip()
        ]
        self.expose_docs = _env_bool("EXPOSE_DOCS", self.is_development)
        self.session_max_age = _env_int("SESSION_MAX_AGE_SECONDS", 60 * 60 * 24 * 7)

        # --- Rate limits ---
        self.test_email_limit = _env_int("TEST_EMAIL_LIMIT_PER_HOUR", 5)
        self.login_limit = _env_int("LOGIN_LIMIT_PER_HOUR", 20)

        self.session_secret = self._resolve_session_secret()
        self.cookie_secure = _env_bool("COOKIE_SECURE", self._default_cookie_secure())

        self._validate()

    # -- derived ----------------------------------------------------------

    @property
    def is_production(self) -> bool:
        return self.environment in {"production", "prod"}

    @property
    def is_development(self) -> bool:
        return not self.is_production

    @property
    def sso_enabled(self) -> bool:
        return bool(
            self.void_auth_client_id
            and self.void_auth_client_secret
            and self.void_auth_domain
        )

    def _default_cookie_secure(self) -> bool:
        if self.is_production:
            return True
        return self.void_auth_redirect_uri.startswith("https://")

    # -- secret handling --------------------------------------------------

    def _resolve_session_secret(self) -> str:
        secret = _env("SESSION_SECRET")
        insecure = secret.lower() in INSECURE_SECRETS or len(secret) < MIN_SECRET_LENGTH

        if not insecure:
            return secret

        # A weak session secret means anyone can forge a session cookie for any
        # user, so refuse to start in any configuration that has real users.
        if self.is_production or self.sso_enabled:
            raise RuntimeError(
                "SESSION_SECRET is missing, too short, or still set to the example "
                f"value. It must be at least {MIN_SECRET_LENGTH} characters of random "
                "data. Generate one with: openssl rand -hex 32"
            )

        print(
            "WARNING: SESSION_SECRET is not set. Using a random ephemeral secret; "
            "all sessions will be invalidated on restart. Set SESSION_SECRET in .env "
            "for anything other than throwaway local use.",
            file=sys.stderr,
        )
        return secrets.token_urlsafe(48)

    # -- validation -------------------------------------------------------

    def _validate(self) -> None:
        if self.sso_enabled:
            scheme = urlparse(self.void_auth_domain).scheme
            if scheme != "https":
                raise RuntimeError(
                    "VOID_AUTH_DOMAIN must use https:// — OAuth client secrets and "
                    f"tokens must never traverse a plaintext channel (got {scheme!r})."
                )
            if self.is_production and not self.void_auth_redirect_uri.startswith("https://"):
                raise RuntimeError(
                    "VOID_AUTH_REDIRECT_URI must use https:// in production."
                )

        if self.is_production and "*" in self.allowed_hosts:
            print(
                "WARNING: ALLOWED_HOSTS is '*' in production. Set it to your real "
                "hostname(s) to prevent Host-header poisoning.",
                file=sys.stderr,
            )

        if self.is_production and not self.sso_enabled:
            print(
                "WARNING: Void Auth is not configured, so the app is running with NO "
                "AUTHENTICATION. Every visitor shares one account and can read the "
                "stored SMTP credentials. Do not expose this to a network.",
                file=sys.stderr,
            )


config = Config()
