"""
Shared security primitives: CSRF tokens, input sanitisation and rate limiting.
"""

import html
import logging
import re
import secrets
import time
from collections import defaultdict, deque
from urllib.parse import parse_qsl, urlencode, urlparse

from fastapi import HTTPException, Request

# --------------------------------------------------------------------------
# CSRF
# --------------------------------------------------------------------------

CSRF_SESSION_KEY = "csrf_token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_FORM_CONTENT_TYPES = (
    "application/x-www-form-urlencoded",
    "multipart/form-data",
)


def get_csrf_token(request: Request) -> str:
    """Return the session's CSRF token, creating one on first use."""
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


async def verify_csrf(request: Request) -> None:
    """
    FastAPI dependency: reject unsafe requests without a valid CSRF token.

    The token is accepted from the `X-CSRF-Token` header (JSON/fetch clients) or
    from a `csrf_token` form field (HTML forms). `SameSite=Lax` cookies are not
    sufficient on their own, so this is enforced for every mutating endpoint.
    """
    if request.method in SAFE_METHODS:
        return

    expected = request.session.get(CSRF_SESSION_KEY)
    submitted = request.headers.get(CSRF_HEADER_NAME)

    if not submitted:
        content_type = request.headers.get("content-type", "")
        if any(content_type.startswith(ct) for ct in _FORM_CONTENT_TYPES):
            form = await request.form()
            value = form.get(CSRF_FORM_FIELD)
            submitted = value if isinstance(value, str) else None

    if not expected or not submitted or not secrets.compare_digest(expected, submitted):
        raise HTTPException(
            status_code=403,
            detail=(
                "CSRF token missing or invalid. Reload the page, or send the token "
                f"from GET /api/csrf-token in the {CSRF_HEADER_NAME} header."
            ),
        )


# --------------------------------------------------------------------------
# Input sanitisation
# --------------------------------------------------------------------------

ALLOWED_URL_SCHEMES = frozenset({"http", "https"})
MAX_URL_LENGTH = 2048
MAX_TITLE_LENGTH = 512
MAX_TAGS_LENGTH = 512
MAX_DESCRIPTION_LENGTH = 8192
MAX_HEADER_LENGTH = 512

_CONTROL_CHARS = re.compile(r"[\r\n\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_url(raw: str) -> str:
    """
    Normalise a bookmark URL, rejecting anything that is not http(s).

    Blocks `javascript:`, `data:`, `vbscript:` and `file:` URIs, which would
    otherwise be rendered as clickable links in the UI and in outgoing email.
    """
    url = _CONTROL_CHARS.sub("", (raw or "").strip())
    if not url:
        raise HTTPException(status_code=422, detail="URL is required.")
    if len(url) > MAX_URL_LENGTH:
        raise HTTPException(
            status_code=422, detail=f"URL exceeds {MAX_URL_LENGTH} characters."
        )
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_URL_SCHEMES:
        raise HTTPException(
            status_code=422, detail="URL must start with http:// or https://"
        )
    if not parsed.netloc:
        raise HTTPException(status_code=422, detail="URL is missing a hostname.")
    return url


def is_safe_url(raw: str | None) -> bool:
    """Non-raising variant of `validate_url`, for rendering existing rows."""
    if not raw:
        return False
    parsed = urlparse(raw.strip())
    return parsed.scheme.lower() in ALLOWED_URL_SCHEMES and bool(parsed.netloc)


def clean_text(raw: str | None, max_length: int) -> str | None:
    """Trim, strip control characters and length-cap a free-text field."""
    if raw is None:
        return None
    value = _CONTROL_CHARS.sub("", raw).strip()
    if not value:
        return None
    return value[:max_length]


def sanitize_header(raw: str | None, max_length: int = MAX_HEADER_LENGTH) -> str:
    """
    Strip CR/LF and NUL from a value destined for an email header.

    Without this, a crafted subject or address can inject extra headers
    (e.g. `Bcc:`) into the outgoing message.
    """
    if not raw:
        return ""
    return _CONTROL_CHARS.sub("", raw).strip()[:max_length]


def is_valid_email(raw: str | None) -> bool:
    value = sanitize_header(raw)
    return bool(value) and bool(_EMAIL_RE.match(value))


def escape_html(raw: str | None) -> str:
    """Escape a value for interpolation into an HTML document (incl. quotes)."""
    return html.escape(raw or "", quote=True)


def safe_relative_path(url_path: str) -> str:
    """
    Reduce a URL to a same-origin relative path.

    Used for post-login redirects so a poisoned Host header or a crafted
    `next` value cannot turn the login flow into an open redirect.
    """
    parsed = urlparse(_CONTROL_CHARS.sub("", url_path or ""))
    # Only the path/query are ever kept, so any scheme or host in the input
    # (including protocol-relative "//evil.com") is discarded outright.
    path = parsed.path or "/"
    if not path.startswith("/") or path.startswith("//"):
        return "/"
    return f"{path}?{parsed.query}" if parsed.query else path


# --------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------


class RateLimiter:
    """
    Fixed-window in-memory rate limiter.

    Deliberately simple: state lives in this process only, so it does not hold
    across restarts or multiple workers. It is a speed bump against abuse of
    expensive endpoints (outbound email, token exchange), not a hard quota.
    Put a real limiter in the reverse proxy for internet-facing deployments.
    """

    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> bool:
        now = time.monotonic()
        events = self._events[key]
        while events and now - events[0] > self.window_seconds:
            events.popleft()
        if len(events) >= self.max_events:
            return False
        events.append(now)
        return True

    def enforce(self, key: str, detail: str = "Too many requests.") -> None:
        if not self.check(key):
            raise HTTPException(status_code=429, detail=detail)


# --------------------------------------------------------------------------
# Log redaction
# --------------------------------------------------------------------------

SENSITIVE_QUERY_PARAMS = frozenset(
    {"code", "state", "token", "access_token", "id_token", "refresh_token", "password"}
)
REDACTED = "[REDACTED]"


def redact_query_string(path: str) -> str:
    if "?" not in path:
        return path
    base, _, query = path.partition("?")
    pairs = [
        (key, REDACTED if key.lower() in SENSITIVE_QUERY_PARAMS else value)
        for key, value in parse_qsl(query, keep_blank_values=True)
    ]
    return f"{base}?{urlencode(pairs, safe='[]/')}" if pairs else base


class QueryRedactionFilter(logging.Filter):
    """
    Strip OAuth codes and tokens out of access-log lines.

    `/auth/callback?code=...` is a plain GET, so without this the single-use
    authorization code is written to disk in cleartext on every login.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = args[:2] + (redact_query_string(args[2]),) + args[3:]
        return True


def install_log_redaction() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, QueryRedactionFilter) for f in access_logger.filters):
        access_logger.addFilter(QueryRedactionFilter())
