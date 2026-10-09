"""Deterministic cross-validation, calibration, and threshold-policy evaluation."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import StratifiedKFold

from .contracts import CV_FOLDS, RANDOM_SEED


METRIC_NAMES = ("accuracy", "precision", "recall", "f1", "roc_auc")
CLASSIFICATION_THRESHOLD = 0.5
MINIMUM_SCREENING_RECALL = 0.75


def evaluate_candidate(
    pipeline: Any,
    X: pd.DataFrame,
    y: pd.Series,
) -> dict[str, Any]:
    """Evaluate one fixed pipeline with common leakage-safe stratified folds."""

    splitter = StratifiedKFold(
        n_splits=CV_FOLDS,
        shuffle=True,
        random_state=RANDOM_SEED,
    )
    oof_probability = np.full(len(y), np.nan, dtype=float)
    fold_rows: list[dict[str, float | int]] = []

    for fold_index, (train_indices, validation_indices) in enumerate(
        splitter.split(X, y), start=1
    ):
        fitted = clone(pipeline)
        fitted.fit(X.iloc[train_indices], y.iloc[train_indices])
        probability = fitted.predict_proba(X.iloc[validation_indices])[:, 1]
        oof_probability[validation_indices] = probability
        predicted = (probability >= CLASSIFICATION_THRESHOLD).astype(int)
        fold_rows.append(
            {
                "fold": fold_index,
                **classification_metrics(
                    y.iloc[validation_indices].to_numpy(),
                    predicted,
                    probability,
                ),
                "brier_score": float(
                    brier_score_loss(y.iloc[validation_indices], probability)
                ),
            }
        )

    if np.isnan(oof_probability).any():
        raise RuntimeError("Cross-validation did not produce one probability per row.")

    oof_predicted = (oof_probability >= CLASSIFICATION_THRESHOLD).astype(int)
    oof_metrics = classification_metrics(y.to_numpy(), oof_predicted, oof_probability)
    false_positive_rate, true_positive_rate, roc_thresholds = roc_curve(
        y, oof_probability
    )
    calibration = calibration_diagnostic(y.to_numpy(), oof_probability)

    summary: dict[str, dict[str, float | list[float]]] = {}
    for metric_name in (*METRIC_NAMES, "brier_score"):
        values = np.asarray([row[metric_name] for row in fold_rows], dtype=float)
        summary[metric_name] = {
            "mean": float(values.mean()),
            "std": float(values.std(ddof=0)),
            "fold_values": [float(value) for value in values],
        }

    return {
        "evaluation_threshold": CLASSIFICATION_THRESHOLD,
        "folds": CV_FOLDS,
        "fold_metrics": fold_rows,
        "cv_summary": summary,
        "oof_metrics": oof_metrics,
        "oof_confusion_matrix": confusion_matrix(y, oof_predicted).astype(int).tolist(),
        "oof_roc_auc": float(roc_auc_score(y, oof_probability)),
        "oof_brier_score": float(brier_score_loss(y, oof_probability)),
        "oof_log_loss": float(log_loss(y, oof_probability, labels=[0, 1])),
        "oof_mean_score": float(oof_probability.mean()),
        "observed_positive_prevalence": float(y.mean()),
        "roc_curve": {
            "false_positive_rate": false_positive_rate.tolist(),
            "true_positive_rate": true_positive_rate.tolist(),
            "thresholds": _finite_or_string(roc_thresholds),
        },
        "calibration": calibration,
        "oof_probabilities": oof_probability.tolist(),
    }


def evaluate_nested_threshold_policy(
    pipeline: Any,
    X: pd.DataFrame,
    y: pd.Series,
    *,
    minimum_recall: float = MINIMUM_SCREENING_RECALL,
) -> dict[str, Any]:
    """Evaluate a training-only threshold-selection policy with nested CV.

    Every outer validation row is classified using a threshold chosen exclusively from
    inner out-of-fold predictions within the corresponding outer training partition.
    """

    outer_splitter = StratifiedKFold(
        n_splits=CV_FOLDS,
        shuffle=True,
        random_state=RANDOM_SEED,
    )
    outer_probability = np.full(len(y), np.nan, dtype=float)
    outer_prediction = np.full(len(y), -1, dtype=int)
    threshold_by_row = np.full(len(y), np.nan, dtype=float)
    fold_rows: list[dict[str, float | int]] = []
    thresholds: list[float] = []

    for fold_index, (outer_train, outer_validation) in enumerate(
        outer_splitter.split(X, y), start=1
    ):
        X_train = X.iloc[outer_train]
        y_train = y.iloc[outer_train]
        inner_splitter = StratifiedKFold(
            n_splits=4,
            shuffle=True,
            random_state=RANDOM_SEED + fold_index,
        )
        inner_probability = np.full(len(y_train), np.nan, dtype=float)
        for inner_train, inner_validation in inner_splitter.split(X_train, y_train):
            inner_fitted = clone(pipeline)
            inner_fitted.fit(X_train.iloc[inner_train], y_train.iloc[inner_train])
            inner_probability[inner_validation] = inner_fitted.predict_proba(
                X_train.iloc[inner_validation]
            )[:, 1]

        threshold = choose_recall_floor_threshold(
            y_train.to_numpy(),
            inner_probability,
            minimum_recall=minimum_recall,
        )
        thresholds.append(threshold)

        outer_fitted = clone(pipeline)
        outer_fitted.fit(X_train, y_train)
        probability = outer_fitted.predict_proba(X.iloc[outer_validation])[:, 1]
        predicted = (probability >= threshold).astype(int)
        outer_probability[outer_validation] = probability
        outer_prediction[outer_validation] = predicted
        threshold_by_row[outer_validation] = threshold
        fold_rows.append(
            {
                "fold": fold_index,
                "selected_threshold": threshold,
                **classification_metrics(
                    y.iloc[outer_validation].to_numpy(), predicted, probability
                ),
            }
        )

    if (
        np.isnan(outer_probability).any()
        or np.isnan(threshold_by_row).any()
        or (outer_prediction < 0).any()
    ):
        raise RuntimeError("Nested evaluation did not produce one result per row.")

    summary: dict[str, dict[str, float | list[float]]] = {}
    for metric_name in METRIC_NAMES:
        values = np.asarray([row[metric_name] for row in fold_rows], dtype=float)
        summary[metric_name] = {
            "mean": float(values.mean()),
            "std": float(values.std(ddof=0)),
            "fold_values": [float(value) for value in values],
        }

    aggregate = classification_metrics(y.to_numpy(), outer_prediction, outer_probability)
    return {
        "policy": (
            "Within each training partition, choose the largest threshold on a 0.01 "
            "grid whose inner out-of-fold recall is at least the declared floor."
        ),
        "minimum_recall": minimum_recall,
        "inner_folds": 4,
        "outer_folds": CV_FOLDS,
        "fold_thresholds": thresholds,
        "threshold_mean": float(np.mean(thresholds)),
        "threshold_std": float(np.std(thresholds, ddof=0)),
        "fold_metrics": fold_rows,
        "cv_summary": summary,
        "aggregate_metrics": aggregate,
        "aggregate_confusion_matrix": confusion_matrix(y, outer_prediction)
        .astype(int)
        .tolist(),
    }


def choose_recall_floor_threshold(
    y_true: np.ndarray,
    probability: np.ndarray,
    *,
    minimum_recall: float = MINIMUM_SCREENING_RECALL,
) -> float:
    """Choose the most specific 0.01-grid threshold meeting a recall floor."""

    if not 0 < minimum_recall <= 1:
        raise ValueError("minimum_recall must be in (0, 1].")
    if len(y_true) != len(probability) or len(y_true) == 0:
        raise ValueError("Threshold selection requires aligned, non-empty arrays.")

    eligible: list[float] = []
    for threshold in np.arange(0.01, 1.0, 0.01):
        predicted = (probability >= threshold).astype(int)
        recall = recall_score(y_true, predicted, zero_division=0)
        if recall >= minimum_recall:
            eligible.append(float(round(threshold, 2)))
    return max(eligible) if eligible else 0.01


def classification_metrics(
    y_true: np.ndarray,
    predicted: np.ndarray,
    probability: np.ndarray,
) -> dict[str, float]:
    return {
        "accuracy": float(accuracy_score(y_true, predicted)),
        "precision": float(precision_score(y_true, predicted, zero_division=0)),
        "recall": float(recall_score(y_true, predicted, zero_division=0)),
        "f1": float(f1_score(y_true, predicted, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, probability)),
    }


def calibration_diagnostic(
    y_true: np.ndarray,
    probability: np.ndarray,
    *,
    bins: int = 10,
) -> dict[str, Any]:
    """Return a fixed-width reliability table and expected calibration error."""

    edges = np.linspace(0.0, 1.0, bins + 1)
    bin_indices = np.clip(np.digitize(probability, edges[1:-1]), 0, bins - 1)
    rows: list[dict[str, float | int]] = []
    weighted_error = 0.0
    for index in range(bins):
        mask = bin_indices == index
        count = int(mask.sum())
        if count == 0:
            continue
        mean_score = float(probability[mask].mean())
        observed_rate = float(y_true[mask].mean())
        weighted_error += count / len(y_true) * abs(mean_score - observed_rate)
        rows.append(
            {
                "bin_lower": float(edges[index]),
                "bin_upper": float(edges[index + 1]),
                "count": count,
                "mean_score": mean_score,
                "observed_positive_fraction": observed_rate,
            }
        )
    return {
        "method": "10 fixed-width bins",
        "expected_calibration_error": float(weighted_error),
        "bins": rows,
        "interpretation": (
            "Internal out-of-fold diagnostic only. The score is not externally calibrated "
            "for an individual Bangladeshi elder and must not be called the chance of disease."
        ),
    }


def strip_large_arrays(result: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-friendly summary without per-row OOF probabilities."""

    return {key: value for key, value in result.items() if key != "oof_probabilities"}


def _finite_or_string(values: np.ndarray) -> list[float | str]:
    return [float(value) if np.isfinite(value) else "infinity" for value in values]
