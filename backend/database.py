"""SQLite connection helpers, schema creation, and shared defaults."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import click
from flask import current_app, g

SCHEMA_VERSION = 1

HIGH_KEYWORDS = [
    "urgent",
    "asap",
    "critical",
    "deadline",
    "overdue",
    "exam",
    "interview",
    "submit",
    "launch",
    "final",
]
MEDIUM_KEYWORDS = [
    "report",
    "review",
    "meeting",
    "prepare",
    "draft",
    "client",
    "follow",
    "plan",
    "demo",
]
CATEGORY_WEIGHTS = {
    "work": 0.62,
    "study": 0.68,
    "personal": 0.35,
    "health": 0.55,
    "finance": 0.72,
    "home": 0.3,
    "other": 0.4,
}

DEFAULT_SETTINGS = {
    "high_keywords": HIGH_KEYWORDS,
    "medium_keywords": MEDIUM_KEYWORDS,
    "category_weights": CATEGORY_WEIGHTS,
    "auto_priority": True,
    "theme": "dark",
}


def utc_now() -> str:
    """Return a sortable UTC timestamp without a timezone suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_db() -> sqlite3.Connection:
    """Open one connection per request and return rows as dictionaries."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db


def close_db(_exception: BaseException | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    """Create the schema. Safe to call on every boot."""
    schema_path = Path(__file__).with_name("schema.sql")
    db = get_db()
    db.executescript(schema_path.read_text(encoding="utf-8"))
    db.commit()


def ensure_settings(db: sqlite3.Connection, user_id: int) -> None:
    """Create a settings row with sensible defaults for a new user."""
    now = utc_now()
    db.execute(
        """
        INSERT OR IGNORE INTO settings
            (user_id, high_keywords, medium_keywords, category_weights,
             auto_priority, theme, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, 'dark', ?, ?)
        """,
        (
            user_id,
            json.dumps(DEFAULT_SETTINGS["high_keywords"]),
            json.dumps(DEFAULT_SETTINGS["medium_keywords"]),
            json.dumps(DEFAULT_SETTINGS["category_weights"]),
            now,
            now,
        ),
    )


def init_app(app) -> None:
    app.teardown_appcontext(close_db)

    @app.cli.command("init-db")
    def init_db_command():
        """Create or upgrade the local SQLite schema."""
        init_db()
        click.echo("Initialized the DeadlineRadar database.")

    with app.app_context():
        init_db()
