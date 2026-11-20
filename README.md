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
- `static/index.html` is the marketing/landing page, `static/app.html` is the
  interview app itself (random questions, live or deferred grading), and
  `static/admin.html` is the admin-only master cheatsheet (full rubric +
  reference answers). All three are vanilla JS, no build step.
- The backend (FastAPI) builds a grading prompt from the question + rubric +
  reference answer + the candidate's answer, sends it to a model running on
  Ollama (currently `qwen3.6:35b` on a Mac Studio over the LAN), and parses
  the model's structured JSON verdict back into the UI.
- Accounts are optional — anyone can take an interview anonymously.
  Email/password accounts are stored in a local SQLite DB (`data/app.db`,
  gitignored) with bcrypt-hashed passwords and a session cookie. Google
  sign-in is wired up but stays disabled until `GOOGLE_CLIENT_ID` /
  `GOOGLE_CLIENT_SECRET` are set in `.env` (see `.env.example`).
- There's a single fixed admin account seeded from `ADMIN_EMAIL` /
  `ADMIN_PASSWORD` in `.env` (defaults to `admin@devops-sim.local` /
  `changeme123` — change these). Signing in as that account unlocks
  `/admin.html`, which shows every question's rubric and reference answer.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # point OLLAMA_BASE_URL at your inference host, set ADMIN_PASSWORD
uvicorn app.main:app --reload --port 8010
```

Open http://localhost:8010.

## Adding questions

Append to `data/question_bank.json` — each question needs `id`, `prompt`,
`rubric` (list of specific points), and `model_answer`. No code changes
needed; the bank is loaded at request time.
