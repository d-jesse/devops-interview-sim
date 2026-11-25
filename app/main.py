import logging
import secrets
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.attempts import list_attempts, save_attempt
from app.auth import (
    create_session,
    current_user,
    destroy_session,
    hash_password,
    require_admin,
    require_user,
    verify_password,
)
from app.config import settings
from app.db import init_db
from app.grading import grade_answer
from app.question_bank import find_question, full_bank, public_categories
from app.users import create_user, get_user_by_email, get_user_by_google_sub, link_google_account, seed_admin

logger = logging.getLogger("devops-interview-sim")

# Keyed by request.client.host, which is only the real visitor IP because
# uvicorn is run with --proxy-headers --forwarded-allow-ips=127.0.0.1 and
# Caddy (the only thing that can reach uvicorn at all) sets X-Forwarded-For
# correctly. Without that, every request would look like it came from
# Caddy itself and this limit would apply globally across all visitors
# combined rather than per visitor.
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="devops-interview-sim")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
OAUTH_STATE_COOKIE = "dis_oauth_state"
OAUTH_NEXT_COOKIE = "dis_oauth_next"


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    seed_admin()


@app.get("/api/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/api/healthz/grading")
async def healthz_grading() -> JSONResponse:
    """Separate from /api/healthz on purpose: this one depends on the Mac
    Studio over Tailscale, so it can go down independently of the app
    itself. Point a second uptime check at this to tell the two apart."""
    try:
        async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=5) as client:
            resp = await client.get("/v1/models")
            resp.raise_for_status()
        return JSONResponse({"status": "ok"})
    except Exception as exc:
        logger.warning("Grading backend unreachable: %s", exc)
        return JSONResponse({"status": "unreachable"}, status_code=503)


@app.get("/api/categories")
async def categories() -> list[dict]:
    return public_categories()


class GradeRequest(BaseModel):
    question_id: str
    answer: str


@app.post("/api/grade")
@limiter.limit("20/minute")
async def grade(request: Request, req: GradeRequest) -> dict:
    question = find_question(req.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Unknown question_id")
    if not req.answer.strip():
        raise HTTPException(status_code=400, detail="Answer is empty")

    try:
        result = await grade_answer(question, req.answer)
    except Exception as exc:
        logger.error("Grading failed for question_id=%s: %s", req.question_id, exc)
        raise HTTPException(
            status_code=502,
            detail="The grading model is temporarily unavailable. Please try again in a moment.",
        ) from exc

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
        secure=settings.session_cookie_secure,
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
@limiter.limit("10/minute")
async def register(request: Request, req: RegisterRequest) -> JSONResponse:
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
@limiter.limit("5/minute")
async def login(request: Request, req: LoginRequest) -> JSONResponse:
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


def _safe_next_path(next_path: str | None) -> str:
    if next_path and next_path.startswith("/") and not next_path.startswith("//"):
        return next_path
    return "/app.html"


@app.get("/api/auth/google/login")
async def google_login(next: str | None = None) -> RedirectResponse:
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
    out.set_cookie(
        OAUTH_STATE_COOKIE, state, httponly=True, samesite="lax",
        secure=settings.session_cookie_secure, max_age=600, path="/",
    )
    out.set_cookie(
        OAUTH_NEXT_COOKIE, _safe_next_path(next), httponly=True, samesite="lax",
        secure=settings.session_cookie_secure, max_age=600, path="/",
    )
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
    next_path = _safe_next_path(request.cookies.get(OAUTH_NEXT_COOKIE))
    out = RedirectResponse(next_path)
    _set_session_cookie(out, token)
    out.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    out.delete_cookie(OAUTH_NEXT_COOKIE, path="/")
    return out


# ---------- history ----------


class AttemptQuestion(BaseModel):
    category: str
    prompt: str
    score: int | None = None
    verdict: str | None = None


class SaveAttemptRequest(BaseModel):
    length: int
    model: str
    grading_mode: str
    avg_score: float | None = None
    questions: list[AttemptQuestion]


@app.post("/api/attempts")
async def create_attempt(req: SaveAttemptRequest, user: dict = Depends(require_user)) -> dict:
    attempt_id = save_attempt(
        user["id"],
        req.length,
        req.model,
        req.grading_mode,
        req.avg_score,
        [q.model_dump() for q in req.questions],
    )
    return {"id": attempt_id}


@app.get("/api/attempts")
async def get_attempts(user: dict = Depends(require_user)) -> list[dict]:
    return list_attempts(user["id"])


# ---------- admin ----------


@app.get("/api/admin/cheatsheet")
async def admin_cheatsheet(admin: dict = Depends(require_admin)) -> list[dict]:
    return full_bank()


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
