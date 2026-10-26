"""Train the optional missed-deadline risk model on synthetic cold-start data.

Usage:
    python -m backend.risk_engine.train --samples 8000

The artifact is written to backend/risk_engine/artifacts/ and is intentionally
gitignored. The app falls back to the deterministic rule engine when it is absent.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

from backend.database import CATEGORY_WEIGHTS, HIGH_KEYWORDS, MEDIUM_KEYWORDS
from backend.risk_engine.features import CATEGORIES, FEATURE_NAMES, extract_features
from backend.risk_engine.rules import RiskContext, compute_risk

MODEL_VERSION = "rf-v1"
DEFAULT_SAMPLES = 8000
DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"

_TITLE_TEMPLATES = [
    "Submit the quarterly report",
    "Prepare the client presentation",
    "Review the project notes",
    "Finish the course assignment",
    "Book the follow-up appointment",
    "Send the invoice",
    "Plan the sprint",
    "Draft the proposal",
    "Complete the compliance form",
    "Update the budget sheet",
    "Write the literature review",
    "Fix the leaking tap",
]
_HIGH_PHRASES = ["urgent", "asap", "critical", "final", "submit", "deadline"]
_MEDIUM_PHRASES = ["review", "draft", "follow up", "prepare", "client", "report"]
_SOFT_PHRASES = ["someday", "maybe", "optional", "whenever"]


def _sigmoid(value: float) -> float:
    value = max(-30.0, min(30.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def _sample_days(rng: random.Random) -> int:
    bucket = rng.choices(
        ["overdue", "today", "soon", "week", "fortnight", "later"],
        weights=[0.08, 0.1, 0.24, 0.24, 0.17, 0.17],
        k=1,
    )[0]
    return {
        "overdue": -rng.randint(1, 8),
        "today": 0,
        "soon": rng.randint(1, 3),
        "week": rng.randint(4, 7),
        "fortnight": rng.randint(8, 14),
        "later": rng.randint(15, 45),
    }[bucket]


def _build_task(rng: random.Random, today: date) -> tuple[dict, RiskContext, int]:
    category = rng.choices(CATEGORIES, weights=[30, 22, 12, 9, 9, 6, 12], k=1)[0]
    days = _sample_days(rng)
    effort = int(min(600, max(10, round(math.exp(rng.gauss(math.log(95), 0.85)) / 5) * 5)))
    created_days_ago = rng.randint(0, 40)
    due = today + timedelta(days=days)
    created_at = (today - timedelta(days=created_days_ago)).isoformat() + "T09:00:00+00:00"

    high = rng.sample(
        HIGH_KEYWORDS, k=rng.choices([0, 1, 2, 3], weights=[0.35, 0.34, 0.21, 0.1], k=1)[0]
    )
    medium = rng.sample(
        MEDIUM_KEYWORDS, k=rng.choices([0, 1, 2], weights=[0.42, 0.4, 0.18], k=1)[0]
    )
    soft = rng.sample(
        _SOFT_PHRASES, k=rng.choices([0, 1], weights=[0.82, 0.18], k=1)[0]
    )

    title = rng.choice(_TITLE_TEMPLATES)
    if rng.random() < 0.55 and high:
        title = f"{title} — {rng.choice(high)}"
    description_bits = []
    if medium:
        description_bits.append(f"{rng.choice(_MEDIUM_PHRASES)} {rng.choice(medium)}")
    if soft:
        description_bits.append(f"{rng.choice(soft)} for now")
    if rng.random() < 0.4:
        description_bits.append("Coordinate with the team and keep notes in the shared doc.")
    description = " ".join(description_bits)

    backlog_count = rng.choices([0, 1, 2, 3, 4, 5, 7, 9], weights=[18, 20, 18, 14, 11, 8, 7, 4], k=1)[0]
    backlog_minutes = sum(rng.randint(20, 150) for _ in range(backlog_count))
    category_samples = rng.choices([0, 1, 2, 4, 7, 12, 20], weights=[20, 12, 14, 18, 16, 12, 8], k=1)[0]
    category_on_time = (
        sum(1 for _ in range(category_samples) if rng.random() < rng.uniform(0.45, 0.9))
        if category_samples
        else 0
    )

    context = RiskContext(
        high_keywords=list(HIGH_KEYWORDS),
        medium_keywords=list(MEDIUM_KEYWORDS),
        category_weights=dict(CATEGORY_WEIGHTS),
        backlog_count=backlog_count,
        backlog_minutes=backlog_minutes,
        category_samples=category_samples,
        category_on_time=category_on_time,
    )
    task = {
        "title": title,
        "description": description,
        "category": category,
        "due_date": due.isoformat(),
        "effort_minutes": effort,
        "created_at": created_at,
        "status": "pending",
    }

    time_pressure = 0.06
    if days < 0:
        time_pressure = 1.0
    elif days == 0:
        time_pressure = 0.86
    elif days <= 3:
        time_pressure = 0.64
    elif days <= 7:
        time_pressure = 0.42
    elif days <= 14:
        time_pressure = 0.2
    features = extract_features(task, context, today)
    latent = (
        -4.0
        + 2.2 * time_pressure
        + 1.2 * min(features["effort_ratio"], 2.5)
        + 0.45 * features["high_keyword_count"]
        + 0.18 * features["medium_keyword_count"]
        - 0.3 * features["soft_keyword_count"]
        + 1.1 * features["category_slip_rate"]
        + 0.12 * features["backlog_count"]
        + 0.025 * features["created_days_ago"]
        + 0.75 * features["category_weight"]
        + rng.gauss(0, 0.8)
    )
    missed = 1 if rng.random() < _sigmoid(latent) else 0
    return task, context, missed


def generate_synthetic_dataset(
    samples: int = DEFAULT_SAMPLES, seed: int = 42
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (features, labels, rule_scores) for a reproducible synthetic dataset."""
    if samples < 100:
        raise ValueError("Generate at least 100 samples.")
    rng = random.Random(seed)
    today = date.today()
    rows: list[list[float]] = []
    labels: list[int] = []
    rule_scores: list[float] = []

    for _ in range(samples):
        task, context, missed = _build_task(rng, today)
        features = extract_features(task, context, today)
        rows.append([features[name] for name in FEATURE_NAMES])
        labels.append(missed)
        rule_scores.append(compute_risk(task, context, today)["risk_score"] / 100)

    return (
        np.asarray(rows, dtype=float),
        np.asarray(labels, dtype=int),
        np.asarray(rule_scores, dtype=float),
    )


def _evaluate(y_true: np.ndarray, probabilities: np.ndarray) -> dict:
    predictions = (probabilities >= 0.5).astype(int)
    matrix = confusion_matrix(y_true, predictions, labels=[0, 1]).tolist()
    return {
        "roc_auc": round(float(roc_auc_score(y_true, probabilities)), 4),
        "accuracy": round(float(accuracy_score(y_true, predictions)), 4),
        "precision": round(float(precision_score(y_true, predictions, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, predictions, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, predictions, zero_division=0)), 4),
        "brier": round(float(brier_score_loss(y_true, probabilities)), 4),
        "positive_rate": round(float(y_true.mean()), 4),
        "confusion_matrix": matrix,
    }


def train_model(
    samples: int = DEFAULT_SAMPLES,
    output_dir: str | Path | None = None,
    seed: int = 42,
) -> dict:
    """Train the risk classifier, write the artifact and metadata, return metrics."""
    output_path = Path(output_dir) if output_dir else DEFAULT_ARTIFACT_DIR
    output_path.mkdir(parents=True, exist_ok=True)

    features, labels, rule_scores = generate_synthetic_dataset(samples, seed)
    x_train, x_test, y_train, y_test, rules_train, rules_test = train_test_split(
        features,
        labels,
        rule_scores,
        test_size=0.2,
        random_state=seed,
        stratify=labels,
    )

    model = RandomForestClassifier(
        n_estimators=220,
        max_depth=11,
        min_samples_leaf=6,
        class_weight="balanced_subsample",
        random_state=seed,
        n_jobs=-1,
    )
    model.fit(x_train, y_train)
    probabilities = model.predict_proba(x_test)[:, 1]

    metrics = _evaluate(y_test, probabilities)
    metrics.update(
        {
            "samples": samples,
            "train_size": len(x_train),
            "test_size": len(x_test),
            "rule_auc": round(float(roc_auc_score(y_test, rules_test)), 4),
            "hybrid_auc": round(
                float(roc_auc_score(y_test, 0.65 * probabilities + 0.35 * rules_test)), 4
            ),
        }
    )

    importances = sorted(
        zip(FEATURE_NAMES, model.feature_importances_, strict=True),
        key=lambda pair: -pair[1],
    )
    feature_importances = {name: round(float(value), 4) for name, value in importances[:12]}
    trained_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    artifact = {
        "model": model,
        "feature_names": FEATURE_NAMES,
        "version": MODEL_VERSION,
        "trained_at": trained_at,
        "metrics": metrics,
        "label": "missed_deadline",
        "synthetic": True,
    }
    joblib.dump(artifact, output_path / "risk_model.joblib")

    metadata = {
        "version": MODEL_VERSION,
        "trained_at": trained_at,
        "synthetic": True,
        "label": "missed_deadline",
        "features": FEATURE_NAMES,
        "metrics": metrics,
        "feature_importances": feature_importances,
    }
    (output_path / "model_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Train DeadlineRadar's risk model.")
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    metadata = train_model(args.samples, args.output, args.seed)
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
