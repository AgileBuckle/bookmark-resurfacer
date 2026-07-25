from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
import os
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Bookmark, User
from app.schemas import BookmarkCreate, BookmarkOut, EmailSettings
from app.settings_service import get_settings, save_settings
from app.scheduler import reschedule_for_user
from app.auth import require_user_or_redirect, require_user, void_auth, DEFAULT_USER_ID

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
jinja_env = Environment(
    loader=FileSystemLoader(os.path.join(BASE_DIR, "templates")),
    autoescape=select_autoescape(["html"]),
)
jinja_env.cache = None


def _render(template_name: str, context: dict) -> str:
    template = jinja_env.get_template(template_name)
    return template.render(**context)


def _bookmark_to_dict(bm: Bookmark) -> dict:
    return {
        "id": bm.id,
        "url": bm.url,
        "title": bm.title,
        "description": bm.description,
        "tags": bm.tags,
        "created_at": bm.created_at,
    }


def _user_context(user: User) -> dict:
    return {
        "user": {
            "id": user.id,
            "display_name": user.display_name,
            "email": user.email,
        },
        "show_login": void_auth.is_configured and user.id == DEFAULT_USER_ID,
    }


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
        "request": request,
        "bookmarks": [_bookmark_to_dict(b) for b in bookmarks],
        **_user_context(user),
    })
    return HTMLResponse(content=html)


@router.post("/bookmarks/add", response_class=RedirectResponse)
def add_bookmark_form(
    request: Request,
    url: str = Form(...),
    title: str = Form(""),
    description: str = Form(""),
    tags: str = Form(""),
    user: User = Depends(require_user_or_redirect),
    db: Session = Depends(get_db),
):
    bookmark = Bookmark(
        user_id=user.id,
        url=url.strip(),
        title=title.strip() or None,
        description=description.strip() or None,
        tags=tags.strip() or None,
    )
    db.add(bookmark)
    db.commit()
    return RedirectResponse(url="/", status_code=302)


@router.get("/bookmarks/{bookmark_id}/delete", response_class=RedirectResponse)
def delete_bookmark_form(
    bookmark_id: int,
    user: User = Depends(require_user_or_redirect),
    db: Session = Depends(get_db),
):
    bookmark = (
        db.query(Bookmark)
        .filter(Bookmark.id == bookmark_id, Bookmark.user_id == user.id)
        .first()
    )
    if bookmark:
        db.delete(bookmark)
        db.commit()
    return RedirectResponse(url="/", status_code=302)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    user: User = Depends(require_user_or_redirect),
    db: Session = Depends(get_db),
):
    settings = get_settings(db, user.id)
    html = _render("settings.html", {
        "request": request,
        "settings": settings,
        **_user_context(user),
    })
    return HTMLResponse(content=html)


@router.post("/settings/save", response_class=RedirectResponse)
def save_settings_form(
    request: Request,
    smtp_host: str = Form(""),
    smtp_port: int = Form(587),
    smtp_username: str = Form(""),
    smtp_password: str = Form(""),
    smtp_use_tls: bool = Form(True),
    email_from: str = Form(""),
    email_to: str = Form(""),
    email_subject: str = Form("Your Bookmarks to Revisit"),
    links_per_email: int = Form(5),
    schedule_interval_hours: float = Form(24),
    user: User = Depends(require_user_or_redirect),
    db: Session = Depends(get_db),
):
    data = {
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_username": smtp_username,
        "smtp_password": smtp_password,
        "smtp_use_tls": str(smtp_use_tls).lower(),
        "email_from": email_from,
        "email_to": email_to,
        "email_subject": email_subject,
        "links_per_email": links_per_email,
        "schedule_interval_hours": schedule_interval_hours,
    }
    save_settings(db, user.id, data)
    reschedule_for_user(user.id)
    return RedirectResponse(url="/settings", status_code=302)


# --- REST API routes ---

@router.get("/api/bookmarks", response_model=list[BookmarkOut])
def api_list_bookmarks(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Bookmark)
        .filter(Bookmark.user_id == user.id)
        .order_by(Bookmark.created_at.desc())
        .all()
    )


@router.post("/api/bookmarks", response_model=BookmarkOut, status_code=201)
def api_create_bookmark(
    data: BookmarkCreate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    bookmark = Bookmark(
        user_id=user.id,
        url=data.url.strip(),
        title=data.title.strip() if data.title else None,
        description=data.description.strip() if data.description else None,
        tags=data.tags.strip() if data.tags else None,
    )
    db.add(bookmark)
    db.commit()
    db.refresh(bookmark)
    return bookmark


@router.delete("/api/bookmarks/{bookmark_id}", status_code=204)
def api_delete_bookmark(
    bookmark_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    bookmark = (
        db.query(Bookmark)
        .filter(Bookmark.id == bookmark_id, Bookmark.user_id == user.id)
        .first()
    )
    if not bookmark:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    db.delete(bookmark)
    db.commit()


@router.get("/api/settings")
def api_get_settings(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    return get_settings(db, user.id)


@router.post("/api/settings")
def api_save_settings(
    data: EmailSettings,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    save_settings(db, user.id, data.model_dump())
    reschedule_for_user(user.id)
    return {"status": "ok"}


@router.post("/api/send-test", status_code=200)
async def api_send_test(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    from app.email_service import send_email_for_user
    success = await send_email_for_user(db, user.id)
    return {"sent": success}
