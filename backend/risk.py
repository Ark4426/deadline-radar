"""Risk preview API: explainable scoring and a rescue plan before saving."""

from __future__ import annotations

from datetime import date

from flask import Blueprint, jsonify, request

from backend.database import get_db, utc_now
from backend.risk_engine import build_rescue_plan, compute_risk, load_context
from backend.security import current_user, login_required
from backend.tasks import CATEGORIES, get_owned_task, parse_iso_date

risk_bp = Blueprint("risk", __name__, url_prefix="/api/risk")


def _preview_task(payload: dict, user_id: int):
    """Validate the small subset of fields needed for a live preview."""
    title = " ".join(str(payload.get("title") or "").split())[:200]
    description = str(payload.get("description") or "").strip()[:4000]
    category = str(payload.get("category") or "other").strip().lower()
    if category not in CATEGORIES:
        return None, "Choose a valid category."

    due_date, error = parse_iso_date(payload.get("due_date"))
    if error:
        return None, error

    try:
        effort = int(payload.get("effort_minutes", 60))
    except (TypeError, ValueError):
        return None, "Effort must be a whole number of minutes."
    if effort < 5 or effort > 10080:
        return None, "Effort must be between 5 and 10080 minutes."

    task_id = payload.get("task_id")
    existing = None
    if task_id is not None:
        try:
            task_id = int(task_id)
        except (TypeError, ValueError):
            return None, "Task id must be a number."
        existing = get_owned_task(task_id, user_id)
        if existing is None:
            return None, "Task not found."

    task = {
        "id": task_id,
        "title": title or "Untitled task",
        "description": description,
        "category": category,
        "due_date": due_date,
        "effort_minutes": effort,
        "status": existing["status"] if existing else "pending",
        "created_at": existing["created_at"] if existing else utc_now(),
    }
    return task, None


@risk_bp.post("/preview")
@login_required
def preview():
    user = current_user()
    payload = request.get_json(silent=True) or {}
    task, error = _preview_task(payload, user["id"])
    if error:
        return jsonify({"error": error}), 400

    db = get_db()
    context = load_context(
        db,
        user["id"],
        task["category"],
        exclude_task_id=task.get("id"),
        today=date.today(),
    )
    assessment = compute_risk(task, context)
    plan = build_rescue_plan(task, assessment, context)

    return jsonify(
        {
            "assessment": assessment,
            "rescue_plan": plan,
            "model": {
                "source": assessment["source"],
                "version": assessment["model_version"],
                "confidence": assessment["confidence"],
            },
        }
    )


@risk_bp.get("/model-info")
@login_required
def model_info():
    return jsonify(
        {
            "source": "rules",
            "version": "rules-v1",
            "model_available": False,
            "description": (
                "Deterministic deadline-risk rules based on time pressure, effort, "
                "urgency language, category weight, queue pressure, task age, and "
                "category history."
            ),
        }
    )
