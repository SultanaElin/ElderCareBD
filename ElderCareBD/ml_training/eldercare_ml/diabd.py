"""Reproducible, leakage-conscious utilities for the Task 13B DiaBD study.

The public CSV is never rewritten. Fixed semantic encoding and plausibility-to-missing
rules are applied in memory, while every learned imputation/scaling operation remains
inside each fitted pipeline and therefore inside each cross-validation training fold.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin, clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupKFold, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .contracts import CV_FOLDS, RANDOM_SEED
from .evaluation import calibration_diagnostic, choose_recall_floor_threshold
from .modeling import ExactSchemaSelector


DIABD_FILENAME = (
    "DiaBD_A Diabetes Dataset for Enhanced Risk Analysis and Research in "
    "Bangladesh.csv"
)
DIABD_SHA256 = "D9F868C9CE8EEFE545294156ED1626F60FDB33F507F9CA021FD34FA4B575741A"
DIABD_COLUMNS = (
    "age",
    "gender",
    "pulse_rate",
    "systolic_bp",
    "diastolic_bp",
    "glucose",
    "height",
    "weight",
    "bmi",
    "family_diabetes",
    "hypertensive",
    "family_hypertension",
    "cardiovascular_disease",
    "stroke",
    "diabetic",
)
DIABD_TARGET = "diabetic"
GENDER_MAPPING = {"Female": 0, "Male": 1}
TARGET_MAPPING = {"No": 0, "Yes": 1}
BINARY_FEATURES = (
    "family_diabetes",
    "hypertensive",
    "family_hypertension",
    "cardiovascular_disease",
    "stroke",
)
CATEGORICAL_FEATURES = ("gender", *BINARY_FEATURES)
NUMERICAL_FEATURES = (
    "age",
    "pulse_rate",
    "systolic_bp",
    "diastolic_bp",
    "glucose",
    "height",
    "weight",
    "bmi",
)

# These are data-quality plausibility gates, not clinical normal ranges. Values outside
# a gate become missing inside the serialized pipeline; rows are never deleted.
PLAUSIBILITY_RANGES: dict[str, tuple[float, float]] = {
    "age": (18.0, 120.0),
    "pulse_rate": (30.0, 220.0),
    "systolic_bp": (60.0, 260.0),
    "diastolic_bp": (30.0, 160.0),
    "glucose": (1.0, 40.0),
    "height": (1.0, 2.3),
    "weight": (20.0, 300.0),
    "bmi": (10.0, 80.0),
}

FEATURE_SETS: dict[str, tuple[str, ...]] = {
    "full_14": DIABD_COLUMNS[:-1],
    "eldercare_reduced_8": (
        "age",
        "gender",
        "systolic_bp",
        "diastolic_bp",
        "glucose",
        "bmi",
        "family_diabetes",
        "family_hypertension",
    ),
    "current_ui_reduced_6": (
        "age",
        "gender",
        "systolic_bp",
        "diastolic_bp",
        "glucose",
        "bmi",
    ),
    "compact_4": ("age", "gender", "glucose", "bmi"),
    "minimal_no_glucose_4": ("age", "gender", "bmi", "family_diabetes"),
}


@dataclass(frozen=True)
class DiaBDCandidate:
    key: str
    display_name: str
    class_weight: str | None


DIABD_CANDIDATES = (
    DiaBDCandidate("logistic_regression", "Logistic Regression", None),
    DiaBDCandidate(
        "logistic_regression_balanced",
        "Logistic Regression (balanced)",
        "balanced",
    ),
    DiaBDCandidate(
        "random_forest_balanced",
        "Random Forest (balanced)",
        "balanced",
    ),
)

METRIC_NAMES = (
    "accuracy",
    "balanced_accuracy",
    "precision",
    "recall",
    "specificity",
    "f1",
    "roc_auc",
    "pr_auc_average_precision",
    "brier_score",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_raw_diabd(data_dir: Path) -> pd.DataFrame:
    """Load and strictly validate the untouched local DiaBD snapshot."""

    path = data_dir / DIABD_FILENAME
    if not path.is_file():
        raise FileNotFoundError(f"Required local DiaBD file is missing: {path}")
    actual_hash = sha256_file(path)
    if actual_hash != DIABD_SHA256:
        raise ValueError(
            f"DiaBD SHA-256 changed: expected {DIABD_SHA256}, got {actual_hash}."
        )
    frame = pd.read_csv(path)
    if tuple(frame.columns) != DIABD_COLUMNS:
        raise ValueError("DiaBD schema or column order differs from the audited snapshot.")
    if len(frame) != 5288:
        raise ValueError("DiaBD row count differs from the audited 5,288-row snapshot.")
    if frame.isna().any().any():
        raise ValueError("DiaBD unexpectedly contains missing values.")
    if frame.astype(str).apply(lambda column: column.str.strip().eq("")).any().any():
        raise ValueError("DiaBD unexpectedly contains blank text values.")
    if frame.duplicated().any():
        raise ValueError("DiaBD unexpectedly contains exact duplicate rows.")
    if set(frame["gender"].unique()) != set(GENDER_MAPPING):
        raise ValueError("DiaBD gender categories differ from the audited mapping.")
    if set(frame[DIABD_TARGET].unique()) != set(TARGET_MAPPING):
        raise ValueError("DiaBD target categories differ from the audited mapping.")
    for column in BINARY_FEATURES:
        if set(frame[column].unique()) != {0, 1}:
            raise ValueError(f"DiaBD binary feature '{column}' is not exactly 0/1.")
    numerical = frame.loc[:, list(NUMERICAL_FEATURES)].to_numpy(dtype=float)
    if not np.isfinite(numerical).all():
        raise ValueError("DiaBD contains non-finite numeric values.")
    predictors = frame.drop(columns=DIABD_TARGET)
    if predictors.duplicated(keep=False).any():
        raise ValueError("DiaBD unexpectedly contains duplicate predictor profiles.")
    return frame


def encoded_xy(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Apply fixed documented category mappings without learning from the target."""

    X = raw.drop(columns=DIABD_TARGET).copy()
    X["gender"] = X["gender"].map(GENDER_MAPPING)
    if X["gender"].isna().any():
        raise ValueError("DiaBD contains an unsupported gender category.")
    X["gender"] = X["gender"].astype(int)
    y = raw[DIABD_TARGET].map(TARGET_MAPPING)
    if y.isna().any():
        raise ValueError("DiaBD contains an unsupported target category.")
    return X, y.astype(int)


class DiaBDPlausibilityToNaN(BaseEstimator, TransformerMixin):
    """Replace only predeclared implausible measurements with fold-imputable NaN."""

    def __init__(
        self,
        ranges: tuple[tuple[str, float, float], ...],
    ) -> None:
        self.ranges = ranges

    def fit(self, X: pd.DataFrame, y: object = None) -> "DiaBDPlausibilityToNaN":
        del y
        self.feature_names_in_ = np.asarray(X.columns, dtype=object)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        transformed = X.copy()
        for column, minimum, maximum in self.ranges:
            if column not in transformed:
                continue
            numeric = pd.to_numeric(transformed[column], errors="coerce").astype(float)
            transformed[column] = numeric.mask(
                (numeric < minimum) | (numeric > maximum), np.nan
            )
        return transformed

    def get_feature_names_out(self, input_features: object = None) -> np.ndarray:
        if input_features is None:
            return self.feature_names_in_
        return np.asarray(input_features, dtype=object)


def build_diabd_pipeline(
    features: tuple[str, ...],
    candidate_key: str,
) -> Pipeline:
    candidate = next(
        (item for item in DIABD_CANDIDATES if item.key == candidate_key), None
    )
    if candidate is None:
        raise ValueError(f"Unknown DiaBD candidate: {candidate_key}")
    unknown = set(features) - set(NUMERICAL_FEATURES) - set(CATEGORICAL_FEATURES)
    if unknown:
        raise ValueError(f"DiaBD features lack preprocessing definitions: {sorted(unknown)}")

    numerical = [name for name in features if name in NUMERICAL_FEATURES]
    categorical = [name for name in features if name in CATEGORICAL_FEATURES]
    scale_numeric = candidate_key.startswith("logistic_regression")
    numeric_steps: list[tuple[str, Any]] = [
        ("imputer", SimpleImputer(strategy="median"))
    ]
    if scale_numeric:
        numeric_steps.append(("scaler", StandardScaler()))

    transformers: list[tuple[str, Any, list[str]]] = []
    if numerical:
        transformers.append(("numeric", Pipeline(numeric_steps), numerical))
    if categorical:
        categories = [[0, 1] for _ in categorical]
        transformers.append(
            (
                "categorical",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        (
                            "one_hot",
                            OneHotEncoder(
                                categories=categories,
                                handle_unknown="error",
                                sparse_output=False,
                            ),
                        ),
                    ]
                ),
                categorical,
            )
        )
    preprocessor = ColumnTransformer(
        transformers=transformers,
        remainder="drop",
        sparse_threshold=0.0,
        verbose_feature_names_out=True,
    )

    if candidate_key.startswith("logistic_regression"):
        classifier: Any = LogisticRegression(
            max_iter=2000,
            class_weight=candidate.class_weight,
            solver="lbfgs",
            random_state=RANDOM_SEED,
        )
    else:
        classifier = RandomForestClassifier(
            n_estimators=300,
            max_depth=None,
            min_samples_split=4,
            min_samples_leaf=2,
            max_features="sqrt",
            class_weight=candidate.class_weight,
            random_state=RANDOM_SEED,
            n_jobs=1,
        )

    ranges = tuple(
        (name, *PLAUSIBILITY_RANGES[name])
        for name in features
        if name in PLAUSIBILITY_RANGES
    )
    return Pipeline(
        [
            ("schema", ExactSchemaSelector(features)),
            ("plausibility_to_missing", DiaBDPlausibilityToNaN(ranges)),
            ("preprocessor", preprocessor),
            ("classifier", classifier),
        ]
    )


def classification_metrics(
    y_true: np.ndarray,
    predicted: np.ndarray,
    probability: np.ndarray,
) -> dict[str, float]:
    matrix = confusion_matrix(y_true, predicted, labels=[0, 1])
    true_negative, false_positive, false_negative, true_positive = matrix.ravel()
    specificity = true_negative / (true_negative + false_positive)
    return {
        "accuracy": float(accuracy_score(y_true, predicted)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, predicted)),
        "precision": float(precision_score(y_true, predicted, zero_division=0)),
        "recall": float(recall_score(y_true, predicted, zero_division=0)),
        "specificity": float(specificity),
        "f1": float(f1_score(y_true, predicted, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, probability)),
        "pr_auc_average_precision": float(
            average_precision_score(y_true, probability)
        ),
        "brier_score": float(brier_score_loss(y_true, probability)),
    }


def _summarize_folds(fold_rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for metric in METRIC_NAMES:
        values = np.asarray([row[metric] for row in fold_rows], dtype=float)
        summary[metric] = {
            "mean": float(values.mean()),
            "std": float(values.std(ddof=0)),
            "fold_values": values.tolist(),
        }
    return summary


def _evaluate_splits(
    pipeline: Pipeline,
    X: pd.DataFrame,
    y: pd.Series,
    splits: Iterable[tuple[np.ndarray, np.ndarray]],
    *,
    threshold: float = 0.5,
) -> dict[str, Any]:
    probability = np.full(len(y), np.nan, dtype=float)
    fold_rows: list[dict[str, Any]] = []
    for fold, (train_indices, validation_indices) in enumerate(splits, start=1):
        fitted = clone(pipeline)
        fitted.fit(X.iloc[train_indices], y.iloc[train_indices])
        fold_probability = fitted.predict_proba(X.iloc[validation_indices])[:, 1]
        probability[validation_indices] = fold_probability
        fold_prediction = (fold_probability >= threshold).astype(int)
        fold_rows.append(
            {
                "fold": fold,
                **classification_metrics(
                    y.iloc[validation_indices].to_numpy(),
                    fold_prediction,
                    fold_probability,
                ),
            }
        )
    if np.isnan(probability).any():
        raise RuntimeError("Cross-validation did not score every row exactly once.")
    prediction = (probability >= threshold).astype(int)
    return {
        "threshold": threshold,
        "fold_metrics": fold_rows,
        "cv_summary": _summarize_folds(fold_rows),
        "oof_metrics": classification_metrics(y.to_numpy(), prediction, probability),
        "oof_confusion_matrix": confusion_matrix(y, prediction, labels=[0, 1])
        .astype(int)
        .tolist(),
        "oof_log_loss": float(log_loss(y, probability, labels=[0, 1])),
        "oof_mean_score": float(probability.mean()),
        "observed_positive_prevalence": float(y.mean()),
        "calibration": calibration_diagnostic(y.to_numpy(), probability),
        "oof_probabilities": probability,
    }


def evaluate_candidate(
    pipeline: Pipeline,
    X: pd.DataFrame,
    y: pd.Series,
) -> dict[str, Any]:
    splitter = StratifiedKFold(
        n_splits=CV_FOLDS,
        shuffle=True,
        random_state=RANDOM_SEED,
    )
    return _evaluate_splits(pipeline, X, y, splitter.split(X, y))


def evaluate_contiguous_block_sensitivity(
    pipeline: Pipeline,
    X: pd.DataFrame,
    y: pd.Series,
) -> dict[str, Any]:
    """Non-primary sensitivity check for hidden row-order/site/batch structure."""

    groups = np.minimum(np.arange(len(y)) * CV_FOLDS // len(y), CV_FOLDS - 1)
    splitter = GroupKFold(n_splits=CV_FOLDS)
    result = _evaluate_splits(pipeline, X, y, splitter.split(X, y, groups))
    result["interpretation"] = (
        "Sensitivity analysis only: contiguous row blocks are not known sites or "
        "participants. Lower performance may indicate hidden collection-order shift, "
        "but cannot identify its cause because DiaBD provides no site/time/person IDs."
    )
    return result


def evaluate_nested_threshold(
    pipeline: Pipeline,
    X: pd.DataFrame,
    y: pd.Series,
    *,
    minimum_recall: float = 0.75,
) -> dict[str, Any]:
    outer = StratifiedKFold(
        n_splits=CV_FOLDS,
        shuffle=True,
        random_state=RANDOM_SEED,
    )
    probability = np.full(len(y), np.nan, dtype=float)
    prediction = np.full(len(y), -1, dtype=int)
    threshold_by_row = np.full(len(y), np.nan, dtype=float)
    thresholds: list[float] = []
    fold_rows: list[dict[str, Any]] = []
    for fold, (outer_train, outer_validation) in enumerate(
        outer.split(X, y), start=1
    ):
        X_train = X.iloc[outer_train]
        y_train = y.iloc[outer_train]
        inner = StratifiedKFold(
            n_splits=4,
            shuffle=True,
            random_state=RANDOM_SEED + fold,
        )
        inner_probability = np.full(len(y_train), np.nan, dtype=float)
        for inner_train, inner_validation in inner.split(X_train, y_train):
            fitted_inner = clone(pipeline)
            fitted_inner.fit(X_train.iloc[inner_train], y_train.iloc[inner_train])
            inner_probability[inner_validation] = fitted_inner.predict_proba(
                X_train.iloc[inner_validation]
            )[:, 1]
        threshold = choose_recall_floor_threshold(
            y_train.to_numpy(),
            inner_probability,
            minimum_recall=minimum_recall,
        )
        fitted = clone(pipeline)
        fitted.fit(X_train, y_train)
        fold_probability = fitted.predict_proba(X.iloc[outer_validation])[:, 1]
        fold_prediction = (fold_probability >= threshold).astype(int)
        probability[outer_validation] = fold_probability
        prediction[outer_validation] = fold_prediction
        threshold_by_row[outer_validation] = threshold
        thresholds.append(threshold)
        fold_rows.append(
            {
                "fold": fold,
                "selected_threshold": threshold,
                **classification_metrics(
                    y.iloc[outer_validation].to_numpy(),
                    fold_prediction,
                    fold_probability,
                ),
            }
        )
    if (
        np.isnan(probability).any()
        or np.isnan(threshold_by_row).any()
        or (prediction < 0).any()
    ):
        raise RuntimeError("Nested threshold evaluation did not score every row.")
    return {
        "policy": (
            "Within each outer-training partition, choose the largest 0.01-grid "
            "threshold whose four-fold inner out-of-fold recall is at least 0.75."
        ),
        "minimum_recall": minimum_recall,
        "fold_thresholds": thresholds,
        "threshold_mean": float(np.mean(thresholds)),
        "threshold_std": float(np.std(thresholds, ddof=0)),
        "fold_metrics": fold_rows,
        "cv_summary": _summarize_folds(fold_rows),
        "aggregate_metrics": classification_metrics(
            y.to_numpy(), prediction, probability
        ),
        "aggregate_confusion_matrix": confusion_matrix(
            y, prediction, labels=[0, 1]
        )
        .astype(int)
        .tolist(),
        "oof_probabilities": probability,
        "oof_predictions": prediction,
        "threshold_by_row": threshold_by_row,
    }


def json_ready_evaluation(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.tolist() if isinstance(value, np.ndarray) else value
        for key, value in result.items()
        if key not in {"oof_probabilities", "oof_predictions", "threshold_by_row"}
    }


def prevalence_brier(y: pd.Series) -> float:
    prevalence = float(y.mean())
    return float(np.mean((y.to_numpy() - prevalence) ** 2))


def validate_probability_vector(probability: np.ndarray, expected_rows: int) -> None:
    if probability.shape != (expected_rows,):
        raise ValueError("Expected exactly one positive-class score per row.")
    if not np.isfinite(probability).all() or not (
        (probability >= 0.0) & (probability <= 1.0)
    ).all():
        raise ValueError("Prediction scores must be finite and within [0, 1].")
    if math.isclose(float(probability.std()), 0.0, abs_tol=1e-15):
        raise ValueError("Prediction scores unexpectedly have zero variance.")
