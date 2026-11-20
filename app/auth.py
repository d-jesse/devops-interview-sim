import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import HTTPException, Request

from app.config import settings
from app.db import get_connection


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=settings.session_ttl_days)).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, expires_at),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def destroy_session(token: str) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()


def get_user_by_session(token: str | None) -> dict | None:
    if not token:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT u.id, u.email, u.name, u.is_admin
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token = ? AND s.expires_at > datetime('now')""",
            (token,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def current_user(request: Request) -> dict | None:
    token = request.cookies.get(settings.session_cookie_name)
    return get_user_by_session(token)


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


def require_admin(request: Request) -> dict:
    user = require_user(request)
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin only")
    return user
