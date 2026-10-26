# DeadlineRadar

A clean-room, Flask + SQLite + vanilla JS task manager that predicts which deadlines are at risk and turns the prediction into a rescue plan.

> The core idea is inspired by smart task managers that auto-prioritize work. This implementation, product angle, UI, data model, and code are original.

## Status

Usable: accounts, task tracking with views/search/sort, risk scoring on every task, and a live risk preview with a rescue plan. Saved tasks are re-scored as their deadlines approach. The optional scikit-learn model (`backend/risk_engine/train.py`) is not wired in yet; scoring uses the rule engine.

## Configuration

Copy `.env.example` to `.env` and set a real `SECRET_KEY`. Environment variables:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session signing key |
| `DATABASE_PATH` | SQLite file location (defaults to `instance/deadline_radar.db`) |
| `FLASK_DEBUG` | `1` enables the debugger locally |
| `SESSION_COOKIE_SECURE` | `1` in production behind HTTPS |

## Stack

- Python 3.10+
- Flask 3
- SQLite
- Vanilla HTML/CSS/JS
- scikit-learn for the optional risk model

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

## Product idea

DeadlineRadar scores each open task for **missed-deadline risk** instead of only assigning a priority label. It explains the score and suggests a small rescue plan.

## Data model

SQLite, created from `backend/schema.sql` on boot:

| Table | Purpose |
|---|---|
| `users` | Account, password hash, timezone |
| `tasks` | Per-user tasks, due date, effort, risk snapshot |
| `risk_predictions` | Audit trail of every risk preview and its signals |
| `settings` | Keyword lists, category weights, and UI preferences |

Schema version is tracked with `PRAGMA user_version`; `flask --app app init-db` creates or upgrades the local database.

## Risk engine

`POST /api/risk/preview` accepts a task draft and returns:

- a 0–100 risk score and band (`critical`, `high`, `watch`, `low`)
- the exact signals that moved the score, with point contributions
- a 2–4 step rescue plan with time estimates

The deterministic baseline weighs deadline proximity, effort vs. spare capacity, urgency language, category weight, queue pressure, task age, and the user's category track record. An optional scikit-learn model can later blend into the same explanation contract.
