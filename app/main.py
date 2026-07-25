import os
import secrets

from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.orm import Session

from app.config import config
from app.database import engine, Base, get_db, secure_database_file
from app.routes import router
from app.scheduler import start_scheduler
from app.auth import void_auth, is_email_allowed
from app.models import User
from app.security import (
    RateLimiter,
    install_log_redaction,
    safe_relative_path,
    sanitize_header,
    verify_csrf,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

install_log_redaction()

login_limiter = RateLimiter(config.login_limit, window_seconds=3600)

# Swagger UI loads its assets from a CDN, so the strict CSP below would break
# it. Docs are off by default in production (EXPOSE_DOCS).
_CSP_EXEMPT_PATHS = ("/docs", "/redoc", "/openapi.json")

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "object-src 'none'",
    ]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.data_dir.mkdir(parents=True, exist_ok=True)
    # The database holds plaintext SMTP credentials; keep it owner-only.
    os.chmod(config.data_dir, 0o700)
    Base.metadata.create_all(bind=engine)
    secure_database_file()
    start_scheduler()
    yield


app = FastAPI(
    title="Bookmark Resurfacer",
    lifespan=lifespan,
    docs_url="/docs" if config.expose_docs else None,
    redoc_url="/redoc" if config.expose_docs else None,
    openapi_url="/openapi.json" if config.expose_docs else None,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(), camera=(), microphone=()"
    )
    if not request.url.path.startswith(_CSP_EXEMPT_PATHS):
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    if config.cookie_secure:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


# Reject requests with an unexpected Host header (cache poisoning / redirect
# abuse). Set ALLOWED_HOSTS to your real hostname(s) in production.
if "*" not in config.allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.allowed_hosts)

app.add_middleware(
    SessionMiddleware,
    secret_key=config.session_secret,
    session_cookie="br_session",
    max_age=config.session_max_age,
    same_site="lax",
    https_only=config.cookie_secure,
)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.get("/auth/login")
async def auth_login(request: Request):
    if not void_auth.is_configured:
        raise HTTPException(status_code=500, detail="Void Auth is not configured")

    client_ip = request.client.host if request.client else "unknown"
    login_limiter.enforce(client_ip, "Too many login attempts. Try again later.")

    state = secrets.token_urlsafe(32)
    verifier, challenge = void_auth.generate_pkce_pair()
    request.session["auth_state"] = state
    request.session["pkce_verifier"] = verifier
    url = void_auth.get_authorization_url(state, challenge)
    return RedirectResponse(url=url, status_code=302)


@app.get("/auth/callback")
async def auth_callback(
    code: str,
    state: str,
    request: Request,
    db: Session = Depends(get_db),
):
    if not void_auth.is_configured:
        raise HTTPException(status_code=500, detail="Void Auth is not configured")

    client_ip = request.client.host if request.client else "unknown"
    login_limiter.enforce(client_ip, "Too many login attempts. Try again later.")

    # Single-use: pop before any validation so a code cannot be replayed.
    stored_state = request.session.pop("auth_state", None)
    code_verifier = request.session.pop("pkce_verifier", None)
    if not stored_state or not secrets.compare_digest(str(stored_state), state):
        raise HTTPException(status_code=400, detail="Invalid state parameter")
    if not code_verifier:
        raise HTTPException(status_code=400, detail="Missing PKCE verifier; restart login")

    token_data = await void_auth.exchange_code(code, code_verifier)
    if not token_data:
        raise HTTPException(status_code=400, detail="Failed to exchange code for token")

    access_token = token_data.get("access_token")
    if not access_token or not isinstance(access_token, str):
        raise HTTPException(status_code=400, detail="No access token received")

    user_info = await void_auth.get_user_info(access_token)
    if not user_info:
        raise HTTPException(status_code=400, detail="Failed to fetch user info")

    user_id = sanitize_header(str(user_info.get("id") or user_info.get("sub") or ""), 256)
    email = sanitize_header(str(user_info.get("email") or ""), 256)
    display_name = sanitize_header(
        str(user_info.get("name") or user_info.get("display_name") or email), 256
    )

    if not user_id:
        raise HTTPException(status_code=400, detail="No user ID in response")

    # Any account on the identity provider can otherwise self-provision here.
    if not is_email_allowed(email):
        raise HTTPException(status_code=403, detail="This account is not authorized")

    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.email = email
        user.display_name = display_name
    else:
        user = User(id=user_id, email=email, display_name=display_name)
        db.add(user)
    db.commit()

    post_login = safe_relative_path(request.session.pop("post_login_redirect", "/") or "/")

    # Rotate the CSRF token on privilege change to prevent session fixation.
    request.session.pop("csrf_token", None)
    request.session["user"] = {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
    }

    return RedirectResponse(url=post_login, status_code=302)


@app.post("/auth/logout", dependencies=[Depends(verify_csrf)])
async def auth_logout(request: Request):
    """POST-only so a third-party page cannot force a logout."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
