"""Strict, serializable inference wrapper for ElderCareBD v2 models."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from typing import Any

import numpy as np
import pandas as pd

from .contracts import FeatureSpec


@dataclass
class RiskModelArtifact:
    """A fitted preprocessing pipeline plus an explicit inference contract.

    The wrapper intentionally rejects missing, unexpected, non-numeric, non-finite,
    and out-of-contract inputs. Task 14 can therefore load one object without
    guessing feature order or silently supplying defaults.
    """

    model_version: str
    disease: str
    model_name: str
    feature_specs: tuple[FeatureSpec, ...]
    classification_threshold: float
    pipeline: Any

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.feature_specs)

    def contract_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "disease": self.disease,
            "model_name": self.model_name,
            "feature_order": list(self.feature_names),
            "features": [spec.to_dict() for spec in self.feature_specs],
            "classification_threshold": self.classification_threshold,
        }

    def validate_input(
        self,
        values: pd.DataFrame | Mapping[str, Any] | Sequence[Mapping[str, Any]],
    ) -> pd.DataFrame:
        """Validate and normalize one or more inference rows."""

        if isinstance(values, pd.DataFrame):
            frame = values.copy()
        elif isinstance(values, Mapping):
            frame = pd.DataFrame([dict(values)])
        elif isinstance(values, Sequence) and not isinstance(
            values, (str, bytes, bytearray)
        ):
            if not all(isinstance(row, Mapping) for row in values):
                raise TypeError("Inference rows must be mappings of feature names to values.")
            frame = pd.DataFrame([dict(row) for row in values])
        else:
            raise TypeError(
                "Inference input must be a pandas DataFrame, a mapping, or a sequence "
                "of mappings."
            )

        if frame.empty:
            raise ValueError("At least one inference row is required.")
        if frame.columns.duplicated().any():
            duplicate_columns = sorted(
                set(frame.columns[frame.columns.duplicated()].astype(str))
            )
            raise ValueError(f"Duplicate feature columns are not allowed: {duplicate_columns}")

        expected = set(self.feature_names)
        actual = set(frame.columns)
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        if missing:
            raise ValueError(f"Missing required features: {missing}")
        if unexpected:
            raise ValueError(f"Unexpected features: {unexpected}")

        frame = frame.loc[:, list(self.feature_names)].copy()
        for spec in self.feature_specs:
            series = frame[spec.name]
            if series.map(lambda value: isinstance(value, (bool, np.bool_))).any():
                raise ValueError(f"Feature '{spec.name}' must not be boolean.")
            if series.map(lambda value: not isinstance(value, Real)).any():
                raise ValueError(
                    f"Feature '{spec.name}' must use a JSON/Python numeric type, not text."
                )
            try:
                numeric = pd.to_numeric(series, errors="raise")
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Feature '{spec.name}' must be numeric.") from exc

            numeric_values = numeric.to_numpy(dtype=float)
            if not np.isfinite(numeric_values).all():
                raise ValueError(f"Feature '{spec.name}' must be finite and non-missing.")

            if spec.data_type == "integer" and not np.equal(
                numeric_values, np.floor(numeric_values)
            ).all():
                raise ValueError(f"Feature '{spec.name}' must contain integer values.")

            if spec.allowed_values is not None:
                invalid = ~numeric.isin(spec.allowed_values)
                if invalid.any():
                    raise ValueError(
                        f"Feature '{spec.name}' must be one of "
                        f"{list(spec.allowed_values)}."
                    )
            if spec.minimum is not None and (numeric < spec.minimum).any():
                raise ValueError(
                    f"Feature '{spec.name}' must be at least {spec.minimum}."
                )
            if spec.maximum is not None and (numeric > spec.maximum).any():
                raise ValueError(
                    f"Feature '{spec.name}' must be at most {spec.maximum}."
                )

            frame[spec.name] = numeric.astype(
                int if spec.data_type == "integer" else float
            )

        return frame

    def predict_proba(
        self,
        values: pd.DataFrame | Mapping[str, Any] | Sequence[Mapping[str, Any]],
    ) -> np.ndarray:
        frame = self.validate_input(values)
        probabilities = np.asarray(self.pipeline.predict_proba(frame), dtype=float)
        if probabilities.ndim != 2 or probabilities.shape[1] != 2:
            raise RuntimeError("The fitted classifier did not return binary probabilities.")
        return probabilities

    def predict_risk_score(
        self,
        values: pd.DataFrame | Mapping[str, Any] | Sequence[Mapping[str, Any]],
    ) -> np.ndarray:
        """Return the positive-class model score; it is not a clinical probability."""

        return self.predict_proba(values)[:, 1]

    def predict(
        self,
        values: pd.DataFrame | Mapping[str, Any] | Sequence[Mapping[str, Any]],
    ) -> np.ndarray:
        return (self.predict_risk_score(values) >= self.classification_threshold).astype(
            int
        )
