import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session

from app.database import engine, Base, get_db
from app.routes import router
from app.scheduler import start_scheduler
from app.auth import SESSION_SECRET, void_auth, require_user, optional_user
from app.models import User

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(os.path.join(BASE_DIR, "..", "data"), exist_ok=True)
    Base.metadata.create_all(bind=engine)
    start_scheduler()
    yield


app = FastAPI(title="Bookmark Resurfacer", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="br_session",
    max_age=86400 * 30,
    same_site="lax",
)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.get("/auth/login")
async def auth_login(request: Request):
    if not void_auth.is_configured:
        raise HTTPException(status_code=500, detail="Void Auth is not configured")
    state = secrets.token_urlsafe(32)
    request.session["auth_state"] = state
    url = void_auth.get_authorization_url(state)
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

    stored_state = request.session.pop("auth_state", None)
    if not stored_state or stored_state != state:
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    token_data = await void_auth.exchange_code(code)
    if not token_data:
        raise HTTPException(status_code=400, detail="Failed to exchange code for token")

    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="No access token received")

    user_info = await void_auth.get_user_info(access_token)
    if not user_info:
        raise HTTPException(status_code=400, detail="Failed to fetch user info")

    user_id = str(user_info.get("id") or user_info.get("sub", ""))
    email = str(user_info.get("email", ""))
    display_name = str(user_info.get("name") or user_info.get("display_name", email))

    if not user_id:
        raise HTTPException(status_code=400, detail="No user ID in response")

    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.email = email
        user.display_name = display_name
    else:
        user = User(id=user_id, email=email, display_name=display_name)
        db.add(user)
    db.commit()

    request.session["user"] = {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
    }

    post_login = request.session.pop("post_login_redirect", None)
    return RedirectResponse(url=post_login or "/", status_code=302)


@app.get("/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)


app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
