"""Turn a risk assessment into a small, realistic rescue plan."""

from __future__ import annotations

import math
from datetime import date, timedelta

from backend.risk_engine.rules import DAILY_CAPACITY_MINUTES, RiskContext


def _format_minutes(minutes: int) -> str:
    minutes = max(0, int(minutes))
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes / 60
    text = f"{hours:.1f}".rstrip("0").rstrip(".")
    return f"{text}h"


def _day_label(target: date, today: date) -> str:
    delta = (target - today).days
    if delta <= 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    return target.strftime("%a %d %b")


def _step(title: str, detail: str, duration_minutes: int, when: str) -> dict:
    return {
        "title": title,
        "detail": detail,
        "duration_minutes": duration_minutes,
        "when": when,
    }


def build_rescue_plan(
    task: dict,
    assessment: dict,
    context: RiskContext | None = None,
    today: date | None = None,
) -> list[dict]:
    """Return 2–4 concrete next actions, focused on reducing deadline risk."""
    today = today or date.today()
    context = context or RiskContext()
    task = dict(task)
    if task.get("status") == "completed":
        return []

    due = date.fromisoformat(task["due_date"]) if task.get("due_date") else None
    days = (due - today).days if due else None
    effort = int(task.get("effort_minutes") or 60)
    band = assessment.get("risk_band", "low")
    title = task.get("title") or "this task"

    if due is not None and days < 0:
        reset = _step(
            "Reset the deadline",
            f"This deadline is {abs(days)} day(s) past. Pick an honest new date today, "
            "or explicitly drop the task instead of letting it sit overdue.",
            10,
            "Today",
        )
    else:
        reset = None

    start = _step(
        "Take a 25-minute first slice",
        f"Open {title!r} and finish the smallest visible piece. A short start beats "
        "a perfect plan; stop after 25 minutes if you need to.",
        25,
        "Today",
    )

    block_count = min(6, max(1, math.ceil(effort / 55)))
    session_minutes = min(55, max(25, math.ceil(effort / block_count)))
    if days is not None and days <= 1:
        block_when = "Today"
    else:
        block_when = f"Across the next {min(block_count, max(1, days or 1))} days"
    blocks = _step(
        f"Book {block_count} focus block{'s' if block_count != 1 else ''}",
        f"Reserve {block_count} × {session_minutes} minutes ({_format_minutes(effort)} total). "
        "Put the first block on the calendar before you close this panel.",
        effort,
        block_when,
    )

    capacity = 120 if days == 0 else max(60, (days or 0) * DAILY_CAPACITY_MINUTES)
    cut_scope = None
    if days is not None and days >= 0 and effort > capacity * 1.25:
        cut_scope = _step(
            "Cut the scope in half",
            "Ship the complete-enough version first: keep the must-haves and move the "
            "rest to a follow-up. The deadline matters more than the polish.",
            10,
            "Today",
        )

    queue = None
    if context.backlog_count >= 3:
        queue = _step(
            "Take one task off this week",
            f"{context.backlog_count} other tasks are due within 7 days. Defer, delegate, "
            "or reschedule one so this task gets your best hours.",
            5,
            "Today",
        )

    if due is not None:
        checkpoint_when = _day_label(due - timedelta(days=1), today)
        if (due - timedelta(days=1)) < today:
            checkpoint_when = "Today"
    else:
        checkpoint_when = "This week"
    checkpoint = _step(
        "Set a 10-minute checkpoint",
        "Review progress and re-run the risk check. If the score is still high, move "
        "the deadline or cut more scope.",
        10,
        checkpoint_when,
    )

    plan: list[dict] = []
    if band in {"critical", "high"}:
        if reset:
            plan.append(reset)
        plan.append(start)
        plan.append(blocks)
        if cut_scope:
            plan.append(cut_scope)
        elif queue:
            plan.append(queue)
    elif band == "watch":
        if reset:
            plan.append(reset)
        plan.append(
            _step(
                "Reserve one protected focus block",
                f"Give {title!r} 45–60 minutes before the day gets busy. One focused "
                "block is usually enough to stop a borderline task from slipping.",
                min(effort, 60),
                "Tomorrow" if days is None or days > 1 else "Today",
            )
        )
        if queue:
            plan.append(queue)
    else:
        if due is None:
            plan.append(
                _step(
                    "Give it a real deadline",
                    "A task without a date cannot be protected. Add a due date so the "
                    "radar can track it.",
                    5,
                    "Today",
                )
            )
        plan.append(
            _step(
                "Keep the current plan",
                "This task has enough runway. Leave it alone unless a higher-risk task "
                "needs the time.",
                5,
                "This week",
            )
        )

    if len(plan) >= 4:
        plan = plan[:3] + [checkpoint]
    else:
        plan.append(checkpoint)
    return plan
