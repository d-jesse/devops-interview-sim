from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.grading import grade_answer
from app.question_bank import find_question, public_categories

app = FastAPI(title="devops-interview-sim")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/api/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/api/categories")
async def categories() -> list[dict]:
    return public_categories()


class GradeRequest(BaseModel):
    question_id: str
    answer: str


@app.post("/api/grade")
async def grade(req: GradeRequest) -> dict:
    question = find_question(req.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Unknown question_id")
    if not req.answer.strip():
        raise HTTPException(status_code=400, detail="Answer is empty")

    try:
        result = await grade_answer(question, req.answer)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Grading failed: {exc}") from exc

    return result


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
