import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, Form, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth import require_user_or_redirect, require_user, void_auth, DEFAULT_USER_ID
from app.config import config
from app.database import get_db
from app.models import Bookmark, User
from app.schemas import (
    BookmarkCreate,
    BookmarkUpdate,
    BookmarkOut,
    EmailSettings,
    EmailSettingsOut,
)
from app.scheduler import reschedule_for_user
from app.security import (
    MAX_DESCRIPTION_LENGTH,
    MAX_TAGS_LENGTH,
    MAX_TITLE_LENGTH,
    RateLimiter,
    clean_text,
    get_csrf_token,
    is_safe_url,
    validate_url,
    verify_csrf,
)
from app.settings_service import get_settings_public, save_settings

logger = logging.getLogger(__name__)

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
jinja_env = Environment(
    loader=FileSystemLoader(os.path.join(BASE_DIR, "templates")),
    autoescape=select_autoescape(
        enabled_extensions=("html",), default_for_string=True, default=True
    ),
)
jinja_env.cache = None

# Sending mail is the only endpoint that reaches out to a third party on
# demand; cap it so a stolen session cannot be used as a mail cannon.
test_email_limiter = RateLimiter(config.test_email_limit, window_seconds=3600)

MAX_SEARCH_LENGTH = 200


def _render(template_name: str, context: dict) -> str:
    template = jinja_env.get_template(template_name)
    return template.render(**context)


def _bookmark_to_dict(bm: Bookmark) -> dict:
    return {
        "id": bm.id,
        "url": bm.url,
        # Rows created before URL validation existed may hold a javascript:
        # or data: URI; the template only links out when this is true.
        "url_is_safe": is_safe_url(bm.url),
        "title": bm.title,
        "description": bm.description,
        "tags": bm.tags,
        "created_at": bm.created_at,
    }


def _base_context(request: Request, user: User) -> dict:
    return {
        "request": request,
        "csrf_token": get_csrf_token(request),
        "user": {
            "id": user.id,
            "display_name": user.display_name,
            "email": user.email,
        },
        "show_login": void_auth.is_configured and user.id == DEFAULT_USER_ID,
        "sso_enabled": void_auth.is_configured,
    }


def _escape_like(term: str) -> str:
    """Escape LIKE wildcards so a search term cannot become a wildcard scan."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _owned_bookmark(db: Session, bookmark_id: int, user: User) -> Bookmark | None:
    return (
        db.query(Bookmark)
        .filter(Bookmark.id == bookmark_id, Bookmark.user_id == user.id)
        .first()
    )


# --- HTML (Web UI) routes ---

@router.get("/", response_class=HTMLResponse)
def index(request: Request, user: User = Depends(require_user_or_redirect), db: Session = Depends(get_db)):
    bookmarks = (
        db.query(Bookmark)
        .filter(Bookmark.user_id == user.id)
        .order_by(Bookmark.created_at.desc())
        .all()
    )
    html = _render("index.html", {
        "bookmarks": [_bookmark_to_dict(b) for b in bookmarks],
        **_base_context(request, user),
    })
    return HTMLResponse(content=html)


@router.post("/bookmarks/add", response_class=RedirectResponse, dependencies=[Depends(verify_csrf)])
def add_bookmark_form(
    request: Request,
    url: str = Form(..., max_length=4096),
    title: str = Form("", max_length=MAX_TITLE_LENGTH),
    description: str = Form("", max_length=MAX_DESCRIPTION_LENGTH),
    tags: str = Form("", max_length=MAX_TAGS_LENGTH),
    user: User = Depends(require_user_or_redirect),
    db: Session = Depends(get_db),
):
    bookmark = Bookmark(
        user_id=user.id,
        url=validate_url(url),
        title=clean_text(title, MAX_TITLE_LENGTH),
        description=clean_text(description, MAX_DESCRIPTION_LENGTH),
        tags=clean_text(tags, MAX_TAGS_LENGTH),
    )
    db.add(bookmark)
    db.commit()
    return RedirectResponse(url="/", status_code=303)


@router.post(
    "/bookmarks/{bookmark_id}/delete",
    response_class=RedirectResponse,
    dependencies=[Depends(verify_csrf)],
)
def delete_bookmark_form(
    bookmark_id: int,
    user: User = Depends(require_user_or_redirect),
    db: Session = Depends(get_db),
):
    """POST-only: a GET delete link is triggerable cross-site and by prefetchers."""
    bookmark = _owned_bookmark(db, bookmark_id, user)
    if bookmark:
        db.delete(bookmark)
        db.commit()
    return RedirectResponse(url="/", status_code=303)


@router.post(
    "/bookmarks/{bookmark_id}/edit",
    response_class=RedirectResponse,
    dependencies=[Depends(verify_csrf)],
)
def edit_bookmark_form(
    bookmark_id: int,
    url: str = Form(..., max_length=4096),
    title: str = Form("", max_length=MAX_TITLE_LENGTH),
    description: str = Form("", max_length=MAX_DESCRIPTION_LENGTH),
    tags: str = Form("", max_length=MAX_TAGS_LENGTH),
    user: User = Depends(require_user_or_redirect),
    db: Session = Depends(get_db),
):
    bookmark = _owned_bookmark(db, bookmark_id, user)
    if bookmark:
        bookmark.url = validate_url(url)
        bookmark.title = clean_text(title, MAX_TITLE_LENGTH)
        bookmark.description = clean_text(description, MAX_DESCRIPTION_LENGTH)
        bookmark.tags = clean_text(tags, MAX_TAGS_LENGTH)
        db.commit()
    return RedirectResponse(url="/", status_code=303)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    saved: bool = False,
    error: str = "",
    user: User = Depends(require_user_or_redirect),
    db: Session = Depends(get_db),
):
    html = _render("settings.html", {
        # Public view: the stored SMTP password is never sent to the browser.
        "settings": get_settings_public(db, user.id),
        "saved": saved,
        "error": error[:200],
        **_base_context(request, user),
    })
    return HTMLResponse(content=html)


@router.post("/settings/save", response_class=RedirectResponse, dependencies=[Depends(verify_csrf)])
def save_settings_form(
    request: Request,
    smtp_host: str = Form("", max_length=255),
    smtp_port: int = Form(587),
    smtp_username: str = Form("", max_length=320),
    smtp_password: str = Form("", max_length=1024),
    clear_smtp_password: bool = Form(False),
    # Absent checkbox means unchecked; the old `Form(True)` default made the
    # setting impossible to turn off.
    smtp_use_tls: bool = Form(False),
    email_from: str = Form("", max_length=320),
    email_to: str = Form("", max_length=320),
    email_subject: str = Form("Your Bookmarks to Revisit", max_length=255),
    links_per_email: int = Form(5),
    schedule_interval_hours: int = Form(24),
    user: User = Depends(require_user_or_redirect),
    db: Session = Depends(get_db),
):
    try:
        payload = EmailSettings(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_username=smtp_username,
            smtp_password=smtp_password,
            clear_smtp_password=clear_smtp_password,
            smtp_use_tls=smtp_use_tls,
            email_from=email_from,
            email_to=email_to,
            email_subject=email_subject,
            links_per_email=links_per_email,
            schedule_interval_hours=schedule_interval_hours,
        )
    except ValidationError:
        return RedirectResponse(
            url="/settings?error=Invalid+settings.+Check+the+addresses+and+numeric+fields.",
            status_code=303,
        )

    _persist_settings(db, user.id, payload)
    return RedirectResponse(url="/settings?saved=true", status_code=303)


def _persist_settings(db: Session, user_id: str, payload: EmailSettings) -> None:
    data = payload.model_dump(exclude={"clear_smtp_password"})
    save_settings(
        db,
        user_id,
        data,
        clear_secrets={"smtp_password"} if payload.clear_smtp_password else frozenset(),
    )
    reschedule_for_user(user_id)


# --- REST API routes ---

@router.get("/api/csrf-token")
def api_csrf_token(request: Request, user: User = Depends(require_user)):
    """Fetch the session CSRF token to send in the X-CSRF-Token header."""
    return {"csrf_token": get_csrf_token(request)}


@router.get("/api/bookmarks", response_model=list[BookmarkOut])
def api_list_bookmarks(
    q: str = Query(default="", max_length=MAX_SEARCH_LENGTH, description="Search query"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    query = db.query(Bookmark).filter(Bookmark.user_id == user.id)
    if q:
        search = f"%{_escape_like(q)}%"
        query = query.filter(
            (Bookmark.title.ilike(search, escape="\\")) |
            (Bookmark.url.ilike(search, escape="\\")) |
            (Bookmark.description.ilike(search, escape="\\")) |
            (Bookmark.tags.ilike(search, escape="\\"))
        )
    return (
        query.order_by(Bookmark.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )


@router.post(
    "/api/bookmarks",
    response_model=BookmarkOut,
    status_code=201,
    dependencies=[Depends(verify_csrf)],
)
def api_create_bookmark(
    data: BookmarkCreate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    bookmark = Bookmark(
        user_id=user.id,
        url=validate_url(data.url),
        title=clean_text(data.title, MAX_TITLE_LENGTH),
        description=clean_text(data.description, MAX_DESCRIPTION_LENGTH),
        tags=clean_text(data.tags, MAX_TAGS_LENGTH),
    )
    db.add(bookmark)
    db.commit()
    db.refresh(bookmark)
    return bookmark


@router.delete(
    "/api/bookmarks/{bookmark_id}",
    status_code=204,
    dependencies=[Depends(verify_csrf)],
)
def api_delete_bookmark(
    bookmark_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    bookmark = _owned_bookmark(db, bookmark_id, user)
    if not bookmark:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    db.delete(bookmark)
    db.commit()


@router.put(
    "/api/bookmarks/{bookmark_id}",
    response_model=BookmarkOut,
    dependencies=[Depends(verify_csrf)],
)
def api_update_bookmark(
    bookmark_id: int,
    data: BookmarkUpdate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    bookmark = _owned_bookmark(db, bookmark_id, user)
    if not bookmark:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    if data.url is not None:
        bookmark.url = validate_url(data.url)
    if data.title is not None:
        bookmark.title = clean_text(data.title, MAX_TITLE_LENGTH)
    if data.description is not None:
        bookmark.description = clean_text(data.description, MAX_DESCRIPTION_LENGTH)
    if data.tags is not None:
        bookmark.tags = clean_text(data.tags, MAX_TAGS_LENGTH)
    db.commit()
    db.refresh(bookmark)
    return bookmark


@router.get("/api/settings", response_model=EmailSettingsOut)
def api_get_settings(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Returns `smtp_password_set` instead of the stored SMTP password."""
    return get_settings_public(db, user.id)


@router.post("/api/settings", dependencies=[Depends(verify_csrf)])
def api_save_settings(
    data: EmailSettings,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    _persist_settings(db, user.id, data)
    return {"status": "ok"}


@router.post("/api/send-test", status_code=200, dependencies=[Depends(verify_csrf)])
async def api_send_test(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    test_email_limiter.enforce(
        f"send-test:{user.id}",
        f"Test email limit reached ({config.test_email_limit}/hour). Try again later.",
    )
    from app.email_service import send_email_for_user

    success, error = await send_email_for_user(db, user.id)
    return {"sent": success, "error": error}
