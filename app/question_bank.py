import json
from functools import lru_cache

from app.config import settings


@lru_cache
def load_bank() -> dict:
    with open(settings.question_bank_path) as f:
        return json.load(f)


def public_categories() -> list[dict]:
    """Categories + questions WITHOUT rubric/model_answer — safe to send to the client."""
    bank = load_bank()
    return [
        {
            "id": cat["id"],
            "name": cat["name"],
            "questions": [{"id": q["id"], "prompt": q["prompt"]} for q in cat["questions"]],
        }
        for cat in bank["categories"]
    ]


def find_question(question_id: str) -> dict | None:
    bank = load_bank()
    for cat in bank["categories"]:
        for q in cat["questions"]:
            if q["id"] == question_id:
                return {**q, "category": cat["name"]}
    return None
