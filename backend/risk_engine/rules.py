"""Explainable, deterministic deadline-risk scoring."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta

from backend.database import CATEGORY_WEIGHTS, HIGH_KEYWORDS, MEDIUM_KEYWORDS

LOW_KEYWORDS = {"someday", "maybe", "optional", "whenever", "low priority", "backlog"}
DAILY_CAPACITY_MINUTES = 180
MAX_SCORE = 100.0


@dataclass
class RiskContext:
    high_keywords: list[str] = field(default_factory=lambda: list(HIGH_KEYWORDS))
    medium_keywords: list[str] = field(default_factory=lambda: list(MEDIUM_KEYWORDS))
    category_weights: dict[str, float] = field(default_factory=lambda: dict(CATEGORY_WEIGHTS))
    backlog_count: int = 0
    backlog_minutes: int = 0
    category_samples: int = 0
    category_on_time: int = 0


def _as_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _safe_json(raw, fallback):
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, type(fallback)) else fallback
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def load_context(
    db,
    user_id: int,
    category: str,
    exclude_task_id: int | None = None,
    today: date | None = None,
) -> RiskContext:
    """Load the per-user signals used by the rule engine."""
    today = today or date.today()
    settings = db.execute("SELECT * FROM settings WHERE user_id = ?", (user_id,)).fetchone()

    if settings:
        high = _safe_json(settings["high_keywords"], [])
        medium = _safe_json(settings["medium_keywords"], [])
        weights = _safe_json(settings["category_weights"], {})
    else:
        high, medium, weights = [], [], {}

    context = RiskContext(
        high_keywords=[str(word) for word in high] or list(HIGH_KEYWORDS),
        medium_keywords=[str(word) for word in medium] or list(MEDIUM_KEYWORDS),
        category_weights={
            **CATEGORY_WEIGHTS,
            **{str(key): float(value) for key, value in weights.items()},
        },
    )

    backlog_query = """
        SELECT COUNT(*) AS count, COALESCE(SUM(effort_minutes), 0) AS minutes
        FROM tasks
        WHERE user_id = ? AND status = 'pending' AND due_date IS NOT NULL
          AND due_date <= ?
    """
    backlog_params: list = [user_id, (today + timedelta(days=7)).isoformat()]
    if exclude_task_id is not None:
        backlog_query += " AND id != ?"
        backlog_params.append(exclude_task_id)
    backlog = db.execute(backlog_query, backlog_params).fetchone()
    context.backlog_count = int(backlog["count"] or 0)
    context.backlog_minutes = int(backlog["minutes"] or 0)

    history_query = """
        SELECT COUNT(*) AS samples,
               COALESCE(SUM(CASE WHEN date(completed_at) <= due_date THEN 1 ELSE 0 END), 0) AS on_time
        FROM tasks
        WHERE user_id = ? AND category = ? AND status = 'completed' AND due_date IS NOT NULL
    """
    history_params: list = [user_id, category]
    if exclude_task_id is not None:
        history_query += " AND id != ?"
        history_params.append(exclude_task_id)
    history = db.execute(history_query, history_params).fetchone()
    context.category_samples = int(history["samples"] or 0)
    context.category_on_time = int(history["on_time"] or 0)
    return context


def _deadline_signal(days: int | None) -> dict:
    if days is None:
        impact, detail = 0, "No deadline is set, so lateness cannot be measured."
    elif days < 0:
        impact, detail = 42, f"Overdue by {abs(days)} day{'s' if abs(days) != 1 else ''}."
    elif days == 0:
        impact, detail = 36, "Due today."
    elif days == 1:
        impact, detail = 30, "Due tomorrow."
    elif days <= 3:
        impact, detail = 24, f"Due in {days} days."
    elif days <= 7:
        impact, detail = 15, f"Due this week ({days} days)."
    elif days <= 14:
        impact, detail = 7, f"Due in {days} days."
    else:
        impact, detail = 2, f"Due in {days} days — still some runway."
    return _signal("deadline", "Deadline proximity", impact, detail)


def _effort_signal(days: int | None, effort_minutes: int) -> dict:
    if days is None:
        return _signal(
            "effort",
            "Effort vs. time left",
            0,
            "Add a due date to compare effort with the time remaining.",
        )
    if days < 0:
        return _signal(
            "effort",
            "Effort vs. time left",
            24,
            f"{_format_minutes(effort_minutes)} of work is still open after the deadline.",
        )

    capacity = 120 if days == 0 else max(60, days * DAILY_CAPACITY_MINUTES)
    ratio = effort_minutes / capacity
    if ratio >= 2:
        impact = 28
    elif ratio >= 1.25:
        impact = 22
    elif ratio >= 0.75:
        impact = 15
    elif ratio >= 0.4:
        impact = 8
    else:
        impact = 3
    return _signal(
        "effort",
        "Effort vs. time left",
        impact,
        f"{_format_minutes(effort_minutes)} of work against roughly "
        f"{_format_minutes(capacity)} of spare capacity before the deadline.",
    )


def _keyword_signal(text: str, context: RiskContext) -> dict:
    lowered = text.lower()
    high_hits = [word for word in context.high_keywords if word and word.lower() in lowered]
    medium_hits = [word for word in context.medium_keywords if word and word.lower() in lowered]
    low_hits = [word for word in LOW_KEYWORDS if word in lowered]

    impact = min(10, len(high_hits) * 5 + len(medium_hits) * 2)
    if not high_hits and low_hits:
        impact = -5
        detail = f"Soft language lowers urgency: {', '.join(sorted(low_hits))}."
    elif high_hits:
        detail = f"Urgency language found: {', '.join(sorted(high_hits)[:3])}."
    elif medium_hits:
        detail = f"Work-related language found: {', '.join(sorted(medium_hits)[:3])}."
    else:
        detail = "No urgency keywords found in the title or description."
    return _signal("keywords", "Urgency language", impact, detail)


def _category_signal(category: str, context: RiskContext) -> dict:
    weight = float(context.category_weights.get(category, 0.4))
    impact = round(max(0.0, min(1.0, weight)) * 10)
    detail = f"Your {category} category carries a {weight:.2f} risk weight."
    return _signal("category", "Category weight", impact, detail)


def _backlog_signal(context: RiskContext) -> dict:
    if context.backlog_count <= 0:
        return _signal(
            "backlog", "Queue pressure", 0, "No other pending tasks are due in the next 7 days."
        )
    capacity = 7 * DAILY_CAPACITY_MINUTES
    ratio = context.backlog_minutes / capacity
    if ratio >= 1.25:
        impact = 10
    elif ratio >= 0.6:
        impact = 7
    else:
        impact = 3
    return _signal(
        "backlog",
        "Queue pressure",
        impact,
        f"{context.backlog_count} other task(s) and "
        f"{_format_minutes(context.backlog_minutes)} of work are due in the next 7 days.",
    )


def _age_signal(created_at, days: int | None, today: date) -> dict:
    if days is not None and days > 14:
        return _signal("age", "Task age", 0, "The deadline is far enough away that age matters less.")
    created = _as_date(created_at)
    if created is None:
        return _signal("age", "Task age", 0, "Creation date is unavailable.")
    age = (today - created).days
    if age >= 21:
        impact = 8
    elif age >= 10:
        impact = 5
    elif age >= 4:
        impact = 2
    else:
        impact = 0
    if impact == 0:
        detail = "This task was added recently."
    else:
        detail = f"Created {age} days ago and still open."
    return _signal("age", "Task age", impact, detail)


def _history_signal(context: RiskContext) -> dict:
    if context.category_samples < 4:
        return _signal(
            "history",
            "Category track record",
            0,
            f"Only {context.category_samples} completed task(s) in this category so far.",
        )
    slip_rate = 1 - (context.category_on_time / context.category_samples)
    impact = max(-5, min(8, round((slip_rate - 0.25) * 12)))
    detail = (
        f"{context.category_on_time} of {context.category_samples} completed tasks in this "
        f"category met their deadline."
    )
    return _signal("history", "Category track record", impact, detail)


def _signal(key: str, label: str, impact: int, detail: str) -> dict:
    direction = "up" if impact > 0 else "down" if impact < 0 else "neutral"
    return {
        "key": key,
        "label": label,
        "impact": impact,
        "direction": direction,
        "detail": detail,
    }


def _format_minutes(minutes: int) -> str:
    minutes = max(0, int(minutes))
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes / 60
    text = f"{hours:.1f}".rstrip("0").rstrip(".")
    return f"{text}h"


def _band(score: float) -> tuple[str, str, str]:
    if score >= 70:
        return "critical", "Critical", "HIGH"
    if score >= 45:
        return "high", "High", "HIGH"
    if score >= 25:
        return "watch", "Watch", "MEDIUM"
    return "low", "Low", "LOW"


def compute_risk(
    task: dict,
    context: RiskContext | None = None,
    today: date | None = None,
) -> dict:
    """Score a task from 0 to 100 and return an explainable breakdown."""
    today = today or date.today()
    context = context or RiskContext()
    task = dict(task)

    if task.get("status") == "completed":
        return {
            "risk_score": 0.0,
            "raw_score": 0.0,
            "risk_band": "low",
            "risk_label": "Low",
            "priority": "LOW",
            "source": "rules",
            "model_version": "rules-v1",
            "confidence": None,
            "signals": [],
            "headline": "Completed — no deadline risk.",
            "summary": "This task is finished, so it is no longer monitored.",
        }

    due = _as_date(task.get("due_date"))
    days = (due - today).days if due else None
    effort = int(task.get("effort_minutes") or 60)
    text = f"{task.get('title') or ''} {task.get('description') or ''}"

    signals = [
        _deadline_signal(days),
        _effort_signal(days, effort),
        _keyword_signal(text, context),
        _category_signal(str(task.get("category") or "other"), context),
        _backlog_signal(context),
        _age_signal(task.get("created_at"), days, today),
        _history_signal(context),
    ]

    raw_score = sum(signal["impact"] for signal in signals)
    score = round(max(0.0, min(MAX_SCORE, raw_score)), 1)
    band, label, priority = _band(score)

    positive = sorted((s for s in signals if s["impact"] > 0), key=lambda s: -s["impact"])
    top_detail = positive[0]["detail"] if positive else "No strong risk signals were found."
    second_detail = positive[1]["detail"] if len(positive) > 1 else ""
    headline = {
        "critical": "Critical — this deadline needs intervention now.",
        "high": "High — the current plan is unlikely to hold.",
        "watch": "Watch — this can slip if the week gets busy.",
        "low": "Low — this task is on track.",
    }[band]
    summary = " ".join(part for part in (top_detail, second_detail) if part)

    return {
        "risk_score": score,
        "raw_score": round(raw_score, 1),
        "risk_band": band,
        "risk_label": label,
        "priority": priority,
        "source": "rules",
        "model_version": "rules-v1",
        "confidence": None,
        "signals": signals,
        "headline": headline,
        "summary": summary,
        "days_until_due": days,
    }
