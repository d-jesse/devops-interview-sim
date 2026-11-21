import json
import re
import time

import httpx

from app.config import settings

GRADING_SYSTEM_PROMPT = """You are a senior DevOps interviewer grading a candidate's free-form answer \
in a live mock interview. You are given the question, a reference answer, a rubric of specific points \
a strong answer should hit, and the candidate's actual answer.

Grade strictly but fairly, the way a real senior engineer would in a technical interview: credit \
correct reasoning and relevant tools/commands even if phrased differently from the reference answer; \
do not require verbatim matches. Penalize vague, hand-wavy, or incorrect answers.

Respond with ONLY a JSON object, no markdown fences, no commentary outside the JSON, in exactly this shape:
{
  "score": <integer 1-10>,
  "verdict": "<one short phrase, e.g. 'Strong answer' or 'Missing key depth'>",
  "strengths": ["<point the candidate got right>", "..."],
  "gaps": ["<point the candidate missed or got wrong>", "..."],
  "feedback": "<2-4 sentences of direct, constructive feedback as if speaking to the candidate>"
}"""


def _build_user_prompt(question: dict, candidate_answer: str) -> str:
    rubric_lines = "\n".join(f"- {point}" for point in question["rubric"])
    return f"""Category: {question['category']}
Question: {question['prompt']}

Reference answer (for your grading context, not to be quoted at the candidate):
{question['model_answer']}

Rubric — specific points a strong answer should hit:
{rubric_lines}

Candidate's answer:
{candidate_answer}

Grade the candidate's answer now. Respond with only the JSON object described in your instructions."""


def _parse_grading_response(raw: str) -> dict:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in model response: {raw[:500]}")
    parsed = json.loads(match.group(0))

    parsed["score"] = max(1, min(10, int(parsed.get("score", 1))))
    parsed.setdefault("verdict", "")
    parsed.setdefault("strengths", [])
    parsed.setdefault("gaps", [])
    parsed.setdefault("feedback", "")
    return parsed


async def grade_answer(question: dict, candidate_answer: str) -> dict:
    payload = {
        "model": settings.grading_model,
        "messages": [
            {"role": "system", "content": GRADING_SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(question, candidate_answer)},
        ],
        "temperature": 0.2,
        "stream": False,
    }

    start = time.monotonic()
    async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=180) as client:
        resp = await client.post("/v1/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
    duration_ms = int((time.monotonic() - start) * 1000)

    raw = data["choices"][0]["message"]["content"]
    parsed = _parse_grading_response(raw)
    parsed["meta"] = {"model": settings.grading_model, "duration_ms": duration_ms}
    return parsed
