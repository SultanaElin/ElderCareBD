"""Strict loading, validation, and audit helpers for the approved local datasets."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .contracts import CV_FOLDS, DatasetConfig


EXPECTED_DATASETS = {
    "diabetes": {
        "sha256": "698C203A14AA31941D2251175330C9199F3CCDB31597ABBBA2A3E35416257A72",
        "rows": 768,
        "bytes": 23873,
    },
    "heart": {
        "sha256": "386015BE85BCC9112CBAC782DAFD145AEEF7ABD4F8B9F2EE65F6C4C56ED82D9F",
        "rows": 297,
        "bytes": 11106,
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_and_validate_dataset(
    config: DatasetConfig,
    data_dir: Path,
    *,
    enforce_approved_hash: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load the repository CSV and reject schema/data states unsafe for evaluation."""

    path = data_dir / config.filename
    if not path.is_file():
        raise ValueError(f"Dataset file does not exist: {path}")

    expected = EXPECTED_DATASETS[config.disease]
    digest = sha256_file(path)
    if enforce_approved_hash and digest != expected["sha256"]:
        raise ValueError(
            f"{config.display_name} dataset hash differs from the approved repository "
            f"snapshot: expected {expected['sha256']}, got {digest}."
        )

    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        raise ValueError(f"Could not parse dataset CSV: {path}") from exc

    if frame.columns.duplicated().any():
        raise ValueError(f"{config.display_name} dataset contains duplicate columns.")
    actual_columns = tuple(frame.columns)
    if actual_columns != config.required_columns:
        missing = sorted(set(config.required_columns) - set(actual_columns))
        unexpected = sorted(set(actual_columns) - set(config.required_columns))
        raise ValueError(
            f"{config.display_name} schema mismatch. Expected exact ordered columns "
            f"{list(config.required_columns)}; missing={missing}, unexpected={unexpected}."
        )
    if len(frame) != expected["rows"]:
        raise ValueError(
            f"{config.display_name} row count mismatch: expected {expected['rows']}, "
            f"got {len(frame)}."
        )
    if frame.empty:
        raise ValueError(f"{config.display_name} dataset is empty.")

    numeric_frame = pd.DataFrame(index=frame.index)
    for column in config.required_columns:
        try:
            numeric_frame[column] = pd.to_numeric(frame[column], errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{config.display_name} column '{column}' must contain only numeric values."
            ) from exc

    if numeric_frame.isna().any().any():
        missing_columns = numeric_frame.columns[numeric_frame.isna().any()].tolist()
        raise ValueError(
            f"{config.display_name} contains explicit missing values in: "
            f"{missing_columns}. Only documented Pima zero sentinels are supported."
        )
    if not np.isfinite(numeric_frame.to_numpy(dtype=float)).all():
        raise ValueError(f"{config.display_name} contains non-finite numeric values.")

    target_values = set(numeric_frame[config.target].unique().tolist())
    expected_targets = set(config.target_mapping)
    if target_values != expected_targets:
        raise ValueError(
            f"{config.display_name} target must contain exactly "
            f"{sorted(expected_targets)}, got {sorted(target_values)}."
        )
    target_counts = numeric_frame[config.target].value_counts().sort_index()
    if int(target_counts.min()) < CV_FOLDS:
        raise ValueError(
            f"{config.display_name} has fewer than {CV_FOLDS} rows in a target class."
        )

    for column, allowed in config.categorical_values.items():
        actual = set(numeric_frame[column].unique().tolist())
        if not actual.issubset(set(allowed)):
            raise ValueError(
                f"{config.display_name} categorical column '{column}' contains "
                f"unsupported values: {sorted(actual - set(allowed))}."
            )

    predictors = numeric_frame.drop(columns=[config.target])
    exact_duplicate_count = int(numeric_frame.duplicated().sum())
    feature_duplicate_count = int(predictors.duplicated(keep=False).sum())
    if exact_duplicate_count:
        raise ValueError(
            f"{config.display_name} contains {exact_duplicate_count} exact duplicate rows."
        )
    if feature_duplicate_count:
        duplicate_targets = numeric_frame.loc[
            predictors.duplicated(keep=False), [*predictors.columns, config.target]
        ]
        grouped_unique_targets = duplicate_targets.groupby(
            list(predictors.columns), dropna=False
        )[config.target].nunique()
        conflicts = int((grouped_unique_targets > 1).sum())
        raise ValueError(
            f"{config.display_name} contains {feature_duplicate_count} rows with "
            f"duplicated predictors ({conflicts} conflicting predictor groups)."
        )

    for name, features in config.feature_sets.items():
        if config.target in features:
            raise ValueError(f"Feature set '{name}' contains the target column.")
        unknown = set(features) - set(predictors.columns)
        if unknown:
            raise ValueError(
                f"Feature set '{name}' references unknown columns: {sorted(unknown)}."
            )

    audit = build_dataset_audit(
        config=config,
        path=path,
        digest=digest,
        frame=numeric_frame,
    )
    return numeric_frame, audit


def build_dataset_audit(
    *,
    config: DatasetConfig,
    path: Path,
    digest: str,
    frame: pd.DataFrame,
) -> dict[str, Any]:
    predictors = frame.drop(columns=[config.target])
    invalid_zero_counts = {
        column: int((frame[column] == 0).sum())
        for column in config.invalid_zero_features
    }
    invalid_zero_union = (
        int((frame[list(config.invalid_zero_features)] == 0).any(axis=1).sum())
        if config.invalid_zero_features
        else 0
    )
    selected_invalid_columns = [
        column
        for column in config.invalid_zero_features
        if column in config.selected_features
    ]
    selected_invalid_union = (
        int((frame[selected_invalid_columns] == 0).any(axis=1).sum())
        if selected_invalid_columns
        else 0
    )

    ranges: dict[str, dict[str, float | int]] = {}
    for column in predictors.columns:
        values = frame[column]
        if column in config.invalid_zero_features:
            values = values[values != 0]
        minimum = values.min()
        maximum = values.max()
        ranges[column] = {
            "minimum": _python_number(minimum),
            "maximum": _python_number(maximum),
        }

    age_column = "Age" if config.disease == "diabetes" else "age"
    age_counts = {
        "age_60_or_older": int((frame[age_column] >= 60).sum()),
        "age_65_or_older": int((frame[age_column] >= 65).sum()),
    }

    return {
        "disease": config.disease,
        "display_name": config.display_name,
        "local_path": f"data/{config.filename}",
        "sha256": digest,
        "bytes": path.stat().st_size,
        "rows": len(frame),
        "columns": list(frame.columns),
        "predictor_count": len(predictors.columns),
        "target": config.target,
        "target_mapping": {str(key): value for key, value in config.target_mapping.items()},
        "target_definition": config.target_definition,
        "class_distribution": {
            str(int(key)): int(value)
            for key, value in frame[config.target].value_counts().sort_index().items()
        },
        "explicit_missing_values": int(frame.isna().sum().sum()),
        "non_finite_values": int(
            (~np.isfinite(frame.to_numpy(dtype=float))).sum()
        ),
        "invalid_zero_convention": invalid_zero_counts,
        "rows_with_any_invalid_zero_full_contract": invalid_zero_union,
        "rows_with_any_invalid_zero_selected_contract": selected_invalid_union,
        "exact_duplicate_rows": int(frame.duplicated().sum()),
        "duplicate_predictor_rows": int(predictors.duplicated(keep=False).sum()),
        "observed_ranges_after_zero_sentinel_exclusion": ranges,
        "age_counts": age_counts,
        "source_name": config.source_name,
        "source_url": config.source_url,
        "distribution_url": config.distribution_url,
        "license_note": config.license_note,
        "missing_value_convention": config.missing_value_convention,
        "source_note": config.source_note,
        "population_and_generalizability": config.population_note,
        "screening_only": True,
    }


def _python_number(value: Any) -> float | int:
    numeric = float(value)
    return int(numeric) if numeric.is_integer() else numeric
