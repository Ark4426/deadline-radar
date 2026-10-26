"""Feature extraction shared by training and inference."""

from __future__ import annotations

from datetime import date

from backend.risk_engine.rules import LOW_KEYWORDS, RiskContext

CATEGORIES = ("work", "study", "personal", "health", "finance", "home", "other")

NUMERIC_FEATURES = [
    "days_until_due",
    "has_due_date",
    "is_overdue",
    "due_today",
    "due_within_3_days",
    "due_within_7_days",
    "due_weekday",
    "effort_minutes",
    "effort_ratio",
    "title_length",
    "description_length",
    "high_keyword_count",
    "medium_keyword_count",
    "soft_keyword_count",
    "category_weight",
    "backlog_count",
    "backlog_pressure",
    "created_days_ago",
    "category_samples",
    "category_slip_rate",
    "category_confidence",
]
CATEGORY_FEATURES = [f"category_{category}" for category in CATEGORIES]
FEATURE_NAMES = NUMERIC_FEATURES + CATEGORY_FEATURES


def _parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _days_ago(created_at, today: date) -> int:
    created = _parse_date(created_at)
    if created is None:
        return 0
    return max(0, (today - created).days)


def extract_features(
    task: dict,
    context: RiskContext | None = None,
    today: date | None = None,
) -> dict[str, float]:
    """Return every model feature for one task draft."""
    today = today or date.today()
    context = context or RiskContext()
    task = dict(task)

    due = _parse_date(task.get("due_date"))
    days = (due - today).days if due else None
    effort = float(task.get("effort_minutes") or 60)
    text = f"{task.get('title') or ''} {task.get('description') or ''}".lower()
    category = str(task.get("category") or "other").lower()
    if category not in CATEGORIES:
        category = "other"

    high_hits = sum(1 for word in context.high_keywords if word and word.lower() in text)
    medium_hits = sum(1 for word in context.medium_keywords if word and word.lower() in text)
    soft_hits = sum(1 for word in LOW_KEYWORDS if word in text)

    if days is None:
        effort_ratio = min(5.0, effort / 10080)
    elif days < 0:
        effort_ratio = min(5.0, effort / 60)
    else:
        capacity = 120 if days == 0 else max(60, days * 180)
        effort_ratio = min(5.0, effort / capacity)

    weight = float(context.category_weights.get(category, 0.4))
    if context.category_samples >= 4:
        slip_rate = 1 - (context.category_on_time / context.category_samples)
    else:
        slip_rate = 0.35

    features = {
        "days_until_due": float(days if days is not None else 60),
        "has_due_date": 1.0 if due else 0.0,
        "is_overdue": 1.0 if days is not None and days < 0 else 0.0,
        "due_today": 1.0 if days == 0 else 0.0,
        "due_within_3_days": 1.0 if days is not None and 0 <= days <= 3 else 0.0,
        "due_within_7_days": 1.0 if days is not None and 0 <= days <= 7 else 0.0,
        "due_weekday": float(due.weekday()) if due else -1.0,
        "effort_minutes": effort,
        "effort_ratio": effort_ratio,
        "title_length": float(len(str(task.get("title") or ""))),
        "description_length": float(len(str(task.get("description") or ""))),
        "high_keyword_count": float(high_hits),
        "medium_keyword_count": float(medium_hits),
        "soft_keyword_count": float(soft_hits),
        "category_weight": weight,
        "backlog_count": float(context.backlog_count),
        "backlog_pressure": min(5.0, context.backlog_minutes / 1260),
        "created_days_ago": float(_days_ago(task.get("created_at"), today)),
        "category_samples": float(context.category_samples),
        "category_slip_rate": float(slip_rate),
        "category_confidence": min(1.0, context.category_samples / 20),
    }
    for name in CATEGORIES:
        features[f"category_{name}"] = 1.0 if category == name else 0.0
    return features


def feature_vector(task: dict, context: RiskContext | None = None, today: date | None = None) -> list[float]:
    features = extract_features(task, context, today)
    return [features[name] for name in FEATURE_NAMES]
