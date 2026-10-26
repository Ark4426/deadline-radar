# DeadlineRadar

A clean-room, Flask + SQLite + vanilla JS task manager that predicts which deadlines are at risk and turns the prediction into a rescue plan.

> The core idea is inspired by smart task managers that auto-prioritize work. This implementation, product angle, UI, data model, and code are original.

## Status

Scaffold in progress. The app is built in 22 incremental commits.

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
