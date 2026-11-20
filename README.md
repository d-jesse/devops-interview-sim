# devops-interview-sim

A single-pane, free-form AI-run DevOps interview. Pick a question, type your
answer like you would out loud in a real interview, and get graded by an LLM
running locally on a Mac Studio against a hand-built answer bank and rubric
— not just "LGTM," but specific strengths, specific gaps, and a score.

## How it works

- `data/question_bank.json` holds categories, questions, a reference answer,
  and a rubric (specific points a strong answer should hit) per question.
  Only the question text is ever sent to the client — the reference answer
  and rubric stay server-side as the grading ground truth.
- The frontend (`static/index.html`) is a single-page vanilla JS app: pick a
  question, submit a free-form answer, see the graded result.
- The backend (FastAPI) builds a grading prompt from the question + rubric +
  reference answer + the candidate's answer, sends it to a model running on
  Ollama (currently `qwen3.6:35b` on a Mac Studio over the LAN), and parses
  the model's structured JSON verdict back into the UI.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # point OLLAMA_BASE_URL at your inference host
uvicorn app.main:app --reload --port 8010
```

Open http://localhost:8010.

## Adding questions

Append to `data/question_bank.json` — each question needs `id`, `prompt`,
`rubric` (list of specific points), and `model_answer`. No code changes
needed; the bank is loaded at request time.
