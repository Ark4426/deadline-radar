"""Task CRUD with per-user ownership, views, filters, and pagination."""

from __future__ import annotations

import math
from datetime import date

from flask import Blueprint, jsonify, request

from backend.database import get_db, utc_now
from backend.risk_engine import compute_risk, load_context
from backend.security import current_user, login_required

tasks_bp = Blueprint("tasks", __name__, url_prefix="/api/tasks")

CATEGORIES = ("work", "study", "personal", "health", "finance", "home", "other")
PRIORITIES = ("HIGH", "MEDIUM", "LOW")
STATUSES = ("pending", "completed")
MAX_TITLE = 200
MAX_DESCRIPTION = 4000


def parse_iso_date(value, field: str = "due_date"):
    if value in (None, ""):
        return None, None
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None, f"{field} must use YYYY-MM-DD format."
    return parsed.isoformat(), None


def serialize_task(row, today: date | None = None) -> dict:
    today = today or date.today()
    task = dict(row)
    due = task.get("due_date")
    days_until_due = None
    is_overdue = False
    if due:
        days_until_due = (date.fromisoformat(due) - today).days
        is_overdue = days_until_due < 0 and task["status"] == "pending"

    risk_score = task.get("risk_score")
    task.update(
        {
            "days_until_due": days_until_due,
            "is_overdue": is_overdue,
            "risk_score": round(float(risk_score), 1) if risk_score is not None else None,
        }
    )
    return task


def refresh_risk(user_id: int) -> None:
    """Re-score every pending task so stored risk and auto priority track today's date."""
    # ponytail: rescans all pending tasks (2 queries each) per call; cache by date if lists get huge
    db = get_db()
    today = date.today()
    rows = db.execute(
        "SELECT * FROM tasks WHERE user_id = ? AND status = 'pending'", (user_id,)
    ).fetchall()
    for row in rows:
        context = load_context(db, user_id, row["category"], exclude_task_id=row["id"], today=today)
        assessment = compute_risk(dict(row), context, today=today)
        db.execute(
            """
            UPDATE tasks
            SET risk_score = ?, risk_band = ?, predicted_priority = ?,
                priority = CASE WHEN priority_source = 'auto' THEN ? ELSE priority END
            WHERE id = ?
            """,
            (
                assessment["risk_score"],
                assessment["risk_band"],
                assessment["priority"],
                assessment["priority"],
                row["id"],
            ),
        )
    db.commit()


def get_owned_task(task_id: int, user_id: int):
    return get_db().execute(
        "SELECT * FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
    ).fetchone()


def _validate_common(payload: dict, partial: bool = False) -> tuple[dict, str | None]:
    clean: dict = {}

    if not partial or "title" in payload:
        title = " ".join(str(payload.get("title") or "").split())
        if not title:
            return {}, "Title is required."
        if len(title) > MAX_TITLE:
            return {}, f"Title must be {MAX_TITLE} characters or fewer."
        clean["title"] = title

    if "description" in payload or not partial:
        description = str(payload.get("description") or "").strip()
        if len(description) > MAX_DESCRIPTION:
            return {}, f"Description must be {MAX_DESCRIPTION} characters or fewer."
        clean["description"] = description

    if "category" in payload or not partial:
        category = str(payload.get("category") or "other").strip().lower()
        if category not in CATEGORIES:
            return {}, "Choose a valid category."
        clean["category"] = category

    if "due_date" in payload or not partial:
        due, error = parse_iso_date(payload.get("due_date"))
        if error:
            return {}, error
        clean["due_date"] = due

    if "effort_minutes" in payload or not partial:
        raw_effort = payload.get("effort_minutes", 60)
        try:
            effort = int(raw_effort)
        except (TypeError, ValueError):
            return {}, "Effort must be a whole number of minutes."
        if effort < 5 or effort > 10080:
            return {}, "Effort must be between 5 and 10080 minutes."
        clean["effort_minutes"] = effort

    if "priority" in payload:
        priority = payload["priority"]
        if priority is not None:
            priority = str(priority).strip().upper()
            if priority not in PRIORITIES:
                return {}, "Priority must be HIGH, MEDIUM, or LOW."
        clean["priority"] = priority

    if "status" in payload:
        status = str(payload.get("status") or "").strip().lower()
        if status not in STATUSES:
            return {}, "Status must be pending or completed."
        clean["status"] = status

    return clean, None


def _task_counts(user_id: int, today: str) -> dict:
    row = get_db().execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(status = 'completed'), 0) AS completed,
            COALESCE(SUM(status = 'pending'), 0) AS pending,
            COALESCE(SUM(status = 'pending' AND due_date = ?), 0) AS today,
            COALESCE(SUM(status = 'pending' AND due_date > ?), 0) AS upcoming,
            COALESCE(SUM(status = 'pending' AND due_date < ?), 0) AS overdue,
            COALESCE(SUM(status = 'pending' AND risk_band IN ('high', 'critical')), 0) AS at_risk
        FROM tasks
        WHERE user_id = ?
        """,
        (today, today, today, user_id),
    ).fetchone()
    return {key: int(row[key] or 0) for key in row.keys()}


@tasks_bp.get("")
@login_required
def list_tasks():
    user = current_user()
    today = date.today()
    today_iso = today.isoformat()

    view = (request.args.get("view") or "all").strip().lower()
    status = (request.args.get("status") or "").strip().lower()
    priority = (request.args.get("priority") or "").strip().upper()
    category = (request.args.get("category") or "").strip().lower()
    search = (request.args.get("search") or "").strip()
    sort = (request.args.get("sort") or "due").strip().lower()

    try:
        page = max(1, int(request.args.get("page", 1)))
        page_size = min(100, max(5, int(request.args.get("page_size", 25))))
    except ValueError:
        return jsonify({"error": "Pagination values must be numbers."}), 400

    filters = ["user_id = ?"]
    params: list = [user["id"]]

    if view == "today":
        filters.append("due_date = ? AND status = 'pending'")
        params.append(today_iso)
    elif view == "upcoming":
        filters.append("due_date > ? AND status = 'pending'")
        params.append(today_iso)
    elif view == "overdue":
        filters.append("due_date < ? AND status = 'pending'")
        params.append(today_iso)
    elif view == "at-risk":
        filters.append("risk_band IN ('high', 'critical') AND status = 'pending'")
    elif view == "completed":
        filters.append("status = 'completed'")
    elif view != "all":
        return jsonify({"error": "Unknown view."}), 400

    if status in STATUSES:
        filters.append("status = ?")
        params.append(status)
    elif status:
        return jsonify({"error": "Invalid status filter."}), 400

    if priority in PRIORITIES:
        filters.append("priority = ?")
        params.append(priority)
    elif priority:
        return jsonify({"error": "Invalid priority filter."}), 400

    if category in CATEGORIES:
        filters.append("category = ?")
        params.append(category)
    elif category:
        return jsonify({"error": "Invalid category filter."}), 400

    if search:
        filters.append("(title LIKE ? OR description LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like])

    order_by = {
        "due": "CASE WHEN due_date IS NULL THEN 1 ELSE 0 END, due_date ASC, created_at DESC",
        "risk": "CASE WHEN risk_score IS NULL THEN 1 ELSE 0 END, risk_score DESC, due_date ASC",
        "created": "created_at DESC",
        "priority": "CASE priority WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, due_date ASC",
    }.get(sort)
    if order_by is None:
        return jsonify({"error": "Invalid sort option."}), 400

    refresh_risk(user["id"])
    where = " AND ".join(filters)
    db = get_db()
    total = db.execute(f"SELECT COUNT(*) FROM tasks WHERE {where}", params).fetchone()[0]
    rows = db.execute(
        f"""
        SELECT * FROM tasks
        WHERE {where}
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
        """,
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()

    return jsonify(
        {
            "tasks": [serialize_task(row, today) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": math.ceil(total / page_size) if total else 0,
            "counts": _task_counts(user["id"], today_iso),
            "view": view,
        }
    )


@tasks_bp.post("")
@login_required
def create_task():
    user = current_user()
    payload = request.get_json(silent=True) or {}
    clean, error = _validate_common(payload)
    if error:
        return jsonify({"error": error}), 400

    now = utc_now()
    priority = clean.get("priority") or "MEDIUM"
    source = "manual" if clean.get("priority") else "auto"

    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO tasks
            (user_id, title, description, category, due_date, status, priority,
             priority_source, effort_minutes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
        """,
        (
            user["id"],
            clean["title"],
            clean["description"],
            clean["category"],
            clean["due_date"],
            priority,
            source,
            clean["effort_minutes"],
            now,
            now,
        ),
    )
    db.commit()
    refresh_risk(user["id"])
    row = get_owned_task(cursor.lastrowid, user["id"])
    return jsonify({"task": serialize_task(row)}), 201


@tasks_bp.get("/<int:task_id>")
@login_required
def get_task(task_id: int):
    user = current_user()
    row = get_owned_task(task_id, user["id"])
    if row is None:
        return jsonify({"error": "Task not found."}), 404
    return jsonify({"task": serialize_task(row)})


@tasks_bp.patch("/<int:task_id>")
@login_required
def update_task(task_id: int):
    user = current_user()
    row = get_owned_task(task_id, user["id"])
    if row is None:
        return jsonify({"error": "Task not found."}), 404

    payload = request.get_json(silent=True) or {}
    clean, error = _validate_common(payload, partial=True)
    if error:
        return jsonify({"error": error}), 400
    if not clean:
        return jsonify({"error": "No supported fields were provided."}), 400

    updates = dict(clean)
    if "priority" in updates:
        if updates["priority"] is None:
            # null hands priority back to the risk engine (refresh_risk sets it below)
            updates.pop("priority")
            updates["priority_source"] = "auto"
        else:
            updates["priority_source"] = "manual"

    if "status" in updates:
        updates["completed_at"] = utc_now() if updates["status"] == "completed" else None

    updates["updated_at"] = utc_now()
    assignments = ", ".join(f"{field} = ?" for field in updates)
    db = get_db()
    db.execute(
        f"UPDATE tasks SET {assignments} WHERE id = ? AND user_id = ?",
        [*updates.values(), task_id, user["id"]],
    )
    db.commit()
    refresh_risk(user["id"])

    updated = get_owned_task(task_id, user["id"])
    return jsonify({"task": serialize_task(updated)})


@tasks_bp.patch("/<int:task_id>/complete")
@login_required
def toggle_complete(task_id: int):
    user = current_user()
    row = get_owned_task(task_id, user["id"])
    if row is None:
        return jsonify({"error": "Task not found."}), 404

    payload = request.get_json(silent=True) or {}
    if "completed" in payload:
        completed = bool(payload["completed"])
    else:
        completed = row["status"] != "completed"

    status = "completed" if completed else "pending"
    db = get_db()
    db.execute(
        "UPDATE tasks SET status = ?, completed_at = ?, updated_at = ? WHERE id = ?",
        (status, utc_now() if completed else None, utc_now(), task_id),
    )
    db.commit()
    refresh_risk(user["id"])
    updated = get_owned_task(task_id, user["id"])
    return jsonify({"task": serialize_task(updated)})


@tasks_bp.delete("/<int:task_id>")
@login_required
def delete_task(task_id: int):
    user = current_user()
    row = get_owned_task(task_id, user["id"])
    if row is None:
        return jsonify({"error": "Task not found."}), 404

    db = get_db()
    db.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user["id"]))
    db.commit()
    return jsonify({"ok": True})
