import secrets
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.auth import (
    create_session,
    current_user,
    destroy_session,
    hash_password,
    require_admin,
    verify_password,
)
from app.config import settings
from app.db import init_db
from app.grading import grade_answer, list_models
from app.question_bank import find_question, full_bank, public_categories
from app.users import create_user, get_user_by_email, get_user_by_google_sub, link_google_account, seed_admin

app = FastAPI(title="devops-interview-sim")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
OAUTH_STATE_COOKIE = "dis_oauth_state"


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    seed_admin()


@app.get("/api/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/api/categories")
async def categories() -> list[dict]:
    return public_categories()


@app.get("/api/models")
async def models() -> dict:
    try:
        available = await list_models()
    except Exception:
        available = []
    return {"default": settings.grading_model, "available": available}


class GradeRequest(BaseModel):
    question_id: str
    answer: str
    model: str | None = None


@app.post("/api/grade")
async def grade(req: GradeRequest) -> dict:
    question = find_question(req.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Unknown question_id")
    if not req.answer.strip():
        raise HTTPException(status_code=400, detail="Answer is empty")

    try:
        result = await grade_answer(question, req.answer, model=req.model)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Grading failed: {exc}") from exc

    return result


# ---------- auth ----------


def _user_public(user: dict) -> dict:
    return {
        "email": user["email"],
        "name": user["name"],
        "is_admin": bool(user["is_admin"]),
    }


def _set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        max_age=settings.session_ttl_days * 86400,
        path="/",
    )


@app.get("/api/auth/config")
async def auth_config() -> dict:
    return {"google_enabled": bool(settings.google_client_id and settings.google_client_secret)}


@app.get("/api/auth/me")
async def auth_me(request: Request) -> dict:
    user = current_user(request)
    return {"user": _user_public(user) if user else None}


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str


@app.post("/api/auth/register")
async def register(req: RegisterRequest) -> JSONResponse:
    email = req.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if get_user_by_email(email):
        raise HTTPException(status_code=409, detail="An account with that email already exists")

    user = create_user(email, req.name.strip() or email, password_hash=hash_password(req.password))
    token = create_session(user["id"])
    out = JSONResponse({"user": _user_public(user)})
    _set_session_cookie(out, token)
    return out


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/login")
async def login(req: LoginRequest) -> JSONResponse:
    user = get_user_by_email(req.email.strip().lower())
    if not user or not user["password_hash"] or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Wrong email or password")

    token = create_session(user["id"])
    out = JSONResponse({"user": _user_public(user)})
    _set_session_cookie(out, token)
    return out


@app.post("/api/auth/logout")
async def logout(request: Request) -> Response:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        destroy_session(token)
    out = Response(status_code=204)
    out.delete_cookie(settings.session_cookie_name, path="/")
    return out


@app.get("/api/auth/google/login")
async def google_login() -> RedirectResponse:
    if not (settings.google_client_id and settings.google_client_secret):
        raise HTTPException(status_code=501, detail="Google sign-in is not configured on this server")

    state = secrets.token_urlsafe(24)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    url = f"{GOOGLE_AUTHORIZE_URL}?{httpx.QueryParams(params)}"
    out = RedirectResponse(url)
    out.set_cookie(OAUTH_STATE_COOKIE, state, httponly=True, samesite="lax", max_age=600, path="/")
    return out


@app.get("/api/auth/google/callback")
async def google_callback(request: Request, code: str | None = None, state: str | None = None):
    expected_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not code or not state or not expected_state or state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]

        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
        )
        userinfo_resp.raise_for_status()
        info = userinfo_resp.json()

    google_sub = info["sub"]
    email = info.get("email", "").lower()
    name = info.get("name") or email

    user = get_user_by_google_sub(google_sub)
    if not user and email:
        user = get_user_by_email(email)
        if user:
            link_google_account(user["id"], google_sub)
    if not user:
        user = create_user(email or f"{google_sub}@google", name, google_sub=google_sub)

    token = create_session(user["id"])
    out = RedirectResponse("/app.html")
    _set_session_cookie(out, token)
    out.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    return out


# ---------- admin ----------


@app.get("/api/admin/cheatsheet")
async def admin_cheatsheet(admin: dict = Depends(require_admin)) -> list[dict]:
    return full_bank()


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
