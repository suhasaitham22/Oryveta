"""Deterministic local benchmark evaluations. No Kaggle credentials or submissions."""

from __future__ import annotations

import hashlib
import json
import platform
import time
from typing import Any

import sklearn
from sklearn.datasets import load_breast_cancer, load_iris, load_wine
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

CHALLENGES = {
    "iris": {
        "id": "iris", "title": "Iris classification", "category": "Classification",
        "description": "Establish a reproducible, stratified classification baseline on Fisher's Iris dataset.",
        "difficulty": "Starter", "samples": 150, "metric": "Accuracy", "source": "scikit-learn",
    },
    "wine": {
        "id": "wine", "title": "Wine recognition", "category": "Classification",
        "description": "Compare linear and nonlinear models on a multiclass chemistry dataset.",
        "difficulty": "Intermediate", "samples": 178, "metric": "Accuracy", "source": "scikit-learn",
    },
    "breast_cancer": {
        "id": "breast_cancer", "title": "Diagnostic classification", "category": "Classification",
        "description": "Evaluate two standard baselines with stratified cross-validation; research-only sample data.",
        "difficulty": "Intermediate", "samples": 569, "metric": "Balanced accuracy", "source": "scikit-learn",
    },
}

LOADERS = {"iris": load_iris, "wine": load_wine, "breast_cancer": load_breast_cancer}


def run_benchmark(challenge_id: str, seed: int = 42) -> dict[str, Any]:
    """Compare pinned modeling pipelines on the same reproducible CV folds.

    This is a starter harness only. Scores do not represent Kaggle or SOTA results.
    """
    if challenge_id not in LOADERS:
        raise ValueError(f"Unknown benchmark: {challenge_id}")
    if not 0 <= seed <= 2**32 - 1:
        raise ValueError("seed out of range")
    started = time.monotonic()
    dataset = LOADERS[challenge_id]()
    x, y = dataset.data, dataset.target
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
    models = {
        "Logistic regression": lambda: make_pipeline(
            StandardScaler(), LogisticRegression(max_iter=2000, random_state=seed)
        ),
        "Random forest": lambda: RandomForestClassifier(
            n_estimators=80, max_depth=8, n_jobs=1, random_state=seed
        ),
    }
    results = []
    for name, factory in models.items():
        scores = []
        for train_idx, valid_idx in folds.split(x, y):
            model = factory()
            model.fit(x[train_idx], y[train_idx])
            predicted = model.predict(x[valid_idx])
            metrics = {
                "accuracy": float(accuracy_score(y[valid_idx], predicted)),
                "balanced_accuracy": float(balanced_accuracy_score(y[valid_idx], predicted)),
                "f1_macro": float(f1_score(y[valid_idx], predicted, average="macro")),
            }
            scores.append(metrics)
        results.append({
            "model": name,
            "folds": scores,
            "mean_accuracy": round(sum(row["accuracy"] for row in scores) / 5, 4),
            "mean_balanced_accuracy": round(sum(row["balanced_accuracy"] for row in scores) / 5, 4),
            "mean_f1_macro": round(sum(row["f1_macro"] for row in scores) / 5, 4),
        })
    metric = "mean_balanced_accuracy" if challenge_id == "breast_cancer" else "mean_accuracy"
    winner = max(results, key=lambda entry: entry[metric])
    evidence = {
        "dataset": challenge_id,
        "samples": len(y),
        "features": len(dataset.feature_names),
        "seed": seed,
        "folds": 5,
        "validation": "StratifiedKFold (5 splits, shuffled, pinned seed)",
        "metric_key": metric,
        "models": results,
        "best_model": winner["model"],
        "best_score": winner[metric],
        "duration_seconds": round(time.monotonic() - started, 3),
        "environment": {
            "python": platform.python_version(), "sklearn": sklearn.__version__,
        },
        "note": "Local public benchmark; no Kaggle entry, leaderboard or external model claims.",
    }
    encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["sha256"] = hashlib.sha256(encoded).hexdigest()
    return evidence
