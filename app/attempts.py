import json

from app.db import get_connection


def save_attempt(
    user_id: int,
    length: int,
    model: str,
    grading_mode: str,
    avg_score: float | None,
    questions: list[dict],
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO attempts (user_id, length, model, grading_mode, avg_score, questions_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, length, model, grading_mode, avg_score, json.dumps(questions)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_attempts(user_id: int) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT id, length, model, grading_mode, avg_score, questions_json, created_at
               FROM attempts WHERE user_id = ? ORDER BY created_at DESC""",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()

    out = []
    for row in rows:
        out.append(
            {
                "id": row["id"],
                "length": row["length"],
                "model": row["model"],
                "grading_mode": row["grading_mode"],
                "avg_score": row["avg_score"],
                "questions": json.loads(row["questions_json"]),
                "created_at": row["created_at"],
            }
        )
    return out
