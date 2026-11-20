from app.auth import hash_password
from app.config import settings
from app.db import get_connection


def get_user_by_id(user_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def get_user_by_email(email: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def get_user_by_google_sub(sub: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE google_sub = ?", (sub,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def create_user(
    email: str,
    name: str,
    password_hash: str | None = None,
    google_sub: str | None = None,
    is_admin: bool = False,
) -> dict:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, name, password_hash, google_sub, is_admin) VALUES (?, ?, ?, ?, ?)",
            (email.lower(), name, password_hash, google_sub, int(is_admin)),
        )
        conn.commit()
        user_id = cur.lastrowid
    finally:
        conn.close()
    return get_user_by_id(user_id)


def link_google_account(user_id: int, google_sub: str) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET google_sub = ? WHERE id = ?", (google_sub, user_id))
        conn.commit()
    finally:
        conn.close()


def seed_admin() -> None:
    """Keep a single fixed admin account in sync with ADMIN_EMAIL / ADMIN_PASSWORD."""
    existing = get_user_by_email(settings.admin_email)
    password_hash = hash_password(settings.admin_password)
    if existing:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE users SET password_hash = ?, is_admin = 1 WHERE id = ?",
                (password_hash, existing["id"]),
            )
            conn.commit()
        finally:
            conn.close()
    else:
        create_user(settings.admin_email, "Admin", password_hash=password_hash, is_admin=True)
